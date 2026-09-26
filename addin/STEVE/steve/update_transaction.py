"""Filesystem half of an in-Fusion update. Also copied into the independent helper."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from uuid import uuid4

MARKER = 'STEVE managed installation'


def managed(folder):
    folder = Path(folder)
    marker = folder / 'steve-install-marker.txt'
    return (folder.name == 'STEVE' and not folder.is_symlink() and folder.is_dir()
            and marker.is_file() and not marker.is_symlink()
            and marker.read_text(encoding='utf-8').strip() == MARKER)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(path)


def verify_payload(folder, sums):
    """Check the complete payload, including runtime bytes, before touching installation."""
    folder = Path(folder)
    expected = {}
    for line in sums.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('Invalid package file checksum.')
        digest, name = match.groups()
        parts = PurePosixPath(name).parts
        if ('\\' in name or ':' in name or name.startswith('/') or
                any(p in ('', '.', '..') for p in name.split('/')) or name in expected):
            raise ValueError('Invalid package file path.')
        path = folder.joinpath(*parts)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('Missing or linked update file.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Update file checksum mismatch: ' + name)
        expected[name] = digest
    actual = set()
    for path in folder.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Update contains a filesystem link.')
        if path.is_file():
            actual.add(path.relative_to(folder).as_posix())
    if actual != set(expected) or not {'STEVE.py', 'STEVE.manifest'} <= actual:
        raise ValueError('Update file list does not match its checksums.')


class Transaction:
    def __init__(self, request_file):
        self.path = Path(request_file)
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        self.target = Path(self.data['target'])
        self.prepared = Path(self.data['prepared'])
        self.backup = Path(self.data['backup'])
        self.failed = Path(self.data['failed'])
        # Every rename stays inside the resolved installation parent. No paths from UI input.
        parent = self.target.parent.resolve()
        if (self.target.name != 'STEVE' or any(p.parent.resolve() != parent or p.is_symlink()
                or getattr(p, 'is_junction', lambda: False)()
                for p in (self.target, self.prepared, self.backup, self.failed))
                or not self.prepared.name.startswith('.STEVE-update-')
                or not self.backup.name.startswith('.STEVE-previous-')
                or not self.failed.name.startswith('.STEVE-failed-')):
            raise ValueError('Invalid update destination.')

    def state(self, phase):
        self.data['phase'] = phase
        write_json(self.path, self.data)

    def activate(self):
        if not managed(self.target) or self.backup.exists() or self.failed.exists():
            raise ValueError('STEVE installation changed while preparing the update.')
        verify_payload(self.prepared, self.data['sums'])
        (self.prepared / 'steve-install-marker.txt').write_text(MARKER, encoding='utf-8')
        if os.name != 'nt':
            for binary in (self.prepared / 'runtime' / 'bin').glob('*'):
                if binary.is_file():
                    binary.chmod(0o755)
        self.state('swapping')
        self.target.rename(self.backup)
        try:
            self.prepared.rename(self.target)
        except Exception:
            self.backup.rename(self.target)
            self.state('rolled_back')
            raise
        self.state('starting')

    def rollback(self):
        if self.backup.exists():
            if self.target.exists():
                self.target.rename(self.failed)
            self.backup.rename(self.target)
        if not managed(self.target):
            raise RuntimeError('The previous installation could not be restored.')
        self.state('rolled_back')

    def result(self, message):
        Path(self.data['result']).write_text(message, encoding='utf-8')


def prepare(package, installed, home, version):
    """Copy and verify off the Fusion thread. The installed folder is untouched."""
    package, installed, home = Path(package), Path(installed), Path(home)
    if not managed(installed):
        raise ValueError('In-app updates require a managed installation; source checkouts are not replaced.')
    sums = (package / 'SHA256SUMS').read_text(encoding='utf-8')
    verify_payload(package / 'STEVE', sums)
    if json.loads((package / 'STEVE/STEVE.manifest').read_text(encoding='utf-8'))['version'] != version:
        raise ValueError('Update version changed.')
    nonce = uuid4().hex
    prepared = installed.parent / ('.STEVE-update-' + nonce)
    shutil.copytree(package / 'STEVE', prepared)
    verify_payload(prepared, sums)
    helper = home / 'update-helpers' / nonce / 'STEVEUpdater'
    helper.mkdir(parents=True)
    source = Path(__file__).parent
    shutil.copyfile(source / 'update_helper.py', helper / 'STEVEUpdater.py')
    shutil.copyfile(source / 'update_transaction.py', helper / 'transaction.py')
    write_json(helper / 'STEVEUpdater.manifest', {
        'autodeskProduct': 'Fusion', 'type': 'addin', 'author': '10-X-eng',
        'description': {'': 'Finishes a STEVE update and recovers interrupted installations.'},
        'version': version, 'runOnStartup': True, 'supportedOS': 'windows|mac'})
    write_json(helper / 'request.json', {
        'target': str(installed.resolve()), 'prepared': str(prepared.resolve()),
        'backup': str(installed.parent.resolve() / ('.STEVE-previous-' + nonce)),
        'failed': str(installed.parent.resolve() / ('.STEVE-failed-' + nonce)),
        'result': str(package.resolve() / 'install-result.txt'), 'home': str(home.resolve()),
        'nonce': nonce, 'version': version, 'phase': 'prepared', 'sums': sums})
    (package / 'install-result.txt').write_text('Update verified; waiting for STEVE to restart.', encoding='utf-8')
    return helper
