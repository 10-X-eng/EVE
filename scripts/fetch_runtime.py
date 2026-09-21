"""Download and verify the complete pinned Codex app-server package for a platform."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "STEVE"))
from steve.transport import VERSION, host_target  # noqa: E402

# SHA-256 digests of the upstream release archives, one per supported platform.
PACKAGES = {
    "x86_64-pc-windows-msvc": "69441ca4c8f6197923dc1b70a8aa870ff912b5367347287d021eaca1f3add971",
    "aarch64-apple-darwin": "90f0467fd03294896204e8856bf969a0691590e8bef78dc2563a264b186f3265",
}


def archive_name(target):
    return f"codex-app-server-package-{target}.tar.gz"


def archive_digest(target):
    if target not in PACKAGES:
        raise RuntimeError(f"No pinned Codex package for {target}. Supported: {', '.join(PACKAGES)}")
    return PACKAGES[target]


def cached_archive(target):
    return ROOT / ".cache" / archive_name(target)


def fetch(target=None):
    target = target or host_target()
    sha256 = archive_digest(target)
    archive = cached_archive(target)
    archive.parent.mkdir(exist_ok=True)
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
    if (destination / "steve-runtime.json").is_file():
        # Replace an earlier runtime completely so no other platform's files remain.
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as package:
        package.extractall(destination, filter="data")
    suffix = ".exe" if target.endswith("-windows-msvc") else ""
    executable = destination / "bin" / ("codex-app-server" + suffix)
    if not executable.is_file() or not executable.with_name("codex-code-mode-host" + suffix).is_file():
        raise RuntimeError("The downloaded package has an unexpected layout.")
    (destination / "steve-runtime.json").write_text(
        json.dumps({"version": VERSION, "target": target, "archive": archive.name, "sha256": sha256}, indent=2),
        encoding="utf-8",
    )
    print(f"Verified Codex {VERSION} ({target}): {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(PACKAGES), default=None,
                        help="Rust target triple; defaults to this machine's platform")
    fetch(parser.parse_args().target)


if __name__ == "__main__":
    main()
