import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "EVE"))
from eve.transport import RuntimeUnavailable, VERSION, data_home, host_target, runtime_command

WINDOWS_TARGET = "x86_64-pc-windows-msvc"
MAC_TARGET = "aarch64-apple-darwin"


class RuntimeSetupTests(unittest.TestCase):
    def scratch(self):
        root = ROOT / ".cache" / "runtime-tests" / str(uuid4())
        root.mkdir(parents=True)
        return root

    def test_missing_incomplete_and_valid_installations(self):
        for target, suffix in ((WINDOWS_TARGET, ".exe"), (MAC_TARGET, "")):
            with self.subTest(target=target):
                root = self.scratch()
                executable = root / f"bin/codex-app-server{suffix}"
                host = root / f"bin/codex-code-mode-host{suffix}"
                with self.assertRaisesRegex(RuntimeUnavailable, "missing"):
                    runtime_command(root, target)
                (root / "bin").mkdir()
                executable.touch()
                (root / "eve-runtime.json").write_text(json.dumps({"version": VERSION, "target": target}))
                with self.assertRaisesRegex(RuntimeUnavailable, "Code Mode host"):
                    runtime_command(root, target)
                host.touch()
                with self.assertRaisesRegex(RuntimeUnavailable, "resources"):
                    runtime_command(root, target)
                (root / "codex-resources").mkdir()
                metadata = root / "codex-package.json"
                metadata.write_text("invalid json")
                with self.assertRaisesRegex(RuntimeUnavailable, "damaged"):
                    runtime_command(root, target)
                metadata.write_text(json.dumps({"version": "0.0.0"}))
                with self.assertRaisesRegex(RuntimeUnavailable, "incompatible"):
                    runtime_command(root, target)
                metadata.write_text(json.dumps({"version": VERSION}))
                if not suffix and os.name != "nt":
                    # Zip extraction can drop Unix permission bits; say so instead of failing at launch.
                    with self.assertRaisesRegex(RuntimeUnavailable, "run permission"):
                        runtime_command(root, target)
                    executable.chmod(0o755)
                    host.chmod(0o755)
                self.assertEqual(runtime_command(root, target), [str(executable), "--listen", "stdio://"])

    def test_runtime_built_for_another_platform_is_rejected(self):
        root = self.scratch()
        (root / "bin").mkdir()
        (root / "bin/codex-app-server").touch()
        (root / "bin/codex-app-server").chmod(0o755)
        (root / "bin/codex-code-mode-host").touch()
        (root / "codex-resources").mkdir()
        (root / "codex-package.json").write_text(json.dumps({"version": VERSION}))
        (root / "eve-runtime.json").write_text(json.dumps({"version": VERSION, "target": "x86_64-apple-darwin"}))
        with self.assertRaisesRegex(RuntimeUnavailable, "built for x86_64-apple-darwin"):
            runtime_command(root, MAC_TARGET)
        # Manifests from earlier packages carry no target and keep working.
        (root / "eve-runtime.json").write_text(json.dumps({"version": VERSION}))
        self.assertEqual(runtime_command(root, MAC_TARGET)[0], str(root / "bin/codex-app-server"))

    def test_host_target_follows_platform_and_architecture(self):
        self.assertEqual(host_target("darwin", "arm64"), MAC_TARGET)
        self.assertEqual(host_target("darwin", "x86_64"), "x86_64-apple-darwin")
        self.assertEqual(host_target("win32", "AMD64"), WINDOWS_TARGET)
        self.assertEqual(host_target("win32", "ARM64"), "aarch64-pc-windows-msvc")
        self.assertEqual(host_target("linux", "aarch64"), "aarch64-unknown-linux-musl")
        self.assertIn(host_target(), {MAC_TARGET, "x86_64-apple-darwin", WINDOWS_TARGET,
                                      "aarch64-pc-windows-msvc", "x86_64-unknown-linux-musl",
                                      "aarch64-unknown-linux-musl"})

    def test_data_home_per_platform(self):
        local = ROOT / ".cache" / "fake-local-appdata"
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            self.assertEqual(data_home("win32"), local / "EVE")
        self.assertEqual(data_home("darwin"), Path.home() / "Library" / "Application Support" / "EVE")
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(local)}):
            self.assertEqual(data_home("linux"), local / "EVE")
        self.assertEqual(data_home(), data_home(sys.platform))


if __name__ == "__main__":
    unittest.main()
