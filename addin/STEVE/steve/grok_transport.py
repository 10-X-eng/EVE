"""Use Codex's conversation engine with xAI authentication and Responses transport."""
import copy
from http.server import BaseHTTPRequestHandler
import json
import secrets
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .grok_auth import API, AuthError, GrokAuth
from .transport import Transport, data_home
from .loopback_http import ThreadingLoopbackHTTPServer


def normalize_request(raw):
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("Expected a Responses request")
    if isinstance(body.get("input"), list):
        body["input"] = [item for item in body["input"] if not isinstance(item, dict) or item.get("type") != "reasoning"]
    for tool in body.get("tools", []):
        if isinstance(tool, dict) and tool.get("type") == "web_search":
            tool.pop("external_web_access", None)
    return json.dumps(body).encode()


class GrokGateway:
    """Loopback-only bridge. xAI tokens never enter Codex config, history, or logs."""
    def __init__(self, auth, opener=urlopen):
        self.auth, self.opener = auth, opener
        self.path = "/" + secrets.token_urlsafe(32)
        self.closed = threading.Event()
        gateway = self
        class Handler(BaseHTTPRequestHandler):
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
                    upstream = None
                    for attempt in range(2):
                        token = gateway.auth.access_token(force=bool(attempt))
                        try:
                            upstream = gateway.opener(Request(API + "/responses", data=body, headers={
                                "Authorization": "Bearer " + token, "Content-Type": "application/json",
                                "Accept": "text/event-stream", "User-Agent": "STEVE"}), timeout=300)
                            break
                        except HTTPError as exc:
                            if exc.code == 401 and attempt == 0:
                                exc.close()
                                continue
                            upstream = exc
                            break
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
                    body = json.dumps({"error": {"message": str(exc) if isinstance(exc, AuthError)
                                      else "STEVE could not reach Grok. Check your connection and sign-in, then retry."}}).encode()
                    try:
                        self.send_response(502)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except OSError:
                        pass
            def log_message(self, *args):
                pass
        self.server = ThreadingLoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_port}{self.path}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1},
                                       daemon=True, name="STEVE-Grok-Responses")
        self.thread.start()

    def close(self):
        self.closed.set()
        self.server.shutdown()
        self.server.server_close()


class GrokTransport(Transport):
    def __init__(self, on_event, home=None, command=None):
        root = home or data_home()
        super().__init__(on_event, home=root / "grok-runtime", command=command)
        self.auth = GrokAuth(root / "grok")
        self.gateway = None
        self.default_model = "grok-4.6"

    def start(self):
        self.gateway = GrokGateway(self.auth)
        try:
            super().start()
        except Exception:
            self.close()
            raise

    def request(self, method, params=None, **kwargs):
        params = copy.deepcopy(params or {})
        if method == "account/read":
            return {"account": self.auth.account(refresh=params.get("refreshToken", False))}
        if method == "account/login/start":
            def completed(login_id, success, message):
                if not self._closed:
                    self.on_event("account/login/completed", {"loginId": login_id, "success": success, "error": message})
            return self.auth.login(params.get("type") == "chatgptDeviceCode", completed)
        if method == "account/login/cancel":
            self.auth.cancel()
            return {}
        if method == "account/logout":
            self.auth.logout()
            return {}
        if method == "model/list":
            result = self.auth.models()
            self.default_model = next(model["id"] for model in result["data"] if model["isDefault"])
            return result
        if method == "thread/list":
            params["modelProviders"] = ["steve_grok"]
        if method in ("thread/start", "thread/resume"):
            params.setdefault("config", {}).update({
                "model_provider": "steve_grok", "model_providers.steve_grok.name": "Grok",
                "model_providers.steve_grok.base_url": self.gateway.base_url,
                "model_providers.steve_grok.requires_openai_auth": False,
                "model_providers.steve_grok.wire_api": "responses",
                "model_providers.steve_grok.supports_websockets": False,
                # xAI receives ordinary function tools; STEVE's Python tools still run whole operations.
                "features.code_mode": {"enabled": False, "direct_only_tool_namespaces": ["core", "conversation", "view"]},
            })
            if method == "thread/start":
                params.setdefault("model", self.default_model)
        return super().request(method, params, **kwargs)

    def close(self):
        self.auth.cancel()
        super().close()
        if self.gateway:
            self.gateway.close()
            self.gateway = None
