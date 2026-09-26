"""Verify downloads and prepare an independent in-Fusion updater."""
import json
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
from uuid import uuid4
import zipfile

from .updates import PLATFORMS, version_key
from .transport import host_target
from .update_transaction import managed, prepare

MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024


def prepare_live_update(package, installed, home, version):
    return prepare(package, installed, home, version)


def launch_live_update(app, helper):
    """Main-thread call only. The helper runs outside the add-in being replaced."""
    script = app.scripts.addExisting(str(helper))
    if not script:
        raise RuntimeError('Fusion could not start the STEVE updater. Your installed files are unchanged.')
    try:
        if not script.run(False):
            raise RuntimeError('Fusion could not start the STEVE updater. Your installed files are unchanged.')
    except Exception:
        script.isRunOnStartup = False
        script.unlink()
        raise


def _verify_staged(archive, destination):
    """A previous attempt's files are not trusted merely because they exist."""
    with zipfile.ZipFile(archive) as source:
        expected = {entry.filename for entry in source.infolist() if not entry.is_dir()}
        actual = set()
        for path in destination.rglob("*"):
            if path.is_symlink():
                raise ValueError("The staged update contains a filesystem link.")
            if path.is_file():
                actual.add(path.relative_to(destination).as_posix())
        if actual - {"install-result.txt"} != expected:
            raise ValueError("The staged update differs from the verified archive. Remove the staged folder and retry.")
        for entry in source.infolist():
            if entry.is_dir():
                continue
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            with source.open(entry) as original, target.open("rb") as staged:
                digest = hashlib.sha256()
                while chunk := original.read(256 * 1024):
                    digest.update(chunk)
                if digest.digest() != hashlib.file_digest(staged, "sha256").digest():
                    raise ValueError("The staged update differs from the verified archive. Remove the staged folder and retry.")


def previous_install_result(home, current):
    """Show only failed attempts at a newer version, never an old success."""
    root = Path(home) / "pending-updates"
    failures = []
    current_key = version_key(current)
    if current_key is None:
        return None
    for folder in root.glob("STEVE-*"):
        if not folder.is_dir() or folder.is_symlink():
            continue
        name = folder.name
        if not (name.endswith("-macos-arm64") or name.endswith("-windows-x64")):
            continue
        version = name.removeprefix("STEVE-").removesuffix("-macos-arm64").removesuffix("-windows-x64")
        release_key = version_key(version)
        if release_key is None or release_key <= current_key:
            continue
        result = folder / "install-result.txt"
        if result.is_file() and not result.is_symlink():
            text = result.read_text(encoding="utf-8", errors="replace")[:2048]
            if "Installation failed" in text:
                failures.append((release_key, f"STEVE {version} update failed. {text.strip()} See {result} for details."))
    return max(failures, default=(None, None))[1]


def stage_update(archive, version, home, addins, platform=None, expected_digest=None):
    platform = platform or sys.platform
    label = PLATFORMS.get(host_target())
    if platform not in ("win32", "darwin") or not label or version_key(version) is None or version.startswith("v"):
        raise ValueError("Unsupported update version or platform.")
    archive, home, addins = Path(archive), Path(home), Path(addins)
    if archive.name != f"STEVE-{version}-{label}.zip" and not archive.name.startswith(f"STEVE-{version}-{label}-"):
        raise ValueError("The downloaded package does not match the update version.")
    if expected_digest is not None:
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected_digest:
                raise ValueError("The downloaded update checksum changed. Download it again.")
    installed = addins / "STEVE"
    if (installed.is_symlink() or not installed.is_dir() or
            not (installed / "steve-install-marker.txt").is_file() or
            (installed / "steve-install-marker.txt").read_text(encoding="utf-8").strip() != "STEVE managed installation"):
        raise ValueError("Automatic installation requires a managed STEVE installation. Use the manual installer for a source checkout.")
    destination = home / "pending-updates" / f"STEVE-{version}-{label}"
    if destination.is_dir() and not destination.is_symlink() and (destination / "SHA256SUMS").is_file():
        _verify_staged(archive, destination)
        return destination
    if destination.exists() or destination.is_symlink():
        raise ValueError("An incomplete update is already staged. Remove it before retrying.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / (".staging-" + uuid4().hex)
    staging.mkdir()
    installer = "Install STEVE.exe" if platform == "win32" else "Install STEVE.command"
    try:
        with zipfile.ZipFile(archive) as source:
            names, total = set(), 0
            if len(source.infolist()) > 20000:
                raise ValueError("The update archive contains too many files.")
            for entry in source.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                mode = entry.external_attr >> 16
                segments = name.rstrip("/").split("/")
                if (not name or "\\" in name or name.startswith("/") or any(p in ("", ".", "..") for p in segments)
                        or (parts[0] != "STEVE" and name not in (installer, "SHA256SUMS", "INSTALL.md", "START HERE.txt", "LICENSE"))
                        or name in names):
                    raise ValueError("The update archive contains an invalid path.")
                names.add(name)
                if stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError("The update archive contains a filesystem link or special file.")
                total += entry.file_size
                if total > MAX_EXTRACT_BYTES:
                    raise ValueError("The update archive is too large to extract.")
            if not {installer, "SHA256SUMS", "STEVE/STEVE.manifest", "STEVE/STEVE.py"}.issubset(names):
                raise ValueError("The update archive is incomplete.")
            for entry in source.infolist():
                target = staging.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(entry) as input_file, target.open("xb") as output:
                        shutil.copyfileobj(input_file, output)
        metadata = json.loads((staging / "STEVE/STEVE.manifest").read_text(encoding="utf-8"))
        if metadata.get("version") != version:
            raise ValueError("The package manifest version does not match the release.")
        staging.rename(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def launch_update(package, platform=None):
    """Detached installer waits for Fusion to exit; it never terminates Fusion."""
    platform = platform or sys.platform
    package = Path(package)
    installer = package / ("Install STEVE.exe" if platform == "win32" else "Install STEVE.command")
    log = package / "install-result.txt"
    command = ([str(installer), "--auto-install", str(log)] if platform == "win32" else
               ["/bin/bash", str(installer), "--auto-install", str(log)])
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "cwd": str(package), "close_fds": True}
    if platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    elif platform == "darwin":
        options["start_new_session"] = True
    else:
        raise ValueError("Automatic installation is not supported on this platform.")
    subprocess.Popen(command, **options)
    return log
