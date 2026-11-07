import csv
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from .storage import Store, lock
from .media import extract, published_copy
from .wps import LocalArchive


def now():
    return datetime.now(timezone.utc).isoformat()


class Service:
    def __init__(self, config='config.json'):
        self.path = Path(config).resolve()
        self.config = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if 'minimum_likes' in self.config:
            minimum=self.config['minimum_likes']
            if isinstance(minimum,bool) or not isinstance(minimum,int) or minimum<0:raise ValueError('minimum_likes must be a non-negative integer')
            self.config['threshold']=minimum-1
        self.root = (self.path.parent / self.config['data_dir']).resolve()
        self.store = Store(self.root)

    def ingest(self, rows, source='import'):
        count = 0
        allowed = {a['id'] for a in self.config['accounts'] if a['id']}
        allowed.update('douyin-public:' + p['sec_uid'] for p in self.config.get('public_profiles', []) if p.get('name_verified'))
        for row in rows:
            aid, vid = str(row['account_id']), str(row['id'])
            if not aid or not vid or (source != 'mock' and aid not in allowed):
                raise ValueError('configure unique account ID before import')
            if source == 'browser' and not row.get('detail_verified'):
                raise ValueError('browser detail verification required')
            likes = int(row['likes'])
            if likes < 0 or row.get('type', 'video') not in ('video', 'image'):
                raise ValueError('invalid likes or media type')
            row = dict(row, account_id=aid, id=vid, likes=likes, source=source)
            old = self.store.rows('SELECT payload FROM works WHERE account_id=? AND id=?', (aid, vid))
            if old:
                prior = json.loads(old[0]['payload'])
                if source in ('official', 'browser'):
                    for field in ('media', 'media_mapping_source', 'asr_vocabulary', 'recognition_review',
                                  'recognition_evidence', 'caption_assisted', 'subtitle_media', 'subtitle_capture'):
                        if field in prior and field not in row:
                            row[field] = prior[field]
            self.store.execute('''INSERT INTO works(account_id,id,payload,likes,checked_at) VALUES(?,?,?,?,?)
              ON CONFLICT(account_id,id) DO UPDATE SET payload=excluded.payload,likes=excluded.likes,checked_at=excluded.checked_at''',
              (aid, vid, json.dumps(row, ensure_ascii=False), likes, now()))
            if source == 'browser' and self.config.get('append_policy'):
                from .append_policy import eligible
                decision, reason = eligible(row, self.store, self.config)
                if not decision and reason not in ('below_threshold',):
                    self.store.execute("UPDATE works SET status='baseline_ignored' WHERE account_id=? AND id=? AND status IN ('discovered','waiting_media')",(aid,vid))
                elif decision:
                    self.store.execute("UPDATE works SET status='discovered' WHERE account_id=? AND id=? AND status='baseline_ignored'",(aid,vid))
            count += 1
        return {'ingested': count, 'source': source}

    def monitor(self, historical=False):
        if self.config['mode'] == 'browser':
            from .browser import BrowserCollector
            return BrowserCollector(self).run(historical=historical, **self.config.get('browser_budgets', {}))
        if self.config['mode'] == 'browser_probe':
            return {'monitor': 'browser_setup_required',
                    'message': 'Run scripts/browser-probe.ps1; public page extraction is not yet verified'}
        if self.config['mode'] != 'official':
            return {'monitor': 'mock_only' if self.config['mode'] == 'mock' else 'authorization_required',
                    'message': 'use import command; no real monitoring active'}
        from .douyin import Official, AuthError, normalize
        results = []
        for account in self.config['accounts']:
            aid = account['id']
            if not aid:
                results.append({'name': account['name'], 'status': 'authorization_required'}); continue
            try:
                api = Official(account, self.store)
                for batch in api.scan(historical):
                    self.ingest([normalize(r, account) for r in batch], 'official')
                ids = [r['id'] for r in self.store.rows("SELECT id FROM works WHERE account_id=? AND status!='archived'", (aid,))]
                for batch in api.recheck(ids):
                    self.ingest([normalize(r, account) for r in batch], 'official')
                status, error = 'real_monitor_ok', None
            except Exception as exc:
                error = str(exc) if isinstance(exc, (AuthError, RuntimeError)) else type(exc).__name__
                status = ('token_invalid' if 'token_invalid' in error else 'authorization_required') if isinstance(exc, AuthError) else 'network_api_error'
                self.store.event(status, error)
            self.store.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?)', (aid, account['name'], status, now(), error))
            results.append({'id': aid, 'status': status, 'error': error})
        return {'accounts': results}

    def process(self, retry=False):
        # Under OS lock, any processing state is from an interrupted previous run.
        self.store.execute("UPDATE works SET status='discovered' WHERE status='processing'")
        statuses = "'discovered','waiting_media','waiting_subtitles'" + (",'failed'" if retry else '')
        rows = self.store.rows(f'SELECT * FROM works WHERE likes>? AND status IN ({statuses})', (self.config['threshold'],))
        result = {'ready': 0, 'waiting_media': 0, 'waiting_subtitles': 0, 'failed': 0}
        proofreader = None
        for row in rows:
            args = (row['account_id'], row['id'])
            self.store.execute("UPDATE works SET status='processing',attempts=attempts+1 WHERE account_id=? AND id=?", args)
            try:
                work = json.loads(row['payload'])
                vocabulary = self.config.get('proofreading', {}).get('asr_vocabulary', [])
                if vocabulary:
                    work['asr_vocabulary'] = list(dict.fromkeys(work.get('asr_vocabulary', []) + vocabulary))
                text = (published_copy(work) if work.get('content_mode') == 'published_copy'
                        else extract(work, self.root, str(self.path.parent / self.config['model'])))
                if text is None:
                    self.store.execute("UPDATE works SET status='waiting_media' WHERE account_id=? AND id=?", args)
                    result['waiting_media'] += 1
                else:
                    from .wps import marker
                    raw_dir = self.root / 'transcripts' / marker(*args).split(':')[1]
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    raw_file = raw_dir / 'raw.txt'
                    raw_file.write_text(text['raw'], encoding='utf-8')
                    (raw_dir/'asr-before-proofreading.json').write_text(json.dumps(text,ensure_ascii=False,indent=2),encoding='utf-8')
                    settings = self.config.get('proofreading', {})
                    if settings.get('enabled') and work.get('type') != 'image' and text.get('source') != 'published_description':
                        if proofreader is None:
                            from .proofreading import Proofreader
                            proofreader = Proofreader(settings, self.path.parent)
                        captions = settings.get('video_subtitles', {})
                        if captions.get('enabled'):
                            from .subtitles import extract_subtitles
                            from .transcript_fusion import reconcile
                            subtitles = extract_subtitles(work, self.root, captions)
                            (raw_dir/'raw-video-subtitles.json').write_text(json.dumps(subtitles,ensure_ascii=False,indent=2),encoding='utf-8')
                            if subtitles['status'] != 'extracted':
                                self.store.execute("UPDATE works SET status='waiting_subtitles',error=? WHERE account_id=? AND id=?",(subtitles.get('reason',subtitles['status']),*args))
                                result['waiting_subtitles'] += 1
                                continue
                            text = reconcile(text, subtitles, library=proofreader.library,
                                             minimum_coverage=float(captions.get('minimum_coverage',.75)),
                                             ocr_corrections=captions.get('reviewed_ocr_corrections',[]))
                        text = proofreader.process(text)
                    transcript_dir = self.root / 'transcripts' / marker(*args).split(':')[1]
                    transcript_dir.mkdir(parents=True, exist_ok=True)
                    for filename, content in [('raw.txt', text['raw']), ('cleaned.txt', text['body']),
                        ('recognition.json', json.dumps({'account_id': row['account_id'], 'id': row['id'],
                            'recognized_at': now(), **text}, ensure_ascii=False, indent=2))]:
                        target = transcript_dir / filename
                        temp = target.with_suffix('.tmp'); temp.write_text(content, encoding='utf-8'); temp.replace(target)
                    payload = json.loads(row['payload'])
                    payload['recognition_review'] = 'publisher_text' if text.get('source') == 'published_description' else 'subtitle_assisted_unreviewed' if text.get('subtitle_primary') else 'reference_assisted_unreviewed' if text.get('proofreading') else 'machine_unreviewed'
                    payload['recognition_evidence'] = str(transcript_dir / 'recognition.json')
                    self.store.execute("UPDATE works SET status='ready_to_archive',raw=?,body=?,payload=?,error=NULL WHERE account_id=? AND id=?",
                        (text['raw'], text['body'], json.dumps(payload, ensure_ascii=False), *args))
                    result['ready'] += 1
            except Exception as exc:
                error = type(exc).__name__ + ': ' + str(exc)[:500]
                self.store.execute("UPDATE works SET status='failed',error=? WHERE account_id=? AND id=?", (error, *args))
                self.store.event('processing_failed', error)
                result['failed'] += 1
        return result

    def archive(self):
        writer = LocalArchive(self.root)
        names = {a['id']: a['name'] for a in self.config['accounts']}
        names.update({'douyin-public:' + p['sec_uid']: p.get('name', p['sec_uid']) for p in self.config.get('public_profiles', [])})
        rows = self.store.rows("SELECT * FROM works WHERE status='ready_to_archive'")
        if self.config.get('proofreading', {}).get('video_subtitles', {}).get('enabled'):
            stale=[]
            for row in rows:
                payload=json.loads(row['payload'])
                if payload.get('type','video') == 'video' and payload.get('content_mode') != 'published_copy' and payload.get('recognition_review') != 'subtitle_assisted_unreviewed':
                    stale.append(row)
            for row in stale:
                self.store.execute("UPDATE works SET status='waiting_subtitles',error='Caption reconciliation required' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
            if stale:raise RuntimeError('Spoken drafts need video caption reconciliation before archive; run process first')

        rows.sort(key=lambda row:(row['account_id'],str(json.loads(row['payload']).get('published_at',''))))
        paths = [writer.stage(row, json.loads(row['payload']), names.get(row['account_id'], row['account_id'])) for row in rows]
        result = {'destination': 'local_outbox', 'files': paths, 'remote': 'setup_required'}
        if self.config.get('wps', {}).get('enabled'):
            from .wps_writer import WPSBrowserWriter
            from .wps_browser import configured_wps_target
            _, title = configured_wps_target(self.config)
            result.update(WPSBrowserWriter(self, target_title=title).run_ready(rows))
        return result

    def status(self):
        return {'readiness': 'testing' if self.config.get('wps', {}).get('enabled') else 'setup_required', 'mode': self.config['mode'], 'wps': 'browser_append_testing' if self.config.get('wps', {}).get('enabled') else 'not_connected',
            'accounts': self.store.rows('SELECT * FROM accounts'),
            'configured_accounts': [{'id': a['id'], 'name': a['name']} for a in self.config['accounts']],
            'works': self.store.rows('SELECT status,count(*) AS count FROM works GROUP BY status'),
            'public_profiles': self.config.get('public_profiles', []),
            'browser_last_run': self.store.get('browser_last_run'),
            'wps_readiness': self.store.get('wps_readiness'),
            'schedule': self.config.get('schedule'),
            'last_scheduled_run': self.store.get('last_scheduled_run'),
            'production_blockers': (['first real new scheduled append', 'actual full cycle with Codex closed', 'at least 24h observation'] if self.config.get('wps', {}).get('enabled') else ['verified public browser collection or official authorization', 'real media validation', 'WPS backup/test/approval', 'scheduler and 24h observation'])}

    def doctor(self):
        import importlib.util
        import subprocess
        task = None
        if __import__('os').name == 'nt':
            task = subprocess.run(['schtasks', '/Query', '/TN', 'DouyinViralCollect'], capture_output=True).returncode == 0
        from .media import ffmpeg_executable, model_is_ready
        try:
            ffmpeg_path = ffmpeg_executable()
        except RuntimeError:
            ffmpeg_path = None
        task_info = None
        if __import__('os').name == 'nt' and task:
            query = subprocess.run(['powershell.exe','-NoProfile','-Command',
                "$t=Get-ScheduledTask -TaskName DouyinViralCollect; $i=Get-ScheduledTaskInfo -TaskName DouyinViralCollect; @{state=[string]$t.State;enabled=[bool]$t.Settings.Enabled;start=$t.Triggers[0].StartBoundary;last_result=$i.LastTaskResult}|ConvertTo-Json -Compress"],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            if query.returncode==0:
                try:task_info=json.loads(query.stdout)
                except ValueError:pass
        return dict(self.status(), ffmpeg=bool(ffmpeg_path), ffmpeg_path=ffmpeg_path, scheduled_task_details=task_info,
            model=model_is_ready(self.path.parent / self.config['model']), scheduled_task=task,
            dependencies={m: importlib.util.find_spec(m) is not None for m in ['faster_whisper', 'rapidocr_onnxruntime', 'fastapi']},
            database=self.store.db.execute('PRAGMA integrity_check').fetchone()[0])

    def run(self, command, **kwargs):
        with lock(self.root / 'collect.lock'):
            if command in ('browser-check', 'browser-backfill', 'browser-import', 'browser-export'):
                from .browser import BrowserCollector
                collector = BrowserCollector(self)
                if command == 'browser-import': return collector.import_evidence()
                if command == 'browser-export': return collector.export_descriptions()
                return collector.run(historical=command == 'browser-backfill', **kwargs)
            if command in ('check', 'backfill'):
                return self.monitor(command == 'backfill')
            if command == 'run':
                backup = self.store.get('last_backup', 0)
                if time.time() - backup > 86400:
                    self.store.backup(); self.store.set('last_backup', time.time())
                monitored = self.monitor()
                from .reference import refresh_reference
                reference = refresh_reference(self)
                processed=self.process(retry=True)
                if self.config.get('word_export',{}).get('enabled'):
                    from .word_export import export_word
                    word=export_word(self)
                    archive=self.archive() if self.config.get('wps',{}).get('enabled') else {'remote':'disabled_by_user','destination':'local_word'}
                    if not self.config.get('wps',{}).get('enabled'):
                        for entry in word['works']:self.store.execute("UPDATE works SET status='exported_local' WHERE account_id=? AND id=? AND status='ready_to_archive'",(entry['account_id'],entry['id']))
                    return {'monitor':monitored,'reference':reference,'process':processed,'word':word,'archive':archive}
                return {'monitor': monitored, 'reference': reference, 'process': processed, 'archive': self.archive()}
            if command == 'process': return self.process(**kwargs)
            if command == 'archive': return self.archive()
            if command == 'status': return self.status()
            if command == 'doctor': return self.doctor()
            if command == 'backup': return {'backup': self.store.backup()}
            if command == 'logs': return self.store.rows('SELECT * FROM events ORDER BY rowid DESC LIMIT 50')
            if command == 'videos': return self.store.rows('SELECT account_id,id,likes,status,error FROM works')
            if command == 'import':
                path = Path(kwargs['file'])
                with path.open(encoding='utf-8-sig', newline='') as f:
                    rows = list(csv.DictReader(f)) if path.suffix.lower() == '.csv' else json.load(f)
                return self.ingest(rows, 'mock' if self.config['mode'] == 'mock' else 'import')
            raise ValueError('unknown command')
