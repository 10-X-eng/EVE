"""Data transfer checks against disposable old installations, without real accounts."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.upgrade import MARKER, migrate_data


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "installation"
        self.install.mkdir()
        (self.install / MARKER).write_text(json.dumps({"previousName": "PreviousAssistant"}))
        self.old = self.root / "PreviousAssistant"
        self.new = self.root / "STEVE"
        (self.old / "codex/sessions").mkdir(parents=True)
        (self.old / "codex/auth.json").write_text('{"token":"fixture-only"}')
        (self.old / "preferences.json").write_text('{"effort":"high"}')
        (self.old / "images").mkdir()
        (self.old / "images/reference.png").write_bytes(b"fixture pixels")
        self.rollout = self.old / "codex/sessions/rollout-fixture.jsonl"
        records = [
            {"type": "session_meta", "payload": {"cwd": str(self.old / "workspace"), "model_provider": "previousassistant_grok"}},
            {"type": "response_item", "payload": {"role": "user", "content": [
                {"type": "input_text", "text": "Keep this historical path: " + str(self.old)},
                {"type": "local_image", "path": str(self.old / "images/reference.png")}]}}
        ]
        self.rollout.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
        with closing(sqlite3.connect(self.old / "codex/state_5.sqlite")) as db, db:
            db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, rollout_path TEXT, model_provider TEXT)")
            db.execute("INSERT INTO threads VALUES (?,?,?,?)", ("chat1", str(self.old / "workspace"), str(self.rollout), "previousassistant_grok"))
            db.execute("CREATE TABLE thread_goals (thread_id TEXT, objective TEXT, status TEXT)")
            db.execute("INSERT INTO thread_goals VALUES ('chat1', 'Keep my goal', 'paused')")

    def test_moves_accounts_images_preferences_and_relocates_chat_metadata(self):
        workspace = self.old / "workspace"
        workspace.mkdir()
        (workspace / "user.sqlite").write_bytes(b"unrelated user data")
        (workspace / "rollout-example.jsonl").write_text("not a runtime file")
        backup = migrate_data(self.install, self.new)
        self.assertFalse(self.old.exists())
        self.assertTrue(backup.is_dir())
        for relative in ("codex/auth.json", "preferences.json", "images/reference.png", "workspace/user.sqlite", "workspace/rollout-example.jsonl"):
            self.assertEqual((self.new / relative).read_bytes(), (backup / relative).read_bytes())
        with closing(sqlite3.connect(self.new / "codex/state_5.sqlite")) as db:
            row = db.execute("SELECT * FROM threads").fetchone()
            self.assertEqual(row, ("chat1", str(self.new / "workspace"), str(self.new / self.rollout.relative_to(self.old)), "steve_grok"))
            self.assertEqual(db.execute("SELECT * FROM thread_goals").fetchone(), ("chat1", "Keep my goal", "paused"))
        records = [json.loads(line) for line in (self.new / self.rollout.relative_to(self.old)).read_text().splitlines()]
        self.assertEqual(records[0]["payload"]["model_provider"], "steve_grok")
        content = records[1]["payload"]["content"]
        self.assertEqual(content[0]["text"], "Keep this historical path: " + str(self.old))
        self.assertEqual(content[1]["path"], str(self.new / "images/reference.png"))
        self.assertIsNone(migrate_data(self.install, self.new))

    def test_duplicate_data_folders_are_never_merged_or_overwritten(self):
        self.new.mkdir()
        (self.new / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "Both previous"):
            migrate_data(self.install, self.new)
        self.assertEqual((self.new / "keep.txt").read_text(), "keep")
        self.assertTrue(self.old.is_dir())

    def test_canonical_rollout_paths_under_an_aliased_parent_are_relocated(self):
        alias = self.root / "alias"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(self.root), str(alias))
        else:
            alias.symlink_to(self.root, target_is_directory=True)
        try:
            with closing(sqlite3.connect(self.old / "codex/state_5.sqlite")) as db, db:
                db.execute("UPDATE threads SET rollout_path=?", (str(self.rollout.resolve()),))
            target = alias / "STEVE"
            migrate_data(self.install, target)
            with closing(sqlite3.connect(target / "codex/state_5.sqlite")) as db:
                rollout = db.execute("SELECT rollout_path FROM threads").fetchone()[0]
            self.assertEqual(Path(rollout), (self.new / self.rollout.relative_to(self.old)).resolve())
            self.assertTrue(Path(rollout).is_file())
        finally:
            if os.name == "nt":
                alias.rmdir()
            else:
                alias.unlink()

    def test_invalid_history_keeps_original_folder_intact(self):
        self.rollout.write_text("invalid json")
        with self.assertRaises(ValueError):
            migrate_data(self.install, self.new)
        self.assertTrue(self.old.is_dir())
        self.assertFalse(self.new.exists())
        self.assertFalse(list(self.root.glob("STEVE-upgrade-staging-*")))

    def test_failed_final_move_restores_original(self):
        rename = Path.rename
        def fail_stage(path, target):
            if path.name.startswith("STEVE-upgrade-staging-"):
                raise OSError("fixture locked destination")
            return rename(path, target)
        with patch.object(Path, "rename", fail_stage), self.assertRaises(OSError):
            migrate_data(self.install, self.new)
        self.assertTrue(self.old.is_dir())
        self.assertFalse(self.new.exists())
        self.assertFalse(list(self.root.glob("STEVE-data-backup-*")))

    def test_recovers_interruption_between_folder_moves(self):
        identity = "a" * 32
        stage = self.root / ("STEVE-upgrade-staging-" + identity)
        stage.mkdir()
        (stage / "steve-upgrade-complete.json").write_text(json.dumps({"previousName": self.old.name}))
        (stage / "keep.txt").write_text("prepared data")
        backup = self.root / ("STEVE-data-backup-" + identity)
        self.old.rename(backup)
        journal = self.root / "STEVE-upgrade-transaction.json"
        journal.write_text(json.dumps({"previousName": self.old.name, "id": identity}))
        self.assertEqual(migrate_data(self.install, self.new), backup)
        self.assertEqual((self.new / "keep.txt").read_text(), "prepared data")
        self.assertFalse(journal.exists())

    def test_rejects_path_escape(self):
        (self.install / MARKER).write_text('{"previousName":"../outside"}')
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            migrate_data(self.install, self.new)

    def test_missing_marker_leaves_all_data_untouched(self):
        (self.install / MARKER).unlink()
        self.assertIsNone(migrate_data(self.install, self.new))
        self.assertTrue(self.old.is_dir())


if __name__ == "__main__":
    unittest.main()
