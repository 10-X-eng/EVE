"""Installer behavior against disposable workspace fixtures; never installs into Fusion."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from eve_package import installer_command, installer_name, package_name  # noqa: E402

INSTALLER = ROOT / "dist" / package_name() / installer_name()


@unittest.skipUnless(INSTALLER.is_file(), "Build the package to test its installer")
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
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(self.source).as_posix()}"
                 for p in sorted(self.source.rglob("*")) if p.is_file()]
        (self.package / "SHA256SUMS").write_text("\n".join(lines), encoding="utf-8")

    def install(self):
        command, options = installer_command(INSTALLER, self.package, self.destination)
        return subprocess.run(command, timeout=60, **options).returncode

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

    @unittest.skipIf(os.name == "nt", "Unix permission bits only")
    def test_runtime_binaries_become_executable_after_zip_extraction(self):
        for relative in ("runtime/bin/codex-app-server", "runtime/codex-path/rg", "runtime/codex-resources/zsh/bin/zsh"):
            binary = self.source / relative
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o644)
        self.manifest()
        self.assertEqual(self.install(), 0)
        for relative in ("runtime/bin/codex-app-server", "runtime/codex-path/rg", "runtime/codex-resources/zsh/bin/zsh"):
            self.assertTrue(os.access(self.destination / "EVE" / relative, os.X_OK), relative)
        self.assertFalse(os.access(self.destination / "EVE" / "EVE.py", os.X_OK))
