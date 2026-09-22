"""In-app installation staging never touches a live or unmanaged add-in."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.app_update import stage_update, launch_update, previous_install_result


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "STEVE-0.5.0-macos-arm64.zip"
        self.home = self.root / "data"
        target = patch("steve.app_update.host_target", return_value="aarch64-apple-darwin")
        target.start()
        self.addCleanup(target.stop)
        self.addins = self.root / "API/AddIns"
        self.addins.mkdir(parents=True)
        installed = self.addins / "STEVE"
        installed.mkdir()
        (installed / "steve-install-marker.txt").write_text("STEVE managed installation")
        self.payload = {"STEVE/STEVE.manifest": json.dumps({"version": "0.5.0"}).encode(),
                        "STEVE/STEVE.py": b"print('fixture')", "Install STEVE.command": b"#!/bin/bash\n",
                        "SHA256SUMS": b"fixture"}
        self.make_zip()

    def make_zip(self, entries=None):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, content in (entries or self.payload).items():
                archive.writestr(name, content)

    def test_stage_only_managed_install_and_expected_version(self):
        staged = stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")
        self.assertEqual((staged / "STEVE/STEVE.py").read_bytes(), self.payload["STEVE/STEVE.py"])
        self.assertEqual((self.addins / "STEVE/steve-install-marker.txt").read_text(), "STEVE managed installation")
        self.assertEqual(len(list((self.home / "pending-updates").iterdir())), 1)
        self.assertEqual(stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin"), staged)
        (self.addins / "STEVE/steve-install-marker.txt").unlink()
        with self.assertRaisesRegex(ValueError, "managed"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")

    def test_rejects_wrong_version_and_archive_escape(self):
        with self.assertRaisesRegex(ValueError, "version"):
            stage_update(self.archive, "0.6.0", self.home, self.addins, platform="darwin")
        self.make_zip({**self.payload, "../escaped": b"bad"})
        with self.assertRaisesRegex(ValueError, "path"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")
        self.assertFalse((self.root / "escaped").exists())

    def test_modified_staged_installer_is_never_reused(self):
        staged = stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")
        (staged / "Install STEVE.command").write_text("malicious replacement")
        with self.assertRaisesRegex(ValueError, "staged"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")

    def test_rejects_zip_modified_after_download(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin", expected_digest="0" * 64)
        self.assertFalse((self.home / "pending-updates").exists())

    def test_rejects_symlink_and_excessive_expansion(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, content in self.payload.items():
                archive.writestr(name, content)
            info = zipfile.ZipInfo("STEVE/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../escape")
        with self.assertRaisesRegex(ValueError, "link"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")
        with patch("steve.app_update.MAX_EXTRACT_BYTES", 10), self.assertRaisesRegex(ValueError, "large"):
            stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")

    def test_launch_uses_installer_without_terminal_and_does_not_quit_fusion(self):
        staged = stage_update(self.archive, "0.5.0", self.home, self.addins, platform="darwin")
        with patch("steve.app_update.subprocess.Popen") as popen:
            launch_update(staged, platform="darwin")
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:3], ["/bin/bash", str(staged / "Install STEVE.command"), "--auto-install"])
        self.assertEqual(kwargs["stdin"], -3)  # subprocess.DEVNULL
        self.assertTrue(kwargs["start_new_session"])

    def test_windows_launch_uses_packaged_exe_without_console(self):
        package = self.root / "windows-package"
        package.mkdir()
        with patch("steve.app_update.subprocess.Popen") as popen:
            launch_update(package, platform="win32")
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:3], [str(package / "Install STEVE.exe"), "--auto-install", str(package / "install-result.txt")])
        self.assertTrue(kwargs["creationflags"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_reports_failed_install_on_next_start_but_not_successful_old_update(self):
        pending = self.home / "pending-updates"
        failed = pending / "STEVE-0.5.0-macos-arm64"
        failed.mkdir(parents=True)
        (failed / "install-result.txt").write_text("Installation failed: fixture error")
        self.assertIn("Installation failed", previous_install_result(self.home, "0.4.0"))
        self.assertIsNone(previous_install_result(self.home, "0.5.0"))
        (failed / "install-result.txt").write_text("Waiting for Fusion to close")
        self.assertIsNone(previous_install_result(self.home, "0.4.0"))

    @unittest.skipUnless(os.name != "nt" and shutil.which("bash") and shutil.which("shasum"), "macOS installer shell tools on POSIX")
    def test_packaged_installer_updates_disposable_managed_addin_and_retains_backup(self):
        package = self.root / "package"
        payload = package / "STEVE"
        payload.mkdir(parents=True)
        (payload / "STEVE.manifest").write_text('{"version":"0.5.0"}')
        (payload / "STEVE.py").write_text("new version")
        (package / "SHA256SUMS").write_text("\n".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in sorted(payload.iterdir())) + "\n")
        installer = Path(__file__).resolve().parents[1] / "scripts/installer/Install STEVE.command"
        (self.addins / "STEVE/STEVE.py").write_text("old version")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        uuid = bin_dir / "uuidgen"
        uuid.write_text("#!/bin/sh\nprintf 'abcdef0123456789abcdef0123456789\\n'\n")
        uuid.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
        result = subprocess.run(["bash", str(installer), "--test-install", str(package), str(self.addins)], env=env, timeout=30)
        self.assertEqual(result.returncode, 0, (package / "installer-test-error.txt").read_text() if (package / "installer-test-error.txt").exists() else "")
        self.assertEqual((self.addins / "STEVE/STEVE.py").read_text(), "new version")
        backups = list((self.addins.parent / "STEVE-install-backups").glob("*/STEVE.py"))
        self.assertEqual([path.read_text() for path in backups], ["old version"])

    @unittest.skipUnless(os.name != "nt" and shutil.which("bash") and shutil.which("shasum"), "macOS installer shell tools on POSIX")
    def test_installer_refuses_when_fusion_reopens_during_swap(self):
        package = self.root / "package"
        payload = package / "STEVE"
        payload.mkdir(parents=True)
        (payload / "STEVE.manifest").write_text('{"version":"0.5.0"}')
        (payload / "STEVE.py").write_text("new version")
        (package / "SHA256SUMS").write_text("\n".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
            for path in sorted(payload.iterdir())) + "\n")
        installed = self.addins / "STEVE/STEVE.py"
        installed.write_text("old version")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        uuid = bin_dir / "uuidgen"
        uuid.write_text("#!/bin/sh\nprintf 'abcdef0123456789abcdef0123456789\\n'\n")
        uuid.chmod(0o755)
        pgrep = bin_dir / "pgrep"
        pgrep.write_text("#!/bin/sh\nif [ ! -f \"$PGREP_STATE\" ]; then printf 'first' > \"$PGREP_STATE\"; exit 1; fi\nexit 0\n")
        pgrep.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
               "PGREP_STATE": str(self.root / "pgrep-called")}
        installer = Path(__file__).resolve().parents[1] / "scripts/installer/Install STEVE.command"
        result = subprocess.run(["bash", str(installer), "--test-install", str(package), str(self.addins)], env=env, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(installed.read_text(), "old version")
        self.assertFalse(list((self.addins.parent / "STEVE-install-backups").glob("*/STEVE.py")))


if __name__ == "__main__":
    unittest.main()
