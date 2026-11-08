import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from douyin_viral_collector.desktop_runner import DesktopRunner
from douyin_viral_collector.environment_setup import choose_runtime,requirements,existing_model
class EnvironmentSetupTests(unittest.TestCase):
 def test_complete_current_environment_skips_install_without_marker(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);host=root/'host/python.exe';host.parent.mkdir();host.touch();events=[];runner=DesktopRunner(root,events.append)
   with patch('douyin_viral_collector.environment_setup.choose_runtime',return_value=(host,[])),patch.object(runner,'_command') as command:runner.prepare()
   command.assert_not_called();self.assertEqual(runner.python,host);self.assertIn('跳过安装',events[-1]['text'])
 def test_optional_proofreading_not_installed_by_default(self):
  self.assertFalse(any('funasr' in x for x in requirements({})));self.assertTrue(any('funasr' in x for x in requirements({'proofreading':{'enabled':True}})))
 def test_existing_runtime_preferred_to_incomplete_project_environment(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);local=root/'.venv/Scripts/python.exe';local.parent.mkdir(parents=True);local.touch();host=root/'host/python.exe';host.parent.mkdir();host.touch()
   with patch('douyin_viral_collector.environment_setup.os.name','nt'),patch('douyin_viral_collector.environment_setup.probe',side_effect=lambda path,needed:{'missing':['playwright']} if Path(path)==local else {'missing':[]}):chosen,missing=choose_runtime(root,host,['playwright'])
   self.assertEqual(chosen,host);self.assertEqual(missing,[])
 def test_incomplete_model_not_reused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'models/faster-whisper-small';folder.mkdir(parents=True);(folder/'model.bin').write_bytes(b'weights');self.assertIsNone(existing_model(root,root/'runtime/Scripts/python.exe','small'))
   for name in ('config.json','tokenizer.json'):(folder/name).write_text('{}',encoding='utf-8')
   self.assertEqual(existing_model(root,root/'runtime/Scripts/python.exe','small'),folder.resolve())
