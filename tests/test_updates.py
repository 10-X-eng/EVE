"""Release discovery uses public metadata, never credentials or installation writes."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin/STEVE"))
from steve.updates import RELEASES, UpdateChecker, check_release, select_release
from steve.version import VERSION


def release(version="0.3.0", platforms=("windows-x64", "macos-arm64")):
    tag = "v" + version
    return {"tag_name": tag, "draft": False, "prerelease": True, "published_at": "2026-09-20T00:00:00Z",
            "assets": [{"name": name, "state": "uploaded", "size": 100,
                        "browser_download_url": f"{RELEASES}/download/{tag}/{name}"}
                       for platform in platforms for name in
                       (f"STEVE-{version}-{platform}.zip", f"STEVE-{version}-{platform}.zip.sha256")]}


class ReleaseTests(unittest.TestCase):
    def choose(self, releases, target="x86_64-pc-windows-msvc"):
        return select_release(releases, current="0.2.0", target=target)

    def test_preview_versions_are_numeric_and_platform_specific(self):
        releases = [release("0.3.0"), release("0.10.0"), release("0.9.0")]
        self.assertEqual(self.choose(releases)["version"], "0.10.0")
        self.assertTrue(self.choose(releases)["downloadUrl"].endswith("windows-x64.zip"))
        self.assertTrue(self.choose(releases, "aarch64-apple-darwin")["downloadUrl"].endswith("macos-arm64.zip"))

    def test_equal_older_drafts_and_invalid_tags_are_ignored(self):
        releases = [release("0.1.0"), release("0.2.0"), release("0.3.0-beta"), release("../../evil")]
        draft = release("0.4.0")
        draft["draft"] = True
        releases.append(draft)
        self.assertIsNone(self.choose(releases))

    def test_incomplete_assets_and_foreign_urls_are_ignored(self):
        good = release()
        broken = []
        for key, value in (("state", "new"), ("size", 0), ("browser_download_url", "https://example.com/evil.zip")):
            item = copy.deepcopy(good)
            item["assets"][0][key] = value
            broken.append(item)
        item = copy.deepcopy(good)
        item["assets"].pop(1)
        broken.append(item)
        broken.append(release(platforms=("macos-arm64",)))
        for item in broken:
            with self.subTest(item=item):
                self.assertIsNone(self.choose([item]))

    def test_release_links_are_constructed_from_validated_tag(self):
        data = release()
        data["html_url"] = "https://example.com/foreign"
        self.assertEqual(self.choose([data])["releaseUrl"], RELEASES + "/tag/v0.3.0")

    def test_malformed_response_and_unsupported_platform_fail_explicitly(self):
        with self.assertRaises(ValueError):
            self.choose({"message": "rate limited"})
        with self.assertRaises(ValueError):
            self.choose([], "x86_64-apple-darwin")
        self.assertIsNone(self.choose([None, {"tag_name": []}]))

    def test_http_request_is_bounded_and_has_no_authentication(self):
        major, minor, patch_number = (int(part) for part in VERSION.split("."))
        future_version = f"{major}.{minor}.{patch_number + 1}"
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([release(future_version)]).encode()
        with patch("steve.updates.urlopen", return_value=response) as urlopen:
            self.assertEqual(check_release()["version"], future_version)
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith("https://api.github.com/repos/10-X-eng/STEVE/releases?"))
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        response.__enter__.return_value.read.assert_called_once_with(2 * 1024 * 1024 + 1)
        response.__enter__.return_value.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
        with patch("steve.updates.urlopen", return_value=response), self.assertRaises(ValueError):
            check_release()

    def test_background_check_coalesces_clicks_and_drops_result_after_close(self):
        entered, finish = threading.Event(), threading.Event()
        events, calls = [], []
        def fetch():
            calls.append(True)
            entered.set()
            finish.wait(2)
            return None
        checker = UpdateChecker(events.append, fetch=fetch)
        try:
            checker.request()
            self.assertTrue(entered.wait(2))
            for _ in range(10):
                checker.request()
            checker.close()
            finish.set()
            checker._thread.join(2)
            self.assertEqual(len(calls), 1)
            self.assertEqual(events, [{"updateChecking": True, "updateStatus": "Checking for updates…"}])
        finally:
            finish.set()
            checker.close()

    def test_periodic_checks_recover_after_network_failure(self):
        done, calls, events = threading.Event(), [], []
        def fetch():
            calls.append(True)
            if len(calls) == 1:
                raise OSError("offline")
            return {"version": "0.3.0"}
        def publish(event):
            events.append(event)
            if event.get("updateInfo"):
                done.set()
        checker = UpdateChecker(publish, fetch=fetch, interval=0.02)
        try:
            checker.request()
            self.assertTrue(done.wait(2))
            self.assertTrue(any("Couldn’t check" in event["updateStatus"] for event in events))
            self.assertTrue(any(event.get("updateInfo") for event in events))
        finally:
            checker.close()
            checker._thread.join(2)


if __name__ == "__main__":
    unittest.main()
