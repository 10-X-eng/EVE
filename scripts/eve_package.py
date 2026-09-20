"""Shared package naming for the build, verification, and installer checks."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin" / "EVE"))
from eve.transport import host_target  # noqa: E402

from eve.version import VERSION  # noqa: E402
PLATFORM_LABELS = {"x86_64-pc-windows-msvc": "windows-x64", "aarch64-apple-darwin": "macos-arm64"}


def executable_suffix(target):
    return ".exe" if target.endswith("-windows-msvc") else ""


def package_name(target=None):
    target = target or host_target()
    if target not in PLATFORM_LABELS:
        raise RuntimeError(f"EVE has no package definition for {target}. Supported: {', '.join(PLATFORM_LABELS)}")
    return f"EVE-{VERSION}-{PLATFORM_LABELS[target]}"


def installer_name(target=None):
    return "Install EVE.exe" if executable_suffix(target or host_target()) else "Install EVE.command"


def installer_command(installer, package, destination, target=None):
    """Command and Popen options that run an installer in its test mode against a package folder."""
    if executable_suffix(target or host_target()):
        return [str(installer), "--test-install", str(package), str(destination)], \
            {"creationflags": subprocess.CREATE_NO_WINDOW}
    return ["bash", str(installer), "--test-install", str(package), str(destination)], {}
