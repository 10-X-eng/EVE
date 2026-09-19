import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin" / "EVE"))
from eve.transport import RuntimeUnavailable, VERSION, runtime_command


class RuntimeSetupTests(unittest.TestCase):
    def test_missing_incomplete_and_valid_installations(self):
        root = Path(__file__).resolve().parents[1] / ".cache" / "runtime-tests" / str(uuid4())
        root.mkdir(parents=True)
        with self.subTest("runtime setup"):
            with self.assertRaisesRegex(RuntimeUnavailable, "missing"):
                runtime_command(root)
            (root / "bin").mkdir()
            (root / "bin/codex-app-server.exe").touch()
            (root / "eve-runtime.json").write_text(json.dumps({"version": VERSION}))
            with self.assertRaisesRegex(RuntimeUnavailable, "Code Mode host"):
                runtime_command(root)
            (root / "bin/codex-code-mode-host.exe").touch()
            with self.assertRaisesRegex(RuntimeUnavailable, "resources"):
                runtime_command(root)
            (root / "codex-resources").mkdir()
            metadata = root / "codex-package.json"
            metadata.write_text("invalid json")
            with self.assertRaisesRegex(RuntimeUnavailable, "damaged"):
                runtime_command(root)
            metadata.write_text(json.dumps({"version": "0.0.0"}))
            with self.assertRaisesRegex(RuntimeUnavailable, "incompatible"):
                runtime_command(root)
            metadata.write_text(json.dumps({"version": VERSION}))
            self.assertEqual(runtime_command(root), [str(root / "bin/codex-app-server.exe"), "--listen", "stdio://"])
