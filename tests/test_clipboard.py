import base64
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve import clipboard

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII=")


class ClipboardTests(unittest.TestCase):
    def read_fixture(self, content=PNG, returncode=0):
        paths = []
        def run(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 10)
            path = Path(kwargs["env"]["STEVE_CLIPBOARD_IMAGE"])
            paths.append(path)
            if content is not None:
                path.write_bytes(content)
            return subprocess.CompletedProcess(command, returncode)
        with patch.object(clipboard.sys, "platform", "darwin"), \
                patch.object(clipboard.shutil, "which", return_value="osascript"), \
                patch.object(clipboard.subprocess, "run", side_effect=run):
            try:
                return clipboard.read_clipboard_image()
            finally:
                for path in paths:
                    self.assertFalse(path.parent.exists(), "Temporary image must be removed on success and failure")

    def test_reads_png_and_removes_temporary_image(self):
        result = self.read_fixture()
        self.assertEqual(base64.b64decode(result["url"].split(",", 1)[1]), PNG)

    def test_non_image_clipboard_is_empty(self):
        self.assertIsNone(self.read_fixture(None))

    def test_rejects_bad_image_and_failed_reader(self):
        with self.assertRaisesRegex(ValueError, "valid PNG"):
            self.read_fixture(b"not an image")
        with self.assertRaisesRegex(RuntimeError, "Could not read"):
            self.read_fixture(None, returncode=1)

    def test_rejects_size_and_pixel_limits(self):
        with patch.object(clipboard, "MAX_BYTES", 10), self.assertRaisesRegex(ValueError, "20 MiB"):
            self.read_fixture()
        with self.assertRaisesRegex(ValueError, "megapixels"):
            self.read_fixture(PNG[:16] + (50000).to_bytes(4, "big") * 2 + PNG[24:])

    def test_timeout_is_actionable(self):
        with patch.object(clipboard.sys, "platform", "darwin"), \
                patch.object(clipboard.shutil, "which", return_value="osascript"), \
                patch.object(clipboard.subprocess, "run", side_effect=subprocess.TimeoutExpired("reader", 10)), \
                self.assertRaisesRegex(RuntimeError, "timed out"):
            clipboard.read_clipboard_image()

    @unittest.skipUnless(sys.platform == "win32", "Windows native image conversion")
    def test_real_windows_conversion_without_touching_system_clipboard(self):
        for mode in ("bitmap", "png"):
            with self.subTest(mode=mode):
                fixture = "$data = New-Object System.Windows.Forms.DataObject; $fixture = New-Object System.Drawing.Bitmap 16, 12; "
                if mode == "bitmap":
                    fixture += "$data.SetImage($fixture)"
                else:
                    fixture += "$png = New-Object System.IO.MemoryStream; $fixture.Save($png, [System.Drawing.Imaging.ImageFormat]::Png); $png.Position = 0; $data.SetData('PNG', $png)"
                script = clipboard.WINDOWS_READER.replace("$data = [System.Windows.Forms.Clipboard]::GetDataObject()", fixture)
                with patch.object(clipboard, "WINDOWS_READER", script), \
                        patch.object(clipboard.subprocess, "run", wraps=subprocess.run) as runner:
                    result = clipboard.read_clipboard_image()
                self.assertTrue(result["url"].startswith("data:image/png;base64,"))
                runner.assert_called_once()
                self.assertEqual(runner.call_args.kwargs["timeout"], 30)
                self.assertEqual(runner.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
