import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from douyin_viral_collector.desktop_runner import DesktopRunner
from douyin_viral_collector.media_binding import bind_media
from douyin_viral_collector.service import Service


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.events=[]
        self.runner=DesktopRunner(self.root,self.events.append)
        self.config={'mode':'browser','data_dir':'data','minimum_likes':500,'accounts':[],
            'public_profiles':[{'sec_uid':'example','name':'示例','name_verified':False}],
            'wps':{'enabled':True,'url':'private-target'},'word_export':{'enabled':True}}
        (self.root/'config.json').write_text(json.dumps(self.config),encoding='utf-8')
        self.model=self.root/'models/faster-whisper-small/model.bin';self.model.parent.mkdir(parents=True);self.model.write_bytes(b'fixture')
    def tearDown(self):self.tmp.cleanup()
    def test_independent_flow_orders_login_before_collection_and_disables_cloud(self):
        calls=[]
        def command(args,login=False):
            calls.append((args,login))
            if args[-1]=='organize':return {'word':{'path':'sample.docx','count':2}}
            return {}
        with patch.object(self.runner,'prepare'),patch.object(self.runner,'_command',side_effect=command):
            self.runner.start('https://www.douyin.com/user/example','500')
        self.assertEqual([c[0][2] for c in calls],['setup','login','organize']);self.assertTrue(calls[1][1]);self.assertFalse(self.runner.config()['wps']['enabled']);self.assertEqual(self.events[-1]['count'],2)
    def test_login_failure_does_not_start_collection(self):
        def command(args,login=False):
            if login:raise RuntimeError('需要用户验证')
            self.assertNotEqual(args[-1],'organize');return {}
        with patch.object(self.runner,'prepare'),patch.object(self.runner,'_command',side_effect=command):
            with self.assertRaisesRegex(RuntimeError,'用户验证'):self.runner.start('https://www.douyin.com/user/example','500')
    def test_verified_profiles_do_not_repeat_manual_login(self):
        self.config['public_profiles'][0]['name_verified']=True;(self.root/'config.json').write_text(json.dumps(self.config),encoding='utf-8');calls=[]
        with patch.object(self.runner,'prepare'),patch.object(self.runner,'_command',side_effect=lambda args,**kw:calls.append(args) or {}):self.runner.start('https://www.douyin.com/user/example','500')
        self.assertEqual([c[2] for c in calls],['setup','organize'])
    def test_invalid_input_prevents_environment_install(self):
        with patch.object(self.runner,'prepare') as prepare:
            with self.assertRaises(ValueError):self.runner.start('not a profile','500')
            with self.assertRaises(ValueError):self.runner.start('https://www.douyin.com/user/example','-1')
        prepare.assert_not_called()
    def test_work_list_is_read_only_and_honors_threshold(self):
        service=Service(self.root/'config.json')
        try:
            for likes in (499,500):service.store.execute('INSERT INTO works(account_id,id,payload,likes,status) VALUES(?,?,?,?,?)',('a',str(likes),json.dumps({'account_name':'示例作者','title':'示例标题'}),likes,'waiting_media'))
        finally:service.store.db.close()
        items=self.runner.items();self.assertEqual([i['likes'] for i in items],[500]);self.assertEqual(items[0]['status'],'waiting_media')
    def test_original_video_mapping_cannot_overwrite_an_existing_export(self):
        service=Service(self.root/'config.json');source=self.root/'original.mp4';source.write_bytes(b'fixture')
        try:
            payload=json.dumps({'id':'x','type':'video','detail_verified':True,'title':'保留标题'})
            service.store.execute('INSERT INTO works(account_id,id,payload,likes,status,body) VALUES(?,?,?,?,?,?)',('a','x',payload,600,'exported_local','用户校订'))
            with self.assertRaises(ValueError):bind_media(service,'x',source)
            self.assertEqual(service.store.rows('SELECT body FROM works')[0]['body'],'用户校订')
        finally:service.store.db.close()
    def test_original_video_mapping_resumes_only_selected_pending_work(self):
        service=Service(self.root/'config.json');source=self.root/'original.mp4';source.write_bytes(b'fixture')
        try:
            payload=json.dumps({'id':'x','type':'video','detail_verified':True,'title':'保留标题'})
            service.store.execute('INSERT INTO works(account_id,id,payload,likes,status) VALUES(?,?,?,?,?)',('a','x',payload,600,'waiting_media'))
            with patch('douyin_viral_collector.media_binding.inspect_media',return_value={'audio':True,'video':True}):result=bind_media(service,'x',source)
            row=service.store.rows('SELECT * FROM works')[0];work=json.loads(row['payload']);self.assertEqual(row['status'],'discovered');self.assertEqual(work['title'],'保留标题');self.assertEqual(work['subtitle_media'],[str(source.resolve())]);self.assertEqual(result['mapping_source'],'user_selected_work_id')
        finally:service.store.db.close()
