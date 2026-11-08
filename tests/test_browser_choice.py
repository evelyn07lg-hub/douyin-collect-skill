import unittest
from unittest.mock import patch
from douyin_viral_collector.browser_choice import browser_options
from douyin_viral_collector.wps_local import open_document
class BrowserAndWpsTests(unittest.TestCase):
 def test_isolated_profiles(self):
  self.assertNotEqual(browser_options({'browser':'edge'},'data')[0],browser_options({'browser':'chrome'},'data')[0])
  self.assertEqual(browser_options({'browser':'chrome'},'data')[1],'chrome')
 def test_unknown_browser_rejected(self):
  with self.assertRaises(ValueError):browser_options({'browser':'unknown'},'data')
 def test_no_word_fallback(self):
  with patch('douyin_viral_collector.wps_local.find_wps',return_value=None),patch('douyin_viral_collector.wps_local.subprocess.Popen') as launch:
   with self.assertRaises(RuntimeError):open_document('example.docx')
   launch.assert_not_called()
