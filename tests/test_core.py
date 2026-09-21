import os
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
from steve.controller import Controller, conversation_messages, install_guide_url, thread_start_params, CONTEXT_PREFIX
from steve.transport import Transport, RuntimeUnavailable, runtime_environment
from steve.debug_log import DebugLog


def process_alive(pid):
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in listing
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(status) and not status.startswith("Z")


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("The expected state was not reached.")


class TransportTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".cache" / "tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.folder = scratch / str(uuid4())
        self.folder.mkdir()
        self.events = []
        self.client = Transport(lambda *args: self.events.append(args),
                                command=[sys.executable, str(ROOT / "tests" / "fake_server.py")],
                                home=self.folder)
        self.client.start()

    def tearDown(self):
        self.client.close()

    def test_interleaved_event_and_unicode_reply(self):
        self.assertEqual(self.client.request("echo", {"text": "café → bracket"}), {"text": "café → bracket"})
        self.assertIn(("test/event", {"text": "hello"}), self.events)

    def test_server_errors_do_not_kill_connection(self):
        with self.assertRaisesRegex(RuntimeError, "fixture error"):
            self.client.request("fail")
        self.assertEqual(self.client.request("echo", {"ok": True}), {"ok": True})

    def test_timeout_removes_pending_request(self):
        with self.assertRaises(TimeoutError):
            self.client.request("ignore", timeout=0.03)
        self.assertFalse(self.client._pending)
        self.assertEqual(self.client.request("echo", {"ok": True}), {"ok": True})

    def test_exit_unblocks_waiter(self):
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            self.client.request("exit", timeout=2)

    def test_close_stops_a_runtime_and_its_helper_that_ignore_shutdown(self):
        helper = self.client.request("linger")["pid"]
        self.assertTrue(process_alive(helper))
        started = time.monotonic()
        self.client.close()
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsNotNone(self.client.process.poll())
        eventually(lambda: not process_alive(helper), timeout=5)

    def test_unsupported_server_request_is_answered(self):
        self.assertTrue(self.client.request("tool")["declined"])

    def test_runtime_stderr_is_drained_and_logging_can_be_toggled(self):
        debug = DebugLog(self.folder)
        self.client.debug = debug
        try:
            self.client.request("stderr")
            self.assertFalse(debug.path.exists())
            debug.set_enabled(True)
            self.client.request("stderr")
            eventually(lambda: "runtime.stderr" in debug.path.read_text(encoding="utf-8"))
            debug.set_enabled(False)
            before = debug.path.read_bytes()
            self.client.request("stderr")
            self.assertEqual(before, debug.path.read_bytes())
        finally:
            debug.close()

    def test_pending_fusion_work_does_not_block_transport(self):
        calls, results = [], []
        self.client.on_request = lambda *args: calls.append(args)
        worker = threading.Thread(target=lambda: results.append(self.client.request("deferred-tool", timeout=3)))
        worker.start()
        try:
            eventually(lambda: bool(calls))
            self.assertEqual(self.client.request("echo", {"responsive": True}), {"responsive": True})
            self.assertIn(("test/while-tool-pending", {}), self.events)
            self.client.reply(calls[0][0], {"success": True, "contentItems": []})
            worker.join(2)
            self.assertEqual(results, [{"success": True, "contentItems": []}])
            self.assertFalse(self.client._incoming)
        finally:
            worker.join(4)

    def test_close_terminates_owned_process_and_is_idempotent(self):
        self.client.close()
        self.client.close()
        self.assertIsNotNone(self.client.process.poll())
        self.assertTrue((self.folder / "workspace" / "closed-cleanly.txt").is_file())

    def test_credentials_are_isolated_from_parent_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "CODEX_ACCESS_TOKEN": "test", "CODEX_HOME": "elsewhere"}):
            env = runtime_environment(self.folder)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_ACCESS_TOKEN", env)
        self.assertEqual(env["CODEX_HOME"], str(self.folder / "codex"))


class FakeClient:
    def __init__(self, notify):
        self.notify = notify
        self.home = ROOT / ".cache" / "controllers" / str(uuid4())
        self.calls = []
        self.closed = False
        self.account = {"type": "chatgpt", "email": "test@example.com", "planType": "plus"}
        self.block_thread = False
        self.entered_thread = threading.Event()
        self.release_thread = threading.Event()
        self.early_complete = False
        self.login_url = "https://auth.openai.com/authorize"
        self.fail_method = None
        self.history = []
        self.history_cursor = None
        self.replies = []
        self.saved_thread = {"id": "saved-thread", "turns": [
            {"items": [{"id": "old-user", "type": "userMessage", "content": [{"type": "text", "text": "Design a bracket"}]},
                       {"id": "old-answer", "type": "agentMessage", "text": "Choose a thickness."}]}]}

    def start(self):
        pass

    def close(self):
        self.closed = True
        self.release_thread.set()

    def reply(self, request_id, result=None, error=None):
        self.replies.append((request_id, result, error))

    def request(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        if method == self.fail_method:
            raise TimeoutError("request timed out")
        if method == "account/read":
            return {"account": self.account}
        if method == "model/list":
            return {"data": [{"id": "model-1", "displayName": "A model", "defaultReasoningEffort": "low",
                              "supportedReasoningEfforts": [{"reasoningEffort": e, "description": e}
                                                            for e in ("low", "high", "ultra")]}]}
        if method == "thread/list":
            return {"data": self.history, "nextCursor": self.history_cursor}
        if method == "thread/resume":
            return {"thread": self.saved_thread, "model": "saved-model"}
        if method == "account/login/start":
            return {"type": "chatgpt", "loginId": "login-1", "authUrl": self.login_url}
        if method == "thread/start":
            self.entered_thread.set()
            if self.block_thread:
                self.release_thread.wait(2)
            return {"thread": {"id": "thread-1"}, "model": "account-default"}
        if method == "turn/start":
            self.notify("turn/started", {"threadId": "thread-1", "turn": {"id": "turn-1"}})
            if self.early_complete:
                self.complete()
            return {"turn": {"id": "turn-1"}}
        if method == "turn/interrupt":
            self.complete("interrupted")
        if method == "account/logout":
            self.account = None
        return {}

    def complete(self, status="completed"):
        self.notify("turn/completed", {"threadId": "thread-1", "turn": {"id": "turn-1", "status": status}})


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.snapshots = []
        self.urls = []
        self.controller = Controller(self.snapshots.append, transport_factory=FakeClient,
                                     open_browser=lambda url: self.urls.append(url),
                                     debug_log=DebugLog(ROOT / ".cache" / "debug-tests" / str(uuid4())))
        self.controller.dispatch("connect")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(2)

    def signed_out(self):
        self.client.account = None
        self.controller.dispatch("accountRefresh")
        eventually(lambda: self.controller.snapshot()["account"] is None)

    def test_startup_validates_saved_account_without_opening_browser(self):
        self.assertTrue(self.controller.snapshot()["accountChecked"])
        self.assertEqual(self.controller.snapshot()["account"]["email"], "test@example.com")
        self.assertIn(("account/read", {"refreshToken": True}), self.client.calls)
        self.assertFalse(self.urls)

    def test_provider_switch_preserves_preferences_and_rejects_stale_events(self):
        def grok_factory(notify):
            client = FakeClient(notify)
            client.account = {"type": "grok", "id": "grok-fixture", "email": "grok@example.com", "planType": "Grok / X"}
            client.login_url = "https://auth.x.ai/oauth2/authorize"
            return client
        self.controller.grok_factory = grok_factory
        self.controller.dispatch("model", {"model": "model-1"})
        self.controller.dispatch("effort", {"effort": "high"})
        eventually(lambda: self.controller.snapshot()["effort"] == "high")
        old = self.client
        self.controller.dispatch("provider", {"provider": "grok"})
        eventually(lambda: self.controller.snapshot()["account"] and self.controller.snapshot()["account"].get("id") == "grok-fixture")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.assertTrue(old.closed)
        self.assertEqual(self.controller.snapshot()["effort"], "")
        self.assertEqual(self.controller.provider_choice.provider, "grok")
        old.notify("steve/disconnected", {"message": "Stale runtime"})
        self.assertEqual(self.controller.snapshot()["connection"], "ready")
        self.controller.dispatch("send", {"text": "Inspect with Grok"})
        eventually(lambda: self.controller.turn_id is not None)
        self.assertFalse(self.controller.dispatch("provider", {"provider": "chatgpt"}))
        self.assertEqual(self.controller.snapshot()["provider"], "grok")
        self.controller.client.complete()
        self.controller.dispatch("provider", {"provider": "chatgpt"})
        eventually(lambda: self.controller.snapshot()["account"] and self.controller.snapshot()["account"].get("email") == "test@example.com")
        eventually(lambda: self.controller.snapshot()["effort"] == "high")
        self.assertEqual(self.controller.snapshot()["model"], "model-1")
        self.assertEqual(self.controller.snapshot()["messages"], [])

    def test_grok_browser_login_uses_xai_allowlist(self):
        self.controller.state["provider"] = "grok"
        self.client.account = None
        self.client.login_url = "https://auth.x.ai/oauth2/authorize"
        self.controller.dispatch("login")
        eventually(lambda: bool(self.urls))
        self.assertEqual(self.urls, ["https://auth.x.ai/oauth2/authorize"])
        self.assertFalse(self.controller.dispatch("provider", {"provider": "chatgpt"}))
        self.controller.dispatch("cancelLogin")
        eventually(lambda: not self.controller.snapshot()["loginPending"])

    def test_local_provider_connects_without_signin_and_keeps_chat_after_server_outage(self):
        def factory(notify):
            client = FakeClient(notify)
            client.account = {"type": "ollama", "id": "local-ollama", "email": "Local Ollama"}
            return client
        self.controller.ollama_factory = factory
        self.controller.dispatch("provider", {"provider": "ollama"})
        eventually(lambda: self.controller.snapshot()["account"] and self.controller.snapshot()["account"].get("id") == "local-ollama")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        client = self.controller.client
        self.controller.dispatch("login")
        self.controller.dispatch("model", {"model": "model-1"})
        eventually(lambda: self.controller.snapshot()["model"] == "model-1")
        self.assertFalse(self.urls)
        self.assertNotIn("account/login/start", [m for m, _ in client.calls])
        self.controller.dispatch("send", {"text": "Inspect locally"})
        eventually(lambda: self.controller.turn_id is not None)
        self.assertEqual(next(p for m, p in client.calls if m == "thread/start")["model"], "model-1")
        client.complete()
        client.account = None
        self.controller.dispatch("accountRefresh")
        eventually(lambda: self.controller.snapshot()["account"] is None)
        self.assertEqual(self.controller.thread_id, "thread-1")
        self.assertEqual(self.controller.snapshot()["messages"][0]["text"], "Inspect locally")
        client.account = {"type": "ollama", "id": "local-ollama", "email": "Local Ollama"}
        self.controller.dispatch("accountRefresh", {"refreshModels": True})
        eventually(lambda: self.controller.snapshot()["model"] == "model-1")
        self.assertEqual(self.controller.thread_id, "thread-1")

    def test_update_checks_and_download_do_not_interrupt_an_active_turn(self):
        release = {"version": "0.3.0", "downloadUrl": "https://github.com/10-X-eng/STEVE/releases/download/v0.3.0/STEVE-0.3.0-windows-x64.zip",
                   "releaseUrl": "https://github.com/10-X-eng/STEVE/releases/tag/v0.3.0"}
        self.controller.updates.fetch = lambda: release
        self.controller.dispatch("send", {"text": "Create a bracket"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("checkUpdates")
        eventually(lambda: self.controller.snapshot()["updateInfo"] is not None)
        self.assertTrue(self.controller.snapshot()["busy"])
        self.controller.dispatch("openUpdate", {"page": "download", "url": "https://example.com/ignored"})
        eventually(lambda: bool(self.urls))
        self.assertEqual(self.urls, [release["downloadUrl"]])
        self.assertEqual(self.controller.turn_id, "turn-1")
        self.controller.updates.fetch = lambda: (_ for _ in ()).throw(OSError("offline"))
        self.controller.dispatch("checkUpdates")
        eventually(lambda: "Couldn’t check" in self.controller.snapshot()["updateStatus"])
        self.assertTrue(self.controller.snapshot()["busy"])
        self.assertEqual(self.controller.snapshot()["error"], "")
        self.assertEqual(self.controller.snapshot()["updateInfo"], release)
        with patch.object(self.controller.downloader, "request") as download:
            self.controller.dispatch("downloadUpdate", {"url": "https://example.com/ignored"})
            eventually(lambda: download.called)
            download.assert_called_once_with(release)
        self.controller._update_state({"updateDownload": {"state": "ready", "path": str(ROOT / ".cache" / "fixture.zip")}})
        with patch("steve.controller.open_folder") as open_downloads:
            self.controller.dispatch("openDownloads", {"path": "ignored"})
            eventually(lambda: open_downloads.called)
            open_downloads.assert_called_once_with(ROOT / ".cache")
        self.assertTrue(self.controller.snapshot()["busy"])

    def test_tool_activity_tracks_code_and_overlapping_calls_without_stale_completions(self):
        pending = []
        class Runner:
            def submit(self, tool, arguments, complete, cancelled):
                pending.append(complete)
        self.controller.fusion_tools = Runner()
        self.controller.dispatch("send", {"text": "Make a bracket"})
        eventually(lambda: self.controller.turn_id is not None)
        def call(request_id, title):
            self.client.on_request(request_id, "item/tool/call", {
                "threadId": "thread-1", "turnId": self.controller.turn_id,
                "tool": "fusion_query_python", "arguments": {
                    "document_id": "fixture", "title": title,
                    "code": "def run(context):\n    return {'private': 'not UI data'}"}})
        call("first", "Inspect faces")
        call("second", "Inspect edges")
        code_messages = [m for m in self.controller.snapshot()["messages"] if m["role"] == "tool"]
        self.assertEqual(len(code_messages), 2)
        self.assertTrue(all(m["toolStatus"] == "running" for m in code_messages))
        self.assertIn("def run(context)", code_messages[0]["code"])
        self.assertEqual(self.controller.snapshot()["activeTools"], [
            {"name": "fusion_query_python", "title": "Inspect faces"},
            {"name": "fusion_query_python", "title": "Inspect edges"}])
        self.client.notify("item/agentMessage/delta", {
            "threadId": "thread-1", "itemId": "answer", "delta": "Checking"})
        self.assertEqual(len(self.controller.snapshot()["activeTools"]), 2)
        pending[1]({"ok": True})
        self.assertEqual(self.controller.snapshot()["messages"][2]["toolStatus"], "completed")
        self.assertEqual(self.controller.snapshot()["activeTools"][0]["title"], "Inspect faces")
        self.client.complete()
        self.assertEqual(self.controller.snapshot()["messages"][1]["toolStatus"], "unconfirmed")
        self.assertEqual(self.controller.snapshot()["activeTools"], [])
        # A delayed callback from the previous turn must not erase the new call.
        self.controller.state["busy"] = True
        self.controller.turn_id = "turn-2"
        call("third", "Measure thickness")
        pending[0]({"ok": False})
        self.assertEqual(self.controller.snapshot()["messages"][1]["toolStatus"], "unconfirmed")
        self.assertEqual(self.controller.snapshot()["activeTools"][0]["title"], "Measure thickness")
        self.client.notify("turn/completed", {"threadId": "thread-1", "turn": {"id": "turn-1"}})
        self.assertTrue(self.controller.snapshot()["busy"])
        pending[2]({"ok": False})
        self.assertEqual(self.controller.snapshot()["messages"][-1]["toolStatus"], "failed")
        self.assertEqual(self.controller.snapshot()["activeTools"], [])
        call("fourth", "Check again")
        self.client.notify("steve/disconnected", {"message": "Runtime closed"})
        self.assertEqual(self.controller.snapshot()["messages"][-1]["toolStatus"], "unconfirmed")
        self.assertEqual(self.controller.snapshot()["activeTools"], [])

    def test_tool_activity_clears_when_submission_fails(self):
        class Runner:
            def submit(self, *args):
                raise RuntimeError("Fusion is unavailable")
        self.controller.fusion_tools = Runner()
        self.controller.dispatch("send", {"text": "Inspect this"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.on_request("failed", "item/tool/call", {
            "threadId": "thread-1", "turnId": "turn-1", "tool": "fusion_api_help",
            "arguments": {"path": "adsk.fusion.Sketch"}})
        self.assertTrue(any(s["activeTools"] for s in self.snapshots))
        self.assertEqual(self.controller.snapshot()["activeTools"], [])
        self.assertFalse(self.client.replies[-1][1]["success"])

    def test_debug_menu_toggle_records_failed_code_and_opens_local_folder(self):
        self.controller.dispatch("debugLogging", {"enabled": True})
        eventually(lambda: self.controller.snapshot()["debugLogging"])
        self.controller.dispatch("send", {"text": "Try an operation"})
        eventually(lambda: self.controller.turn_id is not None)
        code = "def run(context):\n invalid syntax here"
        self.client.on_request("debug-call", "item/tool/call", {
            "threadId": "thread-1", "turnId": "turn-1", "tool": "fusion_execute_python",
            "arguments": {"document_id": "fixture", "title": "Broken operation", "code": code}})
        entries = [json.loads(line) for line in self.controller.debug.path.read_text(encoding="utf-8").splitlines()]
        started = next(entry for entry in entries if entry["event"] == "tool.started")
        completed = next(entry for entry in entries if entry["event"] == "tool.completed")
        self.assertEqual(started["arguments"]["code"], code)
        self.assertFalse(completed["result"]["ok"])
        self.assertEqual(completed["requestId"], started["requestId"])
        self.assertIn("durationMs", completed)
        self.controller.dispatch("debugLogging", {"enabled": False})
        eventually(lambda: not self.controller.snapshot()["debugLogging"])
        with patch("steve.controller.open_folder") as open_folder:
            self.controller.dispatch("openLogs")
            eventually(lambda: open_folder.called)
            open_folder.assert_called_once_with(self.controller.debug.folder)

    def test_missing_codex_exposes_setup_and_recovers_after_repair(self):
        with patch.object(FakeClient, "start", side_effect=RuntimeUnavailable("Codex is missing")):
            self.controller.dispatch("connect")
            eventually(lambda: self.controller.snapshot()["runtimeIssue"])
            self.assertEqual(self.controller.snapshot()["status"], "Codex setup needed")
        self.controller.dispatch("setupHelp", {"page": "codex"})
        eventually(lambda: bool(self.urls))
        self.assertEqual(self.urls, ["https://learn.chatgpt.com/docs/quickstart?setup=app"])
        self.controller.dispatch("setupHelp", {"page": "steve"})
        eventually(lambda: len(self.urls) == 2)
        self.assertEqual(self.urls[1], install_guide_url())
        self.assertEqual(install_guide_url("darwin"), "https://github.com/10-X-eng/STEVE#install-the-macos-preview")
        self.assertEqual(install_guide_url("win32"), "https://github.com/10-X-eng/STEVE#install-the-windows-preview")
        self.controller.dispatch("connect")
        eventually(lambda: self.controller.snapshot()["connection"] == "ready")
        self.assertFalse(self.controller.snapshot()["runtimeIssue"])

    def test_sign_in_reuses_an_existing_account(self):
        before = len(self.client.calls)
        self.controller.dispatch("login")
        eventually(lambda: len(self.client.calls) > before)
        self.assertFalse(any(method == "account/login/start" for method, _ in self.client.calls))
        self.assertFalse(self.urls)

    def test_browser_login_uses_local_completion_page(self):
        self.signed_out()
        self.controller.dispatch("login")
        eventually(lambda: bool(self.urls))
        params = next(params for method, params in self.client.calls if method == "account/login/start")
        self.assertEqual(params, {"type": "chatgpt", "useHostedLoginSuccessPage": False})

    def test_login_completion_validates_account_and_enables_chat(self):
        self.signed_out()
        self.controller.dispatch("login")
        eventually(lambda: bool(self.urls))
        self.client.calls.clear()
        self.client.account = {"type": "chatgpt", "email": "signed-in@example.com", "planType": "plus"}
        self.client.notify("account/login/completed", {"loginId": "login-1", "success": True})
        eventually(lambda: bool(self.controller.snapshot()["account"]))
        self.assertIn(("account/read", {"refreshToken": True}), self.client.calls)
        self.assertFalse(self.controller.snapshot()["loginPending"])

    def test_account_update_recovers_sign_in_without_completion_event(self):
        self.signed_out()
        self.client.account = {"type": "chatgpt", "email": "signed-in@example.com", "planType": "plus"}
        self.client.notify("account/updated", {"authMode": "chatgpt", "planType": "plus"})
        eventually(lambda: bool(self.controller.snapshot()["account"]))

    def test_pending_login_checks_saved_account_when_notifications_are_missing(self):
        self.signed_out()
        self.controller.dispatch("login")
        eventually(lambda: bool(self.urls))
        self.client.account = {"type": "chatgpt", "email": "signed-in@example.com", "planType": "plus"}
        eventually(lambda: bool(self.controller.snapshot()["account"]), timeout=4)
        self.assertFalse(self.controller.snapshot()["loginPending"])

    def test_empty_account_check_preserves_pending_sign_in(self):
        self.signed_out()
        self.controller.dispatch("login")
        eventually(lambda: bool(self.urls))
        before = len(self.client.calls)
        self.controller.dispatch("accountRefresh")
        eventually(lambda: len(self.client.calls) > before)
        self.assertTrue(self.controller.snapshot()["loginPending"])
        self.assertEqual(self.controller.login_id, "login-1")

    def test_streamed_response_and_early_completion(self):
        self.client.early_complete = True
        self.controller.dispatch("send", {"text": "Help with a sketch"})
        eventually(lambda: any(method == "turn/start" for method, _ in self.client.calls))
        eventually(lambda: not self.controller.snapshot()["busy"])
        self.assertIsNone(self.controller.turn_id)

    def test_deltas_are_replaced_by_final_message(self):
        self.controller.dispatch("send", {"text": "Help"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.notify("item/agentMessage/delta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "answer", "delta": "Hello"})
        self.client.notify("item/completed", {"threadId": "thread-1", "turnId": "turn-1", "item": {"id": "answer", "type": "agentMessage", "text": "Hello there"}})
        self.client.complete()
        self.assertEqual(self.controller.snapshot()["messages"][-1]["text"], "Hello there")

    def test_stop_while_thread_is_starting_prevents_turn(self):
        self.client.block_thread = True
        self.controller.dispatch("send", {"text": "Help"})
        self.assertTrue(self.client.entered_thread.wait(1))
        self.controller.dispatch("stop")
        self.client.release_thread.set()
        eventually(lambda: self.controller.snapshot()["status"] == "Stopped")
        self.assertFalse(any(method == "turn/start" for method, _ in self.client.calls))

    def test_interruption_completion_is_not_overwritten_by_stopping(self):
        self.controller.dispatch("send", {"text": "Help"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("stop")
        eventually(lambda: not self.controller.snapshot()["busy"])
        self.assertEqual(self.controller.snapshot()["status"], "Stopped")

    def test_browser_failure_cancels_pending_login(self):
        self.signed_out()
        self.controller.open_browser = lambda url: False
        self.controller.dispatch("login")
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertTrue(any(method == "account/login/cancel" for method, _ in self.client.calls))
        self.assertIsNone(self.controller.login_id)

    def test_rejects_unexpected_login_destination(self):
        self.signed_out()
        self.client.login_url = "https://example.com/authorize"
        self.controller.dispatch("login")
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertFalse(self.urls)

    def test_timed_out_turn_requires_reconnect(self):
        self.client.fail_method = "turn/start"
        self.controller.dispatch("send", {"text": "Help"})
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertEqual(self.controller.snapshot()["connection"], "disconnected")
        self.assertTrue(self.client.closed)

    def test_shutdown_during_thread_start_does_not_start_turn(self):
        self.client.block_thread = True
        self.controller.dispatch("send", {"text": "Help"})
        self.assertTrue(self.client.entered_thread.wait(1))
        self.controller.close()
        self.controller._worker.join(2)
        self.assertFalse(any(method == "turn/start" for method, _ in self.client.calls))

    def test_account_default_restores_original_model_after_override(self):
        self.client.early_complete = True
        self.controller.dispatch("model", {"model": "model-1"})
        self.controller.dispatch("send", {"text": "First question"})
        eventually(lambda: len([m for m, _ in self.client.calls if m == "turn/start"]) == 1)
        eventually(lambda: not self.controller._send_queued)
        self.controller.dispatch("model", {"model": ""})
        self.controller.dispatch("send", {"text": "Second question"})
        eventually(lambda: len([m for m, _ in self.client.calls if m == "turn/start"]) == 2)
        models = [p["model"] for m, p in self.client.calls if m == "turn/start"]
        self.assertEqual(models, ["model-1", "account-default"])

    def test_model_effort_persist_across_restart_reconnect_and_history(self):
        self.controller.dispatch("model", {"model": "model-1"})
        self.controller.dispatch("effort", {"effort": "ultra"})
        eventually(lambda: self.controller.snapshot()["effort"] == "ultra")
        home = self.controller.debug.folder.parent
        self.controller.close()
        self.controller._worker.join(2)
        self.controller = Controller(self.snapshots.append, transport_factory=FakeClient, debug_log=DebugLog(home))
        self.controller.dispatch("connect")
        eventually(lambda: self.controller.snapshot()["effort"] == "ultra")
        self.assertEqual(self.controller.snapshot()["model"], "model-1")
        previous_client = self.controller.client
        self.controller.dispatch("connect")
        eventually(lambda: self.controller.client is not previous_client and bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client
        self.client.history = [{"id": "saved-thread", "preview": "Fixture"}]
        self.controller.dispatch("history")
        eventually(lambda: bool(self.controller.snapshot()["history"]))
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: self.controller.snapshot()["threadId"] == "saved-thread")
        self.controller.dispatch("send", {"text": "Continue"})
        eventually(lambda: any(m == "turn/start" for m, _ in self.client.calls))
        params = next(p for m, p in self.client.calls if m == "turn/start")
        self.assertEqual((params["model"], params["effort"]), ("model-1", "ultra"))

    def test_effort_default_is_sent_explicitly_after_override(self):
        self.client.early_complete = True
        self.controller.dispatch("model", {"model": "model-1"})
        self.controller.dispatch("effort", {"effort": "high"})
        self.controller.dispatch("send", {"text": "First"})
        eventually(lambda: any(m == "turn/start" for m, _ in self.client.calls) and not self.controller._send_queued)
        self.controller.dispatch("effort", {"effort": ""})
        self.controller.dispatch("send", {"text": "Second"})
        eventually(lambda: len([m for m, _ in self.client.calls if m == "turn/start"]) == 2)
        self.assertEqual([p["effort"] for m, p in self.client.calls if m == "turn/start"], ["high", "low"])

    def test_unsupported_effort_is_rejected_and_unavailable_model_preserved(self):
        self.controller.dispatch("model", {"model": "model-1"})
        self.controller.dispatch("effort", {"effort": "invented"})
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertEqual(self.controller.snapshot()["effort"], "")
        self.controller.preferences.save("unavailable-model", "high")
        with self.controller._lock:
            self.controller._choose_preferences()
        self.assertEqual(self.controller.snapshot()["model"], "")
        self.assertIn("unavailable", self.controller.snapshot()["preferenceNotice"])
        self.assertEqual(self.controller.preferences.model, "unavailable-model")

    def test_rejected_send_does_not_capture_or_retarget_fusion(self):
        calls = []
        capture = lambda action: calls.append(action) or {"document_id": "original", "name": "Original"}
        self.controller.dispatch("send", {"text": "Start"}, capture_context=capture)
        self.controller.dispatch("send", {"text": "Duplicate"}, capture_context=capture)
        eventually(lambda: self.controller.snapshot()["busy"])
        self.assertEqual(calls, ["send"])
        self.assertEqual(self.controller.snapshot()["taskDocument"]["id"], "original")

    def test_logout_clears_conversation_and_public_account_state(self):
        self.client.early_complete = True
        self.controller.dispatch("send", {"text": "First question"})
        eventually(lambda: len([m for m, _ in self.client.calls if m == "turn/start"]) == 1)
        eventually(lambda: not self.controller._send_queued)
        self.controller.dispatch("logout")
        eventually(lambda: self.controller.snapshot()["account"] is None)
        self.assertEqual(self.controller.snapshot()["messages"], [])
        self.assertEqual(self.controller.snapshot()["models"], [])
        self.assertIsNone(self.controller.thread_id)

    def test_new_threads_are_persistent(self):
        self.assertFalse(thread_start_params(ROOT)["ephemeral"])

    def test_history_lists_local_threads_and_paginates(self):
        self.client.history = [{"id": "saved-thread", "preview": "Bracket", "updatedAt": 123}]
        self.client.history_cursor = "next-page"
        self.controller.dispatch("history")
        eventually(lambda: len(self.controller.snapshot()["history"]) == 1)
        self.client.history = [{"id": "older-thread", "name": "Old design", "updatedAt": 100}]
        self.client.history_cursor = None
        self.controller.dispatch("history", {"more": True})
        eventually(lambda: len(self.controller.snapshot()["history"]) == 2)
        params = [p for method, p in self.client.calls if method == "thread/list"][-1]
        self.assertEqual(params["cursor"], "next-page")
        self.assertEqual(params["cwd"], str(self.client.home / "workspace"))
        self.assertIsNone(self.controller.snapshot()["historyCursor"])

    def test_open_history_restores_messages_and_continues_original_thread(self):
        self.client.history = [{"id": "saved-thread", "preview": "Bracket"}]
        self.controller.dispatch("history")
        eventually(lambda: bool(self.controller.snapshot()["history"]))
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: self.controller.snapshot()["threadId"] == "saved-thread")
        self.assertEqual([m["text"] for m in self.controller.snapshot()["messages"]],
                         ["Design a bracket", "Choose a thickness."])
        self.controller.dispatch("send", {"text": "Use 5 mm"})
        eventually(lambda: any(m == "turn/start" for m, _ in self.client.calls))
        params = next(p for m, p in self.client.calls if m == "turn/start")
        self.assertEqual(params["threadId"], "saved-thread")
        self.assertEqual(params["model"], "saved-model")
        self.assertFalse(any(m == "thread/start" for m, _ in self.client.calls))

    def test_unknown_history_id_cannot_be_resumed(self):
        self.controller.dispatch("openHistory", {"threadId": "not-listed"})
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertFalse(any(m == "thread/resume" for m, _ in self.client.calls))

    def test_history_cannot_replace_a_running_conversation(self):
        self.controller.dispatch("send", {"text": "Help"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        self.assertFalse(any(m == "thread/resume" for m, _ in self.client.calls))

    def test_history_resume_error_preserves_current_messages(self):
        self.client.history = [{"id": "saved-thread", "preview": "Bracket"}]
        self.controller.dispatch("history")
        eventually(lambda: bool(self.controller.snapshot()["history"]))
        self.client.fail_method = "thread/resume"
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        self.assertFalse(self.controller.snapshot()["busy"])
        self.assertIsNone(self.controller.thread_id)

    def test_history_filters_non_message_items(self):
        self.assertEqual(conversation_messages({"turns": [{"items": [
            {"id": "secret-reasoning", "type": "reasoning", "text": "not a chat message"},
            {"id": "user", "type": "userMessage", "content": [{"type": "text", "text": "Hello"}, {"type": "image"}]},
        ]}]}), [{"id": "user", "role": "user", "text": "Hello",
                "images": [{"id": "", "name": "Saved image (preview unavailable)"}]}])

    def test_history_restores_only_bounded_fusion_python_activity(self):
        script = {"id": "script", "type": "dynamicToolCall", "tool": "fusion_query_python",
                  "arguments": {"title": "Measure", "code": "def run(context): return 1"}, "success": True}
        items = [script, {**script, "id": "failed", "success": False},
                 {**script, "id": "unknown", "success": None},
                 {**script, "tool": "another_tool"}, {**script, "arguments": "invalid"},
                 {**script, "arguments": {"code": "x" * 60001}}]
        messages = conversation_messages({"turns": [{"items": items}]})
        self.assertEqual([m["toolStatus"] for m in messages], ["completed", "failed", "unconfirmed"])
        self.assertTrue(all(m["historical"] for m in messages))
        self.assertEqual(messages[0]["code"], script["arguments"]["code"])

    def test_fusion_tool_call_returns_result_and_can_be_cancelled(self):
        class Runner:
            def submit(runner, tool, arguments, complete, cancelled):
                runner.complete, runner.cancelled = complete, cancelled
        runner = Runner()
        self.controller.fusion_tools = runner
        self.controller.dispatch("send", {"text": "Inspect the active product"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.on_request("call-1", "item/tool/call", {"threadId": "thread-1", "turnId": "turn-1", "tool": "fusion_inspect_document", "arguments": {}})
        self.assertFalse(runner.cancelled())
        self.assertEqual(self.controller.snapshot()["status"], "Inspecting design")
        runner.complete({"ok": True, "products": ["CAMProductType"]})
        self.assertTrue(self.client.replies[-1][1]["success"])
        self.controller.dispatch("stop")
        self.assertTrue(runner.cancelled())

    def test_late_fusion_result_does_not_change_completed_turn_status(self):
        class Runner:
            def submit(runner, tool, arguments, complete, cancelled):
                runner.complete, runner.cancelled = complete, cancelled
        runner = Runner()
        self.controller.fusion_tools = runner
        self.controller.dispatch("send", {"text": "Inspect"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.on_request("call-1", "item/tool/call", {"threadId": "thread-1", "turnId": "turn-1", "tool": "fusion_inspect_document", "arguments": {}})
        self.client.complete()
        self.assertTrue(runner.cancelled())
        runner.complete({"ok": False, "error": "cancelled"})
        self.assertEqual(self.controller.snapshot()["status"], "Ready")

    def test_foreign_tool_call_and_non_fusion_request_are_rejected(self):
        self.client.on_request("foreign", "item/tool/call", {"threadId": "foreign", "tool": "fusion_inspect_document", "arguments": {}})
        self.assertFalse(self.client.replies[-1][1]["success"])
        self.client.on_request("approval", "item/commandExecution/requestApproval", {})
        self.assertEqual(self.client.replies[-1][2]["code"], -32601)

    def test_new_and_resumed_chats_receive_current_tools_and_prompt(self):
        params = thread_start_params(ROOT)
        self.assertEqual({tool["name"] for tool in params["dynamicTools"]},
                         {"fusion_inspect_document", "fusion_query_python", "fusion_execute_python", "fusion_api_help", "fusion_capture_viewport", "list_chat_images", "view_chat_image"})
        self.assertNotIn("No tools are available", params["baseInstructions"])
        self.client.history = [{"id": "saved-thread", "preview": "Old chat"}]
        self.controller.dispatch("history")
        eventually(lambda: bool(self.controller.snapshot()["history"]))
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: self.controller.snapshot()["threadId"] == "saved-thread")
        resumed = next(p for m, p in self.client.calls if m == "thread/resume")
        self.assertNotIn("dynamicTools", resumed)
        self.assertEqual(resumed["baseInstructions"], params["baseInstructions"])

    def test_selection_context_is_sent_to_codex_but_not_rendered_as_chat_text(self):
        context = {"document_id": "doc", "selectionCount": 1, "selection": [{"name": "Selected edge", "entityToken": "token"}]}
        self.controller.dispatch("send", {"text": "Fillet this", "fusionContext": context})
        context["selection"].clear()
        eventually(lambda: self.controller.turn_id is not None)
        params = next(p for method, p in self.client.calls if method == "turn/start")
        self.assertEqual(params["input"][0]["text"], "Fillet this")
        self.assertTrue(params["input"][1]["text"].startswith(CONTEXT_PREFIX))
        self.assertIn("Selected edge", params["input"][1]["text"])
        messages = conversation_messages({"turns": [{"items": [{"type": "userMessage", "id": "user", "content": params["input"]}]}]})
        self.assertEqual(messages[0]["text"], "Fillet this")
        self.assertEqual(self.controller.snapshot()["messages"][0]["selectionCount"], 1)

    def test_steering_targets_active_turn_and_does_not_start_a_second_turn(self):
        self.controller.dispatch("send", {"text": "Make a plate"})
        eventually(lambda: self.controller.turn_id is not None)
        self.assertTrue(self.controller.snapshot()["canSteer"])
        self.controller.dispatch("steer", {"text": "Use 6 mm thickness", "threadId": "thread-1", "turnId": "turn-1", "fusionContext": {"selectionCount": 0}})
        eventually(lambda: any(method == "turn/steer" for method, _ in self.client.calls))
        eventually(lambda: self.controller.snapshot()["messages"][-1].get("delivery") == "sent")
        params = next(p for method, p in self.client.calls if method == "turn/steer")
        self.assertEqual(params["expectedTurnId"], "turn-1")
        self.assertEqual(params["input"][0]["text"], "Use 6 mm thickness")
        self.assertEqual(sum(method == "turn/start" for method, _ in self.client.calls), 1)
        self.assertTrue(self.controller.snapshot()["busy"])

    def test_steering_failure_keeps_active_turn_and_user_message(self):
        self.controller.dispatch("send", {"text": "Make a plate"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.fail_method = "turn/steer"
        self.controller.dispatch("steer", {"text": "Keep the hole", "threadId": "thread-1", "turnId": "turn-1"})
        eventually(lambda: self.controller.snapshot()["messages"][-1].get("delivery") == "failed")
        self.assertTrue(self.controller.snapshot()["busy"])
        self.assertFalse(self.client.closed)
        self.assertEqual(self.controller.snapshot()["messages"][-1]["text"], "Keep the hole")
        self.assertIn("not confirmed", self.controller.snapshot()["error"])

    def test_stale_steering_is_not_applied_to_another_turn(self):
        self.controller.dispatch("send", {"text": "Make a plate"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("steer", {"text": "Change it", "threadId": "thread-1", "turnId": "old-turn"})
        eventually(lambda: self.controller.snapshot()["messages"][-1].get("delivery") == "failed")
        self.assertFalse(any(method == "turn/steer" for method, _ in self.client.calls))

    def test_viewport_image_is_delivered_as_native_image_input_not_nested_tool_output(self):
        class Runner:
            def submit(runner, tool, arguments, complete, cancelled):
                complete({"ok": True, "imageUrl": "data:image/png;base64,fixture", "width": 100, "height": 50})
        self.controller.fusion_tools = Runner()
        self.controller.dispatch("send", {"text": "Check the result"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.on_request("capture", "item/tool/call", {"threadId": "thread-1", "turnId": "turn-1", "tool": "fusion_capture_viewport", "arguments": {"document_id": "doc"}})
        eventually(lambda: bool(self.client.replies))
        params = next(p for method, p in self.client.calls if method == "turn/steer")
        self.assertEqual(params["expectedTurnId"], "turn-1")
        self.assertEqual(params["input"][1], {"type": "image", "url": "data:image/png;base64,fixture"})
        response = self.client.replies[-1][1]
        self.assertTrue(response["success"])
        self.assertNotIn("base64", json.dumps(response))
        self.assertTrue(json.loads(response["contentItems"][0]["text"])["imageDelivered"])
        self.assertEqual(conversation_messages({"turns": [{"items": [{"type": "userMessage", "id": "capture", "content": params["input"]}]}]}), [])

    def test_failed_image_delivery_does_not_claim_visual_verification(self):
        self.controller.dispatch("send", {"text": "Check the model"})
        eventually(lambda: self.controller.turn_id is not None)
        self.client.fail_method = "turn/steer"
        results = []
        self.controller._deliver_image({"client": self.client, "threadId": "thread-1", "turnId": "turn-1",
            "imageUrl": "data:image/png;base64,fixture", "result": {"ok": True}, "complete": results.append, "cancelled": lambda: False})
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["errorCode"], "image_delivery_failed")
        self.assertTrue(self.controller.snapshot()["busy"])


if __name__ == "__main__":
    unittest.main()
