"""Goal lifecycle at STEVE's controller boundary, including automatic turns."""
import copy
import unittest
from uuid import uuid4

from test_core import FakeClient, ROOT, eventually
from steve.controller import Controller, thread_start_params, CONTEXT_PREFIX
from steve.debug_log import DebugLog
from steve.goals import goal_command, validate_goal


class GoalClient(FakeClient):
    def __init__(self, notify):
        super().__init__(notify)
        self.goal = None
        self.turn_number = 0

    def start_goal_turn(self):
        self.turn_number += 1
        self.notify("turn/started", {"threadId": "thread-1", "turn": {"id": f"goal-turn-{self.turn_number}"}})

    def complete(self, status="completed"):
        self.notify("turn/completed", {"threadId": "thread-1", "turn": {
            "id": f"goal-turn-{self.turn_number}", "status": status}})

    def request(self, method, params=None, **kwargs):
        if not method.startswith("thread/goal/"):
            return super().request(method, params, **kwargs)
        self.calls.append((method, copy.deepcopy(params)))
        if method == self.fail_method:
            raise RuntimeError("Goal service unavailable")
        if method == "thread/goal/get":
            return {"goal": copy.deepcopy(self.goal)}
        if method == "thread/goal/clear":
            self.goal = None
            self.notify("thread/goal/cleared", {"threadId": params["threadId"]})
            return {}
        if "objective" in params:
            self.goal = {"threadId": params["threadId"], "objective": params["objective"],
                         "status": "paused", "tokensUsed": 0, "timeUsedSeconds": 0, "tokenBudget": None}
        self.goal.update({k: v for k, v in params.items() if k in ("status", "tokenBudget")})
        result = copy.deepcopy(self.goal)
        self.notify("thread/goal/updated", {"threadId": params["threadId"], "goal": copy.deepcopy(self.goal)})
        if self.goal["status"] == "active":
            self.start_goal_turn()
        return {"goal": result}


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller(lambda s: None, transport_factory=GoalClient,
            debug_log=DebugLog(ROOT / ".cache" / "goal-tests" / str(uuid4())))
        self.controller.dispatch("connect")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client
        self.captures = []

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(2)

    def capture(self, action):
        self.captures.append(action)
        return {"document_id": "doc-a", "name": "Bracket", "task_key": "binding-a", "selectionCount": 2}

    def create(self):
        self.controller.dispatch("send", {"text": "/goal Make a bracket and verify its dimensions"}, capture_context=self.capture)
        eventually(lambda: self.controller.turn_id == "goal-turn-1" and not self.controller.state["goalBusy"])

    def test_commands_and_validation(self):
        for word in ("pause", "resume", "clear", "edit", "help", "status"):
            self.assertEqual(goal_command("/goal " + word), {"command": word})
        self.assertEqual(goal_command("/goal"), {"command": "status"})
        self.assertEqual(goal_command("/goal edit Revised goal"), {"command": "set", "objective": "Revised goal"})
        self.assertIsNone(goal_command("Explain /goal"))
        self.assertIsNone(goal_command("/goalkeeper"))
        for invalid in ("", "x" * 4001):
            with self.assertRaises(ValueError):
                validate_goal({"command": "set", "objective": invalid})
        for budget in (0, -1, True, "200", 1.5, 2**53):
            with self.assertRaises(ValueError):
                validate_goal({"command": "resume", "tokenBudget": budget})
        self.assertTrue(thread_start_params(ROOT)["config"]["features.goals"])

    def test_creation_injects_context_before_activation_and_continues_on_original_target(self):
        self.create()
        methods = [m for m, _ in self.client.calls]
        self.assertNotIn("turn/start", methods)  # Codex starts the goal turn itself.
        injection = next(p for m, p in self.client.calls if m == "thread/inject_items")
        self.assertTrue(injection["items"][0]["content"][1]["text"].startswith(CONTEXT_PREFIX))
        self.assertEqual(self.captures, ["send"])
        self.assertEqual(self.controller.state["taskDocument"]["id"], "doc-a")
        self.client.complete()
        self.assertTrue(self.controller.state["busy"])
        self.assertFalse(self.controller.snapshot()["canSteer"])
        self.client.start_goal_turn()
        self.assertTrue(self.controller.snapshot()["canSteer"])
        self.assertEqual(self.controller.state["taskDocument"]["id"], "doc-a")
        calls = []
        class Fusion:
            def submit(self, tool, args, complete, cancelled):
                calls.append(cancelled())
                complete({"ok": True})
        self.controller.fusion_tools = Fusion()
        self.client.on_request("inspect", "item/tool/call", {"threadId": "thread-1", "turnId": "goal-turn-2",
            "tool": "fusion_inspect_document", "arguments": {}})
        self.assertEqual(calls, [False])

    def test_pause_resume_clear_and_stop_use_native_goal_state(self):
        self.create()
        self.controller.dispatch("steer", {"text": "/goal pause"})
        eventually(lambda: not self.controller.state["goalBusy"] and not self.controller.state["busy"])
        self.assertEqual(self.client.goal["status"], "paused")
        self.assertLess(next(i for i, (m,p) in enumerate(self.client.calls) if m == "thread/goal/set" and p.get("status") == "paused"),
                        next(i for i, (m,_) in enumerate(self.client.calls) if m == "turn/interrupt"))
        self.controller.dispatch("goal", {"command": "resume", "tokenBudget": 1000}, capture_context=self.capture)
        eventually(lambda: self.controller.turn_id == "goal-turn-2" and not self.controller.state["goalBusy"])
        self.assertEqual(self.captures[-1], "resume:binding-a")
        self.assertEqual(self.client.goal["tokenBudget"], 1000)
        self.controller.dispatch("stop")
        eventually(lambda: self.client.goal["status"] == "paused" and not self.controller.state["busy"])
        messages = copy.deepcopy(self.controller.state["messages"])
        self.controller.dispatch("goal", {"command": "clear"})
        eventually(lambda: self.controller.state["goal"] is None and not self.controller.state["goalBusy"])
        self.assertEqual(messages, self.controller.state["messages"])

    def test_stop_between_turns_and_stale_notifications_cannot_restart_work(self):
        self.create()
        self.client.complete()
        self.controller.dispatch("stop")
        self.client.start_goal_turn()  # A continuation was already queued at the runtime.
        eventually(lambda: self.client.goal["status"] == "paused" and not self.controller.state["busy"])
        goal = copy.deepcopy(self.controller.state["goal"])
        self.client.notify("thread/goal/cleared", {"threadId": "another-thread"})
        self.assertEqual(self.controller.state["goal"], goal)

    def test_stop_during_goal_startup_never_activates_it(self):
        self.client.block_thread = True
        self.controller.dispatch("goal", {"command": "set", "objective": "Build a fixture"}, capture_context=self.capture)
        self.assertTrue(self.client.entered_thread.wait(1))
        self.controller.dispatch("stop")
        self.client.release_thread.set()
        eventually(lambda: not self.controller.state["goalBusy"] and self.controller.state["goal"] is not None)
        self.assertEqual(self.client.goal["status"], "paused")
        self.assertFalse(any(m == "thread/goal/set" and p.get("status") == "active" for m, p in self.client.calls))

    def test_paused_goal_pin_is_not_overwritten_by_a_different_chat_context(self):
        self.create()
        self.controller.dispatch("goal", {"command": "pause"})
        eventually(lambda: not self.controller.state["goalBusy"] and not self.controller.state["busy"])
        self.controller._task_context = {"document_id": "doc-b", "name": "Other", "task_key": "binding-b"}
        self.client.notify("thread/goal/updated", {"threadId": "thread-1", "goal": copy.deepcopy(self.client.goal)})
        self.controller.dispatch("goal", {"command": "resume"}, capture_context=self.capture)
        eventually(lambda: not self.controller.state["goalBusy"] and self.controller.state["busy"])
        self.assertEqual(self.captures[-1], "resume:binding-a")

    def test_goal_rpc_failure_does_not_end_running_turn_and_pause_still_interrupts(self):
        self.create()
        self.client.fail_method = "thread/goal/get"
        self.controller.dispatch("goal", {"command": "status"})
        eventually(lambda: not self.controller.state["goalBusy"])
        self.assertTrue(self.controller.state["busy"])
        self.client.fail_method = "thread/goal/set"
        self.controller.dispatch("goal", {"command": "pause"})
        eventually(lambda: not self.controller.state["goalBusy"] and not self.controller.state["busy"])
        self.assertTrue(self.controller._cancel)

    def test_clear_without_a_goal_does_not_stop_an_ordinary_chat(self):
        self.controller.dispatch("send", {"text": "Explain a sketch"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("goal", {"command": "clear"})
        eventually(lambda: not self.controller.state["goalBusy"])
        self.assertFalse(self.controller._cancel)
        self.assertTrue(self.controller.state["busy"])
        self.assertFalse(any(m == "turn/interrupt" for m, _ in self.client.calls))

    def test_history_pauses_saved_goal_before_resuming_thread(self):
        self.client.goal = {"threadId": "saved-thread", "objective": "Saved goal", "status": "active"}
        self.controller.state["history"] = [{"id": "saved-thread"}]
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: self.controller.thread_id == "saved-thread")
        methods = [m for m, _ in self.client.calls]
        self.assertLess(methods.index("thread/goal/set"), methods.index("thread/resume"))
        self.assertEqual(self.controller.state["goal"]["status"], "paused")
        self.assertFalse(self.controller.state["goalHasTarget"])


if __name__ == "__main__":
    unittest.main()
