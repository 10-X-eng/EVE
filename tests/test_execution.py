import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.python_runner import run_python, bounded_result, RESULT_LIMIT
from steve.tool_protocol import validate_call, tool_response


class PythonExecutionTests(unittest.TestCase):
    def test_operation_receives_context_and_returns_output(self):
        context = {"products": {"CAMProductType": {"setups": []}}}
        result = run_python("def run(context):\n context['products']['CAMProductType']['setups'].append('fixture')\n print('Created setup')\n return {'count': 1}", context)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {"count": 1})
        self.assertEqual(result["output"], "Created setup\n")
        self.assertEqual(context["products"]["CAMProductType"]["setups"], ["fixture"])

    def test_requires_entrypoint_before_running_top_level_code(self):
        context = {}
        result = run_python("raise RuntimeError('must not run')", context)
        self.assertIn("Define def run(context)", result["error"])

    def test_crashing_value_introspection_is_rejected_before_any_side_effect(self):
        context = {"changed": False}
        result = run_python("def run(context):\n context['changed'] = True\n return [{'type': p.value.objectType} for p in context['parameters']]", context)
        self.assertEqual(result["errorCode"], "unsafe_value_introspection")
        self.assertFalse(result["executionStarted"])
        self.assertFalse(context["changed"])
        self.assertIn("names and expressions", result["recovery"])

    def test_line_diagnostics_are_bounded_by_source_lines_not_loop_iterations(self):
        events = []
        result = run_python("def run(context):\n for i in range(1000):\n  pass\n return i", {},
                            diagnostic=lambda event, **details: events.append((event, details)))
        self.assertTrue(result["ok"])
        lines = [details["line"] for event, details in events]
        self.assertEqual(set(lines), {1, 2, 3, 4})
        self.assertEqual(len(lines), 4)

    def test_pinned_task_rejects_live_context_reads_before_side_effects(self):
        for member in ("activeDocument", "activeProduct", "activeSelections", "activeProject"):
            context = {"targetPinned": True, "changed": False}
            result = run_python("def run(context):\n context['changed'] = True\n return context['app']." + member, context)
            self.assertEqual(result["errorCode"], "live_context_access")
            self.assertFalse(result["executionStarted"])
            self.assertFalse(context["changed"])

    def test_error_returns_script_line_without_local_traceback_paths(self):
        result = run_python("def run(context):\n raise ValueError('bad geometry')", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["trace"], ["line 2 in run"])
        self.assertNotIn(str(ROOT), json.dumps(result))

    def test_cancellation_prevents_execution(self):
        context = {"changed": False}
        result = run_python("def run(context):\n context['changed'] = True", context, cancelled=lambda: True)
        self.assertFalse(result["ok"])
        self.assertFalse(context["changed"])

    def test_python_loop_expires_and_trace_hook_is_restored(self):
        previous = sys.gettrace()
        result = run_python("def run(context):\n while True:\n  pass", {}, budget_seconds=0.01)
        self.assertFalse(result["ok"])
        self.assertIn("time budget", result["error"])
        self.assertIs(sys.gettrace(), previous)

    def test_native_wait_does_not_consume_python_loop_budget(self):
        previous = sys.getprofile()
        result = run_python("import time\ndef run(context):\n time.sleep(0.06)\n return 'completed'", {}, budget_seconds=0.03)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], "completed")
        self.assertIs(sys.getprofile(), previous)

    def test_python_loop_after_native_wait_still_expires(self):
        result = run_python("import time\ndef run(context):\n time.sleep(0.03)\n while True:\n  pass", {}, budget_seconds=0.02)
        self.assertEqual(result["errorCode"], "python_time_budget")

    def test_print_output_is_bounded_and_return_value_must_be_json(self):
        result = run_python("def run(context):\n print('x' * 20000)\n return object()", {})
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["output"]), 12000)

    def test_fresh_globals_for_each_operation(self):
        self.assertTrue(run_python("stored = 42\ndef run(context):\n return stored", {})["ok"])
        self.assertFalse(run_python("def run(context):\n return stored", {})["ok"])

    def test_large_result_returns_useful_marked_preview_without_repeating_operation(self):
        context = {"calls": 0}
        result = run_python("def run(context):\n context['calls'] += 1\n return [{'name': 'tool-' + str(i), 'details': 'x' * 200} for i in range(1000)]", context)
        self.assertTrue(result["ok"])
        self.assertTrue(result["resultTruncated"])
        self.assertEqual(context["calls"], 1)
        self.assertEqual(result["result"][0]["name"], "tool-0")
        self.assertIn({"path": "$", "returned": 20, "total": 1000}, result["omitted"])
        self.assertIn("Do not repeat a modifying operation", result["guidance"])

    def test_nested_preview_stays_bounded_with_escaped_unicode_and_long_keys(self):
        for value in ({"tools": [{"details": '\"\\\n🙂' * 1000} for _ in range(1000)]},
                      {"x" * 30000: "value"}, [[[[[["x" * 30000]]]]]], "x" * 30000):
            with self.subTest(type=type(value).__name__):
                result = bounded_result(value)
                self.assertTrue(result["resultTruncated"])
                self.assertLessEqual(len(json.dumps(result["result"], ensure_ascii=False)), RESULT_LIMIT)
                self.assertTrue(result["omitted"])
        value = {"items": [1, 2], "complete": True}
        self.assertEqual(bounded_result(value), {"result": value})

    def test_errors_explain_how_to_recover(self):
        for source, code, guidance in [
            ("def run(context):\n return context.no_such_member", "api_member_unavailable", "fusion_api_help"),
            ("def run(context):\n len(1)", "api_signature_mismatch", "argument"),
            ("def run(context):\n return object()", "invalid_result", "JSON primitives"),
            ("def run(context):\n invalid syntax", "invalid_python", "reported line")]:
            result = run_python(source, {})
            self.assertFalse(result["ok"])
            self.assertEqual(result["errorCode"], code)
            self.assertIn(guidance, result["recovery"])
        result = run_python("def run(context):\n print('x' * 20000)\n return 1", {})
        self.assertTrue(result["outputTruncated"])
        self.assertIn("Do not repeat changes", result["outputGuidance"])

    def test_tool_schema_rejects_bad_calls(self):
        for tool, args in [("shell", {}), ("fusion_api_help", {"path": "os.system"}),
                           ("fusion_api_help", {"path": "adsk.__dict__"}),
                           ("fusion_execute_python", {"code": "pass"})]:
            with self.assertRaises(ValueError):
                validate_call(tool, args)
        validate_call("fusion_api_help", {"path": "adsk.cam.CAM"})
        query = {"document_id": "fixture", "title": "List CAM tools", "code": "def run(context):\n return []"}
        validate_call("fusion_query_python", query)
        with self.assertRaises(ValueError):
            validate_call("fusion_query_python", {**query, "execution_mode": "command"})
        validate_call("fusion_execute_python", {"document_id": "fixture", "title": "Inspect CAM", "code": "def run(context):\n return None"})
        application = {"document_id": "fixture", "title": "Create document", "code": "def run(context):\n return None", "execution_mode": "application"}
        validate_call("fusion_execute_python", application)
        with self.assertRaises(ValueError):
            validate_call("fusion_execute_python", {**application, "execution_mode": "unknown"})
        response = tool_response({"ok": False, "error": "fixture"})
        self.assertFalse(response["success"])
        self.assertEqual(response["contentItems"][0]["type"], "inputText")


if __name__ == "__main__":
    unittest.main()
