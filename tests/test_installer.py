"""Installer behavior against disposable workspace fixtures; never installs into Fusion."""
import hashlib
from pathlib import Path
import subprocess
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "dist" / "EVE-0.1.0-windows-x64" / "Install EVE.exe"


@unittest.skipUnless(INSTALLER.is_file(), "Build the Windows package to test its installer")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = ROOT / ".cache" / "installer-tests" / str(uuid4())
        self.package = self.scratch / "package"
        self.source = self.package / "EVE"
        self.source.mkdir(parents=True)
        self.destination = self.scratch / "API" / "AddIns"
        (self.source / "EVE.manifest").write_text('{"type":"addin"}', encoding="utf-8")
        (self.source / "EVE.py").write_text("version = 1", encoding="utf-8")
        self.manifest()

    def manifest(self):
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
                 for p in sorted(self.source.iterdir())]
        (self.package / "SHA256SUMS").write_text("\n".join(lines), encoding="utf-8")

    def install(self):
        return subprocess.run([str(INSTALLER), "--test-install", str(self.package), str(self.destination)],
                              timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).returncode

    def test_installs_and_preserves_previous_version_on_update(self):
        self.assertEqual(self.install(), 0)
        self.assertTrue((self.destination / "EVE" / "eve-install-marker.txt").is_file())
        (self.source / "EVE.py").write_text("version = 2", encoding="utf-8")
        self.manifest()
        self.assertEqual(self.install(), 0)
        self.assertEqual((self.destination / "EVE" / "EVE.py").read_text(), "version = 2")
        backups = list((self.destination.parent / "EVE-install-backups").glob("*/EVE.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "version = 1")

    def test_tampered_package_does_not_touch_existing_installation(self):
        self.assertEqual(self.install(), 0)
        (self.source / "EVE.py").write_text("modified", encoding="utf-8")
        self.assertEqual(self.install(), 1)
        self.assertEqual((self.destination / "EVE" / "EVE.py").read_text(), "version = 1")

    def test_refuses_to_replace_an_unmanaged_directory(self):
        target = self.destination / "EVE"
        target.mkdir(parents=True)
        (target / "user-file.txt").write_text("preserve me")
        self.assertEqual(self.install(), 1)
        self.assertEqual((target / "user-file.txt").read_text(), "preserve me")

    def test_rejects_a_path_outside_the_payload(self):
        (self.package / "SHA256SUMS").write_text("0" * 64 + "  ../outside.txt")
        self.assertEqual(self.install(), 1)
        self.assertFalse(self.destination.exists())
