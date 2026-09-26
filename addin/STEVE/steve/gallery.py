"""Opt-in shared image catalog over the existing, content-addressed image folder."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .images import PREFIXES, MAX_STORED_IMAGE_BYTES, validate_images
from .secure_store import SecureStore

ID = re.compile(r"[0-9a-f]{64}")
MAX_INDEX = 4 * 1024 * 1024


class Gallery:
    def __init__(self, images):
        self.images = images
        self.path = images.folder / 'gallery.json'
        self.guard = SecureStore(images.folder, 'gallery-write')

    def _load(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_INDEX + 1)
        except FileNotFoundError:
            return {}
        if len(raw) > MAX_INDEX:
            raise ValueError('The gallery index is too large.')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('images'), dict):
            raise ValueError('The gallery index could not be read. Existing images have been kept.')
        entries = data['images']
        for key, entry in entries.items():
            if (not ID.fullmatch(key) or not isinstance(entry, dict)
                    or not isinstance(entry.get('name'), str) or len(entry['name']) > 120
                    or not isinstance(entry.get('addedAt', ''), str)
                    or type(entry.get('enabled')) is not bool or type(entry.get('removed')) is not bool):
                raise ValueError('The gallery index contains an invalid entry. Existing images have been kept.')
        return entries

    def _save(self, entries):
        raw = json.dumps({'version': 1, 'images': entries}, ensure_ascii=False).encode('utf-8')
        if len(raw) > MAX_INDEX:
            raise ValueError('The gallery index is full. No existing images were changed.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.gallery-' + uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(raw)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _entry(name):
        return {'name': str(name or 'Reference image')[:120], 'enabled': False, 'removed': False,
                'addedAt': datetime.now(timezone.utc).isoformat()}

    def migrate(self):
        """Discover all old/new cached pixels without moving them or changing chat indexes.

        Removed IDs remain tombstones so another scan cannot restore or enable them.
        A failed catalog replacement is safely retried; known enabled states stay intact.
        """
        with self.guard.locked('The gallery is being updated. Try again in a moment.'):
            entries = self._load()
            candidates = {}
            for path in self.images.folder.iterdir():
                if path.suffix in PREFIXES.values() and ID.fullmatch(path.stem) and path.stem not in entries:
                    candidates.setdefault(path.stem, path)
            if not candidates:
                return {'added': 0, 'unavailable': 0, 'unreadableChatIndexes': 0}
            names, bad_indexes = {}, 0
            for path in sorted((self.images.folder / 'chats').glob('*.json')):
                try:
                    with path.open('rb') as stream:
                        raw = stream.read(MAX_INDEX + 1)
                    if len(raw) > MAX_INDEX:
                        raise ValueError('Oversized chat index')
                    catalog = json.loads(raw)
                    rows = catalog.get('images') if isinstance(catalog, dict) else None
                    if not isinstance(rows, list):
                        raise ValueError('Invalid chat index')
                    for row in rows:
                        if isinstance(row, dict) and row.get('assetId') in candidates:
                            name = row.get('name')
                            if isinstance(name, str) and name.strip():
                                names.setdefault(row['assetId'], name[:120])
                except (OSError, ValueError, TypeError):
                    bad_indexes += 1
            added, unavailable = 0, 0
            for image_id, path in sorted(candidates.items()):
                # ImageStore.read validates content hashes and size. Revalidate the raster header too.
                url = self.images.read(image_id) if not path.is_symlink() else None
                try:
                    validate_images([{'url': url}], max_bytes=MAX_STORED_IMAGE_BYTES)
                except ValueError:
                    unavailable += 1
                    continue
                entries[image_id] = self._entry(names.get(image_id, 'Saved image ' + image_id[:8]))
                added += 1
            if added:
                self._save(entries)
            return {'added': added, 'unavailable': unavailable, 'unreadableChatIndexes': bad_indexes}

    def list(self, query='', offset=0, limit=20, *, enabled_only=False):
        if not isinstance(query, str) or len(query) > 160 or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('Use a short search, a nonnegative offset and a limit from 1 to 20.')
        migration = self.migrate()
        with self.guard.locked():
            entries = self._load()
            rows = [{'imageId': key, **value} for key, value in entries.items()
                    if not value['removed'] and (not enabled_only or value['enabled'])
                    and query.casefold() in value['name'].casefold()]
        rows.sort(key=lambda row: (row.get('addedAt', ''), row['imageId']), reverse=True)
        page = rows[offset:offset + limit]
        result = {'images': [{k: v for k, v in row.items() if k != 'removed'} for row in page],
                  'total': len(rows), 'nextOffset': offset + len(page) if offset + len(page) < len(rows) else None}
        if not enabled_only:
            result['migration'] = migration
        return result

    def read(self, image_id, *, enabled_only=False):
        if not isinstance(image_id, str) or not ID.fullmatch(image_id):
            raise ValueError('Choose an image from the gallery.')
        with self.guard.locked():
            entry = self._load().get(image_id)
            if not entry or entry['removed'] or (enabled_only and not entry['enabled']):
                raise ValueError('This image is not available in the gallery. List enabled gallery images again; the user controls access.')
            url = self.images.read(image_id)
            if not url:
                raise ValueError('This gallery image is missing or damaged. Import it again to repair its saved copy.')
            return {'imageId': image_id, 'name': entry['name'], 'source': 'gallery', 'historical': True}, url

    def import_images(self, images):
        validated = validate_images(images, max_bytes=MAX_STORED_IMAGE_BYTES)
        with self.guard.locked():
            entries = self._load()
            for image in validated:
                self.images.remember(image)
                if image['id'] not in entries or entries[image['id']]['removed']:
                    entries[image['id']] = self._entry(image['name'])
            self._save(entries)
        return {'imported': len(validated)}

    def change(self, image_id, *, name=None, enabled=None, remove=False):
        if not isinstance(image_id, str) or not ID.fullmatch(image_id):
            raise ValueError('Choose an image from the gallery.')
        if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 120):
            raise ValueError('Use an image name from 1 to 120 characters.')
        if enabled is not None and type(enabled) is not bool:
            raise ValueError('Choose whether this image is available to STEVE.')
        with self.guard.locked():
            entries = self._load()
            entry = entries.get(image_id)
            if not entry or entry['removed']:
                raise ValueError('This image is no longer in the gallery. Refresh the gallery.')
            if name is not None:
                entry['name'] = name.strip()
            if enabled is not None:
                entry['enabled'] = enabled
            if remove:
                entry.update(removed=True, enabled=False)
            self._save(entries)
        return {'updated': True}
