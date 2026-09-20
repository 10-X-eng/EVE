"""Install the complete built zip into a workspace fixture and smoke its runtime."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from eve_package import installer_command, installer_name, package_name  # noqa: E402
from eve.transport import host_target  # noqa: E402


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, default=None)
    parser.add_argument("--target", default=None, help="Rust target triple; defaults to this machine's platform")
    args = parser.parse_args()
    target = args.target or host_target()
    archive = (args.archive or ROOT / "dist" / (package_name(target) + ".zip")).resolve()
    expected = archive.with_suffix(".zip.sha256").read_text().split()[0]
    assert digest(archive) == expected, "Zip checksum mismatch"
    scratch = ROOT / ".cache/package-verification" / str(uuid4())
    package = scratch / "package"
    package.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None, "Zip integrity check failed"
        # Python does not restore Unix permission bits here; the installer must make the runtime executable.
        zipped.extractall(package)
    destination = scratch / "API/AddIns"
    command, options = installer_command(package / installer_name(target), package, destination, target)
    subprocess.run(command, check=True, timeout=120, **options)
    installed = destination / "EVE"
    assert (package / "INSTALL.md").read_bytes() == (ROOT / "docs/INSTALL.md").read_bytes(), "Missing or stale installation guide"
    files = 0
    payload_names = set()
    for line in (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        assert relative not in payload_names, "Duplicate payload entry"
        payload_names.add(relative)
        assert digest(installed / relative) == expected, f"Installed file mismatch: {relative}"
        files += 1
    # Ensure the archive contains this checkout's current add-in, not an older build.
    source = ROOT / "addin/EVE"
    expected_names = set()
    for path in source.rglob("*"):
        if path.is_file() and not {"__pycache__", ".vscode"}.intersection(path.parts) and path.suffix not in (".pyc", ".pyo"):
            expected_names.add(path.relative_to(source).as_posix())
            assert digest(path) == digest(installed / path.relative_to(source)), f"Stale package: {path}"
    for path in (ROOT / "licenses").rglob("*"):
        if path.is_file():
            relative = "licenses/" + path.relative_to(ROOT / "licenses").as_posix()
            expected_names.add(relative)
            assert digest(path) == digest(installed / relative), "Stale license file"
    assert payload_names == expected_names, "Package has missing or obsolete payload files"
    print(f"Complete zip installed; {files} payload files verified against checksums and source", flush=True)
    sys.path.insert(0, str(installed))
    from eve.transport import Transport
    from eve.controller import thread_start_params
    client = Transport(lambda method, params: None, home=scratch / "runtime-home")
    try:
        client.start()
        assert client.request("account/read", {"refreshToken": False}).get("account") is None
        assert client.request("model/list", {"limit": 5}).get("data")
        result = client.request("thread/start", thread_start_params(client.home))
        assert result.get("thread", {}).get("id")
    finally:
        client.close()
    assert client.process.poll() is not None, "Packaged runtime did not exit"
    print("Installed runtime handshake, account/model reads, Code Mode thread, and process exit passed")
    print(f"Fixture: {scratch}")


if __name__ == "__main__":
    main()
