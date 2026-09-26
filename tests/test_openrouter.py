"""OpenRouter sign-in, catalog and Responses compatibility, using isolated key fixtures."""
import base64
from contextlib import contextmanager
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.openrouter_auth import MIN_CONTEXT, OpenRouterAuth, OpenRouterError, catalog, login_url_allowed
from steve.openrouter_transport import COMPACT_LIMIT, OpenRouterGateway, OpenRouterTransport, normalize_request
from steve.preferences import ProviderChoice
from steve.transport import Transport

KEY = "sk-or-v1-" + "0" * 64


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "text/event-stream"}


class MemoryStore:
    """Stands in for Keychain/DPAPI; the real store is exercised by RMFG's tests."""
    def __init__(self, value=None):
        self.value = value
        self.writes = 0

    @contextmanager
    def locked(self):
        yield

    def read(self):
        return self.value

    def write(self, value):
        self.writes += 1
        self.value = json.loads(json.dumps(value))


def model(name, **changes):
    item = {"id": name, "name": name.title(), "context_length": 200000, "supported_parameters": ["tools", "reasoning"],
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            "reasoning": {"supported_efforts": ["max", "high", "low", "ultra"], "default_effort": "high"}}
    item.update(changes)
    return item


def key_info(**changes):
    return {"data": {"label": "STEVE", "limit": None, "limit_remaining": None, "is_free_tier": False, **changes}}


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.requests = []
        self.replies = {}
        self.store = MemoryStore()
        self.auth = OpenRouterAuth(Path(self.folder.name) / "openrouter", store=self.store, opener=self.opener)
        self.addCleanup(self.auth.cancel)

    def opener(self, request, timeout):
        self.requests.append(request)
        path = urlsplit(request.full_url).path
        reply = self.replies.get(path, key_info())
        if isinstance(reply, Exception):
            raise reply
        return Response(json.dumps(reply).encode())

    def saved(self):
        self.store.value = {"key": KEY, "account": {"type": "openrouter", "id": "fixture", "email": "STEVE",
                                                    "planType": "OpenRouter · Pay as you go"}}

    def test_catalog_keeps_usable_tool_models_and_prefers_most_popular(self):
        payload = {"data": [model("zeta/popular"), model("alpha/text-only", architecture={"input_modalities": ["text"], "output_modalities": ["text"]}),
                            model("alpha/batch:batch"), model("alpha/no-tools", supported_parameters=["reasoning"]),
                            model("alpha/small", context_length=MIN_CONTEXT - 1), model("alpha/retired", expiration_date="2026-01-01"),
                            model("alpha/images", architecture={"input_modalities": ["text"], "output_modalities": ["image"]}),
                            model("alpha/plain", reasoning=None), "invalid"]}
        result = catalog(payload, today=date(2026, 9, 25))["data"]
        self.assertEqual([m["id"] for m in result], ["alpha/plain", "alpha/text-only", "zeta/popular"])
        popular = result[-1]
        self.assertTrue(popular["isDefault"])
        self.assertEqual(sum(m["isDefault"] for m in result), 1)
        self.assertEqual(popular["group"], "zeta")
        self.assertEqual(popular["context"], 200000)
        self.assertEqual([e["reasoningEffort"] for e in popular["supportedReasoningEfforts"]], ["low", "high", "max"])
        self.assertEqual(popular["defaultReasoningEffort"], "high")
        self.assertFalse(result[1]["supportsImages"])
        self.assertEqual(result[0]["supportedReasoningEfforts"], [])
        with self.assertRaisesRegex(OpenRouterError, "no models"):
            catalog({"data": [model("alpha/no-tools", supported_parameters=[])]})

    def test_models_request_filters_tools_by_popularity_without_the_key(self):
        self.saved()
        self.replies["/api/v1/models"] = {"data": [model("anthropic/claude")]}
        self.assertEqual(self.auth.models()["data"][0]["id"], "anthropic/claude")
        query = parse_qs(urlsplit(self.requests[0].full_url).query)
        self.assertEqual(query, {"supported_parameters": ["tools"], "sort": ["most-popular"]})
        self.assertIsNone(self.requests[0].get_header("Authorization"))

    def test_only_openrouter_sign_in_page_is_allowed(self):
        self.assertTrue(login_url_allowed("https://openrouter.ai/auth?callback_url=x"))
        for url in ("http://openrouter.ai/auth", "https://openrouter.ai.evil/auth", "https://user@openrouter.ai/auth",
                    "https://openrouter.ai:8443/auth", "https://openrouter.ai/other"):
            self.assertFalse(login_url_allowed(url), url)

    def test_browser_pkce_rejects_wrong_path_and_stores_exchanged_key(self):
        finished = threading.Event()
        results = []
        def completed(*args):
            results.append(args)
            finished.set()
        self.replies["/api/v1/auth/keys"] = {"key": KEY}
        self.replies["/api/v1/key"] = key_info(limit_remaining=12.5)
        result = self.auth.login(completed)
        session = self.auth.session
        self.assertTrue(login_url_allowed(result["authUrl"]))
        query = parse_qs(urlsplit(result["authUrl"]).query)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [challenge])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["key_label"], ["STEVE"])
        callback = query["callback_url"][0]
        self.assertTrue(callback.startswith("http://localhost:"))
        wrong = callback.replace(session.path, "/guessed/callback")
        with self.assertRaises(HTTPError) as error:
            urlopen(wrong + "?code=stolen", timeout=2)
        self.assertEqual(error.exception.code, 400)
        self.assertFalse(self.requests)
        with urlopen(callback + "?code=valid", timeout=2) as response:
            self.assertEqual(response.status, 200)
        self.assertTrue(finished.wait(3))
        session.thread.join(2)
        self.assertTrue(results[0][1])
        exchange = json.loads(self.requests[0].data)
        self.assertEqual(exchange, {"code": "valid", "code_verifier": session.verifier, "code_challenge_method": "S256"})
        self.assertEqual(self.requests[1].get_header("Authorization"), "Bearer " + KEY)
        account = self.auth.account()
        self.assertEqual(account["email"], "STEVE")
        self.assertEqual(account["planType"], "OpenRouter · $12.50 key limit left")
        self.assertNotIn(KEY, json.dumps(account))
        self.assertEqual(self.auth.api_key(), KEY)

    def test_cancelled_browser_login_closes_port_without_storing_key(self):
        results = []
        self.auth.login(lambda *args: results.append(args))
        session = self.auth.session
        self.auth.cancel()
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        self.assertFalse(results)
        self.assertEqual(self.store.writes, 0)

    def test_rejected_key_is_forgotten_but_network_failure_keeps_it(self):
        self.saved()
        self.replies["/api/v1/key"] = OSError("offline")
        with self.assertRaisesRegex(OpenRouterError, "Could not reach"):
            self.auth.account(refresh=True)
        self.assertEqual(self.auth.api_key(), KEY)
        self.replies["/api/v1/key"] = key_info(is_free_tier=True)
        self.assertEqual(self.auth.account(refresh=True)["planType"], "OpenRouter · Free tier")
        self.replies["/api/v1/key"] = HTTPError("https://openrouter.ai/api/v1/key", 401, "revoked", {}, io.BytesIO(b"secret body"))
        self.assertIsNone(self.auth.account(refresh=True))
        with self.assertRaisesRegex(OpenRouterError, "Sign in with OpenRouter"):
            self.auth.api_key()

    def test_logout_removes_local_key(self):
        self.saved()
        self.auth.logout()
        self.assertIsNone(self.auth.account())
        self.assertEqual(self.store.value, {})

    def test_normalization_keeps_history_and_removes_local_identifiers(self):
        image = {"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": "data:image/png;base64,fixture"}]}
        result = {"type": "function_call_output", "call_id": "call-1", "output": "done"}
        reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "content": None, "encrypted_content": "opaque"}
        data = {"input": [reasoning, image, result], "client_metadata": {"x-codex-installation-id": "local"},
                "tools": [{"type": "function", "name": "fusion_query_python"}], "store": False}
        normalized = json.loads(normalize_request(json.dumps(data).encode()))
        self.assertNotIn("client_metadata", normalized)
        self.assertEqual(normalized["input"], [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}, image, result])
        self.assertEqual(normalized["tools"], data["tools"])
        self.assertIs(normalized["store"], False)

    def test_gateway_adds_key_at_forward_time_and_only_accepts_responses(self):
        self.saved()
        calls = []
        event = b'data: {"type":"response.completed"}\n\n'
        class UnbufferedStream(Response):
            def read(self, size=-1):
                raise AssertionError("Use read1 to avoid buffering the whole stream")
        def opener(request, timeout):
            calls.append(request)
            return UnbufferedStream(event)
        gateway = OpenRouterGateway(self.auth, opener=opener)
        self.addCleanup(gateway.close)
        with urlopen(Request(gateway.base_url + "/responses", data=b'{"input":[],"client_metadata":{}}',
                             headers={"Authorization": "Bearer wrong-provider"}), timeout=3) as response:
            self.assertEqual(response.read(), event)
        self.assertEqual(calls[0].full_url, "https://openrouter.ai/api/v1/responses")
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(calls[0].get_header("X-openrouter-title"), "STEVE")
        self.assertNotIn(b"client_metadata", calls[0].data)
        for suffix in ("/other", "/responses/../../elsewhere"):
            with self.assertRaises((HTTPError, ConnectionAbortedError, ConnectionResetError)):
                urlopen(Request(gateway.base_url + suffix, data=b'{}'), timeout=3)
        with self.assertRaises(HTTPError):
            urlopen(Request(gateway.base_url + "/responses", data=b'{}', headers={"Origin": "https://example.com"}), timeout=3)
        self.assertEqual(len(calls), 1)

    def test_gateway_explains_credit_and_sign_in_failures_without_upstream_bodies(self):
        self.saved()
        def opener(request, timeout):
            raise HTTPError(request.full_url, 402, "Payment Required", {}, io.BytesIO(b"upstream detail"))
        gateway = OpenRouterGateway(self.auth, opener=opener)
        self.addCleanup(gateway.close)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(gateway.base_url + "/responses", data=b'{"input":[]}'), timeout=3)
        self.assertEqual(error.exception.code, 402)
        self.assertIn("Add credits", json.loads(error.exception.read())["error"]["message"])
        self.auth.forget()
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(gateway.base_url + "/responses", data=b'{"input":[]}'), timeout=3)
        self.assertEqual(error.exception.code, 401)
        self.assertIn("Sign in with OpenRouter", json.loads(error.exception.read())["error"]["message"])

    def transport(self):
        transport = OpenRouterTransport(lambda *args: None, home=Path(self.folder.name), auth=self.auth)
        transport.gateway = type("Gateway", (), {"base_url": "http://127.0.0.1:1234/fixture"})()
        transport.catalog = {"big/model": {"context": 1000000, "supportsImages": True},
                             "small/text": {"context": 100000, "supportsImages": False}}
        transport.default_model = "big/model"
        return transport

    def test_transport_routes_config_without_key_and_sizes_context_per_model(self):
        self.saved()
        transport = self.transport()
        with patch.object(Transport, "request", return_value={"thread": {"id": "thread"}}) as request:
            tools = [{"name": "fusion_query_python"}]
            transport.request("thread/start", {"dynamicTools": tools, "config": {"web_search": "live"}})
            params = request.call_args.args[1]
            self.assertEqual(params["dynamicTools"], tools)
            self.assertEqual(params["model"], "big/model")
            config = params["config"]
            self.assertEqual(config["model_provider"], "steve_openrouter")
            self.assertEqual(config["web_search"], "disabled")
            self.assertFalse(config["features.code_mode"]["enabled"])
            self.assertEqual(config["model_context_window"], 1000000)
            self.assertEqual(config["model_auto_compact_token_limit"], COMPACT_LIMIT)
            self.assertIn("Web search is unavailable", params["baseInstructions"])
            self.assertNotIn(KEY, json.dumps(params))
            transport.request("turn/start", {"threadId": "thread", "model": "big/model", "input": []})
            self.assertEqual([call.args[0] for call in request.call_args_list], ["thread/start", "turn/start"])
            transport.request("turn/start", {"threadId": "thread", "model": "small/text", "input": []})
            resume = request.call_args_list[-2].args
            self.assertEqual(resume[0], "thread/resume")
            self.assertEqual(resume[1]["config"]["model_context_window"], 100000)
            self.assertEqual(resume[1]["config"]["model_auto_compact_token_limit"], 80000)
            count = request.call_count
            for action in ("turn/start", "turn/steer"):
                with self.assertRaisesRegex(OpenRouterError, "image support"):
                    transport.request(action, {"threadId": "thread", "input": [{"type": "image", "url": "data:image/png;base64,fixture"}]})
            self.assertEqual(request.call_count, count)
            transport.request("thread/list")
            self.assertEqual(request.call_args.args[1]["modelProviders"], ["steve_openrouter"])
        self.assertEqual(transport.home.name, "openrouter-runtime")

    def test_transport_resumes_saved_chat_with_its_own_model(self):
        transport = self.transport()
        replies = {"thread/read": {"thread": {"model": "small/text"}}, "thread/resume": {"thread": {"id": "saved"}}}
        with patch.object(Transport, "request", side_effect=lambda method, params, **_: replies[method]) as request:
            transport.request("thread/resume", {"threadId": "saved"})
        self.assertEqual(request.call_args.args[1]["model"], "small/text")
        self.assertEqual(transport.threads["saved"], "small/text")

    def test_transport_owns_account_rpcs_and_rejects_device_code(self):
        self.saved()
        transport = self.transport()
        with patch.object(Transport, "request") as request:
            self.assertEqual(transport.request("account/read")["account"]["email"], "STEVE")
            with self.assertRaisesRegex(ValueError, "browser"):
                transport.request("account/login/start", {"type": "chatgptDeviceCode"})
            transport.request("account/logout")
            request.assert_not_called()
        self.assertIsNone(transport.request("account/read")["account"])

    def test_provider_preferences_remain_separate(self):
        choice = ProviderChoice(self.folder.name)
        for provider in ("chatgpt", "openrouter"):
            choice.save(provider)
            choice.preferences().save(provider + "-model", "")
        self.assertEqual(ProviderChoice(self.folder.name).provider, "openrouter")
        self.assertTrue((Path(self.folder.name) / "openrouter" / "preferences.json").is_file())
        choice.save("chatgpt")
        self.assertEqual(choice.preferences().model, "chatgpt-model")


if __name__ == "__main__":
    unittest.main()
