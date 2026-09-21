"""Installer behavior against disposable workspace fixtures; never installs into Fusion."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from steve_package import installer_command, installer_name, package_name  # noqa: E402

INSTALLER = ROOT / "dist" / package_name() / installer_name()


@unittest.skipUnless(INSTALLER.is_file(), "Build the package to test its installer")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = ROOT / ".cache" / "installer-tests" / str(uuid4())
        self.package = self.scratch / "package"
        self.source = self.package / "STEVE"
        self.source.mkdir(parents=True)
        self.destination = self.scratch / "API" / "AddIns"
        (self.source / "STEVE.manifest").write_text('{"type":"addin"}', encoding="utf-8")
        (self.source / "STEVE.py").write_text("version = 1", encoding="utf-8")
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
        self.assertTrue((self.destination / "STEVE" / "steve-install-marker.txt").is_file())
        (self.source / "STEVE.py").write_text("version = 2", encoding="utf-8")
        self.manifest()
        self.assertEqual(self.install(), 0)
        self.assertEqual((self.destination / "STEVE" / "STEVE.py").read_text(), "version = 2")
        backups = list((self.destination.parent / "STEVE-install-backups").glob("*/STEVE.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "version = 1")

    def test_tampered_package_does_not_touch_existing_installation(self):
        self.assertEqual(self.install(), 0)
        (self.source / "STEVE.py").write_text("modified", encoding="utf-8")
        self.assertEqual(self.install(), 1)
        self.assertEqual((self.destination / "STEVE" / "STEVE.py").read_text(), "version = 1")

    def test_refuses_to_replace_an_unmanaged_directory(self):
        target = self.destination / "STEVE"
        target.mkdir(parents=True)
        (target / "user-file.txt").write_text("preserve me")
        self.assertEqual(self.install(), 1)
        self.assertEqual((target / "user-file.txt").read_text(), "preserve me")

    def test_rejects_a_path_outside_the_payload(self):
        (self.package / "SHA256SUMS").write_text("0" * 64 + "  ../outside.txt")
        self.assertEqual(self.install(), 1)
        self.assertFalse(self.destination.exists())

    def previous(self, name="PreviousAssistant"):
        folder = self.destination / name
        folder.mkdir(parents=True)
        (folder / (name + ".manifest")).write_text(json.dumps({"type": "addin", "author": "10-X-eng",
            "autodeskProduct": "Fusion", "description": {"": name + " — Engineering & Visualization Expert"}}), encoding="utf-8")
        (folder / (name + ".py")).write_text("previous = True")
        (folder / (name.lower() + "-install-marker.txt")).write_text(name + " managed installation")
        return folder

    def test_renames_managed_addin_and_keeps_upgrade_record_on_reinstall(self):
        previous = self.previous()
        self.assertEqual(self.install(), 0)
        self.assertFalse(previous.exists())
        record = self.destination / "STEVE/steve-upgrade.json"
        self.assertEqual(json.loads(record.read_text()), {"previousName": previous.name})
        self.assertEqual(len(list((self.destination.parent / "STEVE-install-backups").glob("*/PreviousAssistant.py"))), 1)
        self.assertEqual(self.install(), 0)
        self.assertEqual(json.loads(record.read_text()), {"previousName": previous.name})

    def test_ambiguous_previous_installations_are_untouched(self):
        one, two = self.previous(), self.previous("AnotherAssistant")
        self.assertEqual(self.install(), 1)
        self.assertTrue(one.is_dir() and two.is_dir())
        self.assertFalse((self.destination / "STEVE").exists())

    def test_unrelated_addins_are_untouched(self):
        folder = self.previous()
        (folder / (folder.name + ".manifest")).write_text('{"type":"addin","author":"SomeoneElse"}')
        self.assertEqual(self.install(), 0)
        self.assertTrue(folder.is_dir())
        self.assertFalse((self.destination / "STEVE/steve-upgrade.json").exists())

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
            self.assertTrue(os.access(self.destination / "STEVE" / relative, os.X_OK), relative)
        self.assertFalse(os.access(self.destination / "STEVE" / "STEVE.py", os.X_OK))
