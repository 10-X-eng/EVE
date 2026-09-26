import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.update_transaction import MARKER, Transaction, prepare, verify_payload


class UpdateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'AddIns/STEVE'
        self.target.mkdir(parents=True)
        (self.target / 'steve-install-marker.txt').write_text(MARKER)
        (self.target / 'STEVE.py').write_text('old version')
        self.package = self.root / 'package'
        payload = self.package / 'STEVE'
        payload.mkdir(parents=True)
        (payload / 'STEVE.py').write_text('new version')
        (payload / 'STEVE.manifest').write_text(json.dumps({'version': '0.7.0'}))
        self.sums = '\n'.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name for p in sorted(payload.iterdir()))
        (self.package / 'SHA256SUMS').write_text(self.sums)
        self.home = self.root / 'home'

    def prepare(self):
        helper = prepare(self.package, self.target, self.home, '0.7.0')
        return Transaction(helper / 'request.json')

    def test_prepare_never_touches_live_files_and_helper_is_independent(self):
        transaction = self.prepare()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')
        self.assertFalse(transaction.path.is_relative_to(self.target))
        self.assertTrue((transaction.path.parent / 'STEVEUpdater.py').is_file())
        self.assertEqual(transaction.data['phase'], 'prepared')

    def test_swap_and_rollback_preserve_both_versions(self):
        transaction = self.prepare()
        transaction.activate()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'new version')
        self.assertEqual((transaction.backup / 'STEVE.py').read_text(), 'old version')
        transaction.rollback()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')
        self.assertEqual((transaction.failed / 'STEVE.py').read_text(), 'new version')
        self.assertEqual(transaction.data['phase'], 'rolled_back')

    def test_changed_prepared_payload_cannot_replace_installation(self):
        transaction = self.prepare()
        (transaction.prepared / 'STEVE.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            transaction.activate()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')

    def test_failed_second_rename_restores_previous_installation(self):
        transaction = self.prepare()
        rename = Path.rename
        def fail(path, destination):
            if path == transaction.prepared:
                raise PermissionError('locked fixture')
            return rename(path, destination)
        with patch.object(Path, 'rename', fail), self.assertRaises(PermissionError):
            transaction.activate()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')

    def test_crash_between_renames_can_be_recovered_from_journal(self):
        transaction = self.prepare()
        transaction.state('swapping')
        self.target.rename(transaction.backup)
        restored = Transaction(transaction.path)
        restored.rollback()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')

    def test_unmanaged_installation_is_never_updated(self):
        (self.target / 'steve-install-marker.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'managed'):
            self.prepare()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')

    def test_checksum_paths_and_extra_files_rejected(self):
        for name in ('../outside', '/outside', 'C' + ':/outside', 'x/../outside', 'x\\outside'):
            with self.assertRaises(ValueError):
                verify_payload(self.package / 'STEVE', 'a' * 64 + '  ' + name)
        (self.package / 'STEVE/unexpected.py').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'file list'):
            self.prepare()

    def test_journal_cannot_redirect_backup_outside_install_parent(self):
        transaction = self.prepare()
        transaction.data['backup'] = str(self.root / '.STEVE-previous-outside')
        transaction.state('prepared')
        with self.assertRaisesRegex(ValueError, 'destination'):
            Transaction(transaction.path)

    def test_helper_restarts_unchanged_target_after_pre_swap_failure(self):
        transaction = self.prepare()
        core = types.ModuleType('adsk.core')
        core.CustomEventHandler = object
        adsk = types.ModuleType('adsk')
        adsk.core = core
        spec = importlib.util.spec_from_file_location('steve._helper_fixture', transaction.path.parent / 'STEVEUpdater.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'adsk': adsk, 'adsk.core': core,
                                    'steve.transaction': sys.modules['steve.update_transaction']}):
            spec.loader.exec_module(module)
        target = Mock(isRunning=False)
        own = Mock()
        module._app = Mock()
        module._app.scripts.itemByPath.side_effect = lambda path: target if path == str(transaction.target) else own
        module._transaction = transaction
        module._phase = 'recover'
        module._error = 'Checksum mismatch'
        module.Tick().notify(None)
        target.run.assert_called_once_with(False)
        target.stop.assert_not_called()
        own.unlink.assert_called_once()
        self.assertEqual((self.target / 'STEVE.py').read_text(), 'old version')

    def test_preparing_retry_clears_stale_failure_receipt(self):
        (self.package / 'install-result.txt').write_text('Installation failed: old attempt')
        self.prepare()
        self.assertFalse((self.package / 'install-result.txt').read_text().startswith('Installation failed:'))

    def test_gallery_permissions_and_chat_images_survive_activation_and_rollback(self):
        from steve.images import ImageStore
        from steve.gallery import Gallery
        from test_gallery import picture
        images = ImageStore(self.home)
        images.record('old-chat', 'turn', [picture(0), picture(1)])
        gallery = Gallery(images)
        gallery.migrate()
        gallery.change(picture(0)['id'], enabled=True)
        gallery.change(picture(1)['id'], remove=True)
        preserved = {p: p.read_bytes() for p in images.folder.rglob('*') if p.is_file()}
        transaction = self.prepare()
        transaction.activate()
        reopened = Gallery(ImageStore(self.home))
        self.assertEqual(reopened.list(enabled_only=True)['total'], 1)
        transaction.rollback()
        self.assertEqual(Gallery(ImageStore(self.home)).list()['total'], 1)
        for path, raw in preserved.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(len(images.list_chat('old-chat')['images']), 2)
