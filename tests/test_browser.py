import json
import tempfile
import unittest
from pathlib import Path
from douyin_viral_collector.browser import BrowserCollector, exact_count, parse_card, validate_detail
from douyin_viral_collector.service import Service


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        p = self.root / 'config.json'
        p.write_text(json.dumps({'mode':'browser_probe','data_dir':'data','threshold':500,
            'model':'models/local','accounts':[], 'public_profiles':[{'sec_uid':'owner','name':'作者','name_verified':True}]}),encoding='utf-8')
        self.s = Service(p)
        self.collector = BrowserCollector(self.s)
        self.card = dict(parse_card({'url':'https://www.douyin.com/video/123','text':'置顶\n501\n\n原始发布文案'}), account_id='douyin-public:owner',account_name='作者')
        self.detail = {'url':self.card['url'],'author_urls':['https://www.douyin.com/user/owner'],
            'work_id':'123','likes_display':'501','description':'完整的发布描述','published_at':'2026-11-02 10:00','expand_remaining':False}

    def tearDown(self):
        self.s.store.db.close();self.tmp.cleanup()

    def test_exact_count_boundaries_and_abbreviations(self):
        for value in (499,500,501): self.assertEqual(exact_count(str(value)),value)
        self.assertEqual(exact_count('7,068'),7068)
        for text in ('2.3万','500+','5,01','1.2K','点赞',''):
            self.assertIsNone(exact_count(text))

    def test_card_pinned_image_and_long_description(self):
        value=parse_card({'url':'https://www.douyin.com/note/2','text':'置顶\n501\n\n'+'文案'*20000})
        self.assertEqual(value['type'],'image')
        self.assertEqual(len(value['description']),40000)
        self.assertIsNone(value['transcript'])
        self.assertIsNone(parse_card({'url':'https://example.com','text':'501'}))

    def test_detail_requires_matching_author_and_work(self):
        for patch in ({'author_urls':['https://www.douyin.com/user/another']}, {'work_id':'456'}, {'url':'https://www.douyin.com/video/456'}):
            with self.assertRaises(ValueError):validate_detail(self.card,dict(self.detail,**patch))

    def test_detail_rejects_approximate_count_and_incomplete_copy(self):
        for patch in ({'likes_display':'2.3万'},{'expand_remaining':True},{'description':''},{'published_at':''}):
            with self.assertRaises(ValueError): validate_detail(self.card,dict(self.detail,**patch))

    def test_verified_publishing_copy_is_not_transcript(self):
        value=validate_detail(self.card,self.detail)
        self.assertTrue(value['detail_verified'])
        self.assertEqual(value['content_kind'],'publishing_description')
        self.assertIsNone(value['transcript'])
        self.s.ingest([value],'browser')
        self.assertEqual(self.s.run('process')['waiting_media'],1)
        self.assertIsNone(self.s.store.rows('SELECT body FROM works')[0]['body'])

    def test_unverified_browser_work_cannot_process(self):
        with self.assertRaises(ValueError): self.s.ingest([dict(self.card,likes=501)],'browser')

    def test_remember_dedup_and_resume(self):
        self.collector.remember(self.card,{'sec_uid':'owner','name':'作者'}, profile_card_verified=True)
        self.collector.remember(dict(self.card,description='更新'),{'sec_uid':'owner','name':'作者'}, profile_card_verified=True)
        rows=self.collector.pending(10)
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0]['payload'])['description'],'更新')
        self.s.ingest([validate_detail(self.card,self.detail)],'browser')
        self.s.store.execute("UPDATE works SET status='archived'")
        self.assertEqual(self.collector.pending(10),[])

    def test_crossed_threshold_refreshes_before_older_below_threshold(self):
        for ident,likes,checked in [('124',100,'2026-10-01'),('125',499,'2026-11-01')]:
            card=dict(self.card,id=ident,url='https://www.douyin.com/video/'+ident,likes_exact_display=506 if ident=='125' else 100)
            self.collector.remember(card,{'sec_uid':'owner','name':'作者'},profile_card_verified=True)
            work=validate_detail(card,dict(self.detail,url=card['url'],work_id=ident,likes_display=str(likes)))
            self.s.ingest([work],'browser')
            self.s.store.execute('UPDATE browser_candidates SET detail_checked=? WHERE id=?',(checked,ident))
        self.assertEqual(self.collector.pending(1)[0]['id'],'125')

    def test_untrusted_saved_links_do_not_enter_detail_queue(self):
        self.collector.remember(self.card, {'sec_uid':'owner','name':'作者'})
        self.assertEqual(self.collector.pending(10), [])

    def test_description_export_scope_idempotence_and_full_text(self):
        detail = dict(self.detail, description='长文案'*20000)
        self.s.ingest([validate_detail(self.card, detail)], 'browser')
        a = self.s.run('browser-export'); b = self.s.run('browser-export')
        self.assertEqual(a['files'], b['files'])
        self.assertIn(detail['description'], Path(a['files'][0]).read_text(encoding='utf-8'))
        self.assertFalse(a['includes_transcript'])
        self.assertFalse(a['remote_archived'])
        self.assertEqual(self.s.run('videos')[0]['status'], 'discovered')

    def test_navigation_interrupt_and_redirect(self):
        from unittest.mock import Mock, patch
        from douyin_viral_collector.browser import BrowserBlocked
        try:
            from playwright.sync_api import Error
        except ImportError:
            self.skipTest('optional browser dependency not installed')
        page = Mock();page.url = self.card['url']
        page.goto.side_effect = Error('interrupted')
        with patch.object(self.collector, 'guard'):
            self.collector.open(page, self.card['url'])
            page.url = 'https://www.douyin.com/jingxuan'
            with self.assertRaises(BrowserBlocked): self.collector.open(page, self.card['url'])

    def test_monitor_refresh_keeps_media_and_review_provenance(self):
        work = validate_detail(self.card, self.detail)
        work.update(media=['original.mp4'], asr_vocabulary=['术语'],
                    recognition_review='machine_unreviewed', recognition_evidence='recognition.json')
        self.s.ingest([work], 'browser')
        self.s.ingest([validate_detail(self.card, self.detail)], 'browser')
        payload = json.loads(self.s.store.rows('SELECT payload FROM works')[0]['payload'])
        self.assertEqual(payload['media'], ['original.mp4'])
        self.assertEqual(payload['asr_vocabulary'], ['术语'])
        self.assertEqual(payload['recognition_review'], 'machine_unreviewed')
        self.assertEqual(payload['recognition_evidence'], 'recognition.json')

    def test_browser_budget_validation(self):
        with self.assertRaises(ValueError): self.collector.run(max_details=101)
        with self.assertRaises(ValueError): self.collector.run(max_scrolls=-1)


if __name__=='__main__':unittest.main()
class HomepageCoCreationTests(unittest.TestCase):
 def test_homepage_membership_accepts_co_created_work(self):
  card={'id':'123','url':'https://www.douyin.com/video/123','account_id':'douyin-public:owner','profile_card_verified':True,'profile_url':'https://www.douyin.com/user/owner'}
  detail={'url':card['url'],'author_urls':['https://www.douyin.com/user/coauthor'],'work_id':'123','likes_display':'305','description':'共创作品','published_at':'2026-09-02','expand_remaining':False}
  result=validate_detail(card,detail,allow_homepage_coauthored=True);self.assertTrue(result['homepage_coauthored']);self.assertEqual(result['account_id'],'douyin-public:owner');self.assertEqual(result['detail_author_urls'],detail['author_urls'])
  with self.assertRaises(ValueError):validate_detail(dict(card,profile_card_verified=False),detail,allow_homepage_coauthored=True)
  with self.assertRaises(ValueError):validate_detail(card,dict(detail,work_id='456'),allow_homepage_coauthored=True)

class ApproximateLikeThresholdTests(unittest.TestCase):
 def test_safe_interval_does_not_invent_exact_count(self):
  from douyin_viral_collector.browser import count_interval
  lower,upper=count_interval('2.3万');self.assertLess(lower,23000);self.assertGreater(upper,23000)
  card={'id':'1','url':'https://www.douyin.com/video/1','account_id':'douyin-public:owner'};detail={'url':card['url'],'work_id':'1','author_urls':['https://www.douyin.com/user/owner'],'likes_display':'2.3万','description':'标题','published_at':'2026-11-08','expand_remaining':False}
  result=validate_detail(card,detail,threshold=500);self.assertFalse(result['likes_exact']);self.assertEqual(result['likes_display'],'2.3万');self.assertGreater(result['likes'],500)
  with self.assertRaises(ValueError):validate_detail(card,detail,threshold=23000)
