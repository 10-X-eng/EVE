from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch
from test_fusion_bridge import Collection, bridge, Host
from steve.verification import Checks, snapshot, report


class VerificationTests(unittest.TestCase):
    def test_failed_check_is_reported_after_command_without_automatic_rollback(self):
        host = Host()
        tools = bridge.FusionTools(host)
        tools.namespaces = lambda: []
        results = []
        try:
            token = tools.inspect_document()["document_id"]
            with patch.object(bridge.adsk.fusion, "FeatureHealthStates", Obj(HealthyFeatureHealthState=0), create=True):
                tools.submit("fusion_execute_python", {"document_id": token, "title": "Measure",
                    "code": "def run(context):\n context['verification'].check('Count', 1, 2)\n return {'created': 1}"}, results.append, lambda: False)
                host.pump()
            self.assertTrue(results[0]["ok"])
            self.assertFalse(host.args.executeFailed)
            self.assertEqual(results[0]["verification"]["status"], "failed")
        finally:
            tools.close()

    def fixture(self):
        old = Obj(name="Existing", entityToken="old", healthState=1, errorOrWarningMessage="Existing warning")
        features = Collection(old)
        design = Obj(allComponents=Collection(Obj(features=features)),
                     findEntityByToken=lambda token: [f for f in features.values if f.entityToken == token])
        return design, features

    def test_new_failure_is_distinct_from_preexisting_warning(self):
        design, features = self.fixture()
        before = snapshot(design)
        features.values.append(Obj(name="Broken", entityToken="new", healthState=2, errorOrWarningMessage="Bad profile"))
        result = report(before, snapshot(design), [], True, 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["newProblems"][0]["name"], "Broken")
        self.assertEqual(result["existingProblems"][0]["name"], "Existing")

    def test_changed_token_is_resolved_not_compared(self):
        design, features = self.fixture()
        before = snapshot(design)
        features.values[0].entityToken = "changed-token"
        design.findEntityByToken = lambda token: [features.values[0]]
        result = report(before, snapshot(design), [], True, 0)
        self.assertEqual(result["createdFeatures"], [])
        self.assertEqual(result["deletedFeatures"], [])
        self.assertEqual(result["status"], "incomplete")

    def test_deleted_features_and_missing_measurements_are_reported(self):
        design, features = self.fixture()
        before = snapshot(design)
        features.values.clear()
        result = report(before, snapshot(design), [], True, 0)
        self.assertEqual(result["deletedFeatures"], ["Existing"])
        self.assertEqual(result["status"], "incomplete")

    def test_measurement_failure_does_not_raise_or_claim_success(self):
        checks = Checks()
        self.assertFalse(checks.check("Thickness", 0.9, 0.8, tolerance=0.01, units="cm"))
        design, _ = self.fixture()
        result = report(snapshot(design), snapshot(design), checks.results, True, 0)
        self.assertEqual(result["status"], "failed")
        with self.assertRaises(ValueError):
            checks.check("Bad", float('nan'), 1)

    def test_limited_snapshot_does_not_call_unknown_problem_new(self):
        design, _ = self.fixture()
        result = report(snapshot(design, limit=0), snapshot(design), [], True, 0)
        self.assertFalse(result["complete"])
        self.assertFalse(result["newProblems"])
        self.assertTrue(result["unclassifiedProblems"])
