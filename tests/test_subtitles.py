import unittest,tempfile,wave
from pathlib import Path
from douyin_viral_collector.subtitles import merge_observations,regroup,subtitle_video
from douyin_viral_collector.transcript_fusion import reconcile,repair_ocr_confusions
from douyin_viral_collector.proofreading import Proofreader
from unittest.mock import Mock


def timed(text,start=0,end=2):
 return {'raw':text,'body':text,'timing':{'segments':[{'start':start,'end':end,'text':text,'words':[{'start':start,'end':end,'word':text,'probability':.99}]}]}}


def captions(text,start=0,end=2):
 return {'status':'extracted','cues':[{'text':text,'start':start,'end':end,'confidence':.99,'samples':4}]}


class SubtitleTests(unittest.TestCase):
 def test_repeated_display_deduplicates_but_later_repeat_remains(self):
  data=[{'time':i*.25,'text':text,'confidence':.99} for i,text in enumerate(['第一句话','第一句话','第二句话','第二句话','第一句话','第一句话'])]
  self.assertEqual([x['text'] for x in merge_observations(data,.25)],['第一句话','第二句话','第一句话'])
 def test_ocr_flicker_uses_multi_frame_majority(self):
  values=['它就是呢性价比的产品会越来越卷']+['它就是啊性价比的产品会越来越卷']*5
  result=merge_observations([{'time':i*.25,'text':text,'confidence':.99} for i,text in enumerate(values)],.25)
  self.assertEqual(len(result),1);self.assertEqual(result[0]['text'],values[-1])
 def test_real_semantic_and_number_change_are_retained(self):
  for values in [('今年我们的这个产品有很多客户','明年我们的这个产品有很多客户'),('这个产品一年可以挣10万元','这个产品一年可以挣20万元')]:
   data=[{'time':i*.25,'text':text,'confidence':.99} for i,text in enumerate(values)]
   self.assertEqual(len(merge_observations(data,.25)),2)
 def test_incremental_caption_keeps_complete_display(self):
  data=[{'time':i*.25,'text':text,'confidence':.99} for i,text in enumerate(['我们要','我们要','我们要继续行动'])]
  self.assertEqual(merge_observations(data,.25)[0]['text'],'我们要继续行动')
 def test_user_confirmed_term_has_priority_over_subtitle_and_audio(self):
  asr=timed('这个狐狸圈子就是最混乱的时期')
  result=reconcile(asr,captions('这个即刻圈子就是最混乱的时期'),ocr_corrections=[{'before':'即刻圈子','after':'蝴蝶圈子','context':'混乱'}])
  self.assertIn('蝴蝶圈子',result['body']);self.assertNotIn('即刻圈子',result['body'])
 def test_short_caption_is_allowed_and_fusion_still_checks_relevance(self):
  data={'sample_fps':4,'raw_observations':[{'time':0,'text':'我们接着行动','confidence':.99},{'time':.25,'text':'我们接着行动','confidence':.99}]}
  self.assertEqual(regroup(data)['status'],'extracted')
 def test_user_term_cannot_be_undone_by_a_library_suggestion(self):
  class Library:
   text='狐狸圈子';sha256='test'
   def correct(self,text):
    at=text.find('蝴蝶圈子')
    return text,([{'start':at,'end':at+4,'before':'蝴蝶圈子','after':'狐狸圈子'}] if at>=0 else [])
  result=reconcile(timed('这个狐狸圈子就是最混乱的时期'),captions('这个即刻圈子就是最混乱的时期'),library=Library(),ocr_corrections=[{'before':'即刻圈子','after':'蝴蝶圈子'}])
  self.assertIn('蝴蝶圈子',result['body'])
 def test_complete_browser_buffer_uses_only_finished_authorized_response(self):
  from douyin_viral_collector.media_sources import complete_browser_buffer
  response=Mock();response.status=206;response.headers={'content-range':'bytes 0-2/3'};response.body.return_value=b'abc'
  source={'bytes':3,'_browser_response':response,'_finished':False}
  self.assertIsNone(complete_browser_buffer(source));response.body.assert_not_called()
  source['_finished']=True;self.assertEqual(complete_browser_buffer(source),b'abc')
  response.status=403;self.assertIsNone(complete_browser_buffer(source))
 def test_browser_caption_evidence_must_match_the_requested_work(self):
  from douyin_viral_collector.subtitles import browser_caption_evidence
  import json
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);p=root/'caption.json';p.write_text(json.dumps({'account_id':'other','work_id':'2','capture_complete':True}),encoding='utf-8')
   with self.assertRaises(ValueError):browser_caption_evidence({'account_id':'a','id':'1','subtitle_capture':str(p)},root)
 def test_two_other_sources_can_correct_a_contextually_wrong_caption_word(self):
  from douyin_viral_collector.transcript_fusion import repair_reference_audio_phrases
  library=Mock();library.text='情绪类目产品如何提高客单价'
  result,changes=repair_reference_audio_phrases('如果你也是做情趣类目产品的','如果你也是做情绪类目产品的',library)
  self.assertEqual(result,'如果你也是做情绪类目产品的');self.assertTrue(changes)
 def test_phrase_guess_does_not_override_a_user_confirmed_term(self):
  from douyin_viral_collector.transcript_fusion import repair_reference_audio_phrases
  library=Mock();library.text='情绪类目产品如何提高客单价'
  result,_=repair_reference_audio_phrases('如果你也是做情趣类目产品的','如果你也是做情绪类目产品的',library,['情趣类目'])
  self.assertIn('情趣类目',result)
 def test_phrase_guess_does_not_infer_dates_or_amounts(self):
  from douyin_viral_collector.transcript_fusion import repair_reference_audio_phrases
  library=Mock();library.text='明年我们的产品成本是三万元'
  result,_=repair_reference_audio_phrases('今年我们的产品成本是五万元','明年我们的产品成本是三万元',library)
  self.assertEqual(result,'今年我们的产品成本是五万元')
 def test_audio_only_media_is_not_represented_as_caption_video(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);audio=root/'audio.wav'
   with wave.open(str(audio),'wb') as f:f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
   self.assertIsNone(subtitle_video({'account_id':'a','id':'1','media':[str(audio)]},root))
 def test_author_subtitle_overrides_misheard_audio(self):
  asr=timed('我卖回责标本能够赚钱');result=reconcile(asr,captions('我卖蝴蝶标本能够赚钱'))
  self.assertEqual(result['body'],'我卖蝴蝶标本能够赚钱');self.assertEqual(result['raw'],asr['raw']);self.assertTrue(result['subtitle_primary'])
 def test_caption_numbers_are_not_replaced_by_reference_or_audio(self):
  result=reconcile(timed('我现在需要准备3000元资金'),captions('我现在需要准备5000元资金'))
  self.assertIn('5000',result['body'])
 def test_unrelated_background_text_is_rejected(self):
  with self.assertRaises(ValueError):reconcile(timed('今天讲创业收入和产品营销'),captions('这是一个完全无关的餐厅招牌'))
 def test_uncaptioned_audio_gap_is_retained(self):
  parts=[('第一段口播',0,1),('中间这句没有字幕',3,4),('最后一段内容',6,7)]
  asr={'raw':''.join(x[0] for x in parts),'body':'','timing':{'segments':[{'text':text,'start':a,'end':b} for text,a,b in parts]}}
  subs={'status':'extracted','cues':[captions(text,a,b)['cues'][0] for text,a,b in [parts[0],parts[2]]]}
  result=reconcile(asr,subs,minimum_coverage=.5);self.assertIn('中间这句没有字幕',result['body'])
 def test_proofreader_does_not_blindly_apply_library_rules_to_captions(self):
  p=Proofreader.__new__(Proofreader);p.settings={'reviewed_replacements':[{'before':'正确字幕','after':'错误改写'}]};p.library=Mock();p.punctuator=None
  p.library.correct.side_effect=AssertionError('Subtitle must remain primary')
  result=p.process(dict(timed('这是正确字幕。'),subtitle_primary=True))
  self.assertEqual(result['body'],'这是正确字幕。')
 def test_ocr_shape_confusion_uses_spoken_context(self):
  result,changes=repair_ocr_confusions('目本经济下行','参考日本经济下行的三十年',None)
  self.assertEqual(result,'日本经济下行');self.assertTrue(changes)

if __name__=='__main__':unittest.main()
