import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.debug_log import DebugLog


class DebugLogTests(unittest.TestCase):
    def setUp(self):
        self.home = ROOT / ".cache/debug-tests" / str(uuid4())
        self.log = DebugLog(self.home)

    def tearDown(self):
        self.log.close()

    def test_default_off_toggle_and_persistence(self):
        self.log.record("ignored", code="not recorded")
        self.assertFalse(self.home.exists())
        self.log.set_enabled(True)
        self.log.record("tool.started", code="def run(context):\n return 'café'")
        self.assertTrue(DebugLog(self.home).enabled)
        self.log.set_enabled(False)
        before = self.log.path.read_bytes()
        self.log.record("ignored", error="not recorded")
        self.assertEqual(before, self.log.path.read_bytes())
        self.assertFalse(DebugLog(self.home).enabled)
        entries = [json.loads(line) for line in before.decode().splitlines()]
        self.assertEqual(entries[1]["code"], "def run(context):\n return 'café'")

    def test_redacts_common_secrets_without_breaking_json(self):
        self.log.set_enabled(True)
        self.log.record("runtime.stderr", message='Bearer secret-token password="secret-pass" api_key=secret-key',
                        result={"access_token": "secret-access", "nested": ["sk-secretkey", "eyJhbGc.payload.signature"]})
        text = self.log.path.read_text(encoding="utf-8")
        for secret in ("secret-token", "secret-pass", "secret-key", "secret-access", "sk-secretkey", "eyJhbGc"):
            self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text.splitlines()[-1])["result"]["access_token"], "[redacted]")

    def test_rotation_is_bounded_and_disk_errors_do_not_escape(self):
        self.log.close()
        self.log = DebugLog(self.home, max_bytes=500)
        self.log.set_enabled(True)
        for index in range(30):
            self.log.record("tool.completed", index=index, output="x" * 200)
        self.assertEqual(len(list(self.log.folder.glob("steve-debug.jsonl*"))), 4)
        with patch.object(self.log._handler, "_open", side_effect=OSError("disk unavailable")):
            self.log._handler.close()
            self.log.record("error", message="must not disrupt Fusion")

    def test_close_stops_late_callbacks_without_changing_preference(self):
        self.log.set_enabled(True)
        self.log.close()
        before = self.log.path.read_bytes()
        self.log.record("late callback")
        self.assertEqual(before, self.log.path.read_bytes())
        self.assertTrue(DebugLog(self.home).enabled)
