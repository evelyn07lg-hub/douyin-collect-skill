import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from docx.oxml.ns import qn
from douyin_viral_collector.service import Service
from douyin_viral_collector.onboarding import setup
from douyin_viral_collector.word_export import export_word

class WordWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'config.json'
  self.path.write_text(json.dumps({'mode':'import','data_dir':'data','minimum_likes':500,'accounts':[],'wps':{'enabled':False},'word_export':{'enabled':True}}),encoding='utf-8');self.s=Service(self.path)
 def tearDown(self):self.s.store.db.close();self.tmp.cleanup()
 def records(self):
  return [dict(account_name='示例作者'+str(i),id=str(i),likes=500,published_at='2026-10-23',title='示例标题',body='第一段，带标点。\n第二段保持原文。') for i in range(5)]
 def test_independent_word_arbitrary_accounts_and_typography(self):
  result=export_word(self.s,records=self.records(),cover=False);self.assertEqual(result['count'],5);self.assertFalse(result['cloud_sharing_enabled'])
  doc=Document(result['path']);self.assertEqual(doc.styles['Normal'].font.size.pt,10.5);self.assertEqual(doc.styles['Normal'].element.rPr.rFonts.get(qn('w:eastAsia')),'宋体')
  heads=[p for p in doc.paragraphs if p.style.name=='Heading 1'];self.assertEqual(len(heads),5);self.assertEqual(doc.styles['Heading 1'].font.size.pt,14);self.assertTrue(all(p.paragraph_format.page_break_before for p in heads[1:]));self.assertIn('第二段保持原文。',[p.text for p in doc.paragraphs]);self.assertIn('评论待获取',doc.paragraphs[1].text)
 def test_boundaries_and_old_configuration(self):
  rows=self.records()[:1];rows.append(dict(rows[0],id='below',likes=499));self.assertEqual(export_word(self.s,records=rows)['count'],1)
  self.s.config.pop('minimum_likes');self.s.config['threshold']=500
  with self.assertRaises(ValueError):export_word(self.s,records=rows)
 def test_existing_output_and_conflicting_body_protected(self):
  out=self.root/'mine.docx';out.write_bytes(b'preserve')
  with self.assertRaises(ValueError):export_word(self.s,out,records=self.records())
  self.assertEqual(out.read_bytes(),b'preserve');rows=self.records()[:1]
  with self.assertRaises(ValueError):export_word(self.s,records=rows+[dict(rows[0],body='另一个版本')])
 def test_pending_is_reported_without_empty_success(self):
  self.s.store.execute("INSERT INTO works(account_id,id,payload,likes,status) VALUES(?,?,?,?,?)",('a','x',json.dumps({'id':'x','likes':600}),600,'waiting_media'))
  with self.assertRaises(ValueError):export_word(self.s)
  report=json.loads(next((self.root/'exports').glob('*.json')).read_text(encoding='utf-8'));self.assertFalse(report['document_generated']);self.assertEqual(report['pending'][0]['status'],'waiting_media')
 def test_fresh_setup_without_cloud_or_incremental_baseline(self):
  path=self.root/'new.json';result=setup(path,profiles=['https://www.douyin.com/user/example_'+str(i) for i in range(5)],min_likes=100)
  cfg=json.loads(path.read_text(encoding='utf-8'));self.assertEqual(len(cfg['public_profiles']),5);self.assertEqual(cfg['minimum_likes'],100);self.assertFalse(cfg['wps']['enabled']);self.assertNotIn('append_policy',cfg);self.assertEqual(cfg['accounts'],[])
 def test_word_mode_does_not_call_cloud_archive(self):
  row=dict(self.records()[0],account_id='a');self.s.store.execute("INSERT INTO works(account_id,id,payload,likes,status,body) VALUES(?,?,?,?,?,?)",('a',row['id'],json.dumps(row),500,'ready_to_archive',row['body']))
  with patch.object(self.s,'monitor',return_value={}),patch.object(self.s,'process',return_value={}),patch('douyin_viral_collector.reference.refresh_reference',return_value={}),patch.object(self.s,'archive') as archive:
   result=self.s.run('run')
  archive.assert_not_called();self.assertEqual(result['word']['count'],1);self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'exported_local')

 def test_status_reports_real_word_export_without_cloud_setup_blocker(self):
  self.assertEqual(self.s.status()['readiness'],'local_word_configured')
  result=export_word(self.s,records=self.records())
  status=self.s.status();self.assertEqual(status['readiness'],'local_export_verified');self.assertEqual(status['wps'],'optional_disabled');self.assertEqual(status['last_word_export']['count'],5)
  Path(result['path']).unlink();self.assertEqual(self.s.status()['readiness'],'local_word_configured')
 def test_publication_dates_respect_timezone_and_timestamp(self):
  from douyin_viral_collector.word_export import _date
  self.assertEqual(_date('2026-10-01T20:30:00Z'),'2026年10月2日');self.assertEqual(_date(0),'1970年1月1日');self.assertEqual(_date(None),'发布时间待获取')

 def test_direct_word_export_records_local_success_but_preserves_cloud_queue(self):
  item=dict(self.records()[0],account_id='a');self.s.store.execute("INSERT INTO works(account_id,id,payload,likes,status,body) VALUES(?,?,?,?,?,?)",('a',item['id'],json.dumps(item),500,'ready_to_archive',item['body']))
  export_word(self.s);self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'exported_local')
  self.s.store.execute("UPDATE works SET status='ready_to_archive'");self.s.config['wps']['enabled']=True;export_word(self.s);self.assertEqual(self.s.store.rows('SELECT status FROM works')[0]['status'],'ready_to_archive')
