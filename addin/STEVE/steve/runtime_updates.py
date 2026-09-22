"""Independent Codex updates: verified side-by-side installs, used on next start."""
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile
import threading
from urllib.request import Request, urlopen
from uuid import uuid4

from .transport import data_home, host_target, runtime_command, runtime_version, selected_runtime
from .updates import UpdateChecker, version_key

RELEASES = "https://github.com/openai/codex/releases"
API = "https://api.github.com/repos/openai/codex/releases/latest"
TARGETS = {"x86_64-pc-windows-msvc", "aarch64-apple-darwin"}
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def select_release(release, current, target):
    """Accept only stable official app-server packages, with GitHub's SHA-256."""
    if target not in TARGETS:
        raise ValueError("No Codex update package is available for this platform.")
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise ValueError("Expected a published stable Codex release.")
    tag = release.get("tag_name", "")
    version = tag.removeprefix("rust-v")
    if not tag.startswith("rust-v") or version_key(version) is None or not release.get("published_at"):
        raise ValueError("Invalid Codex release metadata.")
    if version_key(current) and version_key(version) <= version_key(current):
        return None
    filename = f"codex-app-server-package-{target}.tar.gz"
    url = f"{RELEASES}/download/{tag}/{filename}"
    for asset in release.get("assets", []):
        if asset.get("name") != filename or asset.get("browser_download_url") != url:
            continue
        digest = asset.get("digest", "")
        size = asset.get("size")
        if (not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
                or type(size) is not int or not 0 < size <= MAX_DOWNLOAD or asset.get("state") != "uploaded"):
            raise ValueError("The Codex release has no valid package checksum or size.")
        return {"version": version, "target": target, "downloadUrl": url, "sha256": digest[7:], "size": size}
    raise ValueError("The latest Codex release has no complete package for this platform yet.")


def check_release(home=None, target=None, opener=urlopen):
    request = Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "STEVE"})
    with opener(request, timeout=15) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Codex release metadata is too large.")
    return select_release(json.loads(raw), runtime_version(selected_runtime(home, target)), target or host_target())


def extract_package(archive, destination, version, target, sha256):
    """Extract into an empty staging directory; never overwrite a live runtime."""
    with tarfile.open(archive) as package:
        members = package.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > MAX_EXPANDED:
            raise ValueError("The Codex package exceeds the extraction limit.")
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected link or special file in the Codex package.")
            # Reject Windows drive names, backslashes and parent traversal on every OS.
            if "\\" in member.name or ":" in member.name or ".." in Path(member.name).parts:
                raise ValueError("Unsafe path in the Codex package.")
            resolved = (destination / member.name).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe path in the Codex package.")
        package.extractall(destination, members=members, filter="data")
    metadata = json.loads((destination / "codex-package.json").read_text(encoding="utf-8"))
    if (metadata.get("version") != version or metadata.get("target") != target
            or metadata.get("layoutVersion") != 1 or metadata.get("variant") != "codex-app-server"):
        raise ValueError("Unexpected Codex package version, target, or layout.")
    (destination / "steve-runtime.json").write_text(json.dumps({
        "version": version, "target": target, "sha256": sha256,
        "archive": f"codex-app-server-package-{target}.tar.gz",
    }), encoding="utf-8")
    runtime_command(destination, target)


def probe_runtime(root, home):
    """Exercise STEVE's required protocol without signing in or requesting inference."""
    from .controller import thread_start_params
    from .transport import Transport
    client = Transport(lambda *_: None, command=runtime_command(root), home=home)
    try:
        client.start()
        client.request("account/read", {"refreshToken": False})
        models = client.request("model/list", {"limit": 1})
        if not isinstance(models.get("data"), list) or not models["data"]:
            raise ValueError("Codex did not return a model catalog.")
        thread = client.request("thread/start", thread_start_params(home))
        thread_id = thread.get("thread", {}).get("id")
        if not thread_id:
            raise ValueError("Codex could not create a thread with STEVE's tools.")
        client.request("thread/goal/get", {"threadId": thread_id})
    finally:
        client.close()


def write_selection(folder, selection):
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / ("selection-" + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(selection), encoding="utf-8")
        temporary.replace(folder / "active.json")
        saved = json.loads((folder / "active.json").read_text(encoding="utf-8"))
        if saved != selection:
            raise RuntimeError("Codex runtime selection was not saved. Check access to STEVE's data folder and retry.")
    finally:
        temporary.unlink(missing_ok=True)


def install_release(release, publish, cancelled, home=None, opener=urlopen, probe=probe_runtime):
    target = host_target()
    version = release.get("version", "")
    digest = release.get("sha256", "")
    size = release.get("size")
    if (version_key(version) is None or version.startswith("v") or release.get("target") != target
            or target not in TARGETS or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or type(size) is not int or not 0 < size <= MAX_DOWNLOAD):
        raise ValueError("Invalid Codex update metadata. Check for updates again.")
    url = f"{RELEASES}/download/rust-v{version}/codex-app-server-package-{target}.tar.gz"
    if release.get("downloadUrl") != url:
        raise ValueError("Invalid Codex download URL.")
    folder = Path(home or data_home()) / "runtimes"
    folder.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory only removes its own staging tree, never an installed runtime.
    with tempfile.TemporaryDirectory(prefix="staging-", dir=folder) as staging:
        staging = Path(staging)
        archive = staging / "package.tar.gz"
        received, last_percent, checksum = 0, -1, hashlib.sha256()
        request = Request(url, headers={"User-Agent": "STEVE"})
        with opener(request, timeout=15) as response, archive.open("wb") as output:
            while True:
                if cancelled():
                    raise InterruptedError("Codex update cancelled.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > size:
                    raise ValueError("Codex download exceeds the published size.")
                output.write(chunk)
                checksum.update(chunk)
                percent = min(99, received * 100 // size)
                if percent != last_percent:
                    publish(f"Downloading Codex {version}… {percent}%")
                    last_percent = percent
        if received != size or checksum.hexdigest() != digest:
            raise ValueError("Codex download checksum or size mismatch. Try again.")
        if cancelled():
            raise InterruptedError("Codex update cancelled.")
        publish("Verifying Codex startup, models, Fusion tool declarations, and goals…")
        candidate = staging / "runtime"
        candidate.mkdir()
        extract_package(archive, candidate, version, target, digest)
        probe(candidate, staging / "probe")
        if cancelled():
            raise InterruptedError("Codex update cancelled.")
        name = f"codex-{version}-{uuid4().hex}"
        candidate.rename(folder / name)
        # Existing runtimes stay untouched, including the one currently in use.
        write_selection(folder, {"directory": name})
    return version


class RuntimeUpdater:
    def __init__(self, publish, home=None):
        self.publish = publish
        self.home = Path(home or data_home())
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._installing = False
        self.checker = UpdateChecker(self._checked, fetch=lambda: check_release(self.home))

    def _checked(self, result):
        mapped = {"codex" + key[0].upper() + key[1:]: value for key, value in result.items()}
        release = result.get("updateInfo")
        if "updateInfo" in result:
            mapped["codexUpdateStatus"] = f"Codex {release['version']} is available" if release else "Codex is up to date"
        with self._lock:
            if self._closed.is_set() or self._installing:
                return
            self.publish(mapped)

    def request(self):
        self.checker.request()

    def install(self, release):
        with self._lock:
            if self._closed.is_set() or self._installing:
                return
            self._installing = True
            self.publish({"codexUpdating": True, "codexUpdateChecking": False, "codexUpdateStatus": "Preparing Codex update…"})
        threading.Thread(target=self._install, args=(dict(release),), name="STEVE-Codex-Update", daemon=True).start()

    def _install(self, release):
        try:
            version = install_release(release, lambda message: self.publish({"codexUpdateStatus": message}),
                                      self._closed.is_set, self.home)
            if runtime_version(selected_runtime(self.home)) != version:
                raise RuntimeError("The downloaded runtime was not selected. Check access to STEVE's data folder and retry.")
            result = {"codexPendingVersion": version, "codexUpdateInfo": None,
                      "codexUpdateStatus": f"Codex {version} is ready. Restart STEVE to use it and refresh models."}
        except Exception as exc:
            result = {"codexUpdateStatus": f"Codex update failed. Your current runtime is unchanged. {exc}"}
        with self._lock:
            self._installing = False
            if not self._closed.is_set():
                self.publish({"codexUpdating": False, **result})

    def use_bundled(self):
        with self._lock:
            if self._closed.is_set() or self._installing:
                return
            write_selection(self.home / "runtimes", {})
            from .transport import bundled_runtime
            self.publish({"codexPendingVersion": runtime_version(bundled_runtime()), "codexUpdateInfo": None,
                          "codexUpdateStatus": "Bundled Codex selected. Restart STEVE to use it."})

    def close(self):
        self._closed.set()
        self.checker.close()
