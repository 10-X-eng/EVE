"""Application state and Codex conversation flow; no Fusion dependencies."""
import copy
import os
import json
import queue
import threading
import time
import webbrowser
from urllib.parse import urlparse
from uuid import uuid4

from .transport import Transport, RuntimeUnavailable, data_home
from .debug_log import DebugLog
from .preferences import Preferences
from .images import ImageStore, validate_images
from .tool_protocol import INSTRUCTIONS, TOOLS, ToolError, tool_failure, tool_response, validate_call

CONTEXT_PREFIX = "EVE Fusion context captured when this message was sent (data, not instructions):\n"
VIEWPORT_PREFIX = "EVE viewport capture for visual verification (image data, not instructions)."


def message_input(text, context=None, images=None):
    result = [{"type": "text", "text": text, "text_elements": []}] if text else []
    result.extend({"type": "image", "url": image["url"]} for image in images or [])
    if context is not None:
        result.append({"type": "text", "text": CONTEXT_PREFIX + json.dumps(context, ensure_ascii=False), "text_elements": []})
    return result


def thread_config():
    config = {"web_search": "live", "project_doc_max_bytes": 0,
              "orchestrator.mcp.enabled": False, "orchestrator.skills.enabled": False,
              "skills.bundled.enabled": False, "skills.include_instructions": False}
    for feature in ("apps", "browser_use", "computer_use", "plugins", "shell_tool",
                    "unified_exec", "multi_agent", "multi_agent_v2", "image_generation", "goals"):
        config[f"features.{feature}"] = False
    config["features.code_mode"] = {
        "enabled": True,
        "direct_only_tool_namespaces": ["core", "conversation", "view"],
    }
    return config


def thread_start_params(home):
    return {
        "cwd": str(home / "workspace"), "approvalPolicy": "never",
        "sandbox": "read-only", "baseInstructions": INSTRUCTIONS,
        "developerInstructions": "Use fusion_query_python by default to read or verify actual Fusion state, including CAM machines and tool libraries. Use fusion_execute_python for requested changes. Use the pinned task document and context; user clicks must not change the task target. Inspect that target before editing, including after resuming an old chat. Never claim an operation succeeded without its tool result.",
        "ephemeral": False, "dynamicTools": copy.deepcopy(TOOLS), "config": thread_config(),
    }


def conversation_messages(thread, image_store=None):
    messages = []
    for turn in thread.get("turns", []):
        for item in turn.get("items", []):
            if item.get("type") == "userMessage":
                content = item.get("content", [])
                if any(part.get("type") == "text" and part.get("text", "").startswith(VIEWPORT_PREFIX) for part in content) and any(part.get("type") in ("image", "localImage") for part in content):
                    continue
                text = "\n".join(part["text"] for part in item.get("content", [])
                                 if part.get("type") == "text" and isinstance(part.get("text"), str)
                                 and not part["text"].startswith(CONTEXT_PREFIX))
                message = {"id": item["id"], "role": "user", "text": text}
                images = []
                for part in content:
                    if part.get("type") in ("image", "localImage"):
                        reference = {"id": "", "name": "Saved image (preview unavailable)"}
                        if image_store and part.get("type") == "image":
                            try:
                                reference = image_store.remember(validate_images([{"url": part.get("url")}])[0])
                            except (ValueError, OSError):
                                pass
                        images.append(reference)
                if images:
                    message["images"] = images
                messages.append(message)
            elif item.get("type") == "agentMessage":
                messages.append({"id": item["id"], "role": "assistant", "text": item.get("text", "")})
    return messages


class Controller:
    def __init__(self, publish, transport_factory=Transport, open_browser=webbrowser.open, fusion_tools=None, debug_log=None):
        self.publish = publish
        self.factory = transport_factory
        self.open_browser = open_browser
        self.fusion_tools = fusion_tools
        self.debug = debug_log or DebugLog(data_home())
        self.preferences = Preferences(self.debug.folder.parent)
        self.images = ImageStore(self.debug.folder.parent)
        if self.fusion_tools is not None:
            self.fusion_tools.debug = self.debug
            self.fusion_tools.on_wait = self._fusion_wait
        self.client = None
        self.thread_id = None
        self.turn_id = None
        self.default_model = None
        self.login_id = None
        self._closed = False
        self._cancel = False
        self._send_queued = False
        self._account_check_queued = False
        self._last_emit = 0
        self._lock = threading.RLock()
        self._commands = queue.Queue()
        self.state = {"connection": "starting", "account": None, "models": [], "model": "",
                      "effort": "", "effortOptions": [], "defaultEffort": "", "preferenceNotice": "",
                      "taskDocument": None, "waitingForFusion": False, "waitingReason": "",
                      "messages": [], "busy": False, "loginPending": False, "device": None,
                      "accountChecked": False, "error": "", "status": "Checking your account", "version": "0.1.0",
                      "threadId": None, "history": [], "historyCursor": None, "historyLoading": False,
                      "runtimeIssue": False, "debugLogging": self.debug.enabled,
                      "debugLogPath": str(self.debug.path)}
        self._worker = threading.Thread(target=self._work, name="EVE-Actions", daemon=True)
        self._worker.start()

    def snapshot(self):
        with self._lock:
            return {**copy.deepcopy(self.state), "turnId": self.turn_id,
                    "canSteer": bool(self.turn_id and self.state["busy"] and not self._cancel)}

    def emit(self, force=True):
        if self._closed:
            return
        now = time.monotonic()
        if force or now - self._last_emit >= 0.045:
            self._last_emit = now
            self.publish(self.snapshot())

    def dispatch(self, action, payload=None, capture_context=None):
        with self._lock:
            if self._closed:
                return
            if action == "accountRefresh":
                if self._account_check_queued and not (payload or {}).get("afterLogin"):
                    return
                self._account_check_queued = True
            if action in ("history", "openHistory") and (self.state["busy"] or self._send_queued):
                return
            if action in ("send", "steer"):
                validate_images((payload or {}).get("images"))
            if action == "send":
                if self._send_queued or self.state["busy"]:
                    return False
                if capture_context:
                    payload = {**(payload or {}), "fusionContext": capture_context(action)}
                self._send_queued = True
                self._cancel = False
            elif action == "steer" and capture_context:
                payload = {**(payload or {}), "fusionContext": capture_context(action)}
            if action == "stop":
                self._cancel = True
                if self.fusion_tools and hasattr(self.fusion_tools, "wake"):
                    self.fusion_tools.wake()
            self._commands.put((action, copy.deepcopy(payload or {})))
            return True

    def image_assets(self, ids):
        if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) for i in ids):
            raise ValueError("Request at most four image previews.")
        with self._lock:
            allowed = {image["id"] for message in self.state["messages"] for image in message.get("images", [])}
        return {image_id: self.images.read(image_id) for image_id in ids if image_id in allowed}

    def _fusion_wait(self, waiting, document):
        with self._lock:
            if not self.state["busy"]:
                return
            changed = self.state["waitingReason"] != waiting
            self.state.update(waitingForFusion=bool(waiting), waitingReason=waiting, taskDocument=document)
            self.state["status"] = waiting or "Working in Fusion"
        if changed:
            self.debug.record("fusion.waiting" if waiting else "fusion.resumed", reason=waiting, document=document)
        self.emit()

    def _model_info(self, model=None):
        selected = self.state["model"] if model is None else model
        models = self.state["models"]
        if selected:
            return next((m for m in models if m["id"] == selected), {})
        return next((m for m in models if m.get("isDefault")),
                    next((m for m in models if m["id"] == self.default_model), {}))

    def _choose_preferences(self):
        model = self.preferences.model
        available = {m["id"] for m in self.state["models"]}
        self.state["preferenceNotice"] = ("Saved model is unavailable for this account; using the default."
                                          if model and model not in available else "")
        self.state["model"] = model if model in available else ""
        self._effort_options()

    def _effort_options(self):
        info = self._model_info()
        options = info.get("efforts", [])
        effort = self.preferences.efforts.get(self.state["model"], "")
        self.state.update(effortOptions=options, defaultEffort=info.get("defaultEffort", ""),
                          effort=effort if effort in {e["id"] for e in options} else "")

    def _work(self):
        while True:
            try:
                item = self._commands.get(timeout=2 if self.state["loginPending"] else None)
            except queue.Empty:
                # Recover when the browser callback succeeds but its notification is missed.
                item = ("accountRefresh", {})
            if item is None or self._closed:
                return
            action, payload = item
            try:
                self._handle(action, payload)
            except Exception as exc:
                self.debug.record("controller.error", action=action,
                                  error=type(exc).__name__ if action in ("login", "deviceLogin", "accountRefresh") else str(exc))
                if isinstance(exc, TimeoutError) and self.client:
                    self.client.close()
                    with self._lock:
                        self.state["connection"] = "disconnected"
                with self._lock:
                    self.state["error"] = str(exc)
                    if action != "steer":
                        self.state.update(busy=False, waitingForFusion=False, status="Needs attention")
                    if action == "send" and self.state["messages"]:
                        for message in reversed(self.state["messages"]):
                            if message.get("delivery") == "pending":
                                message["delivery"] = "failed"
                                break
                    self.state["historyLoading"] = False
                    if action in ("login", "deviceLogin"):
                        self.state["loginPending"] = False
                        self.state["device"] = None
                    if action == "connect":
                        self.state["connection"] = "disconnected"
                        self.state["runtimeIssue"] = isinstance(exc, RuntimeUnavailable)
                        if self.state["runtimeIssue"]:
                            self.state["status"] = "Codex setup needed"
                self.emit()
            finally:
                if action == "send":
                    with self._lock:
                        self._send_queued = False
                if action == "accountRefresh":
                    with self._lock:
                        self._account_check_queued = False

    def _handle(self, action, payload):
        if action == "debugLogging":
            self.debug.set_enabled(payload.get("enabled"))
            with self._lock:
                self.state["debugLogging"] = self.debug.enabled
            self.emit()
        elif action == "openLogs":
            self.debug.folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.debug.folder))
        elif action == "sync":
            self.emit()
            if self.state["connection"] == "ready" and not self.state["busy"]:
                self.dispatch("accountRefresh")
        elif action == "connect":
            self._connect()
        elif action == "setupHelp":
            destinations = {
                "eve": "https://github.com/10-X-eng/EVE#install-the-windows-preview",
                "codex": "https://learn.chatgpt.com/docs/quickstart?setup=app",
            }
            destination = destinations.get(payload.get("page"))
            if not destination:
                raise ValueError("Unknown installation help page.")
            if self.open_browser(destination) is False:
                raise RuntimeError("The installation guide could not open in your browser.")
        elif action in ("login", "deviceLogin"):
            self._login(action == "deviceLogin")
        elif action == "cancelLogin":
            if self.login_id:
                self.client.request("account/login/cancel", {"loginId": self.login_id})
            self.login_id = None
            with self._lock:
                self.state.update(loginPending=False, device=None, status="Sign in to begin")
            self.emit()
        elif action == "accountRefresh":
            self._refresh_account(refresh_token=bool(payload.get("refreshToken")),
                                  require_account=bool(payload.get("afterLogin")))
        elif action == "send":
            self._send(str(payload.get("text", "")).strip(), payload.get("fusionContext"), payload.get("images"))
        elif action == "steer":
            self._steer(payload)
        elif action == "viewportImage":
            self._deliver_image(payload)
        elif action == "history":
            self._history(bool(payload.get("more")))
        elif action == "openHistory":
            self._open_history(str(payload.get("threadId", "")))
        elif action == "stop":
            if self.turn_id and self.state["busy"]:
                with self._lock:
                    self.state.update(status="Stopping", waitingForFusion=False)
                self.emit()
                self.client.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})
        elif action == "new":
            if self.state["busy"]:
                return
            self.thread_id = None
            with self._lock:
                self.state.update(messages=[], threadId=None, error="", status="Ready" if self.state["account"] else "Sign in to begin")
            self.emit()
        elif action in ("model", "effort"):
            if self.state["busy"]:
                return
            model = str(payload.get("model", "")) if action == "model" else self.state["model"]
            allowed = {entry["id"] for entry in self.state["models"]} | {""}
            if model not in allowed:
                raise ValueError("Choose an available model.")
            options = self._model_info(model).get("efforts", [])
            effort = str(payload.get("effort", "")) if action == "effort" else self.preferences.efforts.get(model, "")
            if effort and effort not in {e["id"] for e in options}:
                if action == "effort":
                    raise ValueError("Choose an effort supported by this model.")
                effort = ""
            self.preferences.save(model, effort)
            with self._lock:
                self.state["model"] = model
                self.state["preferenceNotice"] = ""
                self._effort_options()
            self.emit()
        elif action == "logout":
            if self.state["busy"]:
                return
            self.client.request("account/logout")
            self.thread_id = None
            with self._lock:
                self.state.update(account=None, messages=[], models=[], model="", threadId=None,
                                  history=[], historyCursor=None, error="", status="Sign in to begin")
            self.emit()

    def _connect(self):
        if self.client:
            self.client.close()
        with self._lock:
            self.thread_id = self.turn_id = self.login_id = None
            self.default_model = None
            self.state.update(connection="starting", busy=False, error="", messages=[], threadId=None,
                              history=[], historyCursor=None, historyLoading=False, runtimeIssue=False,
                              accountChecked=False, loginPending=False, device=None, status="Checking your account")
        self.emit()
        self.client = self.factory(self._notification)
        client = self.client
        client.debug = self.debug
        client.on_request = lambda request_id, method, params: self._tool_request(client, request_id, method, params)
        self.client.start()
        if self._closed:
            self.client.close()
            return
        with self._lock:
            self.state["connection"] = "ready"
        self._refresh_account(refresh_token=True)

    def _tool_request(self, client, request_id, method, params):
        if method != "item/tool/call":
            client.reply(request_id, error={"code": -32601, "message": "Only Fusion tool calls are supported."})
            return
        requested_turn = params.get("turnId") or self.turn_id
        started = time.monotonic()
        identifiers = {"requestId": request_id, "threadId": params.get("threadId"),
                       "turnId": requested_turn, "tool": params.get("tool")}
        def cancelled():
            return (self._closed or self._cancel or client is not self.client or not self.state["busy"]
                    or params.get("threadId") != self.thread_id
                    or (requested_turn is not None and requested_turn != self.turn_id))
        def complete(result):
            if client is not self.client or self._closed:
                return
            image_url = result.pop("imageUrl", None)
            if image_url:
                self._commands.put(("viewportImage", {"client": client, "threadId": params.get("threadId"),
                    "turnId": requested_turn, "imageUrl": image_url, "result": result,
                    "complete": complete, "cancelled": cancelled}))
                return
            self.debug.record("tool.completed", **identifiers,
                              durationMs=round((time.monotonic() - started) * 1000), result=result)
            if client is not self.client or self._closed:
                return
            with self._lock:
                if self.state["busy"] and params.get("threadId") == self.thread_id and requested_turn == self.turn_id:
                    self.state["status"] = "Stopping" if self._cancel else "Thinking"
            self.emit()
            client.reply(request_id, tool_response(result))
        try:
            if cancelled() or (params.get("turnId") and self.turn_id and params["turnId"] != self.turn_id):
                raise ToolError("inactive_request", "This Fusion request is no longer active.")
            if params.get("namespace") not in (None, ""):
                raise ValueError("Unexpected tool namespace.")
            tool, arguments = params.get("tool"), params.get("arguments")
            if tool in {entry["name"] for entry in TOOLS}:
                self.debug.record("tool.started", **identifiers, arguments=arguments)
            validate_call(tool, arguments)
            if self.fusion_tools is None:
                raise ToolError("bridge_unavailable", "The Fusion execution bridge is not available. Restart EVE inside Fusion.")
            with self._lock:
                self.state["status"] = {"fusion_execute_python": "Working in Fusion",
                                        "fusion_query_python": "Querying Fusion",
                                        "fusion_capture_viewport": "Looking at the model",
                                        "fusion_api_help": "Reading Fusion API",
                                        "fusion_inspect_document": "Inspecting design"}[tool]
            self.emit()
            self.fusion_tools.submit(tool, arguments, complete, cancelled)
        except Exception as exc:
            complete(tool_failure(exc, code="invalid_arguments" if isinstance(exc, ValueError) and not isinstance(exc, SyntaxError) else None))

    def _refresh_account(self, refresh_token=False, require_account=False):
        account = self.client.request("account/read", {"refreshToken": refresh_token}).get("account")
        if account and account.get("type") != "chatgpt":
            account = None
        # Only public account metadata reaches the panel.
        public = {key: account.get(key) for key in ("email", "planType")} if account else None
        with self._lock:
            changed = public != self.state["account"]
            identity_changed = bool(public) != bool(self.state["account"]) or (public or {}).get("email") != (self.state["account"] or {}).get("email")
            if identity_changed:
                self.thread_id = self.turn_id = None
                self.state.update(threadId=None, messages=[], history=[], historyCursor=None)
            self.state.update(account=public, accountChecked=True)
            if account:
                self.login_id = None
                if self.state["loginPending"] or changed:
                    self.state["error"] = ""
                self.state.update(loginPending=False, device=None)
                if not self.state["busy"]:
                    self.state["status"] = "Ready"
            elif require_account:
                self.state.update(loginPending=False, device=None, status="Sign in to begin")
                raise RuntimeError("Browser sign-in finished, but no ChatGPT account was found. Try signing in again.")
            elif not self.state["loginPending"]:
                self.state.update(models=[], model="", status="Sign in to begin")
        self.emit()
        if account and (changed or not self.state["models"]):
            models = []
            cursor = None
            while True:
                result = self.client.request("model/list", {"cursor": cursor, "limit": 100})
                for model in result.get("data", []):
                    if not model.get("hidden"):
                        models.append({"id": model.get("model") or model["id"],
                                       "name": model.get("displayName") or model["id"],
                                       "isDefault": bool(model.get("isDefault")),
                                       "defaultEffort": model.get("defaultReasoningEffort") or "",
                                       "efforts": [{"id": e["reasoningEffort"], "description": e.get("description", "")}
                                                   for e in model.get("supportedReasoningEfforts", [])]})
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            with self._lock:
                self.state["models"] = models
                self._choose_preferences()
            self.emit()
        if account and changed:
            self.dispatch("history")

    def _history(self, more=False):
        if not self.state["account"] or self.state["busy"]:
            return
        cursor = self.state["historyCursor"] if more else None
        if more and not cursor:
            return
        with self._lock:
            self.state["historyLoading"] = True
        self.emit()
        result = self.client.request("thread/list", {
            "limit": 30, "cursor": cursor, "sortKey": "updated_at",
            "sourceKinds": ["vscode", "appServer"],
            "cwd": str(self.client.home / "workspace"),
        })
        entries = [{"id": thread["id"], "title": (thread.get("name") or thread.get("preview") or "Untitled conversation")[:120],
                    "updatedAt": thread.get("updatedAt", thread.get("createdAt", 0))}
                   for thread in result.get("data", []) if not thread.get("ephemeral")]
        with self._lock:
            previous = self.state["history"] if more else []
            unique = {entry["id"]: entry for entry in previous + entries}
            self.state.update(history=list(unique.values()), historyCursor=result.get("nextCursor"), historyLoading=False)
        self.emit()

    def _open_history(self, thread_id):
        if not self.state["account"] or self.state["busy"]:
            return
        if thread_id not in {entry["id"] for entry in self.state["history"]}:
            raise ValueError("Choose a conversation from your EVE history.")
        with self._lock:
            self.state.update(busy=True, status="Opening conversation", error="")
        self.emit()
        params = thread_start_params(self.client.home)
        params.pop("ephemeral")
        # Tools are restored by Codex from the original session.
        params.pop("dynamicTools")
        params["threadId"] = thread_id
        result = self.client.request("thread/resume", params)
        thread = result["thread"]
        messages = conversation_messages(thread, self.images)
        with self._lock:
            self.thread_id = thread["id"]
            self.turn_id = None
            self.default_model = result.get("model")
            self.state.update(threadId=self.thread_id, messages=messages, busy=False, status="Ready")
            self._choose_preferences()
        self.emit()

    def _login(self, device=False):
        if self.state["loginPending"]:
            return
        # Ask Codex to validate the saved account before opening a browser.
        self._refresh_account(refresh_token=True)
        if self.state["account"]:
            return
        with self._lock:
            self.state.update(loginPending=True, error="", status="Waiting for sign-in")
        self.emit()
        result = self.client.request("account/login/start", {"type": "chatgptDeviceCode"} if device else
                                     {"type": "chatgpt", "useHostedLoginSuccessPage": False})
        self.login_id = result.get("loginId")
        url = result.get("verificationUrl") if device else result.get("authUrl")
        parsed = urlparse(url or "")
        try:
            if parsed.scheme != "https" or parsed.hostname not in ("auth.openai.com", "chatgpt.com", "auth.chatgpt.com"):
                raise RuntimeError("Codex returned an unexpected sign-in address.")
            if device:
                with self._lock:
                    self.state["device"] = {"code": result.get("userCode", ""), "url": url}
                self.emit()
            if self.open_browser(url) is False:
                raise RuntimeError("Your browser could not open. Try the device-code option.")
        except Exception:
            if self.login_id:
                try:
                    self.client.request("account/login/cancel", {"loginId": self.login_id})
                finally:
                    self.login_id = None
            raise

    def _send(self, text, context=None, images=None):
        images = validate_images(images)
        if (not text and not images) or self.state["busy"]:
            return
        if len(text) > 32000:
            raise ValueError("Please keep your message under 32,000 characters.")
        if not self.state["account"]:
            raise RuntimeError("Sign in with ChatGPT to start a conversation.")
        if len(self.state["messages"]) >= 200:
            raise RuntimeError("Start a new conversation to keep EVE responsive.")
        references = [self.images.remember(image) for image in images]
        with self._lock:
            self.turn_id = None
            self.state.update(busy=True, error="", status="Thinking")
            self.state.update(taskDocument={"id": context.get("document_id"), "name": context.get("name")} if context else None,
                              waitingForFusion=False)
            self.state["messages"].append({"role": "user", "text": text,
                                           "images": references, "delivery": "pending",
                                           "selectionCount": (context or {}).get("selectionCount", 0)})
            message = self.state["messages"][-1]
        self.emit()
        if not self.thread_id:
            result = self.client.request("thread/start", thread_start_params(self.client.home))
            self.thread_id = result["thread"]["id"]
            self.default_model = result.get("model")
            with self._lock:
                self.state["threadId"] = self.thread_id
                self._effort_options()
        if self._closed:
            return
        if self._cancel:
            with self._lock:
                message["delivery"] = "failed"
                self.state.update(busy=False, status="Stopped")
            self.emit()
            return
        params = {"threadId": self.thread_id, "input": message_input(text, context, images)}
        selected_model = self.state["model"] or self._model_info().get("id") or self.default_model
        if selected_model:
            params["model"] = selected_model
        effort = self.state["effort"] or self.state["defaultEffort"]
        if effort:
            params["effort"] = effort
        result = self.client.request("turn/start", params)
        with self._lock:
            message["delivery"] = "sent"
            if self.state["busy"]:
                self.turn_id = result["turn"]["id"]
        self.emit()
        if self._cancel and self.state["busy"]:
            self._handle("stop", {})

    def _steer(self, payload):
        text = str(payload.get("text", "")).strip()
        images = validate_images(payload.get("images"))
        if not text and not images:
            return
        message = {"id": "steer-" + str(uuid4()), "role": "user", "text": text,
                   "images": [self.images.remember(image) for image in images],
                   "selectionCount": (payload.get("fusionContext") or {}).get("selectionCount", 0),
                   "delivery": "pending"}
        with self._lock:
            self.state["messages"].append(message)
        self.emit()
        try:
            if len(text) > 32000:
                raise ValueError("Keep messages under 32,000 characters.")
            if (self._cancel or not self.state["busy"] or not self.turn_id
                    or payload.get("threadId") != self.thread_id or payload.get("turnId") != self.turn_id):
                raise RuntimeError("That response has ended or is stopping. Send this message again to start a new turn.")
            self.client.request("turn/steer", {"threadId": self.thread_id, "expectedTurnId": self.turn_id,
                                               "input": message_input(text, payload.get("fusionContext"), images)})
            with self._lock:
                message["delivery"] = "sent"
        except Exception as exc:
            with self._lock:
                message["delivery"] = "failed"
                self.state["error"] = "Steering message was not confirmed: " + str(exc)
            self.debug.record("steer.failed", error=str(exc))
        self.emit()

    def _deliver_image(self, payload):
        # Use native image input: nested tool-output images can fail
        # when Responses history is replayed. This runs on the controller worker.
        result = payload["result"]
        try:
            if payload["cancelled"]():
                raise ToolError("inactive_request", "The capture's turn is no longer active.")
            payload["client"].request("turn/steer", {"threadId": payload["threadId"],
                "expectedTurnId": payload["turnId"], "input": [
                    {"type": "text", "text": VIEWPORT_PREFIX, "text_elements": []},
                    {"type": "image", "url": payload["imageUrl"]}]})
            result["imageDelivered"] = True
        except Exception as exc:
            result.update(tool_failure(exc, code="image_delivery_failed"))
        payload["complete"](result)

    def _notification(self, method, params):
        if self._closed:
            return
        force = True
        with self._lock:
            if method == "account/login/completed":
                if self.login_id and params.get("loginId") != self.login_id:
                    return
                self.login_id = None
                self.state.update(loginPending=False, device=None)
                if params.get("success"):
                    self.dispatch("accountRefresh", {"refreshToken": True, "afterLogin": True})
                else:
                    self.state.update(error=params.get("error") or "Sign-in was not completed.", status="Sign in to begin")
            elif method == "eve/disconnected":
                self.state.update(connection="disconnected", busy=False, waitingForFusion=False, loginPending=False,
                                  error=params["message"], status="Disconnected")
            elif method == "account/updated":
                if params.get("authMode") == "chatgpt":
                    self.dispatch("accountRefresh")
                elif params.get("authMode") is None:
                    self.thread_id = self.turn_id = None
                    self.state.update(account=None, models=[], model="", messages=[], threadId=None,
                                      history=[], historyCursor=None)
            elif params.get("threadId") != self.thread_id or not self.thread_id:
                return
            elif method == "turn/started":
                self.turn_id = params["turn"]["id"]
            elif method == "item/agentMessage/delta":
                item_id = params.get("itemId", "assistant")
                message = next((m for m in self.state["messages"] if m.get("id") == item_id), None)
                if message is None:
                    message = {"id": item_id, "role": "assistant", "text": ""}
                    self.state["messages"].append(message)
                message["text"] += params.get("delta", "")
                self.state["status"] = "Writing"
                force = False
            elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                item = params["item"]
                message = next((m for m in self.state["messages"] if m.get("id") == item["id"]), None)
                if message is None:
                    self.state["messages"].append({"id": item["id"], "role": "assistant", "text": item.get("text", "")})
                else:
                    message["text"] = item.get("text", message["text"])
            elif method == "turn/completed":
                turn = params.get("turn", {})
                self.state.update(busy=False, status="Stopped" if turn.get("status") == "interrupted" else "Ready")
                if turn.get("error"):
                    self.state["error"] = turn["error"].get("message", "The response failed. Try again.")
                self.turn_id = None
                self.state["waitingForFusion"] = False
                if self.fusion_tools and hasattr(self.fusion_tools, "wake"):
                    self.fusion_tools.wake()
                self._commands.put(("history", {}))
            elif method == "error":
                self.state["error"] = params.get("error", {}).get("message", "Codex encountered an error.")
            else:
                return
        self.emit(force)

    def close(self):
        self._closed = True
        self._commands.put(None)
        if self.client:
            self.client.close()
        self.debug.close()
