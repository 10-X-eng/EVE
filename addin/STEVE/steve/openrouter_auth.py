"""OpenRouter browser PKCE sign-in, protected key storage and model catalog."""
import base64
from datetime import date
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from .loopback_http import LoopbackHTTPServer
from .secure_store import SecureStore

SITE = "https://openrouter.ai"
API = SITE + "/api/v1"
KEYS_URL = SITE + "/settings/keys"
# Attribution shown on OpenRouter; no user or design data.
HEADERS = {"HTTP-Referer": "https://github.com/10-X-eng/STEVE", "X-OpenRouter-Title": "STEVE"}
# STEVE's instructions and tool declarations alone use several thousand tokens.
MIN_CONTEXT = 65536
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


class OpenRouterError(RuntimeError):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def login_url_allowed(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == "openrouter.ai" and parsed.port in (None, 443)
            and not parsed.username and parsed.path == "/auth")


def error_message(status):
    return ("OpenRouter rejected the saved key. Sign in with OpenRouter again." if status == 401
            else "Your OpenRouter credits or this key's limit are used up. Add credits at openrouter.ai, then retry." if status == 402
            else "OpenRouter denied this request. Check your OpenRouter account and privacy settings." if status == 403
            else "OpenRouter or the model's provider is limiting requests. Wait a moment, then retry." if status == 429
            else "OpenRouter is temporarily unavailable. Try again shortly.")


def http_json(url, body=None, key=None, opener=urlopen):
    headers = {"Accept": "application/json", "User-Agent": "STEVE", **HEADERS}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        with opener(Request(url, data=data, headers=headers), timeout=20) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected object")
        return result
    except HTTPError as exc:
        exc.close()
        # Never expose response bodies, keys, authorization codes, or request URLs.
        raise OpenRouterError(error_message(exc.code), exc.code) from None
    except (OSError, ValueError):
        raise OpenRouterError("Could not reach OpenRouter. Check your connection and try again.") from None


def plan(info):
    if info.get("is_free_tier"):
        return "OpenRouter · Free tier"
    remaining = info.get("limit_remaining")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return f"OpenRouter · ${remaining:,.2f} key limit left"
    return "OpenRouter · Pay as you go"


def catalog(payload, today=None):
    """Tool-capable text models in OpenRouter's popularity order; the first is the default."""
    today = (today or date.today()).isoformat()
    models = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        name = item.get("id")
        architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        parameters = item.get("supported_parameters") if isinstance(item.get("supported_parameters"), list) else []
        context = item.get("context_length")
        expires = item.get("expiration_date")
        if (not isinstance(name, str) or "/" not in name or name.endswith(":batch")
                or "tools" not in parameters or "text" not in (architecture.get("output_modalities") or [])
                or not isinstance(context, int) or isinstance(context, bool) or context < MIN_CONTEXT
                or (isinstance(expires, str) and expires[:10] < today)):
            continue
        reasoning = item.get("reasoning") if isinstance(item.get("reasoning"), dict) else {}
        advertised = reasoning.get("supported_efforts") if isinstance(reasoning.get("supported_efforts"), list) else []
        efforts = [level for level in EFFORTS if level in advertised]
        default = reasoning.get("default_effort")
        label = item.get("name") if isinstance(item.get("name"), str) and item["name"] else name
        models.append({"id": name, "model": name, "displayName": label, "group": name.split("/", 1)[0],
                       "supportsImages": "image" in (architecture.get("input_modalities") or []),
                       "context": context, "isDefault": not models,
                       "defaultReasoningEffort": default if default in efforts else "",
                       "supportedReasoningEfforts": [{"reasoningEffort": level, "description": ""} for level in efforts]})
    if not models:
        raise OpenRouterError("OpenRouter returned no models with tool support. Try Refresh models later.")
    models.sort(key=lambda model: (model["group"], model["displayName"].lower()))
    return {"data": models}


class OpenRouterAuth:
    def __init__(self, home, store=None, opener=urlopen):
        self.store = store or SecureStore(Path(home), "openrouter")
        self.opener = opener
        self._lock = threading.RLock()
        self.session = None

    def _load(self):
        saved = self.store.read()
        if (isinstance(saved, dict) and isinstance(saved.get("key"), str) and saved["key"]
                and isinstance(saved.get("account"), dict)):
            return saved
        return None

    def _account(self, key):
        info = http_json(API + "/key", key=key, opener=self.opener).get("data")
        if not isinstance(info, dict):
            raise OpenRouterError("OpenRouter returned invalid key information. Try signing in again.")
        label = info.get("label")
        return {"type": "openrouter", "id": hashlib.sha256(key.encode()).hexdigest()[:24], "planType": plan(info),
                "email": str(label)[:320] if isinstance(label, str) and label else "OpenRouter key"}

    def api_key(self):
        with self._lock:
            saved = self._load()
        if not saved:
            raise OpenRouterError("Sign in with OpenRouter to continue.", 401)
        return saved["key"]

    def account(self, refresh=False):
        with self._lock:
            saved = self._load()
            if not saved or not refresh:
                return saved["account"] if saved else None
            try:
                account = self._account(saved["key"])
            except OpenRouterError as exc:
                if exc.status == 401:
                    self.forget()
                    return None
                raise
            if account != saved["account"]:
                with self.store.locked():
                    self.store.write({"key": saved["key"], "account": account})
            return account

    def models(self):
        return catalog(http_json(API + "/models?" + urlencode({"supported_parameters": "tools", "sort": "most-popular"}),
                                 opener=self.opener))

    def forget(self):
        with self._lock, self.store.locked():
            self.store.write({})

    def logout(self):
        # OpenRouter has no revoke call for this key; the user deletes it in OpenRouter's key settings.
        self.cancel()
        self.forget()

    def cancel(self):
        with self._lock:
            if self.session:
                self.session.cancelled.set()
                self.session = None

    def login(self, completed):
        self.cancel()
        session = Login(self, completed)
        with self._lock:
            self.session = session
        try:
            return session.start()
        except Exception:
            self.cancel()
            raise


class Login:
    def __init__(self, auth, completed):
        self.auth, self.completed = auth, completed
        self.cancelled = threading.Event()
        self.id = secrets.token_hex(16)
        # OpenRouter has no state parameter; an unguessable callback path serves that purpose.
        self.path = "/" + secrets.token_urlsafe(32) + "/callback"
        self.verifier = secrets.token_urlsafe(48)
        self.code = None
        self.server = None

    def start(self):
        session = self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)
            def do_GET(self):
                parts = urlsplit(self.path)
                code = parse_qs(parts.query).get("code", [""])[0]
                if parts.path != session.path or not code:
                    self.send_error(400)
                    return
                session.code = code
                body = b"Sign-in received. Return to STEVE in Fusion to finish."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        self.server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.2
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        url = SITE + "/auth?" + urlencode({"callback_url": f"http://localhost:{self.server.server_port}{self.path}",
                                           "code_challenge": challenge, "code_challenge_method": "S256",
                                           "key_label": "STEVE"})
        self.thread = threading.Thread(target=self._finish, daemon=True, name="STEVE-OpenRouter-Login")
        self.thread.start()
        return {"loginId": self.id, "authUrl": url}

    def _finish(self):
        try:
            # Authorization codes expire after 10 minutes; allow time to create an account first.
            deadline = time.monotonic() + 900
            while not self.cancelled.is_set() and time.monotonic() < deadline:
                self.server.handle_request()
                if self.code is None:
                    continue
                result = http_json(API + "/auth/keys", {"code": self.code, "code_verifier": self.verifier,
                                                        "code_challenge_method": "S256"}, opener=self.auth.opener)
                key = result.get("key")
                if not isinstance(key, str) or not key:
                    raise OpenRouterError("OpenRouter returned no API key. Try signing in again.")
                account = self.auth._account(key)
                with self.auth._lock:
                    if self.cancelled.is_set() or self.auth.session is not self:
                        return
                    with self.auth.store.locked():
                        self.auth.store.write({"key": key, "account": account})
                self.completed(self.id, True, "")
                return
            if not self.cancelled.is_set():
                raise OpenRouterError("OpenRouter sign-in timed out. Try again.")
        except Exception as exc:
            if not self.cancelled.is_set():
                self.completed(self.id, False, "OpenRouter sign-in was not completed. Try again." if isinstance(exc, OpenRouterError)
                               and exc.status in (400, 401, 403) else str(exc) if isinstance(exc, OpenRouterError)
                               else "OpenRouter sign-in failed. Try again.")
        finally:
            self.server.server_close()
