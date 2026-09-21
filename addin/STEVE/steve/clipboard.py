"""Read one image on an explicit palette paste request. Never read clipboard text."""
import base64
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

MAX_BYTES = 20 * 1024 * 1024

# An isolated STA process avoids loading UI frameworks into Fusion's Python host.
WINDOWS_READER = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$image = $null
$source = $null
try {
    $data = [System.Windows.Forms.Clipboard]::GetDataObject()
    if ($null -eq $data) { exit 0 }
    if ($data.GetDataPresent('PNG')) {
        $source = $data.GetData('PNG')
        if ($source -is [System.IO.Stream]) {
            $image = [System.Drawing.Image]::FromStream($source)
        }
    }
    if ($null -eq $image -and $data.GetDataPresent([System.Windows.Forms.DataFormats]::Bitmap)) {
        $image = $data.GetData([System.Windows.Forms.DataFormats]::Bitmap)
    }
    if ($null -eq $image) { exit 0 }
    if ([long]$image.Width * $image.Height -gt 40000000) { throw 'Image exceeds 40 megapixels' }
    $scale = [Math]::Min(1.0, 2048.0 / [Math]::Max($image.Width, $image.Height))
    $bitmap = New-Object System.Drawing.Bitmap ([Math]::Max(1, [int]($image.Width * $scale))), ([Math]::Max(1, [int]($image.Height * $scale)))
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try { $graphics.DrawImage($image, 0, 0, $bitmap.Width, $bitmap.Height) }
        finally { $graphics.Dispose() }
        $bitmap.Save($env:STEVE_CLIPBOARD_IMAGE, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $bitmap.Dispose() }
} finally {
    if ($null -ne $image) { $image.Dispose() }
    if ($source -is [System.IDisposable]) { $source.Dispose() }
}
"""

MACOS_READER = r"""
ObjC.import('AppKit');
function run() {
    const board = $.NSPasteboard.generalPasteboard;
    let data = board.dataForType($.NSPasteboardTypePNG);
    if (!data || data.isNil()) data = board.dataForType($.NSPasteboardTypeTIFF);
    if (!data || data.isNil()) return;
    if (Number(data.length) > 160 * 1024 * 1024) throw Error('Clipboard image is too large');
    const bitmap = $.NSBitmapImageRep.imageRepWithData(data);
    if (!bitmap || bitmap.isNil()) throw Error('Cannot decode clipboard image');
    if (Number(bitmap.pixelsWide) * Number(bitmap.pixelsHigh) > 40000000) throw Error('Image exceeds 40 megapixels');
    const png = bitmap.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $({}));
    if (Number(png.length) > 20 * 1024 * 1024) throw Error('Clipboard image is too large');
    const destination = $.NSProcessInfo.processInfo.environment.objectForKey('STEVE_CLIPBOARD_IMAGE');
    if (!png.writeToFileAtomically(destination, true)) throw Error('Cannot read clipboard image');
}
"""


def read_clipboard_image():
    if sys.platform == "win32":
        windows = os.environ.get("SystemRoot")
        executable = Path(windows) / "System32/WindowsPowerShell/v1.0/powershell.exe" if windows else None
        executable = str(executable) if executable and executable.is_file() else shutil.which("powershell.exe")
        if not executable:
            raise RuntimeError("Windows clipboard support requires Windows PowerShell.")
        command = [executable, "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand",
                   base64.b64encode(WINDOWS_READER.encode("utf-16-le")).decode("ascii")]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW}
    elif sys.platform == "darwin":
        executable = shutil.which("osascript")
        if not executable:
            raise RuntimeError("macOS clipboard support requires osascript.")
        command = [executable, "-l", "JavaScript", "-e", MACOS_READER]
        options = {}
    else:
        raise RuntimeError("Image paste is supported on Windows and macOS.")
    with tempfile.TemporaryDirectory(prefix="steve-clipboard-") as scratch:
        path = Path(scratch) / "image.png"
        env = {**os.environ, "STEVE_CLIPBOARD_IMAGE": str(path)}
        try:
            result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10, **options)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Clipboard image read timed out. Copy the screenshot again and retry paste.") from exc
        if result.returncode:
            raise RuntimeError("Could not read the clipboard image. Copy a screenshot of at most 40 megapixels and retry paste.")
        if not path.exists():
            return None
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Clipboard image exceeds 20 MiB. Crop it before pasting.")
        data = path.read_bytes()
        if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
            raise ValueError("The clipboard did not produce a valid PNG image.")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height or width * height > 40000000:
            raise ValueError("Clipboard image exceeds 40 megapixels or has invalid dimensions.")
        return {"name": "Pasted screenshot.png", "url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}
