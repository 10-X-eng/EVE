"""Download a verified update into Downloads without touching the installed add-in."""
import ctypes
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.request import Request, urlopen
from uuid import UUID

from .updates import RELEASES, PLATFORMS, version_key
from .transport import host_target
from .version import VERSION

MAX_PACKAGE_BYTES = 1024 * 1024 * 1024


def downloads_folder():
    if sys.platform == "darwin":
        return Path.home() / "Downloads"
    if sys.platform != "win32":
        raise OSError("This platform is not supported.")
    # The Known Folder API honors redirected Windows Downloads folders.
    shell = ctypes.WinDLL("shell32")
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    guid = ctypes.create_string_buffer(UUID("374de290-123f-4565-9164-39c4925e467b").bytes_le)
    pointer = ctypes.c_void_p()
    initialized = ole.CoInitializeEx(None, 0)
    try:
        if shell.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(pointer)) != 0 or not pointer.value:
            raise OSError("Windows could not locate your Downloads folder.")
        return Path(ctypes.wstring_at(pointer))
    finally:
        if pointer.value:
            ole.CoTaskMemFree(pointer)
        if initialized >= 0:
            ole.CoUninitialize()


def download_package(release, publish, cancelled, folder=None, opener=urlopen):
    version = release.get("version")
    platform = PLATFORMS.get(host_target())
    if version_key(version) is None or version.startswith("v") or not platform:
        raise ValueError("Invalid update version or platform.")
    filename = f"STEVE-{version}-{platform}.zip"
    url = release.get("downloadUrl")
    if url not in (f"{RELEASES}/download/{tag}/{filename}" for tag in (version, "v" + version)):
        raise ValueError("Invalid update download URL.")
    def request(address):
        return opener(Request(address, headers={"User-Agent": f"STEVE/{VERSION}"}), timeout=15)
    with request(url + ".sha256") as response:
        checksum = response.read(4097).decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?" + re.escape(filename), checksum)
    if not match:
        raise ValueError("The release checksum is missing or invalid.")
    if cancelled():
        raise InterruptedError("Download cancelled.")
    folder = Path(folder) if folder else downloads_folder()
    folder.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # Unique names preserve existing downloads; only verified files acquire .zip.
        with tempfile.NamedTemporaryFile(prefix=filename[:-4] + "-", suffix=".zip.part", dir=folder, delete=False) as output:
            temporary = Path(output.name)
            digest, received, last_percent = hashlib.sha256(), 0, -1
            with request(url) as response:
                size = int(response.headers.get("Content-Length", 0))
                if size < 0 or size > MAX_PACKAGE_BYTES:
                    raise ValueError("The update package exceeds the download limit.")
                while True:
                    if cancelled():
                        raise InterruptedError("Download cancelled.")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_PACKAGE_BYTES:
                        raise ValueError("The update package exceeds the download limit.")
                    output.write(chunk)
                    digest.update(chunk)
                    percent = min(99, int(received * 100 / size)) if size else None
                    if percent != last_percent:
                        publish(percent)
                        last_percent = percent
                if size and received != size:
                    raise ValueError("The update download was incomplete. Try again.")
        if digest.hexdigest() != match[1].lower():
            raise ValueError("The update checksum did not match. Download it again.")
        if cancelled():
            raise InterruptedError("Download cancelled.")
        destination = temporary.with_suffix("")
        if destination.exists():
            raise OSError("The download filename is already in use. Try again.")
        temporary.rename(destination)
        return destination
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class UpdateDownloader:
    def __init__(self, publish, home=None):
        self.publish = publish
        self.receipt = Path(home) / 'downloaded-update.json' if home else None
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread = None

    def request(self, release):
        with self._lock:
            if self._closed.is_set() or (self._thread and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._run, args=(dict(release),), name="STEVE-Download", daemon=True)
            self._thread.start()

    def _run(self, release):
        def progress(percent):
            if not self._closed.is_set():
                self.publish({"updateDownload": {"state": "downloading", "version": release["version"], "percent": percent}})
        progress(None)
        try:
            cached = self._cached(release)
            if cached:
                if not self._closed.is_set():
                    self.publish({'updateDownload': cached})
                return
            path = download_package(release, progress, self._closed.is_set)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            result = {"state": "ready", "version": release["version"], "path": str(path), "sha256": digest}
            if self.receipt:
                try:
                    self.receipt.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.receipt.with_suffix('.tmp')
                    temporary.write_text(json.dumps(result), encoding='utf-8')
                    temporary.replace(self.receipt)
                except OSError:
                    pass  # A cache failure does not invalidate the verified download.
        except Exception as exc:
            result = {"state": "error", "version": release["version"],
                      "message": str(exc) if isinstance(exc, ValueError) else "Download failed. Check your connection and available disk space, then try again."}
        if not self._closed.is_set():
            self.publish({"updateDownload": result})

    def _cached(self, release):
        if not self.receipt:
            return None
        try:
            cached = json.loads(self.receipt.read_text(encoding='utf-8'))
            path = Path(cached['path'])
            if (cached['version'] != release['version'] or cached['state'] != 'ready'
                    or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PACKAGE_BYTES
                    or not path.name.startswith('STEVE-' + release['version'] + '-') or path.suffix != '.zip'):
                return None
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != cached['sha256']:
                    return None
            return cached
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def close(self):
        self._closed.set()
