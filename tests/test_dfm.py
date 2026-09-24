"""DFM evidence contracts, persistence and revision ownership (no CAD host)."""
from pathlib import Path
import math
import sys
import tempfile
from types import SimpleNamespace as Obj
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.dfm import DfmStore, DfmChecks, validate_stages, guide


def stages():
    return [{'process': 'milling', 'material': 'Aluminum', 'notes': 'User chose the cutter',
             'criteria': {'cutter_radius': {'value': 3, 'units': 'mm',
                          'source': 'Selected 6 mm end mill', 'basis': 'profile'}}}]


class DfmTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = DfmStore(self.folder.name)
        self.body = Obj(entityToken='body', revisionId='r1', name='Bracket', nativeObject=None)
        self.design = Obj(findEntityByToken=lambda token: [self.body] if token in ('body', 'new-token') else [])

    def test_default_off_and_strict_remembered_switch(self):
        self.assertFalse(self.store.enabled)
        with self.assertRaises(ValueError):
            self.store.set_enabled('false')
        self.store.set_enabled(True)
        self.assertTrue(DfmStore(self.folder.name).enabled)

    def test_plans_survive_reload_and_resolve_changed_tokens(self):
        self.store.save_plan('saved-document', self.body, self.design, stages())
        self.body.entityToken = 'new-token'
        loaded = DfmStore(self.folder.name)
        self.assertEqual(loaded.plan('saved-document', self.body, self.design)['stages'], stages())
        self.assertIsNone(loaded.plan('different-document', self.body, self.design))
        self.design.findEntityByToken = lambda token: []
        self.assertIsNone(loaded.plan('saved-document', self.body, self.design))

    def test_unsaved_plans_remain_session_only_and_multi_stage(self):
        value = stages() + [{'process': 'fdm', 'criteria': {}}]
        self.store.save_plan('session:one', self.body, self.design, value)
        self.assertEqual(len(self.store.plan('session:one', self.body, self.design)['stages']), 2)
        self.assertIsNone(DfmStore(self.folder.name).plan('session:one', self.body, self.design))

    def test_invalid_profile_does_not_replace_valid_plan(self):
        self.store.save_plan('doc', self.body, self.design, stages())
        invalid = stages()
        invalid[0]['criteria']['cutter_radius']['value'] = float('nan')
        with self.assertRaises(ValueError):
            self.store.save_plan('doc', self.body, self.design, invalid)
        self.assertEqual(self.store.plan('doc', self.body, self.design)['stages'], stages())
        invalid = stages()
        invalid[0]['criteria']['cutter_radius']['source'] = ''
        with self.assertRaises(ValueError):
            validate_stages(invalid)

    def test_two_instances_preserve_each_others_saved_plans_and_switch(self):
        other = DfmStore(self.folder.name)
        self.store.set_enabled(True)
        self.store.save_plan('first-document', self.body, self.design, stages())
        other.save_plan('second-document', self.body, self.design, [{'process':'turning'}])
        loaded = DfmStore(self.folder.name)
        self.assertTrue(loaded.enabled, 'Saving a plan must not overwrite the remembered switch from another instance')
        self.assertIsNotNone(loaded.plan('first-document', self.body, self.design))
        self.assertEqual(self.store.plan('second-document', self.body, self.design)['stages'], [{'process':'turning'}])
        other.set_enabled(False)
        self.assertIsNotNone(DfmStore(self.folder.name).plan('first-document', self.body, self.design))
        self.assertTrue(self.store.enabled, 'Remote preferences must not toggle an active task')

    def test_contended_plan_write_fails_without_clobbering_or_waiting(self):
        other = DfmStore(self.folder.name)
        self.store.save_plan('doc', self.body, self.design, stages())
        with self.store._guard.locked():
            with self.assertRaisesRegex(RuntimeError, 'saving DFM plans'):
                other.save_plan('doc', self.body, self.design, [{'process':'turning'}])
        self.assertEqual(other.plan('doc', self.body, self.design)['stages'], stages())
        other.save_plan('doc', self.body, self.design, [{'process':'turning'}])
        self.assertEqual(self.store.plan('doc', self.body, self.design)['stages'], [{'process':'turning'}])

    def checks(self, stage=None):
        return DfmChecks(self.body, stage or stages()[0])

    def test_comparison_uses_profile_and_rejects_unit_mismatch(self):
        checks = self.checks()
        checks.compare('Internal corner radius', 2, 'cutter_radius', '>=', 'mm')
        report = checks.report(True)
        self.assertEqual(report['findings'][0]['status'], 'concern')
        self.assertEqual(report['status'], 'concerns')
        with self.assertRaisesRegex(ValueError, 'units'):
            checks.compare('Radius', .2, 'cutter_radius', '>=', 'cm')
        with self.assertRaises(ValueError):
            checks.compare('Radius', True, 'cutter_radius', '>=', 'mm')
        with self.assertRaises(ValueError):
            checks.compare('Radius', float('inf'), 'cutter_radius', '>=', 'mm')

    def test_unknown_and_assumed_criteria_cannot_pass(self):
        checks = self.checks()
        checks.compare('Reach', 10, 'missing_tool_reach', '<=', 'mm')
        self.assertEqual(checks.report(True)['findings'][0]['status'], 'unknown')
        stage = stages()[0]
        stage['criteria']['cutter_radius']['basis'] = 'assumption'
        checks = self.checks(stage)
        checks.compare('Radius', 4, 'cutter_radius', '>=', 'mm')
        self.assertEqual(checks.report(True)['findings'][0]['status'], 'unknown')
        self.assertEqual(checks.report(True)['findings'][0]['conditionalResult'], 'pass')

    def test_native_roundoff_is_disclosed_without_a_manufacturing_tolerance(self):
        stage = stages()[0]
        stage['criteria']['cutter_radius']['value'] = 4
        checks = self.checks(stage)
        measured = 4.0000000000000036  # Observed unchanged nominal 4 mm Fusion hole.
        checks.compare('Diameter', measured, 'cutter_radius', '==', 'mm')
        finding = checks.report(True)['findings'][0]
        self.assertEqual(finding['status'], 'pass')
        self.assertEqual(finding['actual'], measured)
        self.assertEqual(finding['limit'], 4)
        self.assertEqual(finding['numericalComparison']['maxUlps'], 8)
        checks.compare('Upper bound', measured, 'cutter_radius', '<=', 'mm')
        checks.compare('Lower bound', 4-4*math.ulp(4), 'cutter_radius', '>=', 'mm')
        self.assertTrue(all(f['status'] == 'pass' for f in checks.report(True)['findings']))
        for relation, value in [('==',4+16*math.ulp(4)), ('<=',4.000001), ('>=',3.999999)]:
            check = self.checks(stage)
            check.compare('Real difference', value, 'cutter_radius', relation, 'mm')
            self.assertEqual(check.report(True)['findings'][0]['status'], 'concern')
        stage['criteria']['cutter_radius']['value'] = 0
        check = self.checks(stage)
        check.compare('No absolute epsilon around zero', 1e-16, 'cutter_radius', '==', 'mm')
        self.assertEqual(check.report(True)['findings'][0]['status'], 'concern')
        stage['criteria']['cutter_radius'].update(value=4, basis='assumption')
        check = self.checks(stage)
        check.compare('Unconfirmed criterion', measured, 'cutter_radius', '==', 'mm')
        self.assertEqual(check.report(True)['findings'][0]['status'], 'unknown')

    def test_empty_failed_and_stale_reports_do_not_pass(self):
        checks = self.checks()
        self.assertEqual(checks.report(True)['status'], 'incomplete')
        checks.compare('Radius', 4, 'cutter_radius', '>=', 'mm')
        self.assertEqual(checks.report(True)['status'], 'checked')
        self.assertEqual(checks.report(False)['status'], 'incomplete')
        self.body.revisionId = 'r2'
        self.assertEqual(checks.report(True)['status'], 'stale')
        self.assertEqual(checks.report(True)['findings'][0]['status'], 'unknown')

    def test_report_without_revision_is_unverified(self):
        self.body.revisionId = None
        checks = self.checks()
        checks.compare('Radius', 4, 'cutter_radius', '>=', 'mm')
        self.assertEqual(checks.report(True)['status'], 'incomplete')

    def test_report_is_bounded_and_cannot_omit_overflow_silently(self):
        checks = self.checks()
        for i in range(24):
            checks.unknown(str(i), 'No measurement')
        with self.assertRaisesRegex(ValueError, '24'):
            checks.unknown('overflow', 'No measurement')
        self.assertEqual(len(checks.report(False)['findings']), 24)

    def test_guides_cover_all_processes_without_universal_limits(self):
        for process in ('milling', 'turning', 'sheet_metal', 'fdm', 'resin', 'powder'):
            self.assertEqual(guide(process)['process'], process)
            self.assertTrue(guide(process)['unchecked'])
        with self.assertRaises(ValueError):
            guide('unknown_process')


if __name__ == '__main__':
    unittest.main()
