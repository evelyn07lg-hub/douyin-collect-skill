import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from douyin_viral_collector.service import Service
from douyin_viral_collector.storage import lock


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'mode': 'mock', 'data_dir': 'data', 'threshold': 500,
            'model': 'models/local', 'accounts': [{'id': str(i), 'name': str(i)} for i in range(3)]}))
        self.s = Service(self.config)

    def tearDown(self):
        self.s.store.db.close()
        self.tmp.cleanup()

    def add(self, aid='0', vid='x', likes=501):
        return self.s.ingest([{'account_id': aid, 'id': vid, 'likes': likes}], 'mock')

    def test_proofreading_failure_keeps_raw_and_prevents_ready(self):
        self.add()
        self.s.config['proofreading']={'enabled':True,'reference_path':'missing.docx'}
        with patch('douyin_viral_collector.service.extract', return_value={'raw':'原始完整识别','body':'尚未校对的正文'}):
            self.assertEqual(self.s.run('process')['failed'],1)
        raw=list((self.s.root/'transcripts').glob('*/raw.txt'))
        self.assertEqual(raw[0].read_text(encoding='utf-8'),'原始完整识别')
        self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'failed')

    def test_reference_refresh_failure_stops_archive(self):
        with patch.object(self.s,'monitor',return_value={}), patch('douyin_viral_collector.reference.refresh_reference',side_effect=RuntimeError('not available')), patch.object(self.s,'archive') as archive:
            with self.assertRaises(RuntimeError):self.s.run('run')
            archive.assert_not_called()

    def test_missing_video_subtitles_keeps_raw_and_waits(self):
        self.add()
        self.s.config['proofreading']={'enabled':True,'video_subtitles':{'enabled':True}}
        from unittest.mock import Mock
        reader=Mock();reader.library=None
        with patch('douyin_viral_collector.service.extract',return_value={'raw':'完整听写结果','body':'待字幕核对的正文'}), patch('douyin_viral_collector.proofreading.Proofreader',return_value=reader), patch('douyin_viral_collector.subtitles.extract_subtitles',return_value={'status':'video_unavailable','reason':'audio_only','cues':[]}):
            result=self.s.run('process')
        self.assertEqual(result['waiting_subtitles'],1)
        self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'waiting_subtitles')
        self.assertEqual(list((self.s.root/'transcripts').glob('*/raw.txt'))[0].read_text(encoding='utf-8'),'完整听写结果')
        reader.process.assert_not_called()

    def test_old_audio_only_ready_draft_cannot_bypass_caption_gate(self):
        self.add();self.s.store.execute("UPDATE works SET status='ready_to_archive',body='旧听写正文'")
        self.s.config['proofreading']={'video_subtitles':{'enabled':True}}
        with self.assertRaises(RuntimeError):self.s.run('archive')
        self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'waiting_subtitles')

    def test_strict_threshold(self):
        for n in (499, 500, 501): self.add(vid=str(n), likes=n)
        with patch('douyin_viral_collector.service.extract', return_value=None) as extract:
            result = self.s.run('process')
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(result['waiting_media'], 1)

    def test_account_identity_and_dedup(self):
        for aid in ('0', '1', '2'):
            self.add(aid); self.add(aid)
        self.assertEqual(len(self.s.run('videos')), 3)

    def test_crash_resume_and_cached_body(self):
        self.add()
        self.s.store.execute("UPDATE works SET status='processing'")
        with patch('douyin_viral_collector.service.extract', return_value={'raw': '原文', 'body': '正文'}):
            self.assertEqual(self.s.run('process')['ready'], 1)
        with patch('douyin_viral_collector.service.extract') as extract:
            self.s.run('process'); extract.assert_not_called()
        self.assertEqual(self.s.store.rows('SELECT raw FROM works')[0]['raw'], '原文')
        files = list((self.s.root / 'transcripts').glob('*/recognition.json'))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text(encoding='utf-8'))['raw'], '原文')

    def test_failed_retry(self):
        self.add()
        with patch('douyin_viral_collector.service.extract', side_effect=ValueError('bad sample')):
            self.assertEqual(self.s.run('process')['failed'], 1)
        with patch('douyin_viral_collector.service.extract', return_value={'raw': 'hello', 'body': 'hello'}):
            self.assertEqual(self.s.run('process', retry=True)['ready'], 1)

    def test_outbox_idempotent_and_not_remote_success(self):
        self.add()
        self.s.store.execute("UPDATE works SET status='ready_to_archive',body=?", ('完整正文' * 10000,))
        a = self.s.run('archive'); b = self.s.run('archive')
        self.assertEqual(a['files'], b['files'])
        self.assertIn('完整正文' * 10000, Path(a['files'][0]).read_text(encoding='utf-8'))
        self.assertEqual(self.s.run('videos')[0]['status'], 'ready_to_archive')

    def test_wps_failure_preserves_status(self):
        self.add()
        self.s.store.execute("UPDATE works SET status='ready_to_archive',body='text'")
        with patch('douyin_viral_collector.wps.LocalArchive.stage', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.s.run('archive')
        self.assertEqual(self.s.run('videos')[0]['status'], 'ready_to_archive')

    def test_lock_prevents_overlap(self):
        with lock(self.s.root / 'collect.lock'):
            with self.assertRaises(RuntimeError): self.s.run('process')
        self.s.run('process')

    def test_backup_valid(self):
        import sqlite3
        self.add()
        target = self.s.run('backup')['backup']
        import contextlib
        with contextlib.closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM works').fetchone()[0], 1)

    def test_cli_json_without_n8n(self):
        result = subprocess.run([sys.executable, '-m', 'douyin_viral_collector.cli', '--config',
            str(self.config), 'status'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['result']['mode'], 'mock')

    def test_missing_media_real_extractor(self):
        self.add()
        self.assertEqual(self.s.run('process')['waiting_media'], 1)

    def test_history_pagination(self):
        from douyin_viral_collector.douyin import Official
        api = Official({'id': '0', 'token_env': 'TEST'}, self.s.store)
        responses = [{'list': [{'item_id': 'one'}], 'cursor': 1, 'has_more': True},
                     {'list': [{'item_id': 'two'}], 'cursor': 2, 'has_more': False}]
        with patch.object(api, 'authorize'), patch.object(api, 'request', side_effect=responses):
            self.assertEqual(len(list(api.scan(True))), 2)

    def test_ordered_ocr_and_cache(self):
        import types
        from douyin_viral_collector.media import extract
        a, b = self.root / 'a.png', self.root / 'b.png'
        a.write_bytes(b'first'); b.write_bytes(b'second')
        engine = unittest.mock.Mock(side_effect=[([[None, '第一页', .99]], None), ([[None, '第二页', .99]], None)])
        fake = types.SimpleNamespace(RapidOCR=lambda: engine)
        work = {'account_id': '0', 'id': 'images', 'type': 'image', 'media': [str(a), str(b)]}
        with patch.dict(sys.modules, {'rapidocr_onnxruntime': fake}):
            text = extract(work, self.s.root, 'local')
            self.assertLess(text['raw'].index('第一页'), text['raw'].index('第二页'))
            self.assertEqual(extract(work, self.s.root, 'local'), text)
            self.assertEqual(engine.call_count, 2)


if __name__ == '__main__': unittest.main()
