"""Machine definition selection, provenance, persistence and revision guards."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve import machines
from steve.dfm import DfmChecks, DfmStore, plan_hash, validate_stages
from steve.tool_protocol import validate_call, tool_failure


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name) / 'definitions'
        self.directory.mkdir()
        self.definition = machines.load('prusa-mk4s')
        self.definition.pop('definition_hash')
        self.path = self.directory / 'prusa-mk4s.json'
        self.write()
        patcher = patch.object(machines, 'DIRECTORY', self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reference = machines.help('prusa-mk4s')['selection']
        self.stage = {'process': 'fdm', 'machine': self.reference}
        self.body = Obj(entityToken='body', nativeObject=None, revisionId='r1', name='Part')

    def write(self):
        self.path.write_text(json.dumps(self.definition), encoding='utf-8')

    def test_catalog_and_detail_are_available_without_api_import_or_new_tool(self):
        from test_fusion_bridge import bridge
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.namespaces = lambda: self.fail('Machine help must not inspect Fusion')
        for path in ('steve.machines', 'steve.machines.prusa-mk4s'):
            validate_call('fusion_api_help', {'path': path})
            self.assertTrue(tools.api_help(path)['ok'])
        self.assertEqual(machines.help()['machines'][0]['id'], 'prusa-mk4s')
        for bad in ('../outside', 'x/y', 'x.y', 'X', ''):
            with self.assertRaises(ValueError):
                machines.load(bad)
        for bad in ('steve.machines.', 'steve.machines.../outside'):
            with self.assertRaises(ValueError):
                validate_call('fusion_api_help', {'path': bad})

    def test_selected_limits_preserve_source_scope_and_relation(self):
        checks = DfmChecks(self.body, self.stage)
        checks.machine['capabilities']['nominal_build_x']['value'] = 1000
        checks.compare('X', 251, 'machine.nominal_build_x', '<=', 'mm')
        report = checks.report(True)
        finding = report['findings'][0]
        self.assertEqual(finding['status'], 'concern')
        self.assertEqual(finding['limit'], 250)
        self.assertEqual(finding['source'], self.definition['sources']['specifications'])
        self.assertIn('excludes supports', finding['capabilityScope'])
        self.assertEqual(report['machine'], self.reference)
        self.assertTrue(report['machineUnchecked'])
        with self.assertRaises(ValueError):
            checks.compare('X', 251, 'machine.nominal_build_x', '>=', 'mm')
        with self.assertRaises(ValueError):
            checks.compare('X', 251, 'machine.nominal_build_x', '<=', 'in')
        checks.compare('Missing', 1, 'machine.minimum_wall', '>=', 'mm')
        self.assertEqual(checks.report(True)['findings'][-1]['status'], 'unknown')

    def test_wrong_process_unselected_machine_and_reserved_override(self):
        with self.assertRaises(machines.MachineDefinitionError):
            DfmChecks(self.body, {**self.stage, 'process': 'milling'})
        checks = DfmChecks(self.body, {'process': 'fdm'})
        self.assertIsNone(checks.machine)
        checks.compare('X', 251, 'machine.nominal_build_x', '<=', 'mm')
        self.assertEqual(checks.report(True)['status'], 'incomplete')
        bad = {**self.stage, 'criteria': {'machine.nominal_build_x': {'value': 1000, 'units': 'mm', 'basis': 'profile', 'source': 'override'}}}
        with self.assertRaises(ValueError):
            validate_stages([bad])

    def test_definition_change_preserves_old_plan_and_requires_explicit_refresh(self):
        store = DfmStore(Path(self.folder.name) / 'state')
        design = Obj(findEntityByToken=lambda _: [self.body])
        store.save_plan('saved', self.body, design, [self.stage])
        before = store.plan('saved', self.body, design)
        checks = DfmChecks(self.body, self.stage)
        self.definition['capabilities']['nominal_build_x']['value'] = 200
        self.write()
        self.assertEqual(checks.machine_status(), 'stale')
        old = DfmStore(store.path.parent).plan('saved', self.body, design)
        self.assertEqual(old, before)
        with self.assertRaises(machines.MachineDefinitionError) as caught:
            DfmChecks(self.body, old['stages'][0])
        self.assertEqual(tool_failure(caught.exception)['errorCode'], 'machine_definition_unavailable')
        with self.assertRaises(machines.MachineDefinitionError):
            store.save_plan('saved', self.body, design, [self.stage])
        refreshed = {**self.stage, 'machine': machines.help('prusa-mk4s')['selection']}
        store.save_plan('saved', self.body, design, [refreshed])
        self.assertNotEqual(plan_hash(before), plan_hash(store.plan('saved', self.body, design)))
        self.path.unlink()
        self.assertEqual(checks.machine_status(), 'unknown')
        self.assertIsNotNone(DfmStore(store.path.parent).plan('saved', self.body, design))

    def test_invalid_definitions_are_reported_not_silently_replaced(self):
        original = copy.deepcopy(self.definition)
        for mutate in (
            lambda d: d.update(id='different'),
            lambda d: d.update(processes=['imaginary']),
            lambda d: d.update(verified_on='yesterday'),
            lambda d: d['capabilities']['nominal_build_x'].update(value=True),
            lambda d: d['capabilities']['nominal_build_x'].update(value=float('nan')),
            lambda d: d['capabilities']['nominal_build_x'].update(source='missing'),
            lambda d: d['sources'].update(specifications='http://example.test/specification'),
        ):
            self.definition = copy.deepcopy(original)
            mutate(self.definition)
            self.write()
            with self.assertRaises(machines.MachineDefinitionError):
                machines.load('prusa-mk4s')
            self.assertEqual(machines.help()['unavailable'], ['prusa-mk4s'])
        self.path.write_bytes(b' ' * 16001)
        with self.assertRaises(machines.MachineDefinitionError):
            machines.load('prusa-mk4s')


if __name__ == '__main__':
    unittest.main()
