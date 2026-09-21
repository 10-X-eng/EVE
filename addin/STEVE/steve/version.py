"""The installed manifest is the source of truth for STEVE's version."""
import json
from pathlib import Path

VERSION = json.loads((Path(__file__).resolve().parents[1] / "STEVE.manifest").read_text(encoding="utf-8"))["version"]
