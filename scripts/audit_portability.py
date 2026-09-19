"""Check distributable source or a release zip for machine-specific paths."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".cache", "dist", "node_modules", ".venv", ".vscode", "__pycache__", "runtime", ".codex", ".agents"}
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".json", ".md", ".txt", ".html", ".css", ".cs", ".manifest", ".svg", ".yml", ".yaml", ".toml"}
ABSOLUTE_PATH = re.compile(r"(?i)\b[a-z]:[\\/]|/(?:Users|home)/[\w.-]+/|file:/{3}")


def source_files():
    for directory, subdirs, files in os.walk(ROOT):
        subdirs[:] = [name for name in subdirs if name not in EXCLUDED]
        for name in files:
            path = Path(directory) / name
            if path.suffix not in {".pyc", ".pyo"}:
                yield path


def local_markers():
    markers = set()
    for path in (ROOT, Path.home()):
        for spelling in (str(path), path.as_posix(), str(path).replace("\\", "\\\\")):
            markers.add(spelling.encode("utf-8").lower())
            markers.add(spelling.encode("utf-16-le").lower())
    return markers


def inspect(name, stream):
    """Stream binaries too: an installer must not embed the build user's path."""
    markers = local_markers()
    overlap = max(map(len, markers))
    tail = b""
    while chunk := stream.read(1024 * 1024):
        data = tail + chunk
        if any(marker in data.lower() for marker in markers):
            return f"{name}: contains this machine's checkout or profile path"
        if Path(name).suffix.lower() in TEXT_SUFFIXES:
            if ABSOLUTE_PATH.search(data.decode("utf-8", errors="replace")):
                return f"{name}: contains a literal absolute filesystem path"
        tail = data[-max(overlap, 512):]
    return None


def verified_runtime_hashes():
    """Identify upstream binaries by bytes, never by an allowlisted path alone."""
    from fetch_runtime import ARCHIVE, SHA256
    archive = ROOT / ".cache" / ARCHIVE
    if not archive.is_file():
        return {}
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
            raise RuntimeError("Upstream runtime archive checksum mismatch")
    hashes = {}
    with tarfile.open(archive) as package:
        for member in package:
            if member.isfile() and Path(member.name).suffix.lower() == ".exe":
                with package.extractfile(member) as stream:
                    hashes["EVE/runtime/" + Path(member.name).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashes


def unchanged_upstream_binary(name, stream, hashes):
    expected = hashes.get(name)
    return expected is not None and hashlib.file_digest(stream, "sha256").hexdigest() == expected


def audit(archive=None):
    failures = []
    count = 0
    upstream_hashes = None
    if archive:
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if entry.is_dir():
                    continue
                if {".vscode", "__pycache__"}.intersection(Path(entry.filename).parts) or Path(entry.filename).suffix in {".pyc", ".pyo"}:
                    failures.append(f"{entry.filename}: local debugger or bytecode artifact")
                with package.open(entry) as stream:
                    failure = inspect(entry.filename, stream)
                if failure and entry.filename.startswith("EVE/runtime/") and Path(entry.filename).suffix.lower() == ".exe":
                    # Vendor debug strings can name the same generic CI profile.
                    # Accept them only when the entire binary matches the pinned download.
                    if upstream_hashes is None:
                        upstream_hashes = verified_runtime_hashes()
                    with package.open(entry) as stream:
                        if unchanged_upstream_binary(entry.filename, stream, upstream_hashes):
                            failure = None
                count += 1
                if failure:
                    failures.append(failure)
    else:
        for path in source_files():
            with path.open("rb") as stream:
                failure = inspect(path.relative_to(ROOT).as_posix(), stream)
            count += 1
            if failure:
                failures.append(failure)
    if failures:
        raise RuntimeError("Portability audit failed:\n" + "\n".join(failures))
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    print(f"Portability audit passed: {audit(args.archive)} files")
