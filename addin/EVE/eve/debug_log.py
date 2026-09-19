"""Opt-in local diagnostics. Never record authentication RPC payloads."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading


class QuietHandler(RotatingFileHandler):
    def handleError(self, record):
        # A full disk or unavailable log folder must not break a Fusion operation.
        pass


def redact(text):
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted]", text)
    return re.sub(r'(?i)((?:access_token|refresh_token|id_token|api_key|authorization|password)[\s"\x27]*[:=][\s"\x27]*)([^\s,"\x27}]+)',
                  r"\1[redacted]", text)


def clean(value):
    if isinstance(value, dict):
        return {str(key): "[redacted]" if re.fullmatch(r"(?i)(access_token|refresh_token|id_token|api_key|authorization|password)", str(key)) else clean(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return redact(value) if isinstance(value, str) else value


class DebugLog:
    def __init__(self, home, max_bytes=2 * 1024 * 1024):
        self.folder = Path(home) / "logs"
        self.path = self.folder / "eve-debug.jsonl"
        self.settings = Path(home) / "debug.json"
        self.enabled = False
        self._handler = None
        self._lock = threading.RLock()
        self.max_bytes = max_bytes
        try:
            self.enabled = json.loads(self.settings.read_text(encoding="utf-8")).get("enabled") is True
        except (OSError, ValueError, AttributeError):
            pass

    def _open(self):
        if self._handler is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._handler = QuietHandler(self.path, maxBytes=self.max_bytes, backupCount=3, encoding="utf-8")

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("Debug logging must be on or off.")
        with self._lock:
            if enabled:
                self._open()
            self.settings.parent.mkdir(parents=True, exist_ok=True)
            self.settings.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
            if not enabled:
                self.record("debug.disabled")
            self.enabled = enabled
            if enabled:
                self.record("debug.enabled")
            elif self._handler:
                self._handler.close()
                self._handler = None

    def record(self, event, **details):
        with self._lock:
            if not self.enabled:
                return
            try:
                self._open()
                encoded = json.dumps(clean(details), ensure_ascii=False, default=str)
                data = json.loads(encoded) if len(encoded) <= 256000 else {"truncated": True, "preview": encoded[:256000]}
                line = json.dumps({"time": datetime.now(timezone.utc).isoformat(), "event": event, **data}, ensure_ascii=False)
                self._handler.handle(logging.LogRecord("eve.debug", logging.INFO, "", 0, line, (), None))
            except (OSError, ValueError, TypeError):
                pass

    def close(self):
        with self._lock:
            self.enabled = False
            if self._handler:
                self._handler.close()
                self._handler = None
