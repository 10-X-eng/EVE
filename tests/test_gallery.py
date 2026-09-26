"""Migration preserves cached bytes/chat indexes and never grants access by discovery."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_images import PNG
import test_images
from test_core import eventually
from steve.images import ImageStore, validate_images
from steve.gallery import Gallery
from steve.tool_protocol import validate_call


def picture(number=0, name='Reference'):
    data = base64.b64decode(PNG.split(',')[1]) + str(number).encode()
    return validate_images([{'name': name, 'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}])[0]


class GalleryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ImageStore(self.temp.name)
        self.gallery = Gallery(self.store)

    def test_all_sources_and_orphan_images_migrate_without_moving_or_changing_history(self):
        for i, source in enumerate(['attachment', 'viewport', 'generated']):
            self.store.record('chat-' + str(i), 'turn', [picture(i, source)], source=source)
        self.store.record('another-chat', 'turn', [picture(0, 'attachment')], source='attachment')
        self.store.remember(picture(4))  # Older versions may have no chat index.
        before = {p: p.read_bytes() for p in self.store.folder.rglob('*') if p.is_file()}
        result = self.gallery.list()
        self.assertEqual(result['total'], 4)
        self.assertEqual(result['migration']['added'], 4)
        self.assertTrue(all(not image['enabled'] for image in result['images']))
        self.assertEqual(self.gallery.list(enabled_only=True)['total'], 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(len(list(self.store.folder.glob('*.png'))), 4)
        for i in range(3):
            entry = self.store.list_chat('chat-' + str(i))['images'][0]
            self.assertEqual(self.store.read_chat('chat-' + str(i), entry['imageId'])[1], picture(i)['url'])
        self.assertTrue({'attachment', 'viewport', 'generated'} <= {r['name'] for r in result['images']})

    def test_repeated_migration_preserves_renames_access_and_removed_tombstones(self):
        self.store.remember(picture())
        identifier = self.gallery.list()['images'][0]['imageId']
        self.gallery.change(identifier, name='Named bracket', enabled=True)
        restarted = Gallery(ImageStore(self.temp.name))
        self.assertEqual(restarted.migrate()['added'], 0)
        self.assertEqual(restarted.list(enabled_only=True)['images'][0]['name'], 'Named bracket')
        restarted.change(identifier, remove=True)
        self.assertEqual(self.gallery.list()['total'], 0)
        with self.assertRaises(ValueError):
            self.gallery.read(identifier, enabled_only=True)
        self.assertEqual(self.store.read(identifier), picture()['url'])
        self.gallery.import_images([picture()])
        self.assertEqual(self.gallery.list()['total'], 1)
        self.assertEqual(self.gallery.list(enabled_only=True)['total'], 0)

    def test_corrupt_oversized_unindexed_and_missing_files_do_not_destroy_valid_images(self):
        good = picture(1, 'Good')
        self.store.record('chat', 'turn', [good])
        for i in [2, 3, 4]:
            self.store.record('broken-' + str(i), 'turn', [picture(i)])
        (self.store.folder / (picture(2)['id'] + '.png')).write_bytes(b'corrupted')
        (self.store.folder / (picture(3)['id'] + '.png')).write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        (self.store.folder / (picture(4)['id'] + '.png')).unlink()
        (self.store.folder / 'chats' / 'bad.json').write_text('{broken')
        (self.store.folder / 'chats' / 'oversized.json').write_bytes(b' ' * (4 * 1024 * 1024 + 1))
        (self.store.folder / 'not-an-image.png').write_text('not imported')
        result = self.gallery.list()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['migration']['unavailable'], 2)
        self.assertEqual(result['migration']['unreadableChatIndexes'], 2)
        self.assertEqual(self.gallery.read(good['id'])[1], good['url'])
        self.assertTrue((self.store.folder / 'not-an-image.png').exists())

    def test_interrupted_index_write_can_retry_without_losing_existing_access(self):
        self.gallery.import_images([picture(1)])
        self.gallery.change(picture(1)['id'], enabled=True)
        before = self.gallery.path.read_bytes()
        self.store.remember(picture(2))
        with patch.object(Path, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.gallery.migrate()
        self.assertEqual(self.gallery.path.read_bytes(), before)
        self.assertFalse(list(self.store.folder.glob('.gallery-*.tmp')))
        self.assertEqual(self.gallery.migrate()['added'], 1)
        self.assertEqual(self.gallery.list(enabled_only=True)['total'], 1)

    def test_corrupt_gallery_index_fails_closed_and_is_not_overwritten(self):
        self.gallery.import_images([picture()])
        self.gallery.path.write_text('{broken')
        with self.assertRaises(ValueError):
            self.gallery.list(enabled_only=True)
        with self.assertRaises(ValueError):
            self.gallery.import_images([picture(1)])
        self.assertEqual(self.gallery.path.read_text(), '{broken')

    def test_paging_search_revocation_and_independent_instances_read_fresh_permissions(self):
        for i in range(25):
            self.store.remember(picture(i, 'Plate ' + str(i)))
        self.assertEqual(self.gallery.list()['nextOffset'], 20)
        self.assertEqual(len(self.gallery.list(offset=20)['images']), 5)
        identifier = picture(0)['id']
        self.gallery.change(identifier, name='Bracket', enabled=True)
        other = Gallery(ImageStore(self.temp.name))
        self.assertEqual(other.list(query='BRACKET', enabled_only=True)['total'], 1)
        self.gallery.change(identifier, enabled=False)
        with self.assertRaises(ValueError):
            other.read(identifier, enabled_only=True)
        self.assertEqual(other.list(enabled_only=True)['total'], 0)
        with self.assertRaises(ValueError):
            other.read('../outside')
        self.assertNotIn('base64', json.dumps(other.list()))

    def test_import_deduplicates_and_does_not_reset_existing_enabled_state(self):
        self.gallery.import_images([picture(0, 'First')])
        self.gallery.change(picture()['id'], enabled=True)
        self.gallery.import_images([picture(0, 'Second')])
        rows = self.gallery.list()['images']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'First')
        self.assertTrue(rows[0]['enabled'])

    def test_tool_schema_does_not_allow_the_model_to_enable_or_manage_images(self):
        validate_call('list_gallery_images', {'query': 'bracket', 'limit': 5})
        validate_call('view_gallery_image', {'image_id': picture()['id']})
        for tool, arguments in [('list_gallery_images', {'enabled_only': False}),
                                ('view_gallery_image', {'image_id': picture()['id'], 'enabled': True}),
                                ('list_gallery_images', {'query': 'x' * 161}),
                                ('list_gallery_images', {'limit': 1000})]:
            with self.assertRaises(ValueError):
                validate_call(tool, arguments)


class GalleryControllerTests(unittest.TestCase):
    setUp = test_images.ImageControllerTests.setUp
    tearDown = test_images.ImageControllerTests.tearDown
    tool_call = test_images.ImageControllerTests.tool_call

    def test_only_enabled_images_cross_chats_and_native_delivery_rechecks_access(self):
        self.controller.images.record('old-chat', 'turn', [picture(0, 'Old chat picture')])
        self.controller.dispatch('send', {'text': 'Use the gallery'})
        eventually(lambda: self.controller.turn_id is not None)
        self.assertEqual(self.tool_call('list_gallery_images', {})['total'], 0)
        identifier = picture()['id']
        self.controller.gallery_request({'action': 'change', 'imageId': identifier, 'enabled': True})
        listed = self.tool_call('list_gallery_images', {})
        self.assertEqual(listed['images'][0]['imageId'], identifier)
        viewed = self.tool_call('view_gallery_image', {'image_id': identifier})
        self.assertTrue(viewed['imageDelivered'])
        native = [p for method, p in self.client.calls if method == 'turn/steer']
        self.assertEqual(native[-1]['input'][1]['url'], picture()['url'])
        self.assertEqual(native[-1]['expectedTurnId'], 'turn-1')
        self.controller.gallery.change(identifier, enabled=False)
        denied = self.tool_call('view_gallery_image', {'image_id': identifier})
        self.assertFalse(denied['ok'])
        self.assertEqual(len([p for method, p in self.client.calls if method == 'turn/steer']), len(native))
        self.assertNotIn('base64', json.dumps(self.controller.snapshot()))
        self.assertNotIn('base64', json.dumps(self.client.replies))

    def test_text_only_model_cannot_receive_gallery_pixels(self):
        self.controller.gallery.import_images([picture()])
        self.controller.gallery.change(picture()['id'], enabled=True)
        self.controller.dispatch('send', {'text': 'Read gallery'})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.state['models'][0]['supportsImages'] = False
        self.controller.state['model'] = self.controller.state['models'][0]['id']
        result = self.tool_call('view_gallery_image', {'image_id': picture()['id']})
        self.assertFalse(result['ok'])
        self.assertFalse(any(m == 'turn/steer' for m, _ in self.client.calls))
