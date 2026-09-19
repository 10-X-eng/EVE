"""Guard regressions use Python stand-ins; never reproduce a native Fusion crash."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/EVE"))
from eve.cam_guard import protect_cam_values
from eve.python_runner import run_python


class CamGuardTests(unittest.TestCase):
    def setUp(self):
        class Parameter:
            def __init__(self, name):
                self.name, self.expression, self.reads = name, "1 mm", 0
            @property
            def value(self):
                self.reads += 1
                return {"fixture": 42}
        self.parameter_class = Parameter
        self.original = Parameter.value
        self.events = []

    def record(self, event, **details):
        self.events.append((event, details))

    def test_probe_value_is_blocked_before_native_getter_including_getattr(self):
        for expression in ("parameter.value", "getattr(parameter, 'value')"):
            parameter = self.parameter_class("probe_geometry")
            with protect_cam_values(self.parameter_class, self.record):
                result = run_python("def run(context):\n parameter = context['parameter']\n return " + expression,
                                    {"parameter": parameter})
            self.assertFalse(result["ok"])
            self.assertEqual(result["errorCode"], "unsafe_cam_probe_value")
            self.assertEqual(parameter.reads, 0)
            self.assertIn("Do not retry", result["recovery"])
            self.assertIs(self.parameter_class.value, self.original)

    def test_scalar_probe_expressions_and_other_cam_values_still_work(self):
        probe = self.parameter_class("probe_clearance")
        feed = self.parameter_class("tool_feedCutting")
        with protect_cam_values(self.parameter_class, self.record):
            result = run_python("def run(context):\n context['probe'].expression = '2 mm'\n return context['feed'].value",
                                {"probe": probe, "feed": feed})
        self.assertTrue(result["ok"])
        self.assertEqual(probe.expression, "2 mm")
        self.assertEqual(probe.reads, 0)
        self.assertEqual(feed.reads, 1)
        self.assertEqual(self.events[0], ("cam.parameter.read", {"parameter": feed.name, "member": "value", "line": 3}))
        self.assertEqual(self.events[1][0], "cam.parameter.read_completed")

    def test_guard_restored_after_exception_and_cancellation(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with protect_cam_values(self.parameter_class, self.record):
                raise RuntimeError("fixture")
        self.assertIs(self.parameter_class.value, self.original)
        with protect_cam_values(self.parameter_class, self.record):
            result = run_python("def run(context):\n return 1", {}, cancelled=lambda: True)
        self.assertEqual(result["errorCode"], "cancelled")
        self.assertIs(self.parameter_class.value, self.original)

    def test_incompatible_wrapper_fails_closed(self):
        class Incompatible:
            value = 1
        with self.assertRaisesRegex(RuntimeError, "crash guard"):
            with protect_cam_values(Incompatible, self.record):
                self.fail("must not execute")

    def test_nested_guards_restore_outer_property(self):
        with protect_cam_values(self.parameter_class, self.record):
            outer = self.parameter_class.value
            with protect_cam_values(self.parameter_class, self.record):
                pass
            self.assertIs(self.parameter_class.value, outer)
        self.assertIs(self.parameter_class.value, self.original)
