import contextlib,importlib.util,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch


class ScheduledWorkerTests(unittest.TestCase):
    def run_worker(self,result):
        script=Path(__file__).resolve().parents[1]/'scripts/scheduled-run.py'
        spec=importlib.util.spec_from_file_location('scheduled_worker_test',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            service=Mock();service.root=Path(directory);service.run.return_value=result
            with patch.object(module,'Service',return_value=service),contextlib.redirect_stdout(io.StringIO()):
                code=module.main()
            report=json.loads((service.root/'scheduler/last-run.json').read_text(encoding='utf-8'))
            return code,report
    def test_network_problem_is_not_reported_as_no_updates(self):
        code,report=self.run_worker({'monitor':{'monitor':'browser_partial','issues':[{'error':'TimeoutError'}]},
            'process':{'failed':0},'archive':{'remote':'no_new_ready_items'}})
        self.assertEqual(code,2);self.assertEqual(report['status'],'needs_attention');self.assertFalse(report['document_updated'])
    def test_missing_media_is_not_document_success(self):
        code,report=self.run_worker({'monitor':{'issues':[]},'process':{'failed':0,'waiting_media':2},
            'archive':{'remote':'no_new_ready_items'}})
        self.assertEqual(code,0);self.assertEqual(report['status'],'waiting_media');self.assertFalse(report['document_updated'])
    def test_only_verified_append_counts_as_document_update(self):
        code,report=self.run_worker({'monitor':{'issues':[]},'process':{'failed':0},
            'archive':{'remote':'verified','results':[{'status':'archived'}]}})
        self.assertEqual(code,0);self.assertTrue(report['document_updated']);self.assertEqual(report['status'],'updated')