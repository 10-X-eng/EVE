"""Build a self-contained zip with a per-user installer for this platform."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import json
import subprocess
import zipfile

from audit_portability import audit
from steve_package import VERSION, executable_suffix, installer_name, package_name
from steve.transport import host_target

ROOT = Path(__file__).resolve().parents[1]

START_HERE = {
    ".exe": (
        f"STEVE {VERSION} - Windows preview\n\n"
        "1. Extract the entire zip into a folder.\n"
        "2. Save your work and close Fusion.\n"
        "3. Double-click Install STEVE.exe and choose Install STEVE.\n"
        "4. Open Fusion. Enable STEVE in Scripts and Add-ins if it does not start automatically.\n"
        "5. Open STEVE from the Quick Access toolbar, choose ChatGPT, Grok / X, Claude (experimental), OpenRouter (experimental), or Ollama (local). See INSTALL.md for setup.\n\n"
        "STEVE can inspect your document and run generated Python through Fusion's installed APIs.\n"
        "This is an early execution prototype; save your work before trying model changes.\n"
        "No separate Python, Node, Codex, API key, or STEVE account is required.\n"
        "Claude additionally requires Claude Code, signed in outside Fusion.\n"
        "The installer is currently unsigned.\n"
        "ChatGPT credentials are managed by Codex under %LOCALAPPDATA%\\STEVE\\codex.\n"
        "Use Settings > AI provider to sign out.\n"
        "Read INSTALL.md for first-use instructions, troubleshooting, updates, and uninstalling.\n"
        "Updates preserve old add-in files under API\\STEVE-install-backups.\n"
    ),
    "": (
        f"STEVE {VERSION} - macOS preview (Apple silicon)\n\n"
        "1. Extract the entire zip into a folder.\n"
        "2. Save your work and quit Fusion.\n"
        "3. Open Terminal, type: bash  (with a space), drag \"Install STEVE.command\" into the window, and press Return.\n"
        "   Double-clicking the installer also works once macOS lets you open it under\n"
        "   System Settings > Privacy & Security, because this preview is not signed.\n"
        "4. Open Fusion. Enable STEVE in Scripts and Add-ins if it does not start automatically.\n"
        "5. Open STEVE from the Quick Access toolbar, choose ChatGPT, Grok / X, Claude (experimental), OpenRouter (experimental), or Ollama (local). See INSTALL.md for setup.\n\n"
        "STEVE can inspect your document and run generated Python through Fusion's installed APIs.\n"
        "This is an early execution prototype; save your work before trying model changes.\n"
        "No separate Python, Node, Codex, API key, or STEVE account is required.\n"
        "Claude additionally requires Claude Code, signed in outside Fusion.\n"
        "ChatGPT credentials are managed by Codex under ~/Library/Application Support/STEVE/codex.\n"
        "Use Settings > AI provider to sign out.\n"
        "Read INSTALL.md for first-use instructions, troubleshooting, updates, and uninstalling.\n"
        "Updates preserve old add-in files under API/STEVE-install-backups.\n"
    ),
}


def find_compiler():
    configured = shutil.which("csc")
    if configured:
        return Path(configured)
    windows = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if windows:
        for framework in ("Framework64", "Framework"):
            compiler = Path(windows) / "Microsoft.NET" / framework / "v4.0.30319" / "csc.exe"
            if compiler.is_file():
                return compiler
    raise RuntimeError("Building the Windows installer requires the .NET Framework C# compiler on PATH or under SystemRoot.")


def check_payload(source, target):
    suffix = executable_suffix(target)
    required = ["STEVE.py", "STEVE.manifest", "resources/32x32.png", "panel/panel.js", "panel/fusion.css", "panel/markdown.js", "steve/dream.py",
                "steve/fusion_tools.py", "steve/python_runner.py", "steve/tool_protocol.py", "steve/debug_log.py",
                "runtime/steve-runtime.json", "runtime/codex-package.json",
                f"runtime/bin/codex-app-server{suffix}", f"runtime/bin/codex-code-mode-host{suffix}"]
    for relative in required:
        if not (source / relative).is_file():
            raise RuntimeError(f"Missing {relative}. Fetch the runtime and generate icons before packaging.")
    built_for = json.loads((source / "runtime/steve-runtime.json").read_text(encoding="utf-8")).get("target")
    if built_for and built_for != target:
        raise RuntimeError(f"The fetched runtime is for {built_for}; fetch the {target} runtime before packaging.")


def add_installer(package, target):
    """Compile the Windows installer, or copy the executable macOS installer script."""
    if executable_suffix(target):
        subprocess.run([str(find_compiler()), "/nologo", "/target:winexe", "/optimize+", "/platform:x64",
                        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Web.Extensions.dll",
                        f"/out:{package / installer_name(target)}", str(ROOT / "scripts/installer/Install.cs")], check=True)
        return
    installer = package / installer_name(target)
    shutil.copyfile(ROOT / "scripts/installer" / installer_name(target), installer)
    installer.chmod(0o755)


def main(target=None):
    audit()
    target = target or host_target()
    source = ROOT / "addin" / "STEVE"
    check_payload(source, target)
    if executable_suffix(target):
        find_compiler()
    package = ROOT / "dist" / package_name(target)
    if package.exists():
        raise RuntimeError(f"Package folder already exists: {package}. Rename it before rebuilding.")
    package.mkdir(parents=True)
    payload = package / "STEVE"
    shutil.copytree(source, payload, ignore=shutil.ignore_patterns("__pycache__", ".vscode", "*.pyc", "*.pyo"))
    shutil.copytree(ROOT / "licenses", payload / "licenses")
    shutil.copyfile(ROOT / "LICENSE", payload / "LICENSE")
    shutil.copyfile(ROOT / "LICENSE", package / "LICENSE")
    shutil.copyfile(ROOT / "docs/INSTALL.md", package / "INSTALL.md")
    add_installer(package, target)
    sums = []
    for path in sorted(payload.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sums.append(f"{digest}  {path.relative_to(payload).as_posix()}")
    (package / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (package / "START HERE.txt").write_text(START_HERE[executable_suffix(target)], encoding="utf-8")
    archive = package.parent / (package.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                # ZipInfo.from_file records Unix permission bits, so Finder keeps executables runnable.
                output.write(path, path.relative_to(package))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    audit(archive)
    print(f"Built {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=None, help="Rust target triple; defaults to this machine's platform")
    main(parser.parse_args().target)
