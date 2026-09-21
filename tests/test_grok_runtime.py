"""Real bundled Codex -> local xAI fixture -> STEVE tool -> response, without inference."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.controller import thread_start_params
from steve.grok_transport import GrokGateway, GrokTransport
from steve.transport import runtime_command, RuntimeUnavailable
from steve.upgrade import MARKER, migrate_data

try:
    runtime_command()
    HAS_RUNTIME = True
except RuntimeUnavailable:
    HAS_RUNTIME = False


class Stream(io.BytesIO):
    status = 200
    headers = {"Content-Type": "text/event-stream"}


@unittest.skipUnless(HAS_RUNTIME, "Fetch the bundled runtime first")
class GrokRuntimeTests(unittest.TestCase):
    def test_real_runtime_streams_and_invokes_fusion_tool_through_grok_provider(self):
        self.run_conversation(False)

    def test_real_runtime_reopens_and_continues_chat_after_folder_upgrade(self):
        self.run_conversation(True)

    def run_conversation(self, relocate):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "PreviousAssistant"
            events, requests, tools = [], [], []
            done = threading.Event()
            def notify(method, params):
                events.append((method, params))
                if method == "turn/completed":
                    done.set()
            def upstream(request, timeout):
                body = json.loads(request.data)
                requests.append(body)
                if len(requests) == 1:
                    item = {"id": "fc_fixture", "type": "function_call", "call_id": "call_fixture",
                            "name": "fusion_inspect_document", "arguments": "{}", "status": "completed"}
                else:
                    item = {"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "Fixture design inspected.", "annotations": []}]}
                response = {"id": "resp_fixture_" + str(len(requests)), "object": "response", "status": "completed",
                            "model": "grok-4.6", "output": [item], "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}}
                packets = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                           {"type": "response.output_item.added", "output_index": 0, "item": item},
                           {"type": "response.output_item.done", "output_index": 0, "item": item},
                           {"type": "response.completed", "response": response}]
                return Stream("".join("data: " + json.dumps(packet) + "\n\n" for packet in packets).encode())
            client = GrokTransport(notify, home=home)
            client.auth.access_token = lambda force=False: "fixture-token"
            def tool_call(request_id, method, params):
                tools.append(params)
                client.reply(request_id, {"success": True, "contentItems": [{"type": "inputText", "text": "Fixture bracket"}]})
            client.on_request = tool_call
            with patch("steve.grok_transport.GrokGateway", side_effect=lambda auth: GrokGateway(auth, opener=upstream)):
                try:
                    client.start()
                    thread = client.request("thread/start", thread_start_params(client.home))["thread"]["id"]
                    client.request("turn/start", {"threadId": thread, "model": "grok-4.6", "effort": "xhigh",
                                   "input": [{"type": "text", "text": "Inspect the fixture design"}]})
                    self.assertTrue(done.wait(15), str(events[-5:]))
                    self.assertEqual([call["tool"] for call in tools], ["fusion_inspect_document"])
                    self.assertEqual(len(requests), 2)
                    self.assertTrue(all(request.get("reasoning", {}).get("effort") == "xhigh" for request in requests))
                    self.assertTrue(any(item.get("type") == "function_call_output" for item in requests[1]["input"]))
                    self.assertFalse(any(item.get("type") == "reasoning" for item in requests[1]["input"]))
                    errors = [params for method, params in events if method == "error"]
                    self.assertFalse(errors)
                    history = client.request("thread/list", {"cwd": str(client.home / "workspace")})
                    self.assertIn(thread, [entry["id"] for entry in history["data"]])
                finally:
                    client.close()
                if relocate:
                    installation = Path(folder) / "installation"
                    installation.mkdir()
                    (installation / MARKER).write_text(json.dumps({"previousName": home.name}))
                    home = Path(folder) / "STEVE"
                    backup = migrate_data(installation, home)
                    self.assertTrue(backup.is_dir())
                client = GrokTransport(notify, home=home)
                client.auth.access_token = lambda force=False: "fixture-token"
                try:
                    client.start()
                    history = client.request("thread/list", {"cwd": str(client.home / "workspace")})
                    self.assertIn(thread, [entry["id"] for entry in history["data"]])
                    params = thread_start_params(client.home)
                    params.pop("ephemeral")
                    params.pop("dynamicTools")
                    params["threadId"] = thread
                    restored = client.request("thread/resume", params)
                    self.assertEqual(restored["model"], "grok-4.6")
                    done.clear()
                    client.request("turn/start", {"threadId": thread, "effort": "low", "input": [{"type": "text", "text": "Continue"}]})
                    self.assertTrue(done.wait(15), str(events[-5:]))
                    self.assertEqual(len(requests), 3)
                    self.assertEqual(requests[-1]["model"], "grok-4.6")
                    self.assertEqual(requests[-1].get("reasoning", {}).get("effort"), "low")
                finally:
                    client.close()
            self.assertFalse(client.alive)


if __name__ == "__main__":
    unittest.main()
