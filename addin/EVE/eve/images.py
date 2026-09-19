"""Bounded image inputs and local previews; never include pixels in state updates."""
import base64
import binascii
import hashlib
from pathlib import Path

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 1024 * 1024
PREFIXES = {"data:image/png;base64,": ".png", "data:image/jpeg;base64,": ".jpg",
            "data:image/webp;base64,": ".webp"}


def validate_images(images):
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
        if not prefix or len(url) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + len(prefix):
            raise ValueError("Use PNG, JPEG, or WebP images under 1 MiB after resizing.")
        try:
            data = base64.b64decode(url[len(prefix):], validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid image data. Paste the image again.") from None
        valid = ((PREFIXES[prefix] == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
                 (PREFIXES[prefix] == ".jpg" and data.startswith(b"\xff\xd8\xff")) or
                 (PREFIXES[prefix] == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
        if not valid or len(data) > MAX_IMAGE_BYTES:
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
        if not path.exists():
            path.write_bytes(base64.b64decode(image["url"][len(prefix):]))
        return {"id": image["id"], "name": image["name"]}

    def read(self, image_id):
        if len(image_id) != 64 or any(c not in "0123456789abcdef" for c in image_id):
            return None
        for prefix, suffix in PREFIXES.items():
            path = self.folder / (image_id + suffix)
            try:
                with path.open("rb") as source:
                    data = source.read(MAX_IMAGE_BYTES + 1)
                if len(data) <= MAX_IMAGE_BYTES:
                    return prefix + base64.b64encode(data).decode("ascii")
            except OSError:
                pass
        return None
