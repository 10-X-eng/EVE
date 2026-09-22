"""Download and verify the complete pinned Codex app-server package for a platform."""
import argparse
import hashlib
from pathlib import Path
import sys
import tempfile
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
from steve.transport import VERSION, host_target  # noqa: E402
from steve.runtime_updates import extract_package  # noqa: E402

# SHA-256 digests of the upstream release archives, one per supported platform.
PACKAGES = {
    "x86_64-pc-windows-msvc": "fcb5234b13ca915a68a1de1e4bcdcca1c789da5702f2f281733882608570aee7",
    "aarch64-apple-darwin": "328e5a416bf64f96e3162439c8c39819c164f1a9cff983ca6f09eb3af90bd760",
}


def archive_name(target):
    return f"codex-app-server-package-{target}.tar.gz"


def archive_digest(target):
    if target not in PACKAGES:
        raise RuntimeError(f"No pinned Codex package for {target}. Supported: {', '.join(PACKAGES)}")
    return PACKAGES[target]


def cached_archive(target):
    return ROOT / ".cache" / ("codex-" + VERSION) / archive_name(target)


def fetch(target=None):
    target = target or host_target()
    sha256 = archive_digest(target)
    archive = cached_archive(target)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print(f"Downloading Codex {VERSION} for {target}…", flush=True)
        partial = archive.with_suffix(".partial")
        urllib.request.urlretrieve(
            f"https://github.com/openai/codex/releases/download/rust-v{VERSION}/{archive.name}",
            partial,
        )
        partial.replace(archive)
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != sha256:
        raise RuntimeError("Codex package checksum mismatch; remove the cached archive and retry.")
    destination = ROOT / "addin" / "STEVE" / "runtime"
    backup = ROOT / ".cache" / ("runtime-before-" + uuid4().hex)
    if not destination.resolve().is_relative_to(ROOT.resolve()) or not backup.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("Runtime build paths must remain inside this checkout.")
    with tempfile.TemporaryDirectory(prefix="runtime-build-", dir=ROOT / ".cache") as staging:
        candidate = Path(staging) / "runtime"
        candidate.mkdir()
        extract_package(archive, candidate, VERSION, target, sha256)
        if destination.exists():
            try:
                destination.rename(backup)
            except OSError as exc:
                raise RuntimeError("Stop the local STEVE add-in before replacing its development runtime. The existing runtime was preserved.") from exc
        try:
            candidate.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
    print(f"Verified Codex {VERSION} ({target}): {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(PACKAGES), default=None,
                        help="Rust target triple; defaults to this machine's platform")
    fetch(parser.parse_args().target)


if __name__ == "__main__":
    main()
