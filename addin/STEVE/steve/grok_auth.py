"""xAI browser PKCE/device login and refresh, isolated from ChatGPT credentials."""
import base64
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from .loopback_http import LoopbackHTTPServer

ISSUER = "https://auth.x.ai"
API = "https://api.x.ai/v1"
# Public Grok CLI client, also used by the reference integration. No client secret.
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPES = "openid profile email offline_access grok-cli:access api:access"


class AuthError(RuntimeError):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


def login_url_allowed(url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in ("auth.x.ai", "accounts.x.ai") and parsed.port in (None, 443) and not parsed.username


def http_json(url, fields=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if fields is not None:
        headers.update({"Content-Type": "application/x-www-form-urlencoded", "x-grok-client-surface": "ui"})
        data = urlencode(fields).encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected object")
        return result
    except HTTPError as exc:
        try:
            code = json.loads(exc.read(4096)).get("error", "")
            code = code if isinstance(code, str) else ""
        except (ValueError, OSError):
            code = ""
        if exc.code == 401 and not code:
            code = "invalid_token"
        # Never expose response bodies, tokens, authorization codes, or request URLs.
        message = ("Grok sign-in expired. Sign in with X / Grok again." if exc.code in (400, 401)
                   else "xAI denied access. Check your Grok account access." if exc.code == 403
                   else "xAI is temporarily unavailable. Try again shortly.")
        raise AuthError(message, code) from None
    except (OSError, ValueError):
        raise AuthError("Could not reach xAI. Check your connection and try again.") from None


def protect(data, decrypt=False):
    """Windows DPAPI binds credentials to the current user; Unix uses file modes."""
    if os.name != "nt":
        return data
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32")
    kernel = ctypes.WinDLL("kernel32")
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    operation.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise AuthError("Could not access protected Grok credentials. Sign in again.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class GrokAuth:
    def __init__(self, home):
        self.path = Path(home) / ("auth.dpapi" if os.name == "nt" else "auth.json")
        self._lock = threading.RLock()
        self.session = None

    def _load(self):
        try:
            value = json.loads(protect(self.path.read_bytes(), decrypt=True))
            if (isinstance(value, dict) and isinstance(value.get("access_token"), str) and value["access_token"]
                    and isinstance(value.get("account"), dict) and isinstance(value.get("expires_at"), (int, float))
                    and math.isfinite(value["expires_at"])):
                return value
        except (OSError, ValueError, AuthError):
            pass
        return None

    def _store(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        content = protect(json.dumps(value).encode())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            if os.name != "nt":
                temporary.chmod(0o600)
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def _tokens(self, payload, previous=None):
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError("xAI returned no access token. Try signing in again.")
        lifetime = float(payload.get("expires_in", 3600))
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise AuthError("xAI returned an invalid token expiry. Try signing in again.")
        account = (previous or {}).get("account")
        if not account:
            info = http_json(ISSUER + "/oauth2/userinfo", token=token)
            if not isinstance(info.get("sub"), str) or not info["sub"]:
                raise AuthError("xAI could not identify this account. Try signing in again.")
            account = {"type": "grok", "id": info["sub"], "planType": "Grok / X",
                       "email": str(info.get("email") or info.get("name") or "Grok account")[:320]}
        return {"access_token": token, "refresh_token": payload.get("refresh_token") or (previous or {}).get("refresh_token", ""),
                "expires_at": time.time() + lifetime, "account": account}

    def access_token(self, force=False):
        with self._lock:
            saved = self._load()
            if not saved:
                raise AuthError("Sign in with X / Grok to continue.")
            if force or time.time() >= float(saved.get("expires_at", 0)) - 60:
                if not saved.get("refresh_token"):
                    raise AuthError("Grok sign-in expired. Sign in again.", "invalid_grant")
                result = http_json(ISSUER + "/oauth2/token", {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                                            "refresh_token": saved["refresh_token"]})
                saved = self._tokens(result, saved)
                self._store(saved)
            return saved["access_token"]

    def account(self, refresh=False):
        with self._lock:
            saved = self._load()
            if saved and refresh:
                try:
                    self.access_token()
                except AuthError as exc:
                    if exc.code in ("invalid_grant", "invalid_token"):
                        self.path.unlink(missing_ok=True)
                        return None
                    raise
                saved = self._load()
            return saved.get("account") if saved else None

    def models(self):
        payload = http_json(API + "/models", token=self.access_token())
        models = {item["id"]: item for item in payload.get("data", []) if isinstance(item, dict)
                      and isinstance(item.get("id"), str) and item["id"].startswith("grok-")
                      and not any(word in item["id"].lower() for word in ("image", "imagine", "video", "audio", "embedding"))}
        ids = sorted(models)
        if not ids:
            raise AuthError("No Grok chat models are available for this account. Check your xAI access.")
        default = "grok-4.6" if "grok-4.6" in ids else ids[0]
        catalog = []
        for name in ids:
            capabilities = models[name].get("capabilities")
            capabilities = capabilities if isinstance(capabilities, dict) else {}
            advertised = capabilities.get("reasoning_effort")
            advertised = advertised if isinstance(advertised, list) else []
            # Use the account's live capabilities, restricted to levels understood by Codex.
            efforts = [level for level in ("none", "minimal", "low", "medium", "high", "xhigh") if level in advertised]
            default_effort = capabilities.get("default_reasoning_effort")
            catalog.append({"id": name, "model": name, "displayName": name, "isDefault": name == default,
                            "defaultReasoningEffort": default_effort if default_effort in efforts else "",
                            "supportedReasoningEfforts": [{"reasoningEffort": level, "description": ""} for level in efforts]})
        return {"data": catalog}

    def logout(self):
        self.cancel()
        with self._lock:
            saved = self._load()
            self.path.unlink(missing_ok=True)
        for kind in ("refresh_token", "access_token"):
            if (saved or {}).get(kind):
                try:
                    http_json(ISSUER + "/oauth2/revoke", {"client_id": CLIENT_ID, "token": saved[kind], "token_type_hint": kind})
                except AuthError:
                    pass

    def cancel(self):
        with self._lock:
            if self.session:
                self.session.cancelled.set()
                self.session = None

    def login(self, device, completed):
        self.cancel()
        session = Login(self, completed)
        with self._lock:
            self.session = session
        try:
            return session.start(device)
        except Exception:
            self.cancel()
            raise


class Login:
    def __init__(self, auth, completed):
        self.auth, self.completed = auth, completed
        self.cancelled = threading.Event()
        self.id = secrets.token_hex(16)
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(48)
        self.callback = None
        self.server = None

    def start(self, device):
        if device:
            details = http_json(ISSUER + "/oauth2/device/code", {"client_id": CLIENT_ID, "scope": SCOPES, "referrer": "steve"})
            url = details.get("verification_uri") or details.get("verification_url")
            if not details.get("device_code") or not details.get("user_code") or not url or not login_url_allowed(url):
                raise AuthError("xAI returned an invalid device sign-in response.")
            result = {"loginId": self.id, "verificationUrl": url, "userCode": details["user_code"]}
        else:
            session = self
            class Handler(BaseHTTPRequestHandler):
                def setup(self):
                    super().setup()
                    self.connection.settimeout(2)
                def do_GET(self):
                    query = parse_qs(urlsplit(self.path).query)
                    if urlsplit(self.path).path != "/callback" or query.get("state") != [session.state]:
                        self.send_error(400)
                        return
                    session.callback = query
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
            self.redirect = f"http://127.0.0.1:{self.server.server_port}/callback"
            challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
            details = None
            result = {"loginId": self.id, "authUrl": ISSUER + "/oauth2/authorize?" + urlencode({
                "client_id": CLIENT_ID, "response_type": "code", "scope": SCOPES, "referrer": "steve",
                "redirect_uri": self.redirect, "state": self.state, "code_challenge": challenge, "code_challenge_method": "S256"})}
        self.thread = threading.Thread(target=self._finish, args=(details,), daemon=True, name="STEVE-Grok-Login")
        self.thread.start()
        return result

    def _finish(self, details):
        try:
            deadline = time.monotonic() + min(900, float((details or {}).get("expires_in", 900)))
            interval = max(1, float((details or {}).get("interval", 5)))
            while not self.cancelled.is_set() and time.monotonic() < deadline:
                if details:
                    if self.cancelled.wait(min(interval, max(0, deadline - time.monotonic()))):
                        return
                    if time.monotonic() >= deadline:
                        break
                    try:
                        payload = http_json(ISSUER + "/oauth2/token", {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                            "client_id": CLIENT_ID, "device_code": details["device_code"]})
                    except AuthError as exc:
                        if exc.code == "slow_down":
                            interval += 5
                        elif exc.code != "authorization_pending":
                            raise
                        continue
                else:
                    self.server.handle_request()
                    if self.callback is None:
                        continue
                    if self.callback.get("error") or not self.callback.get("code"):
                        raise AuthError("Grok sign-in was not completed. Try again.")
                    payload = http_json(ISSUER + "/oauth2/token", {"grant_type": "authorization_code", "client_id": CLIENT_ID,
                        "code": self.callback["code"][0], "redirect_uri": self.redirect, "code_verifier": self.verifier})
                tokens = self.auth._tokens(payload)
                with self.auth._lock:
                    if self.cancelled.is_set() or self.auth.session is not self:
                        return
                    self.auth._store(tokens)
                self.completed(self.id, True, "")
                return
            if not self.cancelled.is_set():
                raise AuthError("Grok sign-in timed out. Try again.")
        except Exception as exc:
            if not self.cancelled.is_set():
                self.completed(self.id, False, str(exc) if isinstance(exc, AuthError) else "Grok sign-in failed. Try again.")
        finally:
            if self.server:
                self.server.server_close()
