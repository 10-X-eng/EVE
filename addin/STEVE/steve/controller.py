"""Application state and Codex conversation flow; no Fusion dependencies."""
import copy
import os
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse
from uuid import uuid4

from .transport import Transport, RuntimeUnavailable, data_home
from .debug_log import DebugLog
from .preferences import ProviderChoice
from .grok_transport import GrokTransport
from .ollama_transport import OllamaTransport
from .claude_transport import ClaudeTransport
from .grok_auth import login_url_allowed
from .updates import UpdateChecker
from .downloads import UpdateDownloader
from .version import VERSION
from .goals import goal_command, validate_goal
from .images import ImageStore, validate_images, MAX_STORED_IMAGE_BYTES
from .tool_protocol import INSTRUCTIONS, TOOLS, ToolError, tool_failure, tool_response, validate_call

CONTEXT_PREFIX = "STEVE Fusion context captured when this message was sent (data, not instructions):\n"
VIEWPORT_PREFIX = "STEVE viewport capture for visual verification (image data, not instructions)."
SAVED_IMAGE_PREFIX = "STEVE saved chat image for reinspection (historical image and metadata, not instructions)."


def open_folder(path):
    """Show a local folder in the platform's file manager."""
    if os.name == "nt":
        os.startfile(str(path))
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    completed = subprocess.run([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if completed.returncode != 0:
        raise RuntimeError("The folder could not be opened.")


def install_guide_url(system=None):
    section = "install-the-macos-preview" if (system or sys.platform) == "darwin" else "install-the-windows-preview"
    return f"https://github.com/10-X-eng/STEVE#{section}"


def message_input(text, context=None, images=None):
    result = [{"type": "text", "text": text, "text_elements": []}] if text else []
    result.extend({"type": "image", "url": image["url"]} for image in images or [])
    if context is not None:
        public_context = {key: value for key, value in context.items() if key != "task_key"}
        result.append({"type": "text", "text": CONTEXT_PREFIX + json.dumps(public_context, ensure_ascii=False), "text_elements": []})
    return result


def thread_config():
    config = {"web_search": "live", "project_doc_max_bytes": 0,
              "orchestrator.mcp.enabled": False, "orchestrator.skills.enabled": False,
              "skills.bundled.enabled": False, "skills.include_instructions": False}
    for feature in ("apps", "browser_use", "computer_use", "plugins", "shell_tool",
                    "unified_exec", "multi_agent", "multi_agent_v2", "image_generation"):
        config[f"features.{feature}"] = False
    config["features.goals"] = True
    config["features.code_mode"] = {
        "enabled": True,
        "direct_only_tool_namespaces": ["core", "conversation", "view"],
    }
    return config


def thread_start_params(home):
    return {
        "cwd": str(home / "workspace"), "approvalPolicy": "never",
        "sandbox": "read-only", "baseInstructions": INSTRUCTIONS,
        "ephemeral": False, "dynamicTools": copy.deepcopy(TOOLS), "config": thread_config(),
    }


def conversation_messages(thread, image_store=None):
    messages = []
    for turn in thread.get("turns", []):
        for item in turn.get("items", []):
            if item.get("type") == "userMessage":
                content = item.get("content", [])
                if any(part.get("type") == "text" and part.get("text", "").startswith((VIEWPORT_PREFIX, SAVED_IMAGE_PREFIX)) for part in content) and any(part.get("type") in ("image", "localImage") for part in content):
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
            elif item.get("type") == "dynamicToolCall":
                activity = python_activity(item.get("tool"), item.get("arguments"), item.get("id"))
                if activity:
                    activity["toolStatus"] = ("completed" if item.get("success") is True else
                                              "failed" if item.get("success") is False else "unconfirmed")
                    activity["historical"] = True
                    messages.append(activity)
    return messages


def python_activity(tool, arguments, identifier):
    """Display submitted Fusion Python, never internal model reasoning or tool results."""
    if tool not in ("fusion_execute_python", "fusion_query_python") or not isinstance(arguments, dict):
        return None
    code = arguments.get("code")
    if not isinstance(code, str) or not code or len(code) > 60000:
        return None
    title = arguments.get("title")
    return {"id": "python-" + str(identifier), "role": "tool", "text": "", "code": code,
            "title": title[:100] if isinstance(title, str) else "Fusion Python",
            "toolStatus": "running", "tool": tool}


class Controller:
    def __init__(self, publish, transport_factory=Transport, open_browser=webbrowser.open, fusion_tools=None, debug_log=None, grok_factory=GrokTransport, ollama_factory=OllamaTransport, claude_factory=ClaudeTransport):
        self.publish = publish
        self.factory = transport_factory
        self.grok_factory = grok_factory
        self.ollama_factory = ollama_factory
        self.claude_factory = claude_factory
        self.open_browser = open_browser
        self.fusion_tools = fusion_tools
        self.debug = debug_log or DebugLog(data_home())
        self.provider_choice = ProviderChoice(self.debug.folder.parent)
        self.preferences = self.provider_choice.preferences()
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
        self._active_tools = {}
        self._goal_revision = 0
        self._task_context = None
        self._goal_contexts = {}
        self.state = {"connection": "starting", "provider": self.provider_choice.provider, "account": None, "models": [], "model": "",
                      "effort": "", "effortOptions": [], "defaultEffort": "", "preferenceNotice": "",
                      "taskDocument": None, "waitingForFusion": False, "waitingReason": "",
                      "goal": None, "goalBusy": False, "goalNotice": "", "goalHasTarget": False,
                      "messages": [], "busy": False, "loginPending": False, "device": None,
                      "accountChecked": False, "localStatus": "", "providerVersion": "", "error": "", "status": "Checking your account", "version": VERSION,
                      "updateInfo": None, "updateChecking": False, "updateStatus": "", "updateDownload": None,
                      "threadId": None, "history": [], "historyCursor": None, "historyLoading": False,
                      "runtimeIssue": False, "debugLogging": self.debug.enabled,
                      "debugLogPath": str(self.debug.path)}
        self._worker = threading.Thread(target=self._work, name="STEVE-Actions", daemon=True)
        self._worker.start()
        self.updates = UpdateChecker(self._update_state)
        self.downloader = UpdateDownloader(self._update_state)

    def _update_state(self, changes):
        with self._lock:
            if self._closed:
                return
            self.state.update(changes)
        self.emit()

    def start_update_checks(self):
        self.updates.request()

    def snapshot(self):
        with self._lock:
            return {**copy.deepcopy(self.state), "turnId": self.turn_id,
                    "activeTools": [dict(entry[3]) for entry in self._active_tools.values()
                                    if self.state["busy"] and entry[:3] == (self.client, self.thread_id, self.turn_id)],
                    "canSteer": bool(self.turn_id and self.state["busy"] and not self._cancel)}

    def emit(self, force=True):
        if self._closed:
            return
        now = time.monotonic()
        if force or now - self._last_emit >= 0.045:
            self._last_emit = now
            self.publish(self.snapshot())

    def dispatch(self, action, payload=None, capture_context=None):
        payload = payload or {}
        if action in ("send", "steer"):
            command = goal_command(str(payload.get("text", "")))
            if command:
                if payload.get("images"):
                    raise ValueError("Send reference images as a chat message before setting a goal.")
                action, payload = "goal", command
        if action == "goal":
            payload = validate_goal(payload)
        with self._lock:
            if self._closed:
                return
            if action == "provider" and (self.state["busy"] or self._send_queued or self.state["loginPending"]):
                return False
            if action == "goal":
                command = payload["command"]
                if self.state["goalBusy"]:
                    return False
                if command in ("set", "resume"):
                    if self.state["busy"] or self._send_queued:
                        raise ValueError("Pause the current task before creating, editing, or resuming a goal.")
                    if command == "resume" and not self.state["goal"]:
                        raise ValueError("No goal to resume. Use /goal <objective> to create one.")
                    if capture_context:
                        target = self._goal_contexts.get((self.state["provider"], self.thread_id)) if command == "resume" else None
                        capture = "resume:" + target["task_key"] if target and target.get("task_key") else "send"
                        payload["fusionContext"] = capture_context(capture)
                    self._cancel = False
                    self._send_queued = True
                if command in ("pause", "clear") and self.state["goal"]:
                    self._cancel = True
                    if self.fusion_tools and hasattr(self.fusion_tools, "wake"):
                        self.fusion_tools.wake()
                self.state["goalBusy"] = True
            if action == "accountRefresh":
                if self._account_check_queued and not (payload or {}).get("afterLogin"):
                    return
                self._account_check_queued = True
            if action in ("history", "openHistory") and (self.state["busy"] or self._send_queued):
                return
            if action in ("send", "steer"):
                validate_images((payload or {}).get("images"))
            if action == "send":
                if self._send_queued or self.state["busy"] or self.state["goalBusy"]:
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
                    if action not in ("steer", "goal", "stop"):
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
                if action == "send" or action == "goal" and payload["command"] in ("set", "resume"):
                    with self._lock:
                        self._send_queued = False
                if action == "goal":
                    with self._lock:
                        self.state["goalBusy"] = False
                    self.emit()
                if action == "accountRefresh":
                    with self._lock:
                        self._account_check_queued = False

    def _handle(self, action, payload):
        if action == "provider":
            if self.state["busy"] or self.state["loginPending"]:
                return
            self.provider_choice.save(payload.get("provider"))
            self.preferences = self.provider_choice.preferences()
            with self._lock:
                self.state.update(provider=self.provider_choice.provider, account=None, models=[], model="", effort="", effortOptions=[])
            self._connect()
        elif action == "checkUpdates":
            self.updates.request()
        elif action == "downloadUpdate":
            with self._lock:
                release = self.state.get("updateInfo")
            if release:
                self.downloader.request(release)
        elif action == "openDownloads":
            with self._lock:
                download = self.state.get("updateDownload")
            if download and download.get("state") == "ready":
                try:
                    open_folder(Path(download["path"]).parent)
                except Exception:
                    self._update_state({"updateStatus": "Couldn’t open Downloads. Open it from your file manager."})
        elif action == "openUpdate":
            with self._lock:
                release = self.state.get("updateInfo")
            if release:
                try:
                    url = release["downloadUrl" if payload.get("page") == "download" else "releaseUrl"]
                    if self.open_browser(url) is False:
                        raise RuntimeError("Browser unavailable")
                except Exception:
                    self._update_state({"updateStatus": "Couldn’t open your browser. Visit github.com/10-X-eng/STEVE/releases."})
        elif action == "debugLogging":
            self.debug.set_enabled(payload.get("enabled"))
            with self._lock:
                self.state["debugLogging"] = self.debug.enabled
            self.emit()
        elif action == "openLogs":
            self.debug.folder.mkdir(parents=True, exist_ok=True)
            open_folder(self.debug.folder)
        elif action == "sync":
            self.emit()
            if self.state["connection"] == "ready" and not self.state["busy"]:
                self.dispatch("accountRefresh")
        elif action == "connect":
            self._connect()
        elif action == "setupHelp":
            destinations = {
                "steve": install_guide_url(),
                "codex": "https://learn.chatgpt.com/docs/quickstart?setup=app",
                "ollama": "https://ollama.com/download",
                "claude": "https://code.claude.com/docs/en/setup",
                "local": "https://github.com/10-X-eng/STEVE/blob/main/docs/INSTALL.md#local-ollama",
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
                                  require_account=bool(payload.get("afterLogin")), refresh_models=bool(payload.get("refreshModels")))
        elif action == "send":
            self._send(str(payload.get("text", "")).strip(), payload.get("fusionContext"), payload.get("images"))
        elif action == "goal":
            self._goal_action(payload)
        elif action == "steer":
            self._steer(payload)
        elif action == "viewportImage":
            self._deliver_image(payload)
        elif action == "chatImageTool":
            self._chat_image_tool(payload)
        elif action == "history":
            self._history(bool(payload.get("more")))
        elif action == "openHistory":
            self._open_history(str(payload.get("threadId", "")))
        elif action == "stop":
            try:
                if self.thread_id and self.state["goal"] and self.state["goal"]["status"] == "active":
                    self._goal_rpc("set", {"status": "paused"})
            finally:
                self._interrupt_turn()
        elif action == "new":
            if self.state["busy"]:
                return
            self.thread_id = None
            self._task_context = None
            with self._lock:
                self.state.update(messages=[], threadId=None, goal=None, goalNotice="", goalHasTarget=False,
                                  taskDocument=None, error="", status="Ready" if self.state["account"] else "Sign in to begin")
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
                self.state.update(account=None, messages=[], models=[], model="", threadId=None, goal=None, goalHasTarget=False,
                                  history=[], historyCursor=None, error="", status="Sign in to begin")
            self.emit()

    def _connect(self):
        if self.client:
            self.client.close()
        with self._lock:
            self._active_tools.clear()
            self.thread_id = self.turn_id = self.login_id = None
            self._task_context = None
            self.default_model = None
            self.state.update(connection="starting", busy=False, error="", messages=[], threadId=None,
                              goal=None, goalBusy=False, goalNotice="", goalHasTarget=False, taskDocument=None,
                              history=[], historyCursor=None, historyLoading=False, runtimeIssue=False,
                              account=None, models=[], accountChecked=False, loginPending=False, device=None,
                              localStatus="", providerVersion="", status="Checking local Ollama" if self.state["provider"] == "ollama" else "Checking your account")
        self.emit()
        factory = {"grok": self.grok_factory, "ollama": self.ollama_factory, "claude": self.claude_factory}.get(self.state["provider"], self.factory)
        client = factory(lambda method, params: self._notification(method, params) if self.client is client else None)
        self.client = client
        client.debug = self.debug
        client.on_request = lambda request_id, method, params: self._tool_request(client, request_id, method, params)
        self.client.start()
        if self._closed:
            self.client.close()
            return
        with self._lock:
            self.state["connection"] = "ready"
        self._refresh_account(refresh_token=True)

    def _interrupt_turn(self):
        if self.turn_id and self.state["busy"]:
            with self._lock:
                self.state.update(status="Stopping", waitingForFusion=False)
            self.emit()
            self.client.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})
        else:
            with self._lock:
                self.state.update(busy=False, status="Goal paused" if self.state["goal"] else "Stopped")
            self.emit()

    def _set_goal_state(self, goal):
        previous = self.state["goal"]
        self.state["goal"] = goal
        key = (self.state["provider"], self.thread_id)
        if not goal:
            self._goal_contexts.pop(key, None)
        elif self._task_context and (key not in self._goal_contexts or
                                    previous and previous["objective"] != goal["objective"]):
            self._goal_contexts[key] = copy.deepcopy(self._task_context)
        self.state["goalHasTarget"] = bool(self._goal_contexts.get(key))
        if not self.turn_id:
            active = bool(goal and goal["status"] == "active" and not self._cancel)
            self.state.update(busy=active, status="Continuing goal" if active else "Ready")

    def _goal_rpc(self, operation, params=None):
        revision = self._goal_revision
        result = self.client.request("thread/goal/" + operation, {"threadId": self.thread_id, **(params or {})})
        with self._lock:
            if revision == self._goal_revision:
                self._set_goal_state(result.get("goal"))
        self.emit()
        return result.get("goal")

    def _ensure_thread(self):
        if self.thread_id:
            return
        params = thread_start_params(self.client.home)
        model = self.state["model"] or self._model_info().get("id")
        if model:
            params["model"] = model
        effort = self.state["effort"] or self.state["defaultEffort"]
        if effort:
            params["config"]["model_reasoning_effort"] = effort
        if self.state["provider"] == "ollama":
            self.state["status"] = "Loading local model"
            self.emit()
        result = self.client.request("thread/start", params)
        with self._lock:
            self.thread_id = result["thread"]["id"]
            self.default_model = result.get("model")
            self.state["threadId"] = self.thread_id
            self._effort_options()

    def _goal_action(self, payload):
        command = payload["command"]
        if command in ("status", "help", "edit"):
            if self.thread_id:
                self._goal_rpc("get")
            self.state["goalNotice"] = "" if self.state["goal"] else "No goal yet. Describe an objective to get started."
            return
        if not self.state["account"] or self.state["connection"] != "ready":
            raise ValueError("Connect your provider before managing a goal.")
        if command in ("pause", "clear"):
            if not self.state["goal"]:
                self.state["goalNotice"] = "No goal to " + command + "."
                return
            try:
                if self.thread_id and self.state["goal"]:
                    self._goal_rpc("clear" if command == "clear" else "set", {} if command == "clear" else {"status": "paused"})
                self.state["goalNotice"] = "Goal cleared. Chat history is kept." if command == "clear" else "Goal paused."
            finally:
                self._interrupt_turn()
            return
        if self.state["busy"]:
            raise ValueError("Pause the current task before changing the goal.")
        if command == "resume" and (not self.state["goal"] or self.state["goal"]["status"] == "complete"):
            raise ValueError("Create a new goal to start more work; this goal is complete or missing.")
        context = payload.get("fusionContext")
        self._task_context = context
        self.state.update(taskDocument={"id": context.get("document_id"), "name": context.get("name")} if context else None,
                          goalNotice="", error="", busy=True, status="Preparing goal")
        self.emit()
        try:
            self._ensure_thread()
            if context:
                self._goal_contexts[(self.state["provider"], self.thread_id)] = copy.deepcopy(context)
            if command == "set":
                previous = self.state["goal"]
                if previous and (previous["objective"] != payload["objective"] or previous["status"] == "complete"):
                    # The pinned runtime retains usage on an objective-only update.
                    # Clear the old goal so replacement starts with fresh accounting.
                    self._goal_rpc("clear")
                params = {"objective": payload["objective"], "status": "paused"}
                if "tokenBudget" in payload:
                    params["tokenBudget"] = payload["tokenBudget"]
                self._goal_rpc("set", params)
            # Configure the next automatic turn while paused, before activation can start it.
            params = thread_start_params(self.client.home)
            params.pop("dynamicTools")
            params.pop("ephemeral")
            params["threadId"] = self.thread_id
            model = self.state["model"] or self._model_info().get("id") or self.default_model
            if model:
                params["model"] = model
            effort = self.state["effort"] or self.state["defaultEffort"]
            if effort:
                params["config"]["model_reasoning_effort"] = effort
            self.client.request("thread/resume", params)
            text = "Goal: " + payload["objective"] if command == "set" else "Resume the current goal. Inspect the pinned Fusion document before continuing."
            content = [{"type": "input_text", "text": part["text"]} for part in message_input(text, context)]
            self.client.request("thread/inject_items", {"threadId": self.thread_id,
                                "items": [{"type": "message", "role": "user", "content": content}]})
            self.state["messages"].append({"id": "goal-" + uuid4().hex, "role": "user", "text": text})
            if self._cancel:
                return  # Stop during startup leaves the new goal paused.
            params = {"status": "active"}
            if command == "resume" and "tokenBudget" in payload:
                params["tokenBudget"] = payload["tokenBudget"]
            self._goal_rpc("set", params)
        finally:
            with self._lock:
                if not self.turn_id:
                    self._set_goal_state(self.state["goal"])
            self.emit()

    def _tool_request(self, client, request_id, method, params):
        if method != "item/tool/call":
            client.reply(request_id, error={"code": -32601, "message": "Only Fusion tool calls are supported."})
            return
        requested_turn = params.get("turnId") or self.turn_id
        activity_id = object()
        code_message = None
        started = time.monotonic()
        identifiers = {"requestId": request_id, "threadId": params.get("threadId"),
                       "turnId": requested_turn, "tool": params.get("tool")}
        def cancelled():
            return (self._closed or self._cancel or client is not self.client or not self.state["busy"]
                    or params.get("threadId") != self.thread_id
                    or (requested_turn is not None and requested_turn != self.turn_id))
        def complete(result):
            if client is not self.client or self._closed:
                with self._lock:
                    self._active_tools.pop(activity_id, None)
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
                self._active_tools.pop(activity_id, None)
                if self.state["busy"] and params.get("threadId") == self.thread_id and requested_turn == self.turn_id:
                    if code_message is not None:
                        code_message["toolStatus"] = "completed" if result.get("ok") else "failed"
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
            with self._lock:
                if cancelled():
                    raise ToolError("inactive_request", "This Fusion request is no longer active.")
                self._active_tools[activity_id] = (client, params.get("threadId"), requested_turn,
                    {"name": tool, "title": arguments.get("title") or arguments.get("path") or {
                        "fusion_inspect_document": "Inspect document",
                        "fusion_capture_viewport": "Capture model view",
                        "list_chat_images": "Find pictures in this chat",
                        "view_chat_image": "Reopen saved picture",
                    }.get(tool, tool)})
                code_message = python_activity(tool, arguments, uuid4().hex)
                if code_message:
                    self.state["messages"].append(code_message)
            if tool in ("list_chat_images", "view_chat_image"):
                with self._lock:
                    self.state["status"] = "Looking up chat images" if tool == "list_chat_images" else "Reopening saved image"
                self.emit()
                self._commands.put(("chatImageTool", {"client": client, "threadId": params.get("threadId"),
                    "turnId": requested_turn, "tool": tool, "arguments": arguments,
                    "complete": complete, "cancelled": cancelled}))
                return
            if self.fusion_tools is None:
                raise ToolError("bridge_unavailable", "The Fusion execution bridge is not available. Restart STEVE inside Fusion.")
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

    def _refresh_account(self, refresh_token=False, require_account=False, refresh_models=False):
        if self.state["busy"]:
            return
        result = self.client.request("account/read", {"refreshToken": refresh_token})
        account = result.get("account")
        local = self.state["provider"] == "ollama"
        if account and account.get("type") != self.state["provider"]:
            account = None
        # Only public account metadata reaches the panel.
        public = {key: account.get(key) for key in ("email", "planType")} if account else None
        if public is not None and account.get("id"):
            public["id"] = account["id"]
        with self._lock:
            changed = public != self.state["account"]
            identity_changed = bool(public) != bool(self.state["account"]) or any((public or {}).get(key) != (self.state["account"] or {}).get(key) for key in ("email", "id"))
            if identity_changed and not local:
                self.thread_id = self.turn_id = None
                self._task_context = None
                self.state.update(threadId=None, messages=[], history=[], historyCursor=None, goal=None, goalHasTarget=False)
            self.state.update(account=public, accountChecked=True, localStatus=result.get("localStatus", ""),
                              providerVersion=result.get("providerVersion", ""))
            if account:
                self.login_id = None
                if self.state["loginPending"] or changed:
                    self.state["error"] = ""
                self.state.update(loginPending=False, device=None)
                if not self.state["busy"]:
                    self.state["status"] = "Ready"
            elif require_account:
                self.state.update(loginPending=False, device=None, status="Sign in to begin")
                raise RuntimeError("Browser sign-in finished, but no account was found. Try signing in again.")
            elif not self.state["loginPending"]:
                self.state.update(models=[], model="", status="Start Ollama to begin" if local else "Sign in to begin")
        self.emit()
        if account and (changed or not self.state["models"] or refresh_models):
            models = []
            cursor = None
            while True:
                result = self.client.request("model/list", {"cursor": cursor, "limit": 100})
                for model in result.get("data", []):
                    if not model.get("hidden"):
                        models.append({"id": model.get("model") or model["id"],
                                       "name": model.get("displayName") or model["id"],
                                       "isDefault": bool(model.get("isDefault")),
                                       "supportsImages": model.get("supportsImages", True),
                                       "defaultEffort": model.get("defaultReasoningEffort") or "",
                                       "efforts": [{"id": e["reasoningEffort"], "description": e.get("description", "")}
                                                   for e in model.get("supportedReasoningEfforts", [])]})
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            with self._lock:
                self.state["models"] = models
                self._choose_preferences()
                if local:
                    self.state.update(error="", status="Ready" if models else "Download a local model",
                        localStatus="Connected to localhost:11434. No sign-in needed." if models else "No local models with tool support found. Download a model, then refresh.")
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
            raise ValueError("Choose a conversation from your STEVE history.")
        with self._lock:
            self.state.update(busy=True, status="Opening conversation", error="")
        self.emit()
        params = thread_start_params(self.client.home)
        params.pop("ephemeral")
        # Tools are restored by Codex from the original session.
        params.pop("dynamicTools")
        params["threadId"] = thread_id
        # Never resume a persisted active goal before a Fusion target is available.
        goal = self.client.request("thread/goal/get", {"threadId": thread_id}).get("goal")
        if goal and goal["status"] == "active":
            goal = self.client.request("thread/goal/set", {"threadId": thread_id, "status": "paused"}).get("goal")
        result = self.client.request("thread/resume", params)
        thread = result["thread"]
        messages = conversation_messages(thread, self.images)
        with self._lock:
            self.thread_id = thread["id"]
            self.turn_id = None
            self._cancel = True
            self._task_context = None
            self.default_model = result.get("model")
            self.state.update(threadId=self.thread_id, messages=messages, busy=False, status="Ready", goal=goal,
                              goalHasTarget=bool(self._goal_contexts.get((self.state["provider"], self.thread_id))),
                              goalNotice="Resume to continue this goal." if goal else "", taskDocument=None)
            self._choose_preferences()
        self.emit()

    def _login(self, device=False):
        if self.state["provider"] in ("ollama", "claude"):
            self._refresh_account(refresh_models=True)
            return
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
            allowed = login_url_allowed(url or "") if self.state["provider"] == "grok" else parsed.scheme == "https" and parsed.hostname in ("auth.openai.com", "chatgpt.com", "auth.chatgpt.com")
            if not allowed:
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
            raise RuntimeError("Start Ollama and refresh models to begin." if self.state["provider"] == "ollama" else "Sign in with your selected provider to start a conversation.")
        if self.state["provider"] == "ollama" and not self.state["models"]:
            raise RuntimeError("Download a local model with tool support, then refresh models.")
        if len(self.state["messages"]) >= 200:
            raise RuntimeError("Start a new conversation to keep STEVE responsive.")
        references = [self.images.remember(image) for image in images]
        with self._lock:
            self.turn_id = None
            self._task_context = context
            self.state.update(busy=True, error="", status="Thinking")
            self.state.update(taskDocument={"id": context.get("document_id"), "name": context.get("name")} if context else None,
                              waitingForFusion=False)
            self.state["messages"].append({"role": "user", "text": text,
                                           "images": references, "delivery": "pending",
                                           "selectionCount": (context or {}).get("selectionCount", 0)})
            message = self.state["messages"][-1]
        self.emit()
        self._ensure_thread()
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
        self._record_chat_images(params["threadId"], result["turn"]["id"], images, message=text)
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
            self._record_chat_images(payload["threadId"], payload["turnId"], images, message=text)
        except Exception as exc:
            with self._lock:
                message["delivery"] = "failed"
                self.state["error"] = "Steering message was not confirmed: " + str(exc)
            self.debug.record("steer.failed", error=str(exc))
        self.emit()

    def _record_chat_images(self, thread_id, turn_id, images, **metadata):
        if not images:
            return []
        try:
            return self.images.record(thread_id, turn_id, images, **metadata)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Delivery already succeeded. A cache failure must never invite resending changes.
            self.debug.record("images.index_failed", error=str(exc), threadId=thread_id)
            with self._lock:
                self.state["error"] = "The image was sent, but STEVE could not save it for later lookup."
            return []

    def _chat_image_tool(self, payload):
        try:
            if payload["cancelled"]():
                raise ToolError("inactive_request", "This image request is no longer active.")
            if payload["tool"] == "list_chat_images":
                result = {"ok": True, **self.images.list_chat(payload["threadId"], **payload["arguments"])}
                if payload["cancelled"]():
                    raise ToolError("inactive_request", "This image request is no longer active.")
                payload["complete"](result)
                return
            try:
                metadata, url = self.images.read_chat(payload["threadId"], payload["arguments"]["image_id"])
            except KeyError as exc:
                raise ToolError("chat_image_not_found", str(exc)) from exc
            except FileNotFoundError as exc:
                raise ToolError("chat_image_unavailable", str(exc)) from exc
            self._deliver_image({**payload, "imageUrl": url, "savedImage": metadata,
                                 "result": {"ok": True, **metadata}})
        except Exception as exc:
            payload["complete"](tool_failure(exc, code="chat_image_index_unavailable" if isinstance(exc, (OSError, ValueError)) else None))

    def _deliver_image(self, payload):
        # Use native image input: nested tool-output images can fail
        # when Responses history is replayed. This runs on the controller worker.
        result = payload["result"]
        try:
            if payload["cancelled"]():
                raise ToolError("inactive_request", "The image request's turn is no longer active.")
            saved = payload.get("savedImage")
            label = SAVED_IMAGE_PREFIX + "\n" + json.dumps(saved, ensure_ascii=False) if saved else VIEWPORT_PREFIX
            payload["client"].request("turn/steer", {"threadId": payload["threadId"],
                "expectedTurnId": payload["turnId"], "input": [
                    {"type": "text", "text": label, "text_elements": []},
                    {"type": "image", "url": payload["imageUrl"]}]})
            result["imageDelivered"] = True
        except Exception as exc:
            result.update(tool_failure(exc, code="chat_image_delivery_failed" if payload.get("savedImage") else "image_delivery_failed"))
        if result.get("imageDelivered") and not payload.get("savedImage"):
            try:
                images = validate_images([{"url": payload["imageUrl"], "name": "Viewport capture"}],
                                         max_bytes=MAX_STORED_IMAGE_BYTES)
                with self._lock:
                    document = copy.deepcopy(self.state.get("taskDocument"))
                recorded = self._record_chat_images(payload["threadId"], payload["turnId"], images,
                    source="viewport", message="Viewport captured for visual verification", document=document)
                if recorded:
                    result["imageId"] = recorded[0]["imageId"]
                else:
                    result["cacheWarning"] = "Image delivered but unavailable for later lookup."
            except ValueError as exc:
                result["cacheWarning"] = "Image delivered but could not be cached."
                self.debug.record("images.index_failed", error=str(exc))
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
            elif method == "steve/disconnected":
                self._active_tools.clear()
                self._finish_code_activity()
                self.state.update(connection="disconnected", busy=False, waitingForFusion=False, loginPending=False,
                                  error=params["message"], status="Disconnected")
            elif method == "account/updated":
                if self.state["provider"] != "chatgpt":
                    return  # External providers own their account state outside the bundled runtime.
                if params.get("authMode") == self.state["provider"]:
                    self.dispatch("accountRefresh")
                elif params.get("authMode") is None:
                    self.thread_id = self.turn_id = None
                    self._task_context = None
                    self.state.update(account=None, models=[], model="", messages=[], threadId=None, goal=None, goalHasTarget=False,
                                      history=[], historyCursor=None)
            elif params.get("threadId") != self.thread_id or not self.thread_id:
                return
            elif method in ("thread/goal/updated", "thread/goal/cleared"):
                self._goal_revision += 1
                self._set_goal_state(params.get("goal") if method.endswith("updated") else None)
            elif method == "turn/started":
                self.turn_id = params["turn"]["id"]
                self.state.update(busy=True, status="Stopping" if self._cancel else "Thinking")
                if self._cancel:
                    self._commands.put(("stop", {}))
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
                if turn.get("id") and self.turn_id and turn["id"] != self.turn_id:
                    return
                self._active_tools.clear()
                self._finish_code_activity()
                continuing = bool(self.state["goal"] and self.state["goal"]["status"] == "active" and not self._cancel)
                self.state.update(busy=continuing, status="Continuing goal" if continuing else
                                  "Stopped" if turn.get("status") == "interrupted" else "Ready")
                if turn.get("error"):
                    self.state["error"] = turn["error"].get("message", "The response failed. Try again.")
                    if continuing:
                        self._cancel = True
                        self._commands.put(("stop", {}))
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

    def _finish_code_activity(self):
        # A missing callback is not proof of success (or of a rolled-back operation).
        for message in self.state["messages"]:
            if message.get("role") == "tool" and message.get("toolStatus") == "running":
                message["toolStatus"] = "unconfirmed"

    def close(self):
        self._closed = True
        self.updates.close()
        self.downloader.close()
        self._commands.put(None)
        if self.client:
            self.client.close()
        self.debug.close()
