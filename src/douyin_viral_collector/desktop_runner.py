"""Standard-library controller used by the independent desktop window."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path


class DesktopRunner:
    def __init__(self, root, emit=lambda event: None):
        self.root = Path(root).resolve()
        self.emit = emit
        self.python = self.root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.cancelled = threading.Event()
        self.process = None

    def _command(self, args, login=False):
        if self.cancelled.is_set():
            raise RuntimeError('操作已取消')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
        env['COLLECT_PROGRESS']='1'
        env['PYTHONPATH']=str(self.root/'src')+os.pathsep+env.get('PYTHONPATH','')
        command = [str(self.python), '-u', *map(str, args)]
        self.process = subprocess.Popen(command, cwd=self.root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if login:
            self.emit({'kind': 'login_required'})
        answer = None
        try:
            for line in self.process.stdout:
                self.emit({'kind': 'log', 'text': line.rstrip()})
                try:
                    item = json.loads(line)
                    if isinstance(item,dict) and item.get('event')=='progress':
                        self.emit({'kind':'stage','text':item['message']})
                        continue
                    if isinstance(item, dict) and 'ok' in item:
                        answer = item
                except ValueError:
                    pass
            code = self.process.wait()
            if self.cancelled.is_set():
                raise RuntimeError('操作已取消')
            if code or (answer is not None and not answer['ok']):
                raise RuntimeError((answer or {}).get('error') or '当前步骤未完成，请查看运行记录。')
            return (answer or {}).get('result', {})
        finally:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None

    def continue_login(self):
        process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write('\n')
            process.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def cancel(self):
        self.cancelled.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def prepare(self):
        from .environment_setup import choose_runtime,requirements
        self.emit({'kind':'stage','text':'检测已有依赖和可复用的 Python 环境'})
        check_config=self.config()
        if getattr(self,'_review_requested',False):check_config.setdefault('proofreading',{})['enabled']=True
        phase=getattr(self,'_phase','collect');features=['core'] if phase=='export' else ['core','browser'] if phase=='login' else None
        needed=requirements(check_config,features=features);self.python,missing=choose_runtime(self.root,sys.executable,needed)
        if not missing:
            self.emit({'kind':'stage','text':'依赖已就绪，跳过安装'})
            return
        if not self.python.is_file():
            self.emit({'kind':'stage','text':'创建项目专用环境'})
            subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(self.root/'.venv')],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        from .environment_setup import probe
        detected=probe(self.python,needed)
        if detected is not None:missing=detected['missing']
        if not missing:
            self.emit({'kind':'stage','text':'依赖已就绪，跳过安装'})
            return
        self.emit({'kind':'stage','text':f'补齐 {len(missing)} 个缺失组件，详情见运行记录'})
        self.emit({'kind':'log','text':'缺失组件：'+', '.join(missing)})
        self._command(['-m','pip','install','--prefer-binary','--disable-pip-version-check',*missing])
        from .environment_setup import probe
        checked=probe(self.python,needed)
        if checked is None or checked['missing']:raise RuntimeError('依赖检查未通过，请查看运行记录。')

    @staticmethod
    def validate(profiles, minimum):
        from .share_links import extract_links
        urls = extract_links(profiles)
        if isinstance(minimum, bool) or not str(minimum).isdigit():
            raise ValueError('点赞门槛需要填写非负整数。')
        return list(dict.fromkeys(urls)), int(minimum)

    def config(self):
        path = self.root / 'config.json'
        return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}

    def start(self, profiles, minimum, strict=False, output_dir='exports', model='small', login_only=False, browser='edge', review=True, image_mode='published_copy'):
        urls, minimum = self.validate(profiles, minimum)
        if model not in ('small', 'large-v3-turbo'):
            raise ValueError('不支持的本地识别模型。')
        self.cancelled.clear()
        self._review_requested=review
        self._phase='login' if login_only else 'collect'
        self.prepare()
        if browser not in ('edge','chrome'):raise ValueError('请选择 Edge 或 Chrome')
        selected=self.config()
        if not selected:
            selected=json.loads((self.root/'config.example.json').read_text(encoding='utf-8-sig'))
        selected['browser']=browser
        selected.setdefault('collection',{})['image_mode']=image_mode
        selected.setdefault('proofreading',{})['enabled']=bool(review)
        selected['proofreading'].setdefault('video_subtitles',{})['enabled']=bool(review)
        selected['proofreading']['caption_policy']='prefer'
        selected['proofreading']['video_subtitles']['sample_fps']=2
        selected.setdefault('word_export',{})['review_required']=bool(review)
        if selected:(self.root/'config.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
        self.emit({'kind': 'stage', 'text': '保存账号和整理条件'})
        args = ['-m', 'douyin_viral_collector.cli', 'setup', '--min-likes', minimum, '--output-dir', output_dir]
        for url in urls:
            args += ['--profile', url]
        if strict:
            args.append('--strict')
        self._command(args)
        config = self.config()
        from .environment_setup import existing_model
        reused=existing_model(self.root,sys.executable,model)
        config['model'] = str(reused) if reused else 'models/faster-whisper-' + model
        if reused:self.emit({'kind':'stage','text':'已找到本机识别模型，跳过下载'})
        config.setdefault('wps', {}).setdefault('enabled', False)
        (self.root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if not login_only and not (self.root / config['model'] / 'model.bin').is_file():
            self.emit({'kind': 'stage', 'text': '首次下载识别模型，此步骤可能需要较长时间'})
            self._command(['scripts/download-model.py', '--model', model])
        if review and not login_only:
            from .quality_setup import punctuation_model
            self.emit({'kind':'stage','text':'检查自动断句组件'})
            punctuation=punctuation_model(self.root,sys.executable)
            if punctuation is None:
                self.emit({'kind':'stage','text':'首次准备标点模型，已有模型将自动复用'})
                self._command(['scripts/download-punctuation.py'])
                punctuation=punctuation_model(self.root,sys.executable)
            if punctuation is None:raise RuntimeError('标点模型未准备完成，请查看运行记录')
            config.setdefault('proofreading',{})['punctuation_model']=str(punctuation)
            (self.root/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        known = config.get('public_profiles', [])
        if login_only or not known or not all(p.get('name_verified') for p in known):
            self.emit({'kind': 'stage', 'text': '请在浏览器完成抖音登录，再点击“登录完成，继续”'})
            self._command(['-m', 'douyin_viral_collector.cli', 'login'], login=True)
        if login_only:
            self.emit({'kind': 'stage', 'text': '登录已完成，可以开始整理。'})
            return {}
        self.emit({'kind': 'stage', 'text': '正在采集和识别，较长视频需要更多时间'})
        result = self._command(['-m', 'douyin_viral_collector.cli', 'organize'])
        monitor=result.get('monitor',{});profiles=monitor.get('profiles',[])
        self.emit({'kind': 'export', **result.get('word', {}), 'scan_observed':sum(p.get('observed',0) for p in profiles),'scan_total':sum(p.get('displayed_total',0) or 0 for p in profiles),'scan_partial':monitor.get('monitor')!='browser_verified'})
        return result

    def export(self):
        self._phase='export'
        self.cancelled.clear()
        if not (self.root / 'config.json').is_file():
            raise ValueError('请先填写账号并开始首次整理。')
        self.prepare()
        result = self._command(['-m', 'douyin_viral_collector.cli', 'export-word'])
        self.emit({'kind': 'export', **result})
        return result

    def bind_and_process(self, work_id, filename):
        self._phase='collect'
        self.cancelled.clear()
        self.prepare()
        self._command(['-m', 'douyin_viral_collector.cli', 'bind-media', '--work-id', work_id, '--file', filename])
        self.emit({'kind': 'stage', 'text': '正在识别关联的原视频'})
        self._command(['-m', 'douyin_viral_collector.cli', 'process', '--retry'])
        return self.export()

    def use_description(self,work_id):
        self.cancelled.clear();self._phase='export';self.prepare()
        self._command(['-m','douyin_viral_collector.cli','use-description','--work-id',work_id,'--confirm-no-speech'])
        return self.export()

    def items(self):
        config = self.config()
        database = self.root / config.get('data_dir', 'data') / 'collect.sqlite3'
        if not database.is_file():
            return []
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute('SELECT id,payload,likes,status FROM works ORDER BY checked_at DESC').fetchall()
            candidates=connection.execute('SELECT id,payload,error,detail_status FROM browser_candidates WHERE detail_status IS NULL OR detail_status!=?',('verified',)).fetchall() if connection.execute("SELECT 1 FROM sqlite_master WHERE name='browser_candidates'").fetchone() else []
        finally:
            connection.close()
        items = []
        threshold = config.get('minimum_likes', config.get('threshold', 500) + 1)
        for row in rows:
            if row['likes'] < threshold:
                continue
            item = json.loads(row['payload'])
            items.append({'id': row['id'], 'account': item.get('account_name', ''),
                'date': item.get('published_at', ''), 'title': item.get('title', ''),
                'url':item.get('url'),'likes': item.get('likes_display') if item.get('likes_exact') is False else row['likes'], 'status': row['status']})
        known={r['id'] for r in rows}
        for row in candidates:
            if row['id'] in known:continue
            work=json.loads(row['payload']);likes=work.get('likes_exact_display')
            if likes is not None and likes<threshold:continue
            items.append({'id':row['id'],'account':work.get('account_name',''),'date':'待核验','title':work.get('description') or '无发布文案作品（待核验）','url':work.get('url'),'likes':likes if likes is not None else '待核验','status':'excluded_other_author' if row['detail_status']=='excluded_other_author' else 'detail_review_required'})
        return items
