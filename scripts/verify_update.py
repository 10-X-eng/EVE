"""Exercise complete-package update and rollback in an isolated filesystem fixture.

Never stops Fusion or touches a real installation. --previous-archive additionally
tests replacing a previously published package; its sibling SHA256 is required.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'addin/STEVE'))
sys.path.insert(0, str(ROOT / 'scripts'))
from steve_package import package_name
from steve.version import VERSION
from steve.transport import host_target
from steve.app_update import stage_update
from steve.update_transaction import prepare, Transaction, MARKER
from steve.images import ImageStore
from steve.gallery import Gallery
from steve.release_notes import ReleaseNotes


def checksum(archive):
    expected = archive.with_suffix('.zip.sha256').read_text().split()[0]
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Archive checksum mismatch'
    return expected


def files(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-archive', type=Path)
    args = parser.parse_args()
    archive = ROOT / 'dist' / (package_name(host_target()) + '.zip')
    expected = checksum(archive)
    scratch = ROOT / '.cache/update-verification' / uuid4().hex
    home = scratch / 'data'
    installed = scratch / 'API/AddIns/STEVE'
    installed.mkdir(parents=True)
    if args.previous_archive:
        checksum(args.previous_archive)
        with zipfile.ZipFile(args.previous_archive) as source:
            for entry in source.infolist():
                if entry.filename.startswith('STEVE/') and not entry.is_dir():
                    destination = installed.parent / entry.filename
                    assert destination.resolve().is_relative_to(installed.resolve())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read(entry))
    else:
        (installed / 'STEVE.py').write_text('# previous installation fixture')
        (installed / 'STEVE.manifest').write_text(json.dumps({'version': '0.7.1'}))
    (installed / 'steve-install-marker.txt').write_text(MARKER)
    before = files(installed)
    images = ImageStore(home)
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlSAAAAAASUVORK5CYII=')
    image = {'id': hashlib.sha256(png).hexdigest(), 'name':'Old reference.png',
             'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}
    images.record('existing-chat', 'turn', [image])
    (home / 'preferences.json').write_text('{"fixture":true}')
    preserved = files(home)
    package = stage_update(archive, VERSION, home, installed.parent, expected_digest=expected)
    helper = prepare(package, installed, home, VERSION)
    assert files(installed) == before, 'Staging changed the running installation'
    transaction = Transaction(helper / 'request.json')
    transaction.activate()
    assert json.loads((installed / 'STEVE.manifest').read_text())['version'] == VERSION
    for line in (package / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        assert hashlib.sha256((installed / relative).read_bytes()).hexdigest() == digest, relative
    # Old chat pixels migrate only after activation and never opt in automatically.
    gallery = Gallery(images)
    assert gallery.migrate()['added'] == 1
    assert gallery.list(enabled_only=True)['total'] == 0
    gallery.change(image['id'], enabled=True)
    notes = ReleaseNotes(home)
    assert notes.unread()
    notes.acknowledge(VERSION)
    transaction.rollback()
    assert files(installed) == before, 'Rollback did not restore every previous file'
    assert gallery.list(enabled_only=True)['total'] == 1
    assert not ReleaseNotes(home).unread()
    for relative, digest in preserved.items():
        assert hashlib.sha256((home / relative).read_bytes()).hexdigest() == digest, relative
    # Repeat the update after rollback; retained gallery preferences must survive.
    helper = prepare(package, installed, home, VERSION)
    Transaction(helper / 'request.json').activate()
    assert Gallery(ImageStore(home)).list(enabled_only=True)['total'] == 1
    assert len(images.list_chat('existing-chat')['images']) == 1
    print('Full package: verified staging, activation, image migration, permission/read-state preservation, rollback and retry passed.')
    print('Filesystem fixture only; Fusion was not stopped or accessed.')
    print(scratch)


if __name__ == '__main__':
    main()
