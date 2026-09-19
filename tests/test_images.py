import base64
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/EVE"))
from eve.images import ImageStore, validate_images, MAX_IMAGE_BYTES
from eve.controller import Controller, conversation_messages, message_input, VIEWPORT_PREFIX
from eve.debug_log import DebugLog
from test_core import FakeClient, eventually

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII="


class ImageTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
