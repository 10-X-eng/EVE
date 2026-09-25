"""Use Codex's conversation engine with an OpenRouter key and OpenRouter's Responses API."""
import copy
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .loopback_http import ThreadingLoopbackHTTPServer
from .openrouter_auth import API, HEADERS, OpenRouterAuth, OpenRouterError, error_message
from .transport import Transport, data_home

# Used only when a saved chat's model is missing from the current catalog.
FALLBACK_CONTEXT = 131072
# The API is stateless: each request resends the history, so large windows compact earlier.
COMPACT_LIMIT = 200000
MAPPED_ERRORS = (401, 402, 403, 429)


def normalize_request(raw):
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("Expected a Responses request")
    # Installation and session identifiers stay on this computer.
    body.pop("client_metadata", None)
    if isinstance(body.get("input"), list):
        for item in body["input"]:
            # Reasoning is replayed for models that need it during tool calls; null content is not part of the schema.
            if isinstance(item, dict) and item.get("type") == "reasoning" and item.get("content") is None:
                item.pop("content", None)
    return json.dumps(body).encode()


class OpenRouterGateway:
    """Loopback-only bridge. The OpenRouter key never enters Codex config, history, or logs."""
    def __init__(self, auth, opener=urlopen):
        self.auth, self.opener = auth, opener
        self.path = "/" + secrets.token_urlsafe(32)
        self.closed = threading.Event()
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def reply_error(self, status, message):
                body = json.dumps({"error": {"message": message}}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_POST(self):
                if self.path != gateway.path + "/responses" or self.headers.get("Origin") or gateway.closed.is_set():
                    self.send_error(404)
                    return
                headers_sent = False
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 64 * 1024 * 1024:
                        self.send_error(413)
                        return
                    self.connection.settimeout(30)
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("Incomplete request")
                    body = normalize_request(raw)
                    self.connection.settimeout(300)
                    try:
                        upstream = gateway.opener(Request(API + "/responses", data=body, headers={
                            "Authorization": "Bearer " + gateway.auth.api_key(), "Content-Type": "application/json",
                            "Accept": "text/event-stream", "User-Agent": "STEVE", **HEADERS}), timeout=300)
                    except HTTPError as exc:
                        if exc.code in MAPPED_ERRORS:
                            exc.close()
                            self.reply_error(exc.code, error_message(exc.code))
                            return
                        upstream = exc  # OpenRouter's own message explains other failures.
                    with upstream:
                        self.send_response(upstream.status)
                        self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        headers_sent = True
                        read = getattr(upstream, "read1", upstream.read)
                        while not gateway.closed.is_set():
                            chunk = read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    if headers_sent:
                        return  # Close an interrupted stream; never append HTTP headers inside SSE.
                    if isinstance(exc, OpenRouterError):
                        self.reply_error(exc.status or 502, str(exc))
                    else:
                        self.reply_error(502, "STEVE could not reach OpenRouter. Check your connection and sign-in, then retry.")
            def log_message(self, *args):
                pass
        self.server = ThreadingLoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_port}{self.path}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1},
                                       daemon=True, name="STEVE-OpenRouter-Responses")
        self.thread.start()

    def close(self):
        self.closed.set()
        self.server.shutdown()
        self.server.server_close()


class OpenRouterTransport(Transport):
    def __init__(self, on_event, home=None, command=None, auth=None):
        root = Path(home or data_home())
        super().__init__(on_event, home=root / "openrouter-runtime", command=command)
        self.auth = auth or OpenRouterAuth(root / "openrouter")
        self.gateway = None
        self.catalog = {}
        self.default_model = None
        self.threads = {}

    def start(self):
        self.gateway = OpenRouterGateway(self.auth)
        try:
            super().start()
        except Exception:
            self.close()
            raise

    def config(self, model):
        context = (self.catalog.get(model) or {}).get("context") or FALLBACK_CONTEXT
        return {"model_provider": "steve_openrouter", "model_providers.steve_openrouter.name": "OpenRouter",
                "model_providers.steve_openrouter.base_url": self.gateway.base_url,
                "model_providers.steve_openrouter.requires_openai_auth": False,
                "model_providers.steve_openrouter.wire_api": "responses",
                "model_providers.steve_openrouter.supports_websockets": False,
                "model_context_window": context, "model_auto_compact_token_limit": min(context * 4 // 5, COMPACT_LIMIT),
                "web_search": "disabled",
                # OpenRouter models receive ordinary function tools; STEVE's Python tools still run whole operations.
                "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]}}

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            return {"account": self.auth.account(refresh=params.get("refreshToken", False))}
        if method == "account/login/start":
            if params.get("type") == "chatgptDeviceCode":
                raise ValueError("OpenRouter sign-in uses your browser. Choose Sign in with OpenRouter.")
            def completed(login_id, success, message):
                if not self._closed:
                    self.on_event("account/login/completed", {"loginId": login_id, "success": success, "error": message})
            return self.auth.login(completed)
        if method == "account/login/cancel":
            self.auth.cancel()
            return {}
        if method == "account/logout":
            self.auth.logout()
            return {}
        if method == "model/list":
            result = self.auth.models()
            self.catalog = {model["id"]: model for model in result["data"]}
            self.default_model = next(model["id"] for model in result["data"] if model["isDefault"])
            return result
        if method == "thread/list":
            params["modelProviders"] = ["steve_openrouter"]
        if method in ("thread/start", "thread/resume"):
            if not self.catalog:
                self.request("model/list")
            model = params.get("model")
            if not model and method == "thread/resume":
                saved = super().request("thread/read", {"threadId": params["threadId"], "includeTurns": False})
                model = saved.get("thread", {}).get("model")
            model = model or self.default_model
            params["model"] = model
            params.setdefault("config", {}).update(self.config(model))
            params["baseInstructions"] = params.get("baseInstructions", "") + "\nThis is an OpenRouter session. Web search is unavailable. Use fusion_api_help and fusion_fetch_docs for Fusion API documentation."
            result = super().request(method, params, **kwargs)
            self.threads[result["thread"]["id"]] = model
            return result
        if method == "turn/start":
            model = params.get("model") or self.threads.get(params["threadId"]) or self.default_model
            if model != self.threads.get(params["threadId"]):
                # Context limits are thread settings; apply the new model's before its first request.
                super().request("thread/resume", {"threadId": params["threadId"], "model": model, "config": self.config(model)})
                self.threads[params["threadId"]] = model
            params["model"] = model
        if method in ("turn/start", "turn/steer"):
            info = self.catalog.get(self.threads.get(params["threadId"]), {})
            if info.get("supportsImages") is False and any(item.get("type") in ("image", "localImage") for item in params.get("input", [])):
                raise OpenRouterError("This model cannot read images. Select an OpenRouter model with image support, then resend the image.")
        return super().request(method, params, **kwargs)

    def close(self):
        self.auth.cancel()
        super().close()
        if self.gateway:
            self.gateway.close()
            self.gateway = None
