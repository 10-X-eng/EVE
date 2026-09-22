"""Runtime upgrades must never damage or interrupt the currently running version."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
from steve import runtime_updates as updates
from steve.transport import bundled_runtime, host_target, runtime_command, runtime_version, selected_runtime


def archive_bytes(version="99.0.0", target=None, extra=None):
    target = target or host_target()
    suffix = ".exe" if "windows" in target else ""
    files = {f"bin/codex-app-server{suffix}": b"fixture", f"bin/codex-code-mode-host{suffix}": b"fixture",
             "codex-resources/fixture": b"fixture",
             "codex-package.json": json.dumps({"version": version, "target": target, "layoutVersion": 1,
                                               "variant": "codex-app-server"}).encode()}
    files.update(extra or {})
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o755
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def release_metadata(data, version="99.0.0", target=None):
    target = target or host_target()
    filename = f"codex-app-server-package-{target}.tar.gz"
    return {"tag_name": "rust-v" + version, "published_at": "2026-09-22", "assets": [{
        "name": filename, "state": "uploaded", "size": len(data),
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "browser_download_url": f"{updates.RELEASES}/download/rust-v{version}/{filename}"}]}


class RuntimeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.data = archive_bytes()
        self.release = updates.select_release(release_metadata(self.data), "0.1.0", host_target())
        self.probes = []

    def install(self, data=None, release=None, probe=None, cancelled=lambda: False):
        return updates.install_release(release or self.release, lambda _: None, cancelled, self.home,
            opener=lambda *_args, **_kwargs: io.BytesIO(self.data if data is None else data),
            probe=probe or (lambda root, home: self.probes.append(root)))

    def test_both_platforms_use_stable_official_full_packages(self):
        for target in updates.TARGETS:
            metadata = release_metadata(self.data, target=target)
            result = updates.select_release(metadata, "0.1.0", target)
            self.assertEqual(result["target"], target)
            self.assertIsNone(updates.select_release(metadata, "99.0.0", target))
            self.assertIsNone(updates.select_release(metadata, "100.0.0", target))
            for changes in ({"prerelease": True}, {"draft": True}, {"tag_name": "rust-v99.0.0-alpha.1"}):
                with self.assertRaises(ValueError):
                    updates.select_release({**metadata, **changes}, "0.1.0", target)
            for key, value in (("digest", None), ("size", updates.MAX_DOWNLOAD + 1),
                               ("browser_download_url", "https://example.com/runtime")):
                bad = json.loads(json.dumps(metadata))
                bad["assets"][0][key] = value
                with self.assertRaises(ValueError):
                    updates.select_release(bad, "0.1.0", target)

    def test_side_by_side_install_accepts_newer_version_and_keeps_old_files(self):
        self.assertEqual(self.install(), "99.0.0")
        first = selected_runtime(self.home)
        first_files = {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}
        self.assertEqual(runtime_version(first), "99.0.0")
        self.assertTrue(runtime_command(first)[0].startswith(str(first)))
        data = archive_bytes("100.0.0")
        release = updates.select_release(release_metadata(data, "100.0.0"), "99.0.0", host_target())
        self.install(data, release)
        second = selected_runtime(self.home)
        self.assertNotEqual(first, second)
        self.assertEqual(runtime_version(second), "100.0.0")
        self.assertEqual(first_files, {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()})
        self.assertEqual(len(self.probes), 2)
        self.assertFalse(list((self.home / "runtimes").glob("staging-*")))

    def test_failed_or_cancelled_update_preserves_selection(self):
        self.install()
        selected = selected_runtime(self.home)
        with self.assertRaisesRegex(ValueError, "checksum|size"):
            self.install(data=b"bad archive")
        def incompatible(*_):
            raise RuntimeError("missing goal protocol")
        with self.assertRaisesRegex(RuntimeError, "goal protocol"):
            self.install(probe=incompatible)
        with self.assertRaises(InterruptedError):
            self.install(cancelled=lambda: True)
        cancelled = threading.Event()
        with self.assertRaises(InterruptedError):
            self.install(probe=lambda *_: cancelled.set(), cancelled=cancelled.is_set)
        self.assertEqual(selected_runtime(self.home), selected)
        self.assertFalse(list((self.home / "runtimes").glob("staging-*")))

    def test_package_mismatch_and_path_traversal_never_activate(self):
        for data in (archive_bytes("98.0.0"), archive_bytes(extra={"../escaped": b"bad"}),
                     archive_bytes(extra={"bin\\escaped": b"bad"})):
            release = updates.select_release(release_metadata(data), "0.1.0", host_target())
            with self.assertRaises(ValueError):
                self.install(data, release)
        self.assertEqual(selected_runtime(self.home), bundled_runtime())
        self.assertFalse(self.probes)
        self.assertFalse((self.home / "escaped").exists())

    def test_selection_is_confined_and_missing_runtime_uses_bundle(self):
        folder = self.home / "runtimes"
        for name in ("../outside", "codex-99.0.0-" + "a" * 32):
            updates.write_selection(folder, {"directory": name})
            self.assertEqual(selected_runtime(self.home), bundled_runtime())

    def test_revert_selects_bundle_without_removing_downloaded_runtime(self):
        self.install()
        installed = selected_runtime(self.home)
        states = []
        updater = updates.RuntimeUpdater(states.append, self.home)
        try:
            updater.use_bundled()
            self.assertEqual(selected_runtime(self.home), bundled_runtime())
            self.assertTrue(installed.exists())
            self.assertIn("Restart STEVE", states[-1]["codexUpdateStatus"])
        finally:
            updater.close()

    def test_background_update_deduplicates_and_only_schedules_restart(self):
        entered, finish = threading.Event(), threading.Event()
        states = []
        updater = updates.RuntimeUpdater(states.append, self.home)
        def install(*args):
            entered.set()
            finish.wait(2)
            return "99.0.0"
        try:
            with patch.object(updates, "install_release", side_effect=install) as installing, \
                    patch.object(updates, "runtime_version", return_value="99.0.0"):
                updater.install(self.release)
                self.assertTrue(entered.wait(2))
                updater.install(self.release)
                finish.set()
                from test_core import eventually
                eventually(lambda: any(s.get("codexPendingVersion") for s in states))
                self.assertEqual(installing.call_count, 1)
                self.assertFalse(states[-1]["codexUpdating"])
                self.assertIn("Restart STEVE", states[-1]["codexUpdateStatus"])
        finally:
            finish.set()
            updater.close()

    def test_missing_activation_never_reports_update_ready(self):
        from test_core import eventually
        states = []
        updater = updates.RuntimeUpdater(states.append, self.home)
        try:
            with patch.object(updates, "install_release", return_value="99.0.0"):
                updater.install(self.release)
                eventually(lambda: any(s.get("codexUpdating") is False for s in states))
            self.assertNotIn("codexPendingVersion", states[-1])
            self.assertIn("not selected", states[-1]["codexUpdateStatus"])
        finally:
            updater.close()


if __name__ == "__main__":
    unittest.main()
