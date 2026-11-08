import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from douyin_viral_collector.audio_quality import audio_quality
from douyin_viral_collector.service import Service
from douyin_viral_collector.publisher_selection import choose_description

class CustomerQualityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=self.root/'config.json';self.config.write_text(json.dumps({'mode':'import','data_dir':'data','threshold':29,'accounts':[],'model':'models/local','proofreading':{'enabled':True,'caption_policy':'prefer','video_subtitles':{'enabled':True}},'wps':{'enabled':False},'word_export':{'enabled':True}}),encoding='utf-8');self.s=Service(self.config)
 def tearDown(self):self.s.store.db.close();self.tmp.cleanup()
 def work(self,ident='1',description='完整的发布文案。'):
  work={'account_id':'a','account_name':'示例作者','id':ident,'type':'video','likes':31,'detail_verified':True,'description_complete':True,'description':description,'title':description,'published_at':'2026-11-08'};self.s.store.execute('INSERT INTO works(account_id,id,payload,likes,status) VALUES(?,?,?,?,?)',('a',ident,json.dumps(work,ensure_ascii=False),31,'waiting_media'));return work
 def audio(self,p=.95):
  return {'raw':'先弄明白再行动','body':'先弄明白再行动','timing':{'segments':[{'start':0,'end':3,'words':[{'word':'先弄明白','probability':p},{'word':'再行动','probability':p}]}]}}
 def test_low_confidence_is_not_exported_as_reviewed(self):
  self.assertTrue(audio_quality(self.audio())['accepted']);self.assertFalse(audio_quality(self.audio(.2))['accepted']);self.assertFalse(audio_quality({'raw':'空缺证据'})['accepted'])
 def test_no_captions_can_use_reliable_audio_and_punctuation(self):
  self.work();reader=Mock();reader.library=None;reader.process.side_effect=lambda text:dict(text,body='先弄明白，再行动。',proofreading={'punctuation_enabled':True})
  with patch('douyin_viral_collector.service.extract',return_value=self.audio()),patch('douyin_viral_collector.proofreading.Proofreader',return_value=reader),patch('douyin_viral_collector.subtitles.extract_subtitles',return_value={'status':'insufficient_captions','cues':[]}):result=self.s.run('process')
  row=self.s.store.rows('SELECT * FROM works')[0];self.assertEqual(result['ready'],1);self.assertEqual(json.loads(row['payload'])['recognition_review'],'audio_punctuation_checked');self.assertEqual(row['body'],'先弄明白，再行动。');self.assertEqual(row['raw'],'先弄明白再行动')
 def test_unreliable_audio_keeps_pending_and_raw_evidence(self):
  self.work();reader=Mock();reader.library=None
  with patch('douyin_viral_collector.service.extract',return_value=self.audio(.15)),patch('douyin_viral_collector.proofreading.Proofreader',return_value=reader),patch('douyin_viral_collector.subtitles.extract_subtitles',return_value={'status':'insufficient_captions','cues':[]}):result=self.s.run('process')
  row=self.s.store.rows('SELECT * FROM works')[0];self.assertEqual(row['status'],'waiting_review');self.assertEqual(result['waiting_review'],1);reader.process.assert_not_called();self.assertTrue(list((self.s.root/'transcripts').glob('*/raw.txt')))
 def test_publisher_choice_requires_confirmation_and_preserves_words(self):
  self.work()
  with self.assertRaises(ValueError):choose_description(self.s,'1')
  choose_description(self.s,'1',True);row=self.s.store.rows('SELECT * FROM works')[0];self.assertEqual(row['body'],'完整的发布文案。');self.assertEqual(json.loads(row['payload'])['recognition_review'],'publisher_text');self.assertIn('1',json.loads(self.config.read_text(encoding='utf-8'))['caption_only_work_ids'])
 def test_empty_publisher_text_does_not_create_a_fake_body(self):
  self.work(description='')
  with self.assertRaises(ValueError):choose_description(self.s,'1',True)
  self.assertIsNone(self.s.store.rows('SELECT body FROM works')[0]['body'])
 def test_collection_uses_history_and_never_claims_pending_is_complete(self):
  self.work();monitor={'profiles':[{'observed':47,'displayed_total':46,'historical_complete':True}],'issues':[],'unverified_count':0}
  with patch.object(self.s,'monitor',return_value=monitor) as scan,patch.object(self.s,'process',return_value={}),patch('douyin_viral_collector.reference.refresh_reference',return_value={}):result=self.s.run('run')
  scan.assert_called_once_with(historical=True);self.assertFalse(result['word']['document_generated']);self.assertFalse(result['word']['delivery_ready']);self.assertEqual(result['word']['pending_count'],1)
