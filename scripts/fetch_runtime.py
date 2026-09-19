"""Download and verify the complete pinned Windows Codex app-server package."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

VERSION = "0.153.4"
ARCHIVE = "codex-app-server-package-x86_64-pc-windows-msvc.tar.gz"
SHA256 = "69441ca4c8f6197923dc1b70a8aa870ff912b5367347287d021eaca1f3add971"
ROOT = Path(__file__).resolve().parents[1]


def main():
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    archive = cache / ARCHIVE
    if not archive.exists():
        print(f"Downloading Codex {VERSION}…", flush=True)
        partial = archive.with_suffix(".partial")
        urllib.request.urlretrieve(
            f"https://github.com/openai/codex/releases/download/rust-v{VERSION}/{ARCHIVE}",
            partial,
        )
        partial.replace(archive)
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != SHA256:
        raise RuntimeError("Codex package checksum mismatch; remove the cached archive and retry.")
    destination = ROOT / "addin" / "EVE" / "runtime"
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as package:
        package.extractall(destination, filter="data")
    executable = destination / "bin" / "codex-app-server.exe"
    if not executable.is_file() or not executable.with_name("codex-code-mode-host.exe").is_file():
        raise RuntimeError("The downloaded package has an unexpected layout.")
    (destination / "eve-runtime.json").write_text(
        json.dumps({"version": VERSION, "archive": ARCHIVE, "sha256": SHA256}, indent=2),
        encoding="utf-8",
    )
    print(f"Verified Codex {VERSION}: {destination}")


if __name__ == "__main__":
    main()
