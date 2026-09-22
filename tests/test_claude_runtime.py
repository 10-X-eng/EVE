"""Bundled Codex -> Claude Responses adapter -> STEVE tool loop; no paid calls."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.claude_transport import ClaudeTransport
from steve.claude_responses import ClaudeGateway
from steve.controller import thread_start_params
from steve.transport import runtime_command, RuntimeUnavailable
from test_claude import completion, FixtureStream

try:
    runtime_command()
    HAS_RUNTIME = True
except RuntimeUnavailable:
    HAS_RUNTIME = False


@unittest.skipUnless(HAS_RUNTIME, "Fetch the bundled runtime first")
class ClaudeRuntimeTests(unittest.TestCase):
    def test_goal_continues_and_completes_with_native_goal_tool(self):
        from steve.controller import Controller
        from steve.debug_log import DebugLog
        from steve.preferences import ProviderChoice
        from test_core import eventually
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            ProviderChoice(home).save("claude")
            calls = []
            class Model:
                def create(self, **params):
                    calls.append(params)
                    tool = [{"id": "goal_done", "type": "function", "function": {"name": "update_goal", "arguments": '{"status":"complete"}'}}] if len(calls) == 2 else None
                    return FixtureStream([completion("Verified fixture step.", tool)])
                def cancel(self):
                    pass
                def close(self):
                    pass
            status = {"account": {"type": "claude", "email": "fixture@example.com", "planType": "Claude Pro"}}
            catalog = {"data": [{"id": "fixture", "isDefault": True}], "nextCursor": None}
            with patch("steve.claude_transport.ClaudeGateway", side_effect=lambda path: ClaudeGateway(path, Model)), patch("steve.claude_transport.account_status", return_value=status), patch("steve.claude_transport.discover_models", return_value=catalog):
                controller = Controller(lambda _: None, debug_log=DebugLog(home),
                    claude_factory=lambda notify: ClaudeTransport(notify, home=home))
                try:
                    controller.dispatch("connect")
                    eventually(lambda: bool(controller.state["models"] or controller.state["error"]), 35)
                    self.assertTrue(controller.state["models"], controller.state["error"])
                    controller.dispatch("goal", {"command": "set", "objective": "Verify fixture", "tokenBudget": 100},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture", "task_key": "fixture"})
                    eventually(lambda: controller.state["goal"] and controller.state["goal"]["status"] == "complete" and not controller.state["busy"], 20)
                    self.assertFalse(controller.state["error"], controller.state["error"])
                    self.assertEqual(len(calls), 3)
                    self.assertTrue({"create_goal", "get_goal", "update_goal"} <= {t["function"]["name"] for t in calls[0]["tools"]})
                finally:
                    controller.close()
                    controller._worker.join(5)

    def test_native_failure_reaches_chat_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            done = threading.Event()
            errors, calls = [], []
            def notify(method, params):
                if method == "error":
                    errors.append(params)
                if method == "turn/completed":
                    done.set()
            class Model:
                def create(self, **params):
                    calls.append(params)
                    raise RuntimeError("Fixture subscription limit reached. Try again after your limit resets.")
                def cancel(self):
                    pass
                def close(self):
                    pass
            with patch("steve.claude_transport.ClaudeGateway", side_effect=lambda path: ClaudeGateway(path, Model)), patch("steve.claude_transport.account_status", return_value={"account": {"type": "claude"}}):
                client = ClaudeTransport(notify, home=Path(folder))
                try:
                    client.start()
                    params = thread_start_params(client.home)
                    params["model"] = "fixture"
                    thread = client.request("thread/start", params)["thread"]["id"]
                    client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Hello"}]})
                    self.assertTrue(done.wait(15))
                    self.assertEqual(len(calls), 1)
                    self.assertIn("subscription limit reached", str(errors))
                finally:
                    client.close()

    def test_tools_images_steering_history_and_resume_through_real_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            done, entered, release = threading.Event(), threading.Event(), threading.Event()
            events, calls, tools = [], [], []
            def notify(method, params):
                events.append((method, params))
                if method == "turn/completed":
                    done.set()
            class Model:
                def create(self, **params):
                    calls.append(params)
                    if len(calls) == 1:
                        entered.set()
                        release.wait(15)
                        return FixtureStream([completion("Inspecting.", [{"id": "tool1", "type": "function",
                            "function": {"name": "fusion_inspect_document", "arguments": "{}"}}])])
                    return FixtureStream([completion("Fixture design inspected.")])
                def cancel(self):
                    release.set()
                def close(self):
                    pass
            status = {"account": {"type": "claude", "email": "fixture@example.com", "planType": "Claude Pro"}}
            with patch("steve.claude_transport.ClaudeGateway", side_effect=lambda folder: ClaudeGateway(folder, Model)), patch("steve.claude_transport.account_status", return_value=status):
                client = ClaudeTransport(notify, home=Path(folder))
                def tool_call(request_id, method, params):
                    tools.append(params)
                    client.reply(request_id, {"success": True, "contentItems": [{"type": "inputText", "text": "Fixture bracket"}]})
                client.on_request = tool_call
                try:
                    client.start()
                    params = thread_start_params(client.home)
                    params["model"] = "claude-fixture"
                    thread = client.request("thread/start", params)["thread"]["id"]
                    turn = client.request("turn/start", {"threadId": thread, "effort": "high", "input": [
                        {"type": "text", "text": "Inspect this"}, {"type": "image", "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="}]})
                    self.assertTrue(entered.wait(10), str(events[-5:]))
                    client.request("turn/steer", {"threadId": thread, "expectedTurnId": turn["turn"]["id"],
                                   "input": [{"type": "text", "text": "Use 40mm instead"}]})
                    release.set()
                    self.assertTrue(done.wait(20), str(events[-5:]))
                    self.assertEqual([tool["tool"] for tool in tools], ["fusion_inspect_document"])
                    self.assertEqual(len(calls), 2, str(events[-5:]))
                    self.assertTrue(any(m["role"] == "tool" for m in calls[1]["messages"]))
                    self.assertIn("Use 40mm instead", str(calls[1]["messages"]))
                    self.assertIn("image_url", str(calls[0]["messages"]))
                    self.assertTrue(all(c["extra_body"]["reasoning"]["effort"] == "high" for c in calls))
                    self.assertTrue(any(m == "item/agentMessage/delta" for m, p in events))
                    self.assertFalse([p for m, p in events if m == "error"], str(events[-5:]))
                finally:
                    client.close()
                client = ClaudeTransport(notify, home=Path(folder))
                try:
                    client.start()
                    history = client.request("thread/list", {"cwd": str(client.home / "workspace")})
                    self.assertIn(thread, [entry["id"] for entry in history["data"]])
                    params = thread_start_params(client.home)
                    params.pop("ephemeral")
                    params.pop("dynamicTools")
                    params["threadId"] = thread
                    client.request("thread/resume", params)
                    done.clear()
                    client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Continue"}]})
                    self.assertTrue(done.wait(20), str(events[-5:]))
                    self.assertEqual(len(calls), 3)
                    self.assertTrue(any(m.get("reasoning_details") for m in calls[-1]["messages"]))
                finally:
                    client.close()


if __name__ == "__main__":
    unittest.main()
