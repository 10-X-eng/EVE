"""Exercise DFM through STEVE's actual queue/runner, with a fake Fusion host."""
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

from test_fusion_bridge import bridge, Host
from test_dfm import stages
from steve.dfm import DfmStore
from steve.tool_protocol import validate_call


class DfmBridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.host = Host()
        self.tools = bridge.FusionTools(self.host, self.folder.name)
        self.addCleanup(self.tools.close)
        self.tools.message_context('send')
        self.tools.inspect_document = lambda: {'document_id': self.tools.document_id}
        self.body = Obj(entityToken='body', revisionId='r1', nativeObject=None, isValid=True, name='Fixture')
        self.design = Obj(findEntityByToken=lambda token: [self.body] if token == 'body' else [])
        self.tools.context = lambda: {'design': self.design, 'document': self.host.activeDocument}
        patcher = patch.object(bridge.adsk.fusion, 'BRepBody', Obj(cast=lambda obj: obj), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, tool, **arguments):
        results = []
        arguments = {'document_id': self.tools.document_id, 'part_token': 'body', **arguments}
        validate_call(tool, arguments)
        self.tools.submit(tool, arguments, results.append, lambda: False)
        self.host.pump()
        return results

    def test_disabled_tools_fail_without_running_code(self):
        result = self.call('fusion_dfm_plan', stages=stages())[0]
        self.assertEqual(result['errorCode'], 'dfm_disabled')
        self.assertEqual(self.host.executions, 0)

    def test_plan_and_read_only_check_share_main_thread_runner(self):
        self.tools.dfm.set_enabled(True)
        result = self.call('fusion_dfm_plan', stages=stages())[0]
        self.assertEqual(result['persistence'], 'session')
        result = self.call('fusion_dfm_check', stage=0, title='Check corner', code=
            "def run(context):\n context['dfm'].compare('Corner radius', 2, 'cutter_radius', '>=', 'mm')")[0]
        self.assertTrue(result['ok'])
        self.assertEqual(result['dfm']['status'], 'concerns')
        self.assertEqual(result['executionMode'], 'query')
        self.assertEqual(self.host.executions, 0)

    def test_other_document_waits_and_invalid_stage_guides_recovery(self):
        self.tools.dfm.set_enabled(True)
        self.call('fusion_dfm_plan', stages=stages())
        original = self.host.activeDocument
        self.host.activeDocument = Obj(name='Other')
        results = self.call('fusion_dfm_check', stage=0, title='Check', code='def run(context):\n return None')
        self.assertFalse(results)
        self.host.activeDocument = original
        self.tools.wake()
        self.host.pump()
        self.assertEqual(results[0]['dfm']['status'], 'incomplete')
        result = self.call('fusion_dfm_check', stage=1, title='Check', code='def run(context):\n return None')[0]
        self.assertEqual(result['errorCode'], 'dfm_plan_required')
        self.assertIn('save its stages', result['recovery'])

    def test_error_after_measurement_does_not_validate_partial_result(self):
        self.tools.dfm.set_enabled(True)
        self.call('fusion_dfm_plan', stages=stages())
        result = self.call('fusion_dfm_check', stage=0, title='Check', code=
            "def run(context):\n context['dfm'].compare('Radius', 4, 'cutter_radius', '>=', 'mm')\n raise RuntimeError('incomplete scan')")[0]
        self.assertFalse(result['ok'])
        self.assertEqual(result['dfm']['findings'][0]['status'], 'unknown')

    def test_requested_clear_removes_plan_and_next_check_requires_new_intent(self):
        self.tools.dfm.set_enabled(True)
        self.call('fusion_dfm_plan',stages=stages())
        result=self.call('fusion_dfm_plan',stages=[])[0]
        self.assertTrue(result['ok'])
        self.assertIsNone(result['plan'])
        self.assertIsNone(self.call('fusion_dfm_plan')[0]['plan'])
        result=self.call('fusion_dfm_check',stage=0,title='Check',code='def run(context):\n return None')[0]
        self.assertEqual(result['errorCode'],'dfm_plan_required')
        self.assertEqual(self.host.executions,0)

    def test_help_and_schema_reject_unsupported_and_misleading_requests(self):
        validate_call('fusion_api_help', {'path': 'steve.dfm.fdm'})
        self.assertEqual(self.tools.api_help('steve.dfm.fdm')['process'], 'fdm')
        with self.assertRaises(ValueError):
            validate_call('fusion_dfm_check', {'document_id': 'd', 'part_token': 'body',
                'title': 'x', 'code': 'def run(c): pass', 'stage': True})
        with self.assertRaises(ValueError):
            validate_call('fusion_dfm_plan', {'document_id': 'd', 'part_token': 'body', 'enabled': True})

    def test_other_instance_edit_or_clear_during_check_invalidates_result(self):
        self.host.activeDocument.dataFile = Obj(id='saved-document')
        self.tools.dfm.set_enabled(True)
        other = DfmStore(self.folder.name)
        original_run = bridge.run_python
        original_stages = stages() + [{'process': 'fdm'}]
        for replacement in (stages() + [{'process': 'resin'}], list(reversed(original_stages)), []):
            with self.subTest(replacement=replacement):
                before = self.call('fusion_dfm_plan', stages=original_stages)[0]
                def change_after_measurement(*args, **kwargs):
                    result = original_run(*args, **kwargs)
                    if replacement:
                        other.save_plan('saved-document', self.body, self.design, replacement)
                    else:
                        other.clear_plan('saved-document', self.body, self.design)
                    return result
                with patch.object(bridge, 'run_python', side_effect=change_after_measurement):
                    result = self.call('fusion_dfm_check', stage=0, title='Check', code=
                        "def run(context):\n context['dfm'].compare('Radius', 4, 'cutter_radius', '>=', 'mm')")[0]
                self.assertTrue(result['ok'])
                self.assertEqual(result['dfm']['status'], 'stale')
                self.assertEqual(result['dfm']['findings'][0]['status'], 'unknown')
                self.assertEqual(result['dfm']['findings'][0]['limit'], 3)
                self.assertEqual(result['dfm']['planHash'], before['reportBinding']['planHash'])
                after = self.call('fusion_dfm_plan')[0]
                self.assertNotEqual(after['reportBinding']['planHash'], result['dfm']['planHash'])
                self.assertEqual(after['reportBinding']['revision'], result['dfm']['revision'])
                self.assertEqual(self.host.executions, 0)

    def test_unreadable_plan_after_execution_retains_unknown_report_without_replay(self):
        self.tools.dfm.set_enabled(True)
        self.call('fusion_dfm_plan', stages=stages())
        original_plan = self.tools.dfm.plan
        count = 0
        def read_plan(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError('Another process holds the plan lock')
            return original_plan(*args, **kwargs)
        with patch.object(self.tools.dfm, 'plan', side_effect=read_plan):
            with patch.object(bridge, 'run_python', wraps=bridge.run_python) as run:
                result = self.call('fusion_dfm_check', stage=0, title='Check', code=
                    "def run(context):\n context['dfm'].compare('Radius', 4, 'cutter_radius', '>=', 'mm')")[0]
                self.assertEqual(run.call_count, 1)
        self.assertTrue(result['ok'])
        self.assertEqual(result['dfm']['status'], 'incomplete')
        self.assertEqual(result['dfm']['configurationStatus'], 'unknown')
        self.assertEqual(result['dfm']['findings'][0]['status'], 'unknown')

    def test_historical_binding_changes_with_geometry_and_preserves_unchanged_plan(self):
        self.tools.dfm.set_enabled(True)
        before = self.call('fusion_dfm_plan', stages=stages())[0]
        result = self.call('fusion_dfm_check', stage=0, title='Check', code=
            "def run(context):\n context['dfm'].compare('Radius', 4, 'cutter_radius', '>=', 'mm')")[0]
        self.assertEqual(result['dfm']['status'], 'checked')
        self.assertEqual(result['dfm']['planHash'], before['reportBinding']['planHash'])
        self.assertEqual(result['dfm']['document_id'], before['document_id'])
        self.body.revisionId = 'r2'
        after = self.call('fusion_dfm_plan')[0]
        self.assertNotEqual(after['reportBinding']['revision'], result['dfm']['revision'])
        self.assertEqual(after['reportBinding']['planHash'], result['dfm']['planHash'])


if __name__ == '__main__':
    unittest.main()
