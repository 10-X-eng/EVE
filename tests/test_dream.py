import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'addin/STEVE'))
from steve.controller import Controller, conversation_messages, thread_start_params
from steve.debug_log import DebugLog
from steve.images import ImageStore, validate_images, MAX_STORED_IMAGE_BYTES
from steve.dream import concept_message
from test_core import FakeClient, eventually

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII='


class DreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = ImageStore(self.home)
        self.item = {'id': 'generation-1', 'type': 'imageGeneration', 'status': 'completed',
                     'result': PNG, 'revisedPrompt': 'An enclosure with four mounting holes'}

    def test_chatgpt_enables_native_generation_only_and_keeps_sandbox(self):
        for provider in ('chatgpt', 'grok', 'claude', 'ollama', 'openrouter'):
            params = thread_start_params(self.home, provider)
            self.assertEqual(params['config']['features.image_generation'], provider == 'chatgpt')
            self.assertEqual('STEVE Dream' in params['baseInstructions'], provider == 'chatgpt')
            self.assertEqual(params['sandbox'], 'read-only')
            self.assertFalse(params['config']['features.shell_tool'])

    def test_completed_image_is_visible_cached_retrievable_and_restored_without_original(self):
        message = concept_message(self.store, 'chat-a', 'turn-a', self.item)
        self.assertEqual(message['conceptStatus'], 'completed')
        self.assertNotIn('base64', json.dumps(message))
        entry = self.store.list_chat('chat-a')['images'][0]
        self.assertEqual(entry['source'], 'generated')
        self.assertEqual(self.store.read_chat('chat-a', entry['imageId'])[1], 'data:image/png;base64,' + PNG)
        with self.assertRaises(KeyError):
            self.store.read_chat('chat-b', entry['imageId'])
        restored = conversation_messages({'id': 'chat-a', 'turns': [{'id': 'turn-a',
            'items': [{**self.item, 'result': '', 'savedPath': 'missing.png'}]}]}, ImageStore(self.home))
        self.assertEqual(restored, [message])

    def test_history_recovers_only_this_threads_native_file(self):
        root = self.home / 'codex/generated_images'
        target = root / 'chat-a' / 'image.png'
        target.parent.mkdir(parents=True)
        target.write_bytes(base64.b64decode(PNG))
        item = {**self.item, 'result': '', 'savedPath': str(target)}
        wrong_chat = concept_message(self.store, 'chat-b', 'turn', item, root)
        self.assertEqual(wrong_chat['conceptStatus'], 'unavailable')
        self.assertEqual(concept_message(self.store, 'chat-a', 'turn', item, root)['conceptStatus'], 'completed')
        # A different item must not inherit the earlier generation's cache.
        outside = {**item, 'id': 'outside', 'savedPath': str(self.home / 'secret.png')}
        self.assertEqual(concept_message(self.store, 'chat-a', 'turn', outside, root)['conceptStatus'], 'unavailable')

    def test_bad_oversized_or_failed_generation_has_no_preview(self):
        for value in ('not-base64!', base64.b64encode(b'not an image').decode(),
                      'A' * (4 * ((MAX_STORED_IMAGE_BYTES + 2) // 3) + 4)):
            message = concept_message(self.store, 'chat', 'turn', {**self.item, 'result': value})
            self.assertEqual(message['conceptStatus'], 'unavailable')
            self.assertNotIn('images', message)
        failed = concept_message(self.store, 'chat', 'turn', {**self.item, 'status': 'failed',
                                 'failure': {'message': 'Usage limit reached. Try again after reset.'}})
        self.assertEqual(failed['conceptStatus'], 'failed')
        self.assertIn('Usage limit', failed['text'])
        self.assertEqual(self.store.list_chat('chat')['total'], 0)

    def test_controller_handles_native_events_exports_and_ignores_other_threads(self):
        controller = Controller(lambda state: None, transport_factory=FakeClient, debug_log=DebugLog(self.home))
        self.addCleanup(controller.close)
        controller.dispatch('connect')
        eventually(lambda: controller.snapshot()['account'])
        controller.thread_id = 'chat-a'
        controller.turn_id = 'turn-a'
        controller._notification('item/started', {'threadId': 'chat-a', 'turnId': 'turn-a',
            'item': {'id': self.item['id'], 'type': 'imageGeneration', 'status': 'in_progress'}})
        self.assertEqual(controller.snapshot()['messages'][0]['conceptStatus'], 'running')
        event = {'threadId': 'chat-a', 'turnId': 'turn-a', 'item': self.item}
        controller._notification('item/completed', event)
        eventually(lambda: controller.snapshot()['messages'][0].get('images'))
        controller._notification('item/completed', event)
        eventually(lambda: controller._commands.unfinished_tasks == 0)
        self.assertEqual(len(controller.snapshot()['messages']), 1)
        self.assertNotIn(PNG, json.dumps(controller.snapshot()))
        asset = controller.snapshot()['messages'][0]['images'][0]['id']
        with patch('steve.controller.downloads_folder', return_value=self.home / 'Downloads'):
            first = controller.save_concept(asset)
            second = controller.save_concept(asset)
        self.assertNotEqual(first, second)
        self.assertEqual((self.home / 'Downloads' / first['filename']).read_bytes(), base64.b64decode(PNG))
        with self.assertRaises(ValueError):
            controller.save_concept('a' * 64)
        controller._notification('item/completed', {**event, 'threadId': 'other'})
        self.assertEqual(len(controller.snapshot()['messages']), 1)


if __name__ == '__main__':
    unittest.main()
