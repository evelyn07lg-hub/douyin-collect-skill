import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from douyin_viral_collector.onboarding import verify_profiles
class LoginStartupTests(unittest.TestCase):
 def test_browser_selection_reaches_launcher_without_name_error(self):
  for browser,channel in [('edge','msedge'),('chrome','chrome')]:
   with self.subTest(browser=browser),tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'config.json';path.write_text(json.dumps({'mode':'browser','data_dir':'data','threshold':500,'accounts':[],'public_profiles':[],'browser':browser}),encoding='utf-8')
    with patch('playwright.sync_api.sync_playwright') as factory:
     launch=factory.return_value.__enter__.return_value.chromium.launch_persistent_context;launch.side_effect=RuntimeError('launcher reached')
     with self.assertRaisesRegex(RuntimeError,'launcher reached'):verify_profiles(path)
     self.assertEqual(launch.call_args.kwargs['channel'],channel)
