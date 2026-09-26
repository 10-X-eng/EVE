"""Real bundled Codex -> local OpenRouter fixture -> STEVE tool -> response, without inference."""
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
from steve.openrouter_auth import OpenRouterAuth
from steve.openrouter_transport import OpenRouterGateway, OpenRouterTransport
from steve.transport import runtime_command, RuntimeUnavailable
from test_openrouter import KEY, MemoryStore

try:
    runtime_command()
    HAS_RUNTIME = True
except RuntimeUnavailable:
    HAS_RUNTIME = False

CATALOG = {"data": [
    {"id": "anthropic/claude-fixture", "model": "anthropic/claude-fixture", "displayName": "Claude fixture", "group": "anthropic",
     "isDefault": True, "supportsImages": True, "context": 1000000, "defaultReasoningEffort": "high",
     "supportedReasoningEfforts": [{"reasoningEffort": "high", "description": ""}]},
    {"id": "qwen/coder-fixture", "model": "qwen/coder-fixture", "displayName": "Coder fixture", "group": "qwen",
     "isDefault": False, "supportsImages": False, "context": 131072, "defaultReasoningEffort": "",
     "supportedReasoningEfforts": []}]}


class Stream(io.BytesIO):
    status = 200
    headers = {"Content-Type": "text/event-stream"}


@unittest.skipUnless(HAS_RUNTIME, "Fetch the bundled runtime first")
class OpenRouterRuntimeTests(unittest.TestCase):
    def test_real_runtime_streams_tools_replays_reasoning_and_continues_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "STEVE"
            store = MemoryStore({"key": KEY, "account": {"type": "openrouter", "id": "fixture", "email": "STEVE", "planType": "OpenRouter"}})
            events, requests, tools = [], [], []
            done = threading.Event()
            def notify(method, params):
                events.append((method, params))
                if method == "turn/completed":
                    done.set()
            def upstream(request, timeout):
                self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
                body = json.loads(request.data)
                requests.append(body)
                reasoning = {"id": "rs_" + str(len(requests)), "type": "reasoning", "summary": [], "encrypted_content": "signed-fixture"}
                if len(requests) == 1:
                    item = {"id": "fc_fixture", "type": "function_call", "call_id": "call_fixture",
                            "name": "fusion_inspect_document", "arguments": "{}", "status": "completed"}
                else:
                    item = {"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "Fixture design inspected.", "annotations": []}]}
                response = {"id": "resp_fixture_" + str(len(requests)), "object": "response", "status": "completed",
                            "model": body["model"], "output": [reasoning, item],
                            "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}}
                packets = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                           {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
                           {"type": "response.output_item.added", "output_index": 1, "item": item},
                           {"type": "response.output_item.done", "output_index": 1, "item": item},
                           {"type": "response.completed", "response": response}]
                # OpenRouter sends SSE comments while a provider is working.
                return Stream((": OPENROUTER PROCESSING\n\n" + "".join("data: " + json.dumps(p) + "\n\n" for p in packets)).encode())
            def transport():
                auth = OpenRouterAuth(home / "openrouter", store=store)
                auth.models = lambda: json.loads(json.dumps(CATALOG))
                client = OpenRouterTransport(notify, home=home, auth=auth)
                def tool_call(request_id, method, params):
                    tools.append(params)
                    client.reply(request_id, {"success": True, "contentItems": [{"type": "inputText", "text": "Fixture bracket"}]})
                client.on_request = tool_call
                return client
            with patch("steve.openrouter_transport.OpenRouterGateway", side_effect=lambda auth: OpenRouterGateway(auth, opener=upstream)):
                client = transport()
                try:
                    client.start()
                    self.assertEqual(client.request("account/read")["account"]["email"], "STEVE")
                    thread = client.request("thread/start", thread_start_params(client.home))["thread"]["id"]
                    client.request("turn/start", {"threadId": thread, "model": "anthropic/claude-fixture", "effort": "high",
                                   "input": [{"type": "text", "text": "Inspect the fixture design"}]})
                    self.assertTrue(done.wait(15), str(events[-5:]))
                    self.assertEqual([call["tool"] for call in tools], ["fusion_inspect_document"])
                    self.assertEqual(len(requests), 2)
                    self.assertFalse([params for method, params in events if method == "error"])
                    for body in requests:
                        self.assertEqual(body["model"], "anthropic/claude-fixture")
                        self.assertEqual(body["reasoning"]["effort"], "high")
                        self.assertIs(body["store"], False)
                        self.assertNotIn("previous_response_id", body)
                        self.assertNotIn("client_metadata", body)
                        self.assertTrue(all(tool["type"] == "function" for tool in body["tools"]))
                    replayed = [item for item in requests[1]["input"] if item.get("type") == "reasoning"]
                    self.assertEqual(replayed, [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "signed-fixture"}])
                    self.assertTrue(any(item.get("type") == "function_call_output" for item in requests[1]["input"]))
                    history = client.request("thread/list", {"cwd": str(client.home / "workspace")})
                    self.assertIn(thread, [entry["id"] for entry in history["data"]])
                finally:
                    client.close()
                client = transport()
                try:
                    client.start()
                    history = client.request("thread/list", {"cwd": str(client.home / "workspace")})
                    self.assertIn(thread, [entry["id"] for entry in history["data"]])
                    params = thread_start_params(client.home)
                    params.pop("ephemeral")
                    params.pop("dynamicTools")
                    params["threadId"] = thread
                    restored = client.request("thread/resume", params)
                    self.assertEqual(restored["model"], "anthropic/claude-fixture")
                    done.clear()
                    client.request("turn/start", {"threadId": thread, "model": "qwen/coder-fixture",
                                                  "input": [{"type": "text", "text": "Continue"}]})
                    self.assertTrue(done.wait(15), str(events[-5:]))
                    self.assertEqual(len(requests), 3)
                    self.assertEqual(requests[-1]["model"], "qwen/coder-fixture")
                    self.assertEqual(client.threads[thread], "qwen/coder-fixture")
                finally:
                    client.close()
            self.assertFalse(client.alive)


if __name__ == "__main__":
    unittest.main()
