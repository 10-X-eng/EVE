"""Bundled, offline release highlights and per-installation read state."""
import json
from pathlib import Path
from uuid import uuid4
from .version import VERSION


def highlights():
    return {'version': VERSION, 'title': 'Long chats, reliable jobs and working links', 'items': [
        'Continue long conversations without the old 200-entry cutoff, including paused jobs.',
        'The panel shows 200 recent entries at a time. Use Show earlier messages and Back to latest to browse without deleting saved history or model context.',
        'Paused jobs recover Resume when idle. If a response is still finishing, the panel explains the wait instead of offering Pause again.',
        'Reply links open in your browser again.',
        'A late turn-start reply can no longer replace the current turn ID and incorrectly reject its tool calls.',
    ], 'note': 'These fixes work in existing chats. If upgrading from before 0.8.0, start a new chat for gallery lookup tools and screenshot isolation; Gallery Attach also works in older chats.'}


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
