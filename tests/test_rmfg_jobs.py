"""Automatic supplier lifecycle and bounded exports; no account or network required."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as Obj
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.rmfg import RMFGError
from steve.rmfg_jobs import RMFGJobs
from steve.rmfg_service import RMFGService
from steve.rmfg_snapshot import export_snapshot
from steve.tool_protocol import ToolError, validate_call


class Client:
    def __init__(self):
        self.calls = []
        self.fail = False
    def analyze(self, data, key):
        self.calls.append((data,key))
        if self.fail:
            raise RMFGError('Interrupted')
        return {'id': 'design1'}
    def design(self, design_id):
        return {'id':design_id,'status':'ready','parts':[{'id':'part1','suggested_process':'sheet_metal','name':'Bracket','analysis_status':'ready'}]}
    def create_dfm(self, design_id, parts, key):
        return {'id':'report1','design_id':design_id,'status':'requires_input','configuration_hash':'material1',
                'requirements':[{'type':'review'}], 'parts':[{'part_id':'part1','issues':[
                    {'code':'TOO_CLOSE','message':'Hole near bend','severity':'warning'},
                    {'code':'PRIVATE','message':'internal','customer_visible':False}]}],
                'model_url':'https://example.invalid/private-signed-url'}
    def dfm(self, report_id):
        return self.create_dfm('design1',[],None)


class RMFGJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = Obj(connection_id=lambda:'connection1',access_token=lambda:'fake-token')
        self.client = Client()
        self.jobs = RMFGJobs(self.temp.name, self.auth, self.client)
        self.snapshot = {'step':b'ISO-10303-21;\nfixture','body':'Bracket','documentKey':'doc1','partToken':'token1','revision':'r1'}

    def ready(self):
        job = self.jobs.prepare(self.snapshot)
        self.jobs.upload(job['id'])
        return job

    def test_prepared_snapshot_uploads_without_a_user_decision(self):
        job = self.jobs.prepare(self.snapshot)
        self.assertEqual(job['state'], 'prepared')
        self.assertFalse(self.client.calls)
        result = self.jobs.upload(job['id'])
        self.assertEqual(result['designState'], 'ready')
        self.assertEqual(self.client.calls, [(self.snapshot['step'], job['uploadKey'])])

    def test_interrupted_upload_survives_restart_and_reuses_exact_body_and_key(self):
        job = self.jobs.prepare(self.snapshot)
        self.client.fail=True
        with self.assertRaises(RMFGError):
            self.jobs.upload(job['id'])
        self.assertEqual(self.jobs.read(job['id'])['state'],'uploading')
        reloaded = RMFGJobs(self.temp.name,self.auth,self.client)
        self.client.fail=False
        result=reloaded.upload(job['id'])
        self.assertEqual(result['designState'],'ready')
        self.assertEqual(self.client.calls[0], self.client.calls[1])
        self.assertEqual(result['snapshot']['binding']['revision'],'r1')

    def test_modified_snapshot_bytes_and_different_connection_are_rejected(self):
        job=self.jobs.prepare(self.snapshot)
        (self.jobs.folder/(job['id']+'.step')).write_bytes(b'different')
        with self.assertRaises(RMFGError):
            self.jobs.upload(job['id'])
        self.auth.connection_id=lambda:'other-account'
        with self.assertRaises(RMFGError):
            self.jobs.read(job['id'])
        self.assertFalse(self.client.calls)

    def test_cross_instance_writes_are_exclusive_and_submitted_upload_cannot_repeat(self):
        second=RMFGJobs(self.temp.name,self.auth,self.client)
        with self.jobs.guard.locked():
            with self.assertRaises(RuntimeError):
                second.prepare(self.snapshot)
        job=self.ready()
        with self.assertRaisesRegex(RMFGError,'already uploaded'):
            second.upload(job['id'])
        self.assertEqual(len(self.client.calls),1)

    def test_report_keeps_supplier_warnings_without_private_links_or_hidden_issues(self):
        job=self.ready()
        result=self.jobs.check(job['id'],[{'part_id':'part1','material_id':'aluminum'}])
        self.assertEqual(result['status'],'requires_input')
        self.assertEqual(result['issues'][0]['code'],'TOO_CLOSE')
        self.assertEqual(len(result['issues']),1)
        self.assertTrue(result['requirementsPresent'])
        self.assertNotIn('private',json.dumps(result))
        with self.assertRaises(RMFGError):
            self.jobs.check(job['id'],[{'part_id':'part1','material_id':'steel'}])

    def test_scope_rejects_neighbors_before_export_and_checks_revision(self):
        component=Obj(bRepBodies=Obj(count=2),occurrences=Obj(count=0),meshBodies=Obj(count=0))
        body=Obj(parentComponent=component,isSolid=True,revisionId='r1',entityToken='b',name='Part')
        exports=[]
        def write(path):
            exports.append(path)
            Path(path).write_bytes(b'ISO-10303-21;')
            return True
        design=Obj(exportManager=Obj(createSTEPExportOptions=lambda path, comp:path,execute=write))
        with self.assertRaises(ToolError):
            export_snapshot(body,design,'doc')
        self.assertFalse(exports)
        component.bRepBodies=Obj(count=1,item=lambda index:body)
        result=export_snapshot(body,design,'doc')
        self.assertEqual(result['step'],b'ISO-10303-21;')
        self.assertFalse(Path(exports[0]).exists())
        component.occurrences.count=1
        with self.assertRaises(ToolError):
            export_snapshot(body,design,'doc')

    def test_service_automatically_uploads_after_export_and_publishes_progress(self):
        published=[]
        bridge=Obj(submit=lambda tool,args,done,cancelled:done({'ok':True,**self.snapshot}))
        service=RMFGService(self.temp.name,self.auth,published.append,bridge)
        self.addCleanup(service.close)
        service.jobs=self.jobs
        done=threading.Event()
        results=[]
        def complete(result):
            results.append(result); done.set()
        service.submit('fusion_rmfg',{'action':'prepare'},complete,lambda:False)
        self.assertTrue(done.wait(3))
        self.assertTrue(results[0]['ok'],results)
        self.assertEqual(len(self.client.calls),1)
        self.assertEqual(published, [{'status': 'Uploading part to RMFG'}])

    def test_cancel_after_export_or_before_upload_prevents_submission(self):
        for cancel_at in ('export', 'upload'):
            with self.subTest(cancel_at=cancel_at):
                cancelled = threading.Event()
                def export(tool, args, done, is_cancelled):
                    if cancel_at == 'export':
                        cancelled.set()
                    done({'ok': True, **self.snapshot})
                def publish(state):
                    if cancel_at == 'upload':
                        cancelled.set()
                service = RMFGService(self.temp.name, self.auth, publish, Obj(submit=export))
                self.addCleanup(service.close)
                service.jobs = self.jobs
                done = threading.Event(); results = []
                service.submit('fusion_rmfg', {'action': 'prepare'},
                               lambda result: (results.append(result), done.set()), cancelled.is_set)
                self.assertTrue(done.wait(3))
                self.assertEqual(results[0]['errorCode'], 'cancelled')
                self.assertFalse(self.client.calls)

    def test_export_failure_prevents_submission(self):
        bridge = Obj(submit=lambda tool,args,done,cancelled: done({'ok': False, 'error': 'Unsupported scope'}))
        service = RMFGService(self.temp.name, self.auth, lambda state: None, bridge)
        self.addCleanup(service.close)
        service.jobs = self.jobs
        done = threading.Event(); results = []
        service.submit('fusion_rmfg', {'action': 'prepare'},
                       lambda result: (results.append(result), done.set()), lambda: False)
        self.assertTrue(done.wait(3))
        self.assertFalse(results[0]['ok'])
        self.assertFalse(self.client.calls)

    def test_stale_check_does_not_submit_supplier_request(self):
        job=self.ready()
        bridge=Obj(submit=lambda tool,args,done,cancelled:done({'ok':True,'snapshotMatches':False}))
        service=RMFGService(self.temp.name,self.auth,lambda state:None,bridge)
        self.addCleanup(service.close)
        service.jobs=self.jobs
        done=threading.Event(); results=[]
        service.submit('fusion_rmfg',{'action':'check','job_id':job['id'],'parts':[{'part_id':'part1','material_id':'aluminum'}]},
                       lambda result:(results.append(result),done.set()),lambda:False)
        self.assertTrue(done.wait(3))
        self.assertFalse(results[0]['ok'])
        self.assertIn('changed',results[0]['error'])
        self.assertNotIn('dfmKey',self.jobs.read(job['id']))

    def test_tool_rejects_risk_acceptance_and_arbitrary_paths(self):
        base={'document_id':'doc','part_token':'body','action':'check','job_id':'job1'}
        for part in ({'part_id':'part1','material_id':'steel','accepted_risks':['bad-bend']},
                     {'part_id':'../data','material_id':'steel'}):
            with self.assertRaises(ValueError):
                validate_call('fusion_rmfg',{**base,'parts':[part]})


if __name__ == '__main__':
    unittest.main()
