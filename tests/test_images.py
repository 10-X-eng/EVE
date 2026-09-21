import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.images import ImageStore, validate_images, MAX_IMAGE_BYTES, MAX_STORED_IMAGE_BYTES
from steve.controller import Controller, conversation_messages, message_input, VIEWPORT_PREFIX, SAVED_IMAGE_PREFIX
from steve.tool_protocol import validate_call
from steve.debug_log import DebugLog
from test_core import FakeClient, eventually

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII="


class ImageTests(unittest.TestCase):
    def test_chat_catalog_survives_restart_and_rejects_other_chats(self):
        home = ROOT / ".cache/image-tests" / str(uuid4())
        store = ImageStore(home)
        images = validate_images([{"url": PNG, "name": "Original bracket"}])
        entry = store.record("chat-a", "turn-a", images, message="Make this bracket")[0]
        reopened = ImageStore(home)
        listing = reopened.list_chat("chat-a")
        self.assertEqual(listing["images"][0]["name"], "Original bracket")
        self.assertEqual(listing["images"][0]["message"], "Make this bracket")
        self.assertEqual(reopened.read_chat("chat-a", entry["imageId"])[1], PNG)
        with self.assertRaises(KeyError):
            reopened.read_chat("chat-b", entry["imageId"])
        self.assertNotIn("base64", json.dumps(listing))
        self.assertNotIn("assetId", json.dumps(listing))

    def test_catalog_pages_and_deduplicates_pixels_without_losing_revisions(self):
        store = ImageStore(ROOT / ".cache/image-tests" / str(uuid4()))
        images = validate_images([{"url": PNG}])
        for index in range(23):
            store.record("chat", f"turn-{index}", images, source="viewport")
        store.record("chat", "turn-22", images, source="viewport")
        first = store.list_chat("chat")
        self.assertEqual((first["returned"], first["total"], first["nextOffset"]), (20, 23, 20))
        second = store.list_chat("chat", offset=20)
        self.assertEqual(second["returned"], 3)
        self.assertIsNone(second["nextOffset"])
        self.assertTrue(all(entry["historical"] for entry in first["images"]))
        self.assertEqual(len(list(store.folder.glob("*.png"))), 1)

    def test_missing_or_modified_pixels_are_not_shown_and_reattaching_repairs_cache(self):
        store = ImageStore(ROOT / ".cache/image-tests" / str(uuid4()))
        images = validate_images([{"url": PNG}])
        entry = store.record("chat", "turn", images)[0]
        path = store.folder / (images[0]["id"] + ".png")
        path.write_bytes(b"wrong bytes")
        with self.assertRaises(FileNotFoundError):
            store.read_chat("chat", entry["imageId"])
        store.record("chat", "turn", images)
        self.assertEqual(store.read_chat("chat", entry["imageId"])[1], PNG)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            store.read_chat("chat", entry["imageId"])

    def test_capture_size_limit_does_not_expand_user_attachment_limit(self):
        data = base64.b64decode(PNG.split(",")[1]) + b"x" * MAX_IMAGE_BYTES
        url = "data:image/png;base64," + base64.b64encode(data).decode()
        with self.assertRaises(ValueError):
            validate_images([{"url": url}])
        capture = validate_images([{"url": url}], max_bytes=MAX_STORED_IMAGE_BYTES)
        store = ImageStore(ROOT / ".cache/image-tests" / str(uuid4()))
        entry = store.record("chat", "turn", capture, source="viewport")[0]
        self.assertEqual(store.read_chat("chat", entry["imageId"])[1], url)

    def test_image_tool_arguments_are_bounded_and_chat_scope_cannot_be_overridden(self):
        validate_call("list_chat_images", {})
        validate_call("view_chat_image", {"image_id": "a" * 64})
        for args in ({"limit": 21}, {"offset": -1}, {"offset": True}, {"thread_id": "other"}):
            with self.assertRaises(ValueError):
                validate_call("list_chat_images", args)
        for args in ({"image_id": "../picture"}, {"image_id": "a" * 64, "thread_id": "other"}):
            with self.assertRaises(ValueError):
                validate_call("view_chat_image", args)

    def test_validation_rejects_remote_executable_invalid_and_excessive_inputs(self):
        for value in ("https://example.com/image.png", (ROOT / "fixture.png").as_uri(), "data:image/svg+xml;base64,PHN2Zz4=",
                      "data:image/png;base64,broken!", "data:image/png;base64," + base64.b64encode(b"not png").decode(),
                      "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES).decode()):
            with self.subTest(value=value[:60]), self.assertRaises(ValueError):
                validate_images([{"url": value}])
        with self.assertRaises(ValueError):
            validate_images([{"url": PNG}] * 5)

    def test_durable_store_and_history_keep_pixels_out_of_messages(self):
        store = ImageStore(ROOT / ".cache/image-tests" / str(uuid4()))
        image = validate_images([{"name": "Reference", "url": PNG}])[0]
        ref = store.remember(image)
        self.assertEqual(store.read(ref["id"]), PNG)
        self.assertIsNone(store.read("../../outside"))
        self.assertEqual(ImageStore(store.folder.parent).read(ref["id"]), PNG)
        content = message_input("Make this", {"selectionCount": 1}, [image])
        messages = conversation_messages({"turns": [{"items": [{"id": "msg", "type": "userMessage", "content": content}]}]}, store)
        self.assertEqual(messages[0]["text"], "Make this")
        self.assertEqual(messages[0]["images"][0]["id"], ref["id"])
        self.assertNotIn("base64", json.dumps(messages))
        content[0]["text"] = VIEWPORT_PREFIX
        self.assertEqual(conversation_messages({"turns": [{"items": [{"id": "capture", "type": "userMessage", "content": content}]}]}, store), [])


class ImageControllerTests(unittest.TestCase):
    def tool_call(self, tool, arguments):
        previous = len(self.client.replies)
        self.client.on_request("lookup", "item/tool/call", {"threadId": "thread-1", "turnId": "turn-1",
            "tool": tool, "arguments": arguments})
        eventually(lambda: len(self.client.replies) > previous)
        return json.loads(self.client.replies[-1][1]["contentItems"][0]["text"])

    def setUp(self):
        self.controller = Controller(lambda state: None, transport_factory=FakeClient,
            debug_log=DebugLog(ROOT / ".cache/image-controller-tests" / str(uuid4())))
        self.controller.dispatch("connect")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(2)

    def test_image_only_send_and_steering_use_native_input_and_separate_previews(self):
        self.controller.dispatch("send", {"images": [{"url": PNG, "name": "Bracket"}]})
        eventually(lambda: self.controller.turn_id is not None)
        first = next(params for method, params in self.client.calls if method == "turn/start")
        self.assertEqual(first["input"], [{"type": "image", "url": PNG}])
        snapshot = self.controller.snapshot()
        self.assertNotIn("base64", json.dumps(snapshot))
        ref = snapshot["messages"][0]["images"][0]
        self.assertEqual(self.controller.image_assets([ref["id"]]), {ref["id"]: PNG})
        self.assertEqual(self.controller.image_assets(["a" * 64]), {})
        with self.assertRaises(ValueError):
            self.controller.image_assets([ref["id"]] * 5)
        self.controller.dispatch("steer", {"text": "Use this profile", "images": [{"url": PNG}],
                                           "threadId": "thread-1", "turnId": "turn-1"})
        eventually(lambda: any(method == "turn/steer" for method, params in self.client.calls))
        update = next(params for method, params in self.client.calls if method == "turn/steer")
        self.assertEqual(update["input"][1], {"type": "image", "url": PNG})
        self.assertTrue(self.controller.snapshot()["busy"])

    def test_invalid_image_rejected_before_context_capture_without_stopping_turn(self):
        self.controller.dispatch("send", {"text": "Start"})
        eventually(lambda: self.controller.turn_id is not None)
        captured = []
        with self.assertRaises(ValueError):
            self.controller.dispatch("steer", {"images": [{"url": "https://example.com/private.png"}]},
                                     capture_context=lambda action: captured.append(action))
        self.assertTrue(self.controller.snapshot()["busy"])
        self.assertFalse(captured)

    def test_failed_send_keeps_image_reference_for_explicit_retry(self):
        self.client.fail_method = "turn/start"
        self.controller.dispatch("send", {"images": [{"url": PNG}]})
        eventually(lambda: bool(self.controller.snapshot()["error"]))
        message = self.controller.snapshot()["messages"][-1]
        self.assertEqual(message["delivery"], "failed")
        self.assertEqual(self.controller.image_assets([message["images"][0]["id"]])[message["images"][0]["id"]], PNG)
        self.assertEqual(self.controller.images.list_chat("thread-1")["total"], 0)

    def test_list_and_view_reinject_pixels_only_on_request_without_fusion_calls(self):
        self.controller.dispatch("send", {"text": "Use this bracket", "images": [{"url": PNG, "name": "Bracket"}]})
        # Wait for the worker to finish its atomic index replacement before reading on Windows.
        eventually(lambda: not self.controller._send_queued and self.controller.images.list_chat("thread-1")["total"] == 1)
        result = self.tool_call("list_chat_images", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["images"][0]["message"], "Use this bracket")
        self.assertFalse(any(method == "turn/steer" for method, _ in self.client.calls))
        result = self.tool_call("view_chat_image", {"image_id": result["images"][0]["imageId"]})
        self.assertTrue(result["imageDelivered"])
        params = next(params for method, params in self.client.calls if method == "turn/steer")
        self.assertEqual(params["expectedTurnId"], "turn-1")
        self.assertTrue(params["input"][0]["text"].startswith(SAVED_IMAGE_PREFIX))
        self.assertEqual(params["input"][1]["url"], PNG)
        self.assertEqual(self.controller.images.list_chat("thread-1")["total"], 1)
        self.assertNotIn("base64", json.dumps(self.client.replies))
        self.assertEqual(conversation_messages({"turns": [{"items": [{"type": "userMessage", "content": params["input"]}]}]}), [])

    def test_view_rejects_foreign_image_and_reports_failed_delivery(self):
        foreign = self.controller.images.record("other-chat", "turn", validate_images([{"url": PNG}]))[0]
        self.controller.dispatch("send", {"images": [{"url": PNG}]})
        # Wait for the worker to finish its atomic index replacement before reading on Windows.
        eventually(lambda: not self.controller._send_queued and self.controller.images.list_chat("thread-1")["total"] == 1)
        result = self.tool_call("view_chat_image", {"image_id": foreign["imageId"]})
        self.assertEqual(result["errorCode"], "chat_image_not_found")
        own = self.controller.images.list_chat("thread-1")["images"][0]
        self.client.fail_method = "turn/steer"
        result = self.tool_call("view_chat_image", {"image_id": own["imageId"]})
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("imageDelivered"))
        self.assertEqual(result["errorCode"], "chat_image_delivery_failed")

    def test_reopened_chat_can_retrieve_pixels_after_controller_restart(self):
        self.controller.dispatch("send", {"images": [{"url": PNG, "name": "First screenshot"}]})
        # Wait for the worker to finish its atomic index replacement before reading on Windows.
        eventually(lambda: not self.controller._send_queued and self.controller.images.list_chat("thread-1")["total"] == 1)
        home = self.controller.images.folder.parent
        self.controller.close()
        self.controller._worker.join(2)
        self.controller = Controller(lambda state: None, transport_factory=FakeClient, debug_log=DebugLog(home))
        self.controller.dispatch("connect")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client
        self.client.saved_thread = {"id": "thread-1", "turns": []}
        self.client.history = [{"id": "thread-1", "preview": "Reference chat"}]
        self.controller.dispatch("history")
        eventually(lambda: bool(self.controller.snapshot()["history"]))
        self.controller.dispatch("openHistory", {"threadId": "thread-1"})
        eventually(lambda: self.controller.thread_id == "thread-1")
        self.controller.dispatch("send", {"text": "Look at the first screenshot again"})
        eventually(lambda: self.controller.turn_id is not None)
        listed = self.tool_call("list_chat_images", {})
        self.assertEqual(listed["images"][0]["name"], "First screenshot")
        viewed = self.tool_call("view_chat_image", {"image_id": listed["images"][0]["imageId"]})
        self.assertTrue(viewed["imageDelivered"])
        self.assertFalse(any(method == "thread/start" for method, _ in self.client.calls))

    def test_cancelled_view_does_not_deliver_pixels(self):
        self.controller.dispatch("send", {"images": [{"url": PNG}]})
        # Wait for the worker to finish its atomic index replacement before reading on Windows.
        eventually(lambda: not self.controller._send_queued and self.controller.images.list_chat("thread-1")["total"] == 1)
        own = self.controller.images.list_chat("thread-1")["images"][0]
        self.controller._cancel = True
        result = self.tool_call("view_chat_image", {"image_id": own["imageId"]})
        self.assertEqual(result["errorCode"], "inactive_request")
        self.assertFalse(any(method == "turn/steer" for method, _ in self.client.calls))

    def test_viewport_is_cached_with_history_label_and_document(self):
        class Runner:
            def submit(runner, tool, arguments, complete, cancelled):
                complete({"ok": True, "imageUrl": PNG, "width": 1, "height": 1})
        self.controller.fusion_tools = Runner()
        self.controller.dispatch("send", {"text": "Check the model", "fusionContext": {"document_id": "doc", "name": "Bracket"}})
        eventually(lambda: self.controller.turn_id is not None)
        result = self.tool_call("fusion_capture_viewport", {"document_id": "doc"})
        self.assertTrue(result["imageDelivered"])
        entry = self.controller.images.list_chat("thread-1")["images"][0]
        self.assertEqual(entry["source"], "viewport")
        self.assertTrue(entry["historical"])
        self.assertEqual(entry["document"]["name"], "Bracket")
        self.assertEqual(entry["imageId"], result["imageId"])
        viewed = self.tool_call("view_chat_image", {"image_id": entry["imageId"]})
        self.assertTrue(viewed["historical"])

    def test_cache_failure_after_send_does_not_mark_delivery_failed_or_repeat_turn(self):
        with patch.object(self.controller.images, "record", side_effect=OSError("disk full")):
            self.controller.dispatch("send", {"images": [{"url": PNG}]})
            eventually(lambda: "could not save" in self.controller.snapshot()["error"])
        self.assertEqual(self.controller.snapshot()["messages"][0]["delivery"], "sent")
        self.assertEqual(sum(method == "turn/start" for method, _ in self.client.calls), 1)


if __name__ == "__main__":
    unittest.main()
