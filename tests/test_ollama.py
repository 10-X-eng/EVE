"""Local provider boundaries, model capability discovery, and runtime configuration."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.ollama_transport import BASE_URL, MAX_METADATA, OllamaAPI, OllamaError, OllamaTransport
from steve.preferences import ProviderChoice
from steve.transport import Transport


def shown(vision=True, **extra):
    return {"capabilities": ["completion", "tools"] + (["vision"] if vision else []),
            "parameters": "num_ctx 8192", "details": {},
            "model_info": {"general.architecture": "fixture", "fixture.context_length": 32768}, **extra}


class OllamaTests(unittest.TestCase):
    def test_catalog_filters_cloud_and_non_tool_models_and_prefers_configured_small_model(self):
        api = OllamaAPI()
        entries = [{"name": name, "size": size} for name, size in
                   [("large", 100), ("small", 50), ("unconfigured", 1), ("plain", 2), ("remote", 3), ("x:cloud", 4)]]
        info = {"large": shown(), "small": shown(False), "unconfigured": shown(parameters=""),
                "plain": shown(capabilities=["completion"]), "remote": shown(remote_host="https://ollama.com")}
        api.request = lambda path, body=None: {"models": entries} if path == "/api/tags" else info[body["model"]]
        catalog = api.models()["data"]
        self.assertEqual([m["id"] for m in catalog], ["small", "large", "unconfigured"])
        self.assertTrue(catalog[0]["isDefault"])
        self.assertFalse(catalog[0]["supportsImages"])
        self.assertEqual(catalog[0]["supportedReasoningEfforts"], [])

    def test_metadata_is_loopback_bounded_and_has_no_credentials(self):
        api = OllamaAPI()
        api.opener = Mock()
        api.opener.open.return_value = io.BytesIO(b'{"version":"0.34.2"}')
        self.assertEqual(api.request("/api/version")["version"], "0.34.2")
        request = api.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, BASE_URL + "/api/version")
        self.assertNotIn("Authorization", request.headers)
        api.opener.open.return_value = io.BytesIO(b"x" * (MAX_METADATA + 1))
        with self.assertRaisesRegex(OllamaError, "too much"):
            api.request("/api/version")
        api.opener.open.side_effect = URLError("offline")
        with self.assertRaisesRegex(OllamaError, "Start the Ollama app"):
            api.request("/api/version")

    def test_bad_metadata_and_server_failure_do_not_become_empty_catalog(self):
        api = OllamaAPI()
        api.opener = Mock()
        api.opener.open.return_value = io.BytesIO(b'[]')
        with self.assertRaisesRegex(OllamaError, "invalid model information"):
            api.request("/api/tags")
        api.request = Mock(side_effect=[{"models": [{"name": "small"}]}, OllamaError("offline")])
        with self.assertRaisesRegex(OllamaError, "offline"):
            api.models()

    def test_prepare_uses_actual_allocation_and_shared_parent_runner(self):
        api = OllamaAPI()
        api.request = Mock(side_effect=[shown(details={"parent_model": "original"}), {"done": True},
                                       {"models": [{"name": "original", "context_length": 16384}]}])
        prepared = api.prepare("configured")
        self.assertEqual(prepared, {"model": "configured", "context": 16384, "vision": True})
        self.assertNotIn("options", api.request.call_args_list[1].args[1])
        config = OllamaTransport.config(prepared)
        self.assertEqual(config["model_context_window"], 16384)
        self.assertEqual(config["model_auto_compact_token_limit"], 12288)
        self.assertFalse(config["model_providers.steve_ollama.requires_openai_auth"])
        self.assertEqual(config["web_search"], "disabled")
        self.assertFalse(config["features.code_mode"]["enabled"])

    def test_low_missing_and_overstated_context_are_rejected(self):
        for allocated, supported in [(4096, 131072), (0, 131072), (16384, 4096)]:
            with self.subTest(allocated=allocated, supported=supported):
                api = OllamaAPI()
                api.request = Mock(side_effect=[shown(model_info={"general.architecture": "fixture", "fixture.context_length": supported}),
                                               {"done": True}, {"models": [{"name": "small", "context_length": allocated}]}])
                with self.assertRaisesRegex(OllamaError, "num_ctx.*8192"):
                    api.prepare("small")

    def test_no_signin_and_offline_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            api = Mock()
            api.request.side_effect = OllamaError("Start Ollama")
            client = OllamaTransport(lambda *args: None, home=Path(folder), api=api)
            self.assertIsNone(client.request("account/read")["account"])
            api.request.side_effect = None
            api.request.return_value = {"version": "0.34.2"}
            self.assertEqual(client.request("account/read")["account"]["type"], "ollama")
            api.request.return_value = {"version": "0.12.0"}
            outdated = client.request("account/read")
            self.assertIsNone(outdated["account"])
            self.assertIn("Update Ollama", outdated["localStatus"])
            for action in ("account/login/start", "account/logout"):
                with self.assertRaisesRegex(OllamaError, "no sign-in"):
                    client.request(action)
            self.assertEqual(client.home.name, "ollama-runtime")

    def test_model_switch_refreshes_context_and_text_models_reject_images(self):
        with tempfile.TemporaryDirectory() as folder:
            api = Mock()
            prepared = {"model": "small", "context": 8192, "vision": True}
            api.prepare.return_value = prepared
            client = OllamaTransport(lambda *args: None, home=Path(folder), api=api)
            with patch.object(Transport, "request", return_value={"thread": {"id": "thread"}}) as rpc:
                client.request("thread/start", {"model": "small", "baseInstructions": "Fusion instructions", "dynamicTools": [{"name": "test"}]})
                start = rpc.call_args.args[1]
                self.assertIn("Fusion instructions", start["baseInstructions"])
                self.assertEqual(start["dynamicTools"], [{"name": "test"}])
                client.request("turn/start", {"threadId": "thread", "model": "small", "input": []})
                self.assertEqual(len(rpc.call_args_list), 2)
                api.prepare.return_value = {"model": "other", "context": 16384, "vision": False}
                client.request("turn/start", {"threadId": "thread", "model": "other", "input": []})
                self.assertEqual(rpc.call_args_list[-2].args[0], "thread/resume")
                self.assertEqual(rpc.call_args_list[-2].args[1]["config"]["model_context_window"], 16384)
                for action in ("turn/start", "turn/steer"):
                    with self.assertRaisesRegex(OllamaError, "vision support"):
                        client.request(action, {"threadId": "thread", "input": [{"type": "image", "url": "data:image/png;base64,fixture"}]})
                client.request("thread/list")
                self.assertEqual(rpc.call_args.args[1]["modelProviders"], ["steve_ollama"])

    def test_three_providers_keep_preferences_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            choice = ProviderChoice(folder)
            for provider in ("chatgpt", "grok", "ollama"):
                choice.save(provider)
                choice.preferences().save(provider + "-model", "")
            self.assertEqual(ProviderChoice(folder).provider, "ollama")
            for provider in ("chatgpt", "grok", "ollama"):
                choice.save(provider)
                self.assertEqual(choice.preferences().model, provider + "-model")


if __name__ == "__main__":
    unittest.main()
