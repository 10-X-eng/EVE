"""Downloads are verified and isolated from installed files and existing downloads."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.downloads import UpdateDownloader, download_package, downloads_folder
from steve.updates import RELEASES


class Response(io.BytesIO):
    def __init__(self, data, size=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if size is None else size)}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.target = patch("steve.downloads.host_target", return_value="x86_64-pc-windows-msvc")
        self.target.start()
        self.addCleanup(self.target.stop)
        self.filename = "STEVE-0.3.0-windows-x64.zip"
        self.release = {"version": "0.3.0", "downloadUrl": f"{RELEASES}/download/v0.3.0/{self.filename}"}
        self.data = b"package fixture" * 30000
        self.checksum = f"{hashlib.sha256(self.data).hexdigest()}  {self.filename}\n".encode()
        self.size = len(self.data)
        self.calls, self.progress = [], []

    def opener(self, request, timeout):
        self.calls.append(request.full_url)
        self.assertEqual(timeout, 15)
        self.assertNotIn("Authorization", request.headers)
        return Response(self.checksum if request.full_url.endswith(".sha256") else self.data, self.size)

    def download(self, cancelled=lambda: False):
        return download_package(self.release, self.progress.append, cancelled, self.folder, self.opener)

    def test_verified_zip_preserves_existing_download_and_reports_progress(self):
        original = self.folder / self.filename
        original.write_bytes(b"existing user file")
        downloaded = self.download()
        self.assertEqual(downloaded.parent, self.folder)
        self.assertEqual(downloaded.suffix, ".zip")
        self.assertEqual(downloaded.read_bytes(), self.data)
        self.assertEqual(original.read_bytes(), b"existing user file")
        self.assertTrue(self.progress)
        self.assertFalse(list(self.folder.glob("*.part")))

    def test_bad_checksum_or_truncated_stream_leaves_no_zip_or_partial_file(self):
        self.data += b"tampered"
        self.size = len(self.data)
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.download()
        self.assertEqual(list(self.folder.iterdir()), [])
        self.size += 100
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.download()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_cancellation_during_stream_removes_partial_file(self):
        def cancelled():
            return bool(self.progress)
        with self.assertRaises(InterruptedError):
            self.download(cancelled)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_invalid_urls_and_checksum_names_are_rejected(self):
        self.release["downloadUrl"] = "https://example.com/evil.zip"
        with self.assertRaisesRegex(ValueError, "URL"):
            self.download()
        self.assertFalse(self.calls)
        self.release["downloadUrl"] = f"{RELEASES}/download/v0.3.0/{self.filename}"
        self.checksum = b"a" * 64 + b"  wrong-package.zip"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.download()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_package_size_limit_prevents_unbounded_download(self):
        self.size = 2 * 1024 ** 3
        with self.assertRaisesRegex(ValueError, "limit"):
            self.download()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_macos_downloads_path_uses_current_users_home(self):
        with patch("steve.downloads.sys.platform", "darwin"), patch("steve.downloads.Path.home", return_value=self.folder):
            self.assertEqual(downloads_folder(), self.folder / "Downloads")

    @unittest.skipUnless(sys.platform == "win32", "Windows Known Folder API")
    def test_windows_known_folder_path_is_absolute_without_creating_it(self):
        self.assertTrue(downloads_folder().is_absolute())

    def test_background_download_coalesces_and_does_not_publish_after_close(self):
        started, finish = threading.Event(), threading.Event()
        events = []
        def fetch(*args):
            started.set()
            finish.wait(2)
            return self.folder / "fixture.zip"
        downloader = UpdateDownloader(events.append)
        try:
            with patch("steve.downloads.download_package", side_effect=fetch) as download:
                downloader.request(self.release)
                self.assertTrue(started.wait(2))
                downloader.request(self.release)
                downloader.close()
                finish.set()
                downloader._thread.join(2)
                self.assertEqual(download.call_count, 1)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["updateDownload"]["state"], "downloading")
        finally:
            finish.set()
            downloader.close()


if __name__ == "__main__":
    unittest.main()
