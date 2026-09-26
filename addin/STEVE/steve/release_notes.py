"""Bundled, offline release highlights and per-installation read state."""
import json
from pathlib import Path
from uuid import uuid4
from .version import VERSION


def highlights():
    return {'version': VERSION, 'title': 'Reliable paused-job controls', 'items': [
        'Paused jobs recover their Resume button when the runtime is idle. If a response is still finishing, the panel explains the wait and no longer offers Pause again.',
        'Image gallery in the top bar: browse, import, rename and reuse images across conversations.',
        'Your existing pictures appear automatically. Enable Available to STEVE for references it may find in any chat; access starts off.',
        'STEVE now has guidance to build and check one functional part before moving on, then verify assembly fit.',
        'Update controls explain why they are waiting and clearly announce the STEVE restart. Fusion stays open.',
        'Close-ups keep the camera outside the assembly. STEVE can temporarily isolate a part for a clear screenshot, then restore visibility.',
    ], 'note': 'Start a new chat after updating so STEVE receives the gallery lookup tools and the capture tool’s isolate option. Gallery Attach also works in older chats.'}


class ReleaseNotes:
    def __init__(self, home):
        self.path = Path(home) / 'release-notes-seen.json'

    def unread(self):
        try:
            with self.path.open('rb') as stream:
                data = stream.read(1025)
            return len(data) > 1024 or json.loads(data).get('version') != VERSION
        except (OSError, ValueError, AttributeError):
            return True

    def acknowledge(self, version):
        if version != VERSION:
            raise ValueError('Read the notes for this STEVE version.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.release-notes-' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'version': VERSION}), encoding='utf-8')
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
