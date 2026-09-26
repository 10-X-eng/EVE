"""Bounded image inputs and local previews; never include pixels in state updates."""
import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 1024 * 1024
MAX_STORED_IMAGE_BYTES = 8 * 1024 * 1024
PREFIXES = {"data:image/png;base64,": ".png", "data:image/jpeg;base64,": ".jpg",
            "data:image/webp;base64,": ".webp"}


def validate_images(images, max_bytes=MAX_IMAGE_BYTES):
    if images is None:
        return []
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError("Attach at most four images per message.")
    result = []
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Choose a PNG, JPEG, or WebP image.")
        url = image.get("url", "")
        if not isinstance(url, str):
            raise ValueError("Invalid image data. Paste the image again.")
        prefix = next((p for p in PREFIXES if url.startswith(p)), None)
        if not prefix or len(url) > 4 * ((max_bytes + 2) // 3) + len(prefix):
            raise ValueError(f"Use PNG, JPEG, or WebP images under {max_bytes // (1024 * 1024)} MiB after resizing.")
        try:
            data = base64.b64decode(url[len(prefix):], validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid image data. Paste the image again.") from None
        valid = ((PREFIXES[prefix] == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
                 (PREFIXES[prefix] == ".jpg" and data.startswith(b"\xff\xd8\xff")) or
                 (PREFIXES[prefix] == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
        if not valid or len(data) > max_bytes:
            raise ValueError("That image could not be read. Paste it again or choose another image.")
        result.append({"id": hashlib.sha256(data).hexdigest(),
                       "name": str(image.get("name") or "Reference image")[:120], "url": url})
    return result


class ImageStore:
    def __init__(self, home):
        self.folder = Path(home) / "images"

    def remember(self, image):
        prefix = next(p for p in PREFIXES if image["url"].startswith(p))
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / (image["id"] + PREFIXES[prefix])
        if self.read(image["id"]) != image["url"]:
            temporary = path.with_name('.image-' + uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(base64.b64decode(image["url"][len(prefix):]))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return {"id": image["id"], "name": image["name"]}

    def read(self, image_id):
        if not isinstance(image_id, str) or len(image_id) != 64 or any(c not in "0123456789abcdef" for c in image_id):
            return None
        for prefix, suffix in PREFIXES.items():
            path = self.folder / (image_id + suffix)
            try:
                if path.is_symlink():
                    continue
                with path.open("rb") as source:
                    data = source.read(MAX_STORED_IMAGE_BYTES + 1)
                if len(data) <= MAX_STORED_IMAGE_BYTES and hashlib.sha256(data).hexdigest() == image_id:
                    return prefix + base64.b64encode(data).decode("ascii")
            except OSError:
                pass
        return None

    def _catalog_path(self, thread_id):
        if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 200:
            raise ValueError("A current conversation is required for image lookup.")
        key = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
        return self.folder / "chats" / (key + ".json")

    def _catalog(self, thread_id):
        path = self._catalog_path(thread_id)
        try:
            with path.open("rb") as source:
                data = source.read(4 * 1024 * 1024 + 1)
        except FileNotFoundError:
            return []
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("This chat's image index exceeds the supported size.")
        catalog = json.loads(data)
        if not isinstance(catalog, dict) or catalog.get("threadId") != thread_id or not isinstance(catalog.get("images"), list):
            raise ValueError("This chat's image index could not be read.")
        if any(not isinstance(entry, dict) or not {"imageId", "assetId", "name", "source", "turnId"} <= set(entry)
               for entry in catalog["images"]):
            raise ValueError("This chat's image index contains an invalid entry.")
        return catalog["images"]

    def record(self, thread_id, turn_id, images, *, source="attachment", message="", document=None, item_id=None):
        """Record confirmed deliveries; identical pixels remain one file across chats."""
        if source not in ("attachment", "viewport", "generated"):
            raise ValueError("Unknown chat image source.")
        entries = self._catalog(thread_id)
        recorded = []
        for image in images:
            reference = self.remember(image)
            identity = json.dumps([thread_id, turn_id, source, reference["id"]] + ([item_id] if source == "generated" else []))
            image_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            entry = next((entry for entry in entries if entry["imageId"] == image_id), None)
            if entry is None:
                entry = {"imageId": image_id, "assetId": reference["id"], "name": reference["name"],
                         "source": source, "turnId": turn_id, "message": str(message)[:320],
                         "recordedAt": datetime.now(timezone.utc).isoformat(), "historical": source == "viewport"}
                if document:
                    entry["document"] = {key: document[key] for key in ("id", "name") if key in document}
                if item_id:
                    entry["itemId"] = str(item_id)[:200]
                entries.append(entry)
            recorded.append(self._public_entry(entry))
        encoded = json.dumps({"threadId": thread_id, "images": entries}, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 4 * 1024 * 1024:
            raise ValueError("This chat's image index is full. Start a new chat for more images.")
        path = self._catalog_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
        return recorded

    @staticmethod
    def _public_entry(entry):
        fields = ("imageId", "name", "source", "turnId", "message", "recordedAt", "historical", "document")
        return {key: entry[key] for key in fields if key in entry}

    def list_chat(self, thread_id, offset=0, limit=20):
        entries = self._catalog(thread_id)
        page = entries[offset:offset + limit]
        end = offset + len(page)
        return {"images": [self._public_entry(entry) for entry in page], "total": len(entries),
                "offset": offset, "returned": len(page), "nextOffset": end if end < len(entries) else None}

    def read_chat(self, thread_id, image_id):
        entry = next((entry for entry in self._catalog(thread_id) if entry["imageId"] == image_id), None)
        if entry is None:
            raise KeyError("That image is not indexed in the current conversation.")
        url = self.read(entry["assetId"])
        if url is None:
            raise FileNotFoundError("That cached image is missing or damaged. Ask the user to attach it again.")
        return self._public_entry(entry), url
