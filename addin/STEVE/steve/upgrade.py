"""Transfer a previous installation's data before any account or runtime is opened."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from uuid import uuid4

MARKER = "steve-upgrade.json"


def _runtime_files(home, pattern):
    # Workspace files belong to the user; only repair Codex's own persisted state.
    for relative in ("codex", "grok-runtime/codex", "ollama-runtime/codex"):
        root = home / relative
        if pattern == "*.sqlite":
            yield from root.glob(pattern)
        else:
            for folder in ("sessions", "archived_sessions"):
                yield from (root / folder).rglob(pattern)


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()) or bool(
        getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _relocate(value, old, new):
    if not isinstance(value, str):
        return value
    # Codex canonicalizes rollout paths, while cwd can retain the supplied path.
    # Account for parent aliases (macOS temp roots, Windows short names/junctions).
    for previous, current in ((old, new), (old.resolve(), new.resolve())):
        for source, target in ((str(previous), str(current)), (previous.as_posix(), current.as_posix())):
            match, prefix = os.path.normcase(value), os.path.normcase(source)
            if match == prefix or match.startswith(prefix + "/") or match.startswith(prefix + "\\"):
                return target + value[len(source):]
    return value


def _repair(stage, old, new):
    providers = {old.name.lower() + "_" + kind: "steve_" + kind for kind in ("grok", "ollama")}
    for database in _runtime_files(stage, "*.sqlite"):
        with closing(sqlite3.connect(database, timeout=1)) as connection, connection:
            # Leave messages, goal records, IDs, and all other state unchanged.
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "threads" not in tables:
                continue
            columns = {row[1] for row in connection.execute('PRAGMA table_info("threads")')}
            for column in ("cwd", "rollout_path", "model_provider"):
                if column not in columns:
                    continue
                for identity, value in connection.execute(f'SELECT id, "{column}" FROM threads').fetchall():
                    changed = providers.get(value, value) if column == "model_provider" else _relocate(value, old, new)
                    if changed != value:
                        connection.execute(f'UPDATE threads SET "{column}"=? WHERE id=?', (changed, identity))
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Saved chat database failed its integrity check.")

    def paths(item):
        if isinstance(item, list):
            return [paths(child) for child in item]
        if isinstance(item, dict):
            return {key: _relocate(value, old, new) if key in ("cwd", "path", "image_url") else paths(value)
                    for key, value in item.items()}
        return item

    for rollout in _runtime_files(stage, "rollout-*.jsonl"):
        temporary = rollout.with_suffix(".upgrade-tmp")
        with rollout.open(encoding="utf-8") as source, temporary.open("w", encoding="utf-8", newline="\n") as output:
            for line in source:
                record = json.loads(line)
                original = record
                if record.get("type") in ("session_meta", "turn_context", "response_item"):
                    record = paths(record)
                    if record.get("type") == "session_meta":
                        payload = record.get("payload", {})
                        if payload.get("model_provider") in providers:
                            payload["model_provider"] = providers[payload["model_provider"]]
                output.write(json.dumps(record, ensure_ascii=False) + "\n" if record != original else line)
        shutil.copymode(rollout, temporary)
        temporary.replace(rollout)


def migrate_data(installation, destination):
    """Copy and validate first, then switch folders; retain the original as a backup.

    The installer supplies a discovered predecessor name, never a machine path.
    A receipt makes retries safe even if Fusion stops after the final folder move.
    """
    marker = Path(installation) / MARKER
    if not marker.is_file():
        return None
    name = json.loads(marker.read_text(encoding="utf-8-sig")).get("previousName")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", name) or name.lower() == "steve":
        raise RuntimeError("The installer upgrade record is invalid. Reinstall STEVE.")
    destination = Path(destination).absolute()
    source = destination.parent / name
    receipt = destination / "steve-upgrade-complete.json"
    journal = destination.parent / "STEVE-upgrade-transaction.json"
    if journal.exists():
        transaction = json.loads(journal.read_text(encoding="utf-8"))
        identity = transaction.get("id", "")
        if transaction.get("previousName") != name or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise RuntimeError("A different data upgrade is pending. Preserve the data folders and contact support.")
        stage = destination.parent / ("STEVE-upgrade-staging-" + identity)
        backup = destination.parent / ("STEVE-data-backup-" + identity)
        if not source.exists() and not destination.exists() and backup.is_dir() and stage.is_dir():
            stage.rename(destination)
        if not source.exists() and receipt.is_file():
            journal.unlink()
            return backup
        if source.exists() and not destination.exists():
            # The interrupted attempt never switched folders; the original is intact.
            journal.unlink()
        else:
            raise RuntimeError("An interrupted data upgrade needs attention. All saved folders have been retained.")
    if destination.exists() and receipt.is_file():
        if json.loads(receipt.read_text(encoding="utf-8")).get("previousName") == name and not source.exists():
            return None
    if not source.exists():
        return None
    if destination.exists():
        raise RuntimeError("Both previous and STEVE data folders exist. Neither was changed. "
                           "Back up both folders and resolve the duplicate before starting STEVE.")
    # Do not follow links outside the user's original data tree.
    for directory, dirs, files in os.walk(source, followlinks=False):
        for path in [Path(directory)] + [Path(directory) / entry for entry in dirs + files]:
            if _linked(path):
                raise RuntimeError("The previous data folder contains a filesystem link. "
                                   "No data was moved; remove the link before retrying.")
    identity = uuid4().hex
    stage = destination.parent / ("STEVE-upgrade-staging-" + identity)
    backup = destination.parent / ("STEVE-data-backup-" + identity)
    try:
        shutil.copytree(source, stage)
        # SQLite's backup API includes committed WAL state in a consistent snapshot.
        for database in _runtime_files(source, "*.sqlite"):
            copied = stage / database.relative_to(source)
            snapshot = copied.with_suffix(".upgrade-snapshot")
            with closing(sqlite3.connect(database, timeout=1)) as original, closing(sqlite3.connect(snapshot)) as target:
                original.backup(target)
            for suffix in ("-wal", "-shm"):
                Path(str(copied) + suffix).unlink(missing_ok=True)
            shutil.copymode(copied, snapshot)
            snapshot.replace(copied)
        _repair(stage, source, destination)
        (stage / "steve-upgrade-complete.json").write_text(json.dumps({"previousName": name}), encoding="utf-8")
        pending = journal.with_suffix(".tmp")
        pending.write_text(json.dumps({"previousName": name, "id": identity}), encoding="utf-8")
        pending.replace(journal)
        source.rename(backup)
        try:
            stage.rename(destination)
        except BaseException:
            backup.rename(source)
            raise
        journal.unlink()
    except BaseException:
        if stage.is_dir():
            shutil.rmtree(stage)
        if source.exists():
            journal.unlink(missing_ok=True)
        raise
    return backup
