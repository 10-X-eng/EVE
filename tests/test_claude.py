"""Subscription setup, replay, and fail-closed Responses translation; no paid calls."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.claude_setup import account_status, cli_version, discover_models, model_label, resolve_claude, checked_environment
from steve.claude_responses import ClaudeGateway, ReplayStore, translate, response_events
from steve.claude_native.directsdk import Client, obj, projection, CARRIER, request_body
from steve.claude_transport import ClaudeTransport
from steve.preferences import ProviderChoice
from steve.transport import Transport


def completion(text="Ready", calls=None, stop="end_turn"):
    message = {"role": "assistant", "content": text, "tool_calls": calls}
    message["reasoning_details"] = [{"type": CARRIER, "version": 1, "projection": projection(message),
        "messages": [{"role": "assistant", "content": [{"type": "thinking", "thinking": "fixture", "signature": "signed"},
                       {"type": "text", "text": text}], "stop_reason": stop}]}]
    result = obj({"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                  "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}})
    chunk = Client._chunk("fixture", {"content": text})
    chunk._response = result
    return chunk


class FixtureStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self):
        return iter(self.chunks)
    def close(self):
        self.closed = True


class ClaudeTests(unittest.TestCase):
    def test_model_labels_show_resolved_versions_without_date_suffixes(self):
        for model, native, expected in (
            ("claude-opus-5", "Opus", "Opus 5"),
            ("claude-opus-5[1m]", "Opus (1M context)", "Opus 5 (1M context)"),
            ("claude-sonnet-5", "Default (recommended)", "Sonnet 5 (recommended)"),
            ("claude-haiku-4-5-20251001", "Haiku", "Haiku 4.5"),
            ("claude-fable-5-1[1m]", "Fable", "Fable 5.1 (1M context)"),
            ("claude-new-model-6-2", "New model", "New Model 6.2"),
            ("claude-preview-special", "Preview", "Preview (claude-preview-special)"),
        ):
            with self.subTest(model=model):
                self.assertEqual(model_label(model, {"displayName": native}), expected)

    def test_cli_version_is_probed_again_after_update_and_bad_output_is_not_shown(self):
        with patch("steve.claude_setup.checked_environment", return_value={}), patch("steve.claude_setup.resolve_claude", return_value=["fixture"]), patch("steve.claude_setup.subprocess.run") as run:
            run.side_effect = [Mock(stdout="2.1.260 (Claude Code)\n", returncode=0),
                               Mock(stdout="2.1.263 (Claude Code)\n", returncode=0),
                               Mock(stdout="unexpected diagnostic", returncode=0)]
            self.assertEqual(cli_version(), "2.1.260")
            self.assertEqual(cli_version(), "2.1.263")
            self.assertEqual(cli_version(), "")
            self.assertTrue(all(call.args[0] == ["fixture", "--version"] for call in run.call_args_list))

    def test_catalog_refresh_reads_new_versions_and_keeps_credit_notice(self):
        def reply(model):
            return Mock(stdout=json.dumps({"type": "control_response", "response": {"response": {
                "models": [{"resolvedModel": model, "displayName": "Opus (1M context) · usage credits"}],
                "account": {"subscriptionType": "pro"}}}}), returncode=0)
        with patch("steve.claude_setup.checked_environment", return_value={}), patch("steve.claude_setup.resolve_claude", return_value=["fixture"]), patch("steve.claude_setup.subprocess.run", side_effect=[reply("claude-opus-5[1m]"), reply("claude-opus-5-1[1m]")]):
            self.assertEqual(discover_models()["data"][0]["displayName"], "Opus 5 (1M context) · usage credits")
            self.assertEqual(discover_models()["data"][0]["displayName"], "Opus 5.1 (1M context) · usage credits")

    def test_controller_checks_external_login_without_opening_browser(self):
        from test_core import FakeClient, eventually
        from steve.controller import Controller
        from steve.debug_log import DebugLog
        with tempfile.TemporaryDirectory() as folder:
            ProviderChoice(folder).save("claude")
            def factory(notify):
                client = FakeClient(notify)
                client.account = None
                return client
            browser = Mock()
            controller = Controller(lambda _: None, debug_log=DebugLog(folder), claude_factory=factory, open_browser=browser)
            try:
                controller.dispatch("connect")
                eventually(lambda: controller.state["accountChecked"])
                client = controller.client
                client.account = {"type": "claude", "email": "fixture@example.com", "planType": "Claude Pro"}
                controller.dispatch("login")
                eventually(lambda: bool(controller.state["models"]))
                self.assertFalse(controller.state["loginPending"])
                self.assertEqual(controller.state["account"]["email"], "fixture@example.com")
                self.assertNotIn("account/login/start", [method for method, params in client.calls])
                browser.assert_not_called()
                original = client.request
                revision = ["2.1.260", "Opus 5"]
                def refreshed(method, params=None, **kwargs):
                    result = original(method, params, **kwargs)
                    if method == "account/read":
                        result["providerVersion"] = revision[0]
                    elif method == "model/list":
                        result["data"][0]["displayName"] = revision[1]
                    return result
                client.request = refreshed
                controller.thread_id = "existing-chat"
                for version, model in (("2.1.260", "Opus 5"), ("2.1.263", "Opus 5.1")):
                    revision[:] = [version, model]
                    controller.dispatch("accountRefresh", {"refreshModels": True})
                    eventually(lambda: controller.state["providerVersion"] == version and controller.state["models"][0]["name"] == model)
                    self.assertEqual(controller.thread_id, "existing-chat")
            finally:
                controller.close()
                controller._worker.join(5)

    def test_native_install_found_when_gui_path_omits_it(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / ".local/bin" / ("claude.exe" if os.name == "nt" else "claude")
            exe.parent.mkdir(parents=True)
            exe.touch()
            with patch("steve.claude_setup.shutil.which", return_value=None), patch("steve.claude_setup.Path.home", return_value=Path(folder)):
                self.assertEqual(resolve_claude(env={}), [str(exe)])
                self.assertIsNone(resolve_claude(env={"STEVE_CLAUDE_COMMAND": "missing-custom-cli"}))

    def test_subscription_check_exposes_only_public_metadata_and_rejects_api_billing(self):
        auth = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "pro", "email": "test@example.com", "privateField": "never-publish"}
        with patch("steve.claude_setup.checked_environment", return_value={}), patch("steve.claude_setup.resolve_claude", return_value=["fixture"]), patch("steve.claude_setup.subprocess.run") as run:
            run.return_value = Mock(stdout=json.dumps(auth), returncode=0)
            result = account_status()
            self.assertEqual(result["account"]["type"], "claude")
            self.assertNotIn("never-publish", json.dumps(result))
            self.assertEqual(run.call_args.args[0], ["fixture", "auth", "status"])
            for method in ("api_key", "console", None):
                run.return_value.stdout = json.dumps({**auth, "authMethod": method})
                self.assertIsNone(account_status()["account"])
            run.return_value.stdout = json.dumps({"loggedIn": False})
            self.assertIn("claude auth login", account_status()["localStatus"])

    def test_conflicting_environment_names_are_reported_without_values(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret-do-not-print"}):
            with self.assertRaisesRegex(ValueError, "ANTHROPIC_API_KEY") as error:
                checked_environment()
            self.assertNotIn("secret-do-not-print", str(error.exception))

    def test_replay_survives_restart_but_not_model_or_content_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            message = completion()._response.model_dump()["choices"][0]["message"]
            ReplayStore(folder).save("fixture", message)
            body = {"model": "fixture", "input": [{"role": "user", "content": "begin"},
                    {"role": "assistant", "content": "Ready"}, {"role": "user", "content": "continue"}]}
            result = translate(body, ReplayStore(folder))
            self.assertEqual(result["messages"][1]["reasoning_details"], message["reasoning_details"])
            body["model"] = "different"
            self.assertNotIn("reasoning_details", translate(body, ReplayStore(folder))["messages"][1])
            body["model"] = "fixture"
            body["input"][1]["content"] = "Edited"
            self.assertNotIn("reasoning_details", translate(body, ReplayStore(folder))["messages"][1])

    def test_signed_replay_is_isolated_by_chat(self):
        with tempfile.TemporaryDirectory() as folder:
            gateway = ClaudeGateway(folder)
            try:
                gateway.bind("first-route", "first-chat")
                gateway.bind("second-route", "second-chat")
                gateway.bind("resumed-route", "first-chat")
                message = completion()._response.model_dump()["choices"][0]["message"]
                gateway.scopes["first-route"].save("fixture", message)
                public = {"role": "assistant", "content": "Ready"}
                gateway.scopes["second-route"].restore("fixture", public)
                self.assertNotIn("reasoning_details", public)
                gateway.scopes["resumed-route"].restore("fixture", public)
                self.assertIn("reasoning_details", public)
            finally:
                gateway.close()

    def test_images_tools_and_effort_translation_preserve_input_and_reject_remote_images(self):
        with tempfile.TemporaryDirectory() as folder:
            image = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
            body = {"model": "fixture", "reasoning": {"effort": "high"}, "input": [
                {"role": "user", "content": [image]},
                {"type": "function_call", "name": "fusion_query_python", "arguments": '{"code":"x"}', "call_id": "call1"},
                {"type": "function_call_output", "call_id": "call1", "output": [{"type": "input_text", "text": "ok"}]},
                {"role": "user", "content": "Actually, use 40mm"}],
                "tools": [{"type": "function", "name": "fusion_query_python", "parameters": {"type": "object"}}]}
            before = copy.deepcopy(body)
            result = translate(body, ReplayStore(folder))
            self.assertEqual(body, before)
            self.assertEqual(result["messages"][0]["content"][0]["image_url"]["url"], image["image_url"])
            self.assertEqual(result["messages"][2]["tool_call_id"], "call1")
            self.assertEqual(result["messages"][-1]["content"], "Actually, use 40mm")
            self.assertEqual(result["extra_body"]["reasoning"]["effort"], "high")
            wire, inventory, names = request_body(result)
            self.assertEqual(json.loads(wire)["tools"][0]["name"], "mcp__steve__fusion_query_python")
            image["image_url"] = "https://example.com/image.png"
            with self.assertRaisesRegex(ValueError, "attached as image data"):
                translate(body, ReplayStore(folder))

    def test_incomplete_or_token_limited_generations_never_publish_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = [{"id": "tool1", "type": "function", "function": {"name": "fusion_execute_python", "arguments": "{}"}}]
            client = Mock()
            stream = FixtureStream([completion(calls=calls, stop="max_tokens")])
            client.create.return_value = stream
            events = []
            with self.assertRaisesRegex(RuntimeError, "limit"):
                for event in response_events({"model": "fixture"}, client, ReplayStore(folder)):
                    events.append(event)
            self.assertFalse(any(e.get("item", {}).get("type") == "function_call" for e in events))
            self.assertFalse(any(e["type"] == "response.completed" for e in events))
            self.assertTrue(stream.closed)
            client.create.return_value = FixtureStream([])
            with self.assertRaisesRegex(RuntimeError, "complete response"):
                list(response_events({"model": "fixture"}, client, ReplayStore(folder)))

    def test_provider_keeps_isolated_history_and_disables_native_web_search_and_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            choices = ProviderChoice(home)
            choices.save("claude")
            self.assertEqual(ProviderChoice(home).provider, "claude")
            transport = ClaudeTransport(lambda *args: None, home=home)
            transport.gateway = Mock(base_url="http://127.0.0.1/fixture")
            with patch.object(Transport, "request", return_value={"thread": {"id": "fixture-thread"}}) as request:
                transport.request("thread/start", {"model": "fixture"})
                params = request.call_args.args[1]
                self.assertEqual(params["config"]["web_search"], "disabled")
                self.assertEqual(params["config"]["model_providers.steve_claude.stream_max_retries"], 0)
                transport.request("thread/list")
                self.assertEqual(request.call_args.args[1]["modelProviders"], ["steve_claude"])
                transport.request("turn/interrupt", {"threadId": "a", "turnId": "b"})
                transport.gateway.cancel.assert_called_once()
            self.assertEqual(transport.home, home / "claude-runtime")
            with self.assertRaisesRegex(ValueError, "outside Fusion"):
                transport.request("account/logout")


if __name__ == "__main__":
    unittest.main()
