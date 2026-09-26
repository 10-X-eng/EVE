"""Native Codex concept images, cached with the conversation rather than UI state."""
import base64
from pathlib import Path
import re

from .images import MAX_STORED_IMAGE_BYTES, PREFIXES, validate_images

DREAM_INSTRUCTIONS = """
STEVE Dream
When asked for a concept image, use image generation. Use attached images or a captured
Fusion viewport as references when relevant. Image generation uses the user's Codex
limits; generate only when requested, not automatically during design or DFM work.
Refine a chosen concept using its original image. Use list_chat_images and
view_chat_image to retrieve earlier concepts when needed. Generated concepts are visual
references, never evidence of existing geometry, dimensions, fit, or manufacturability.
Keep stated requirements separate from visual guesses. Creating an image does not
authorize changing the Fusion design. The UI displays generated images automatically.
"""


def concept_message(store, thread_id, turn_id, item, generated_root=None):
    """Decode a completed native event or recover its chat-scoped cached preview."""
    message = {"id": "dream-" + str(item.get("id", "")), "role": "assistant",
               "concept": True, "text": "Concept · Visual reference, not verified geometry."}
    if item.get("status") != "completed" or item.get("failure"):
        message.update(conceptStatus="failed", text="Image generation did not complete. Check the response for details, then retry when ready.")
        failure = item.get('failure')
        if isinstance(failure, dict) and isinstance(failure.get('message'), str):
            message['text'] = failure['message'][:1000]
        return message
    try:
        cached = next((entry for entry in store._catalog(thread_id)
                       if entry.get("itemId") == item.get("id") and entry["source"] == "generated"), None)
        if cached and store.read(cached["assetId"]):
            message.update(conceptStatus="completed", images=[{"id": cached["assetId"], "name": cached["name"], "generated": True}])
            return message
        raw = item.get("result")
        if isinstance(raw, str) and raw:
            if len(raw) > 4 * ((MAX_STORED_IMAGE_BYTES + 2) // 3):
                raise ValueError("The generated image exceeds the 8 MiB preview limit. Ask for a smaller image.")
            data = base64.b64decode(raw, validate=True)
        else:
            # Resumed threads may contain only savedPath. Never read arbitrary model paths.
            if not generated_root or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", thread_id):
                raise ValueError("The saved concept is unavailable.")
            path = Path(item.get("savedPath") or "")
            allowed = Path(generated_root).resolve() / thread_id
            if not path.is_absolute() or not path.resolve().is_relative_to(allowed) or path.is_symlink():
                raise ValueError("The saved concept is outside this conversation's image folder.")
            with path.open("rb") as source:
                data = source.read(MAX_STORED_IMAGE_BYTES + 1)
        suffix = ".png" if data.startswith(b"\x89PNG") else ".jpg" if data.startswith(b"\xff\xd8\xff") else ".webp"
        prefix = next(prefix for prefix, extension in PREFIXES.items() if extension == suffix)
        images = validate_images([{"name": "STEVE Dream concept", "url": prefix + base64.b64encode(data).decode("ascii")}],
                                 max_bytes=MAX_STORED_IMAGE_BYTES)
        store.record(thread_id, turn_id, images, source="generated", message=item.get("revisedPrompt") or "Generated concept",
                     item_id=item.get("id"))
        message.update(conceptStatus="completed", images=[{**store.remember(images[0]), "generated": True}])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        message.update(conceptStatus="unavailable", text="The concept was generated, but its preview could not be saved. " +
                       (str(exc) if isinstance(exc, ValueError) else "Try reopening this conversation."))
    return message
