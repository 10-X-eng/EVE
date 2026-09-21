"""Read public release metadata off the Fusion thread; never replace live files."""
import json
import re
import threading
from urllib.request import Request, urlopen

from .transport import host_target
from .version import VERSION

RELEASES = "https://github.com/10-X-eng/STEVE/releases"
API = "https://api.github.com/repos/10-X-eng/STEVE/releases?per_page=30"
PLATFORMS = {"x86_64-pc-windows-msvc": "windows-x64", "aarch64-apple-darwin": "macos-arm64"}
INTERVAL = 12 * 60 * 60


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        return None
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def select_release(releases, current=VERSION, target=None):
    platform = PLATFORMS.get(target or host_target())
    if not platform:
        raise ValueError("No STEVE package is available for this platform.")
    if not isinstance(releases, list) or version_key(current) is None:
        raise ValueError("Invalid release metadata.")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or not release.get("published_at"):
            continue
        tag = release.get("tag_name")
        version = version_key(tag)
        if version is None or version <= version_key(current):
            continue
        # Preview releases are intentional. /latest excludes them.
        number = tag.removeprefix("v")
        filename = f"STEVE-{number}-{platform}.zip"
        download = f"{RELEASES}/download/{tag}/{filename}"
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        ready = {asset.get("name") for asset in assets if isinstance(asset, dict)
                 and asset.get("state") == "uploaded" and isinstance(asset.get("size"), int)
                 and asset["size"] > 0 and asset.get("name") in (filename, filename + ".sha256")
                 and asset.get("browser_download_url") == f"{RELEASES}/download/{tag}/{asset['name']}"}
        if filename in ready and filename + ".sha256" in ready:
            candidates.append((version, {"version": number, "releaseUrl": f"{RELEASES}/tag/{tag}",
                                         "downloadUrl": download}))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def check_release():
    request = Request(API, headers={"Accept": "application/vnd.github+json",
                                   "User-Agent": f"STEVE/{VERSION}", "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=10) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Release metadata is too large.")
    return select_release(json.loads(data))


class UpdateChecker:
    def __init__(self, publish, fetch=check_release, interval=INTERVAL):
        self.publish, self.fetch, self.interval = publish, fetch, interval
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._checking = False
        self._thread = None

    def request(self):
        with self._lock:
            if self._closed or self._checking:
                return
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="STEVE-Updates", daemon=True)
                self._thread.start()
            else:
                self._wake.set()

    def _run(self):
        while True:
            with self._lock:
                if self._closed:
                    return
                self._checking = True
                self._wake.clear()
            self.publish({"updateChecking": True, "updateStatus": "Checking for updates…"})
            try:
                release = self.fetch()
                result = {"updateChecking": False, "updateInfo": release,
                          "updateStatus": f"STEVE {release['version']} is available" if release else "You’re up to date"}
            except Exception:
                result = {"updateChecking": False,
                          "updateStatus": "Couldn’t check for updates. Check your connection and try again."}
            with self._lock:
                if self._closed:
                    return
                self._checking = False
            self.publish(result)
            self._wake.wait(self.interval)

    def close(self):
        with self._lock:
            self._closed = True
            self._wake.set()
