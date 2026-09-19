"""Build a self-contained Windows zip with a per-user GUI installer."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from audit_portability import audit

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"


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


def main():
    audit()
    source = ROOT / "addin" / "EVE"
    required = ["EVE.py", "EVE.manifest", "resources/32x32.png", "panel/panel.js", "panel/fusion.css",
                "eve/fusion_tools.py", "eve/python_runner.py", "eve/tool_protocol.py", "eve/debug_log.py",
                "runtime/eve-runtime.json", "runtime/codex-package.json",
                "runtime/bin/codex-app-server.exe", "runtime/bin/codex-code-mode-host.exe"]
    for relative in required:
        if not (source / relative).is_file():
            raise RuntimeError(f"Missing {relative}. Fetch the runtime and generate icons before packaging.")
    compiler = find_compiler()
    package = ROOT / "dist" / f"EVE-{VERSION}-windows-x64"
    if package.exists():
        raise RuntimeError(f"Package folder already exists: {package}. Rename it before rebuilding.")
    package.mkdir(parents=True)
    payload = package / "EVE"
    shutil.copytree(source, payload, ignore=shutil.ignore_patterns("__pycache__", ".vscode", "*.pyc", "*.pyo"))
    shutil.copytree(ROOT / "licenses", payload / "licenses")
    shutil.copyfile(ROOT / "docs/INSTALL.md", package / "INSTALL.md")
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/optimize+", "/platform:x64",
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    f"/out:{package / 'Install EVE.exe'}", str(ROOT / "scripts/installer/Install.cs")], check=True)
    sums = []
    for path in sorted(payload.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sums.append(f"{digest}  {path.relative_to(payload).as_posix()}")
    (package / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (package / "START HERE.txt").write_text(
        "EVE 0.1.0 - Windows preview\n\n"
        "1. Extract the entire zip into a folder.\n"
        "2. Save your work and close Fusion.\n"
        "3. Double-click Install EVE.exe and choose Install EVE.\n"
        "4. Open Fusion. Enable EVE in Scripts and Add-ins if it does not start automatically.\n"
        "5. Open EVE from the Quick Access toolbar and choose Sign in with ChatGPT.\n\n"
        "EVE can inspect your document and run generated Python through Fusion's installed APIs.\n"
        "This is an early execution prototype; save your work before trying model changes.\n"
        "No separate Python, Node, Codex, API key, or EVE account is required.\n"
        "The installer is currently unsigned.\n"
        "ChatGPT credentials are managed by Codex under %LOCALAPPDATA%\\EVE\\codex.\n"
        "Use the EVE account menu to sign out.\n"
        "Read INSTALL.md for first-use instructions, troubleshooting, updates, and uninstalling.\n"
        "Updates preserve old add-in files under API\\EVE-install-backups.\n",
        encoding="utf-8",
    )
    archive = package.parent / (package.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in package.rglob("*"):
            if path.is_file():
                output.write(path, path.relative_to(package))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    audit(archive)
    print(f"Built {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    main()
