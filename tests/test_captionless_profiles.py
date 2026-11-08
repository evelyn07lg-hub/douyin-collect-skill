import unittest
from douyin_viral_collector.browser import author_cover_matches
class CaptionlessProfileTests(unittest.TestCase):
 def test_captionless_cover_is_included(self):
  self.assertTrue(author_cover_matches('示例博主于20260101发布的作品','示例博主'))
  self.assertTrue(author_cover_matches('示例博主：示例文案','示例博主'))
 def test_unrelated_authors_and_partial_name_not_accepted(self):
  self.assertFalse(author_cover_matches('其他人于20260101发布的作品','示例博主'))
  self.assertFalse(author_cover_matches('示例博主的小号：测试','示例博主'))
