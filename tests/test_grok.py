"""Grok authentication and Responses compatibility, using isolated credential fixtures."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.grok_auth import AuthError, GrokAuth, ISSUER, CLIENT_ID, Login, login_url_allowed
from steve.grok_transport import GrokGateway, GrokTransport, normalize_request
from steve.preferences import ProviderChoice
from steve.transport import Transport


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "text/event-stream"}


class GrokTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.auth = GrokAuth(Path(self.folder.name) / "grok")
        self.addCleanup(self.auth.cancel)
        self.account = {"type": "grok", "id": "account-1", "email": "fixture@example.com", "planType": "Grok / X"}

    def saved(self, expired=False):
        self.auth._store({"access_token": "fixture-access", "refresh_token": "fixture-refresh",
                          "account": self.account, "expires_at": time.time() + (-1 if expired else 3600)})

    def test_private_store_and_restart_preserve_only_grok_credentials(self):
        self.saved()
        reopened = GrokAuth(self.auth.path.parent)
        self.assertEqual(reopened.account(), self.account)
        self.assertEqual(reopened.access_token(), "fixture-access")
        if os.name == "nt":
            self.assertNotIn(b"fixture-access", self.auth.path.read_bytes())
        else:
            self.assertEqual(self.auth.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.auth.path.parent.stat().st_mode & 0o777, 0o700)

    def test_refresh_rotation_and_invalid_grant_can_sign_in_again(self):
        self.saved(expired=True)
        with patch("steve.grok_auth.http_json", return_value={"access_token": "fresh", "refresh_token": "rotated", "expires_in": 3600}) as request:
            self.assertEqual(self.auth.access_token(), "fresh")
            request.assert_called_once()
        self.assertEqual(self.auth._load()["refresh_token"], "rotated")
        self.saved(expired=True)
        with patch("steve.grok_auth.http_json", side_effect=AuthError("expired", "invalid_grant")):
            self.assertIsNone(self.auth.account(refresh=True))
        self.assertFalse(self.auth.path.exists())

    def test_network_failure_preserves_credentials_and_logout_removes_them(self):
        self.saved(expired=True)
        with patch("steve.grok_auth.http_json", side_effect=AuthError("offline")):
            with self.assertRaises(AuthError):
                self.auth.account(refresh=True)
            self.assertTrue(self.auth.path.exists())
            self.auth.logout()
        self.assertFalse(self.auth.path.exists())

    def test_browser_pkce_rejects_wrong_state_and_exchanges_only_matching_callback(self):
        finished = threading.Event()
        results, calls = [], []
        def completed(*args):
            results.append(args)
            finished.set()
        def request(url, fields=None, token=None):
            calls.append((url, fields, token))
            if url.endswith("/token"):
                return {"access_token": "issued", "refresh_token": "refresh", "expires_in": 1000}
            return {"sub": "account-1", "email": "fixture@example.com"}
        with patch("steve.grok_auth.http_json", side_effect=request):
            result = self.auth.login(False, completed)
            session = self.auth.session
            query = parse_qs(urlsplit(result["authUrl"]).query)
            self.assertEqual(query["client_id"], [CLIENT_ID])
            self.assertEqual(query["code_challenge_method"], ["S256"])
            challenge = base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest()).rstrip(b"=").decode()
            self.assertEqual(query["code_challenge"], [challenge])
            redirect = query["redirect_uri"][0]
            with self.assertRaises(HTTPError) as error:
                urlopen(redirect + "?state=incorrect&code=stolen", timeout=2)
            self.assertEqual(error.exception.code, 400)
            self.assertFalse(calls)
            with urlopen(redirect + "?state=" + session.state + "&code=valid", timeout=2) as response:
                self.assertEqual(response.status, 200)
            self.assertTrue(finished.wait(3))
            session.thread.join(2)
            self.assertTrue(results[0][1])
            self.assertEqual(calls[0][1]["code_verifier"], session.verifier)
            self.assertEqual(self.auth.account()["id"], "account-1")

    def test_cancelled_browser_login_closes_port_without_storing_credentials(self):
        results = []
        self.auth.login(False, lambda *args: results.append(args))
        session = self.auth.session
        self.auth.cancel()
        session.thread.join(2)
        self.assertFalse(session.thread.is_alive())
        self.assertFalse(results)
        self.assertFalse(self.auth.path.exists())

    def test_device_login_does_not_expose_device_secret(self):
        details = {"device_code": "private-device-code", "user_code": "ABCD", "verification_uri": "https://accounts.x.ai/device", "interval": 5}
        with patch("steve.grok_auth.http_json", return_value=details):
            result = self.auth.login(True, lambda *args: None)
        session = self.auth.session
        self.assertNotIn("private-device-code", json.dumps(result))
        self.assertEqual(result["userCode"], "ABCD")
        self.auth.cancel()
        session.thread.join(2)
        self.assertFalse(self.auth.path.exists())

    def test_unexpected_device_url_is_rejected(self):
        with patch("steve.grok_auth.http_json", return_value={"device_code": "private", "user_code": "ABCD", "verification_uri": "https://example.com/device"}):
            with self.assertRaises(AuthError):
                self.auth.login(True, lambda *args: None)
        for url in ("http://accounts.x.ai", "https://accounts.x.ai.evil.test", "https://user@accounts.x.ai", "https://auth.x.ai:444"):
            self.assertFalse(login_url_allowed(url))

    def test_device_pending_and_slow_down_then_success(self):
        waits, results = [], []
        class ClockEvent:
            stopped = False
            def wait(self, seconds):
                waits.append(seconds)
                return self.stopped
            def is_set(self):
                return self.stopped
            def set(self):
                self.stopped = True
        session = Login(self.auth, lambda *args: results.append(args))
        session.cancelled = ClockEvent()
        self.auth.session = session
        responses = [AuthError("pending", "authorization_pending"), AuthError("slow", "slow_down"),
                     {"access_token": "issued", "refresh_token": "refresh", "expires_in": 1000},
                     {"sub": "fixture-user", "email": "fixture@example.com"}]
        with patch("steve.grok_auth.http_json", side_effect=responses):
            session._finish({"device_code": "private-code", "interval": 1, "expires_in": 60})
        self.assertEqual(waits, [1, 1, 6])
        self.assertTrue(results[0][1])
        self.assertEqual(self.auth.account()["id"], "fixture-user")

    def test_cancellation_during_exchange_prevents_late_token_write(self):
        results = []
        session = Login(self.auth, lambda *args: results.append(args))
        self.auth.session = session
        session.redirect = "http://127.0.0.1:1234/callback"
        session.callback = {"code": ["fixture-code"]}
        session.server = type("Server", (), {"handle_request": lambda self: None, "server_close": lambda self: None})()
        def exchange(*args, **kwargs):
            session.cancelled.set()
            return {"access_token": "issued", "expires_in": 1000}
        with patch("steve.grok_auth.http_json", side_effect=exchange), patch.object(self.auth, "_tokens", return_value={"access_token": "issued"}):
            session._finish(None)
        self.assertFalse(results)
        self.assertFalse(self.auth.path.exists())

    def test_model_catalog_filters_non_chat_models_without_inventing_effort_options(self):
        self.saved()
        with patch("steve.grok_auth.http_json", return_value={"data": [{"id": name} for name in ("grok-4.6", "grok-imagine-image", "grok-4-fast", "other")]}):
            result = self.auth.models()["data"]
        self.assertEqual({model["id"] for model in result}, {"grok-4.6", "grok-4-fast"})
        self.assertTrue(next(model for model in result if model["id"] == "grok-4.6")["isDefault"])
        self.assertTrue(all(model["supportedReasoningEfforts"] == [] for model in result))

    def test_model_catalog_uses_live_per_model_effort_capabilities(self):
        self.saved()
        models = [{"id": "grok-4.6", "capabilities": {"reasoning_effort": ["low", "medium", "high", "xhigh"],
                                                                  "default_reasoning_effort": "high"}},
                  {"id": "grok-4.3", "capabilities": {"reasoning_effort": ["none", "low", "low", "future-level"],
                                                                  "default_reasoning_effort": "low"}},
                  {"id": "grok-unknown", "capabilities": None},
                  {"id": "grok-malformed", "capabilities": {"reasoning_effort": "high", "default_reasoning_effort": "high"}}]
        with patch("steve.grok_auth.http_json", return_value={"data": models}):
            catalog = {model["id"]: model for model in self.auth.models()["data"]}
        self.assertEqual([e["reasoningEffort"] for e in catalog["grok-4.6"]["supportedReasoningEfforts"]],
                         ["low", "medium", "high", "xhigh"])
        self.assertEqual(catalog["grok-4.6"]["defaultReasoningEffort"], "high")
        self.assertEqual([e["reasoningEffort"] for e in catalog["grok-4.3"]["supportedReasoningEfforts"]], ["none", "low"])
        self.assertEqual(catalog["grok-4.3"]["defaultReasoningEffort"], "low")
        for name in ("grok-unknown", "grok-malformed"):
            self.assertEqual(catalog[name]["supportedReasoningEfforts"], [])
            self.assertEqual(catalog[name]["defaultReasoningEffort"], "")

    def test_normalization_preserves_images_and_tool_results(self):
        image = {"type": "message", "content": [{"type": "input_image", "image_url": "data:image/png;base64,fixture"}]}
        result = {"type": "function_call_output", "call_id": "call-1", "output": "done"}
        data = {"input": [{"type": "reasoning", "encrypted_content": "not-an-xai-field"}, image, result],
                "tools": [{"type": "web_search", "external_web_access": True}, {"type": "function", "name": "fusion_query_python"}]}
        normalized = json.loads(normalize_request(json.dumps(data).encode()))
        self.assertEqual(normalized["input"], [image, result])
        self.assertEqual(normalized["tools"][0], {"type": "web_search"})
        self.assertEqual(normalized["tools"][1], data["tools"][1])

    def test_gateway_authenticates_at_forward_time_and_only_accepts_responses(self):
        self.saved()
        calls = []
        event = b'data: {"type":"response.completed"}\n\n'
        def opener(request, timeout):
            calls.append(request)
            return Response(event)
        gateway = GrokGateway(self.auth, opener=opener)
        self.addCleanup(gateway.close)
        with urlopen(Request(gateway.base_url + "/responses", data=b'{"input":[]}', headers={"Authorization": "Bearer wrong-provider"}), timeout=3) as response:
            self.assertEqual(response.read(), event)
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer fixture-access")
        self.assertEqual(calls[0].full_url, "https://api.x.ai/v1/responses")
        for suffix in ("/other", "/responses/../../elsewhere"):
            # Windows may reset a rejected connection with an unread request body.
            # Either denial must leave the upstream request count unchanged.
            with self.assertRaises((HTTPError, ConnectionAbortedError, ConnectionResetError)):
                urlopen(Request(gateway.base_url + suffix, data=b'{}'), timeout=3)
        self.assertEqual(len(calls), 1)

    def test_provider_settings_remain_separate_and_default_to_chatgpt(self):
        choice = ProviderChoice(self.folder.name)
        self.assertEqual(choice.provider, "chatgpt")
        choice.preferences().save("gpt-fixture", "high")
        choice.save("grok")
        choice.preferences().save("grok-4.6", "")
        self.assertEqual(ProviderChoice(self.folder.name).provider, "grok")
        choice.save("chatgpt")
        self.assertEqual(choice.preferences().model, "gpt-fixture")

    def test_gateway_retries_401_with_refreshed_token_and_streams_without_buffering(self):
        self.saved()
        attempts = []
        class UnbufferedStream(Response):
            def read(self, size=-1):
                raise AssertionError("Use read1 to avoid buffering the whole stream")
        def opener(request, timeout):
            attempts.append(request.get_header("Authorization"))
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 401, "expired", {}, io.BytesIO())
            return UnbufferedStream(b"data: fixture\n\n")
        gateway = GrokGateway(self.auth, opener=opener)
        self.addCleanup(gateway.close)
        with patch("steve.grok_auth.http_json", return_value={"access_token": "fresh", "expires_in": 3600}):
            with urlopen(Request(gateway.base_url + "/responses", data=b'{"input":[]}'), timeout=3) as response:
                self.assertEqual(response.read(), b"data: fixture\n\n")
        self.assertEqual(attempts, ["Bearer fixture-access", "Bearer fresh"])

    def test_grok_transport_routes_config_without_tokens_and_preserves_tools(self):
        transport = GrokTransport(lambda *args: None, home=Path(self.folder.name))
        transport.gateway = type("Gateway", (), {"base_url": "http://127.0.0.1:1234/fixture"})()
        with patch.object(Transport, "request", return_value={}) as request:
            tools = [{"name": "fusion_query_python"}]
            transport.request("thread/start", {"dynamicTools": tools, "config": {"web_search": "live"}})
            params = request.call_args.args[1]
        self.assertEqual(params["dynamicTools"], tools)
        self.assertEqual(params["model"], "grok-4.6")
        self.assertFalse(params["config"]["features.code_mode"]["enabled"])
        self.assertEqual(params["config"]["model_provider"], "steve_grok")
        self.assertNotIn("fixture-access", json.dumps(params))
        self.assertEqual(transport.home.name, "grok-runtime")


if __name__ == "__main__":
    unittest.main()
