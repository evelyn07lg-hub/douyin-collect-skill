import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from douyin_viral_collector.service import Service
from douyin_viral_collector.append_policy import ensure_baseline,eligible
from douyin_viral_collector.media_sources import collect_response,save_visible_audio


class AppendPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        path=self.root/'config.json';path.write_text(json.dumps({'data_dir':'data','threshold':500,'accounts':[],
            'append_policy':{'start_at':'2026-11-03T00:00:00+08:00'}}),encoding='utf-8')
        self.s=Service(path);ensure_baseline(self.s.store)
        self.work={'account_id':'a','id':'1','likes':501,'published_at':'2026-11-03 08:00'}
    def tearDown(self):self.s.store.db.close();self.tmp.cleanup()
    def check(self,work=None):return eligible(work or self.work,self.s.store,self.s.config)[0]
    def test_new_qualified_work(self):self.assertTrue(self.check())
    def test_500_does_not_qualify(self):self.assertFalse(self.check(dict(self.work,likes=500)))
    def test_previously_qualified_history_is_skipped(self):
        self.s.store.execute('INSERT INTO append_baseline VALUES(?,?,?,?)',('a','1',501,'setup'))
        self.assertFalse(self.check())
    def test_old_low_work_can_newly_cross_threshold(self):
        self.s.store.execute('INSERT INTO append_baseline VALUES(?,?,?,?)',('a','1',500,'setup'))
        self.assertTrue(self.check(dict(self.work,published_at='2026-10-01')))
    def test_older_unseen_high_work_is_not_backfilled(self):
        self.assertFalse(self.check(dict(self.work,published_at='2026-10-01')))
        self.assertEqual(self.s.store.rows('SELECT likes FROM append_baseline')[0]['likes'],501)
    def test_unrecorded_latest_video_is_not_lost_to_activation_baseline(self):
        self.s.config['append_policy']['recorded_through']={'a':'2026-10-23'}
        self.s.store.execute('INSERT INTO append_baseline VALUES(?,?,?,?)',('a','1',501,'setup'))
        self.assertTrue(self.check(dict(self.work,published_at='2026-10-30')))

    def test_unknown_date_never_qualifies(self):self.assertFalse(self.check(dict(self.work,published_at='unknown')))


    def test_explicit_history_approval_is_limited_to_exact_account_and_work(self):
        self.s.config['append_policy']['approved_historical_works']=[{'account_id':'a','id':'1'}]
        old=dict(self.work,published_at='2026-10-01')
        self.assertTrue(self.check(old))
        self.assertFalse(self.check(dict(old,id='2')))
        self.assertFalse(self.check(dict(old,account_id='b')))
        self.assertFalse(self.check(dict(old,likes=500)))

    def test_explicit_history_approval_still_requires_publication_date(self):
        self.s.config['append_policy']['approved_historical_works']=[{'account_id':'a','id':'1'}]
        self.assertFalse(self.check(dict(self.work,published_at='unknown')))


class AuthorizedSourceTests(unittest.TestCase):
    def response(self,url='https://v11-weba.douyinvod.com/video',status=206):
        response=Mock();response.url=url;response.status=status
        response.headers={'content-type':'video/mp4','content-range':'bytes 0-9/100'}
        return response
    def test_only_actual_https_media_hosts_are_collected(self):
        sources={};collect_response(self.response(),sources);self.assertEqual(len(sources),1)
        for url in ('http://v11-weba.douyinvod.com/video','https://v11-weba.douyinvod.com.evil.test/video','https://127.0.0.1/video'):
            result={};collect_response(self.response(url),result);self.assertEqual(result,{})
        result={};collect_response(self.response(status=403),result);self.assertEqual(result,{})
    def test_denied_media_is_not_retried_or_bypassed(self):
        import sys,types
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'av':types.SimpleNamespace()}):
            ctx=Mock();response=ctx.request.get.return_value;response.status=403
            value=save_visible_audio(ctx,{'account_id':'a','id':'1'}, {'s':{'url':'https://v11-weba.douyinvod.com/video','bytes':10,'host':'v11-weba.douyinvod.com'}},[10],Path(directory))
            self.assertEqual(value['status'],'waiting_media');self.assertEqual(ctx.request.get.call_count,1)
            self.assertEqual(ctx.request.get.call_args.kwargs['max_redirects'],0)
    def test_unverified_player_duration_prevents_download(self):
        import sys,types
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'av':types.SimpleNamespace()}):
            ctx=Mock();value=save_visible_audio(ctx,{'account_id':'a','id':'1'},{},[],Path(directory))
            self.assertEqual(value['status'],'waiting_media');ctx.request.get.assert_not_called()
class NoPolicyThresholdTests(unittest.TestCase):
 def test_low_like_work_does_not_trigger_media_acquisition(self):
  from douyin_viral_collector.append_policy import eligible
  self.assertEqual(eligible({'likes':4},None,{'threshold':29}),(False,'below_threshold'))
  self.assertTrue(eligible({'likes':30},None,{'threshold':29})[0])
  self.assertFalse(eligible({'likes':30},None,{'threshold':30})[0])
