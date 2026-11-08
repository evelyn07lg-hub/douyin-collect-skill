import unittest
from douyin_viral_collector.share_links import extract_links,profile_url,resolve_profiles
class ShareLinksTests(unittest.TestCase):
 def test_pasted_share_with_escaped_colon(self):
  self.assertEqual(extract_links(r'https\://v.douyin.com/aV8-4e3l7Cg/ 8@1.com :8pm'),['https://v.douyin.com/aV8-4e3l7Cg/'])
 def test_multiple_and_unrelated_links(self):
  self.assertEqual(extract_links('https://www.douyin.com/user/one;https://www.douyin.com/user/two 账号分享'),['https://www.douyin.com/user/one','https://www.douyin.com/user/two'])
  with self.assertRaises(ValueError):extract_links('https://douyin.com.example.org/user/test')
 def test_profile_normalizes_without_browser(self):
  self.assertEqual(resolve_profiles(['看看 https://www.douyin.com/user/example?foo=1 复制打开'],'unused'),['https://www.douyin.com/user/example'])
