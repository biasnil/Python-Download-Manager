# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build for PyDM.

    pip install pyinstaller
    pyinstaller PyDM.spec --noconfirm

Result:  dist/PyDM/PyDM.exe   (+ dist/PyDM/extension for the browser)

Choices that matter:
  • one-folder build (not --onefile): starts faster and is flagged by
    antivirus far less often than a self-extracting single .exe
  • UPX compression OFF: UPX-packed files are a classic false-positive trigger
  • Windows version info embedded: an .exe with a proper name/company/version
    looks less anonymous to Defender / SmartScreen
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
APP_NAME = "PyDM"
VERSION = (1, 0, 0, 0)

# ── files shipped with the app ──────────────────────────────────────────────
datas = [(str(ROOT / "icon"), "icon")]          # SVG icons, read by pydm/icons.py

# Optional / lazily-imported packages PyInstaller can't see on its own:
#   h2 + friends → HTTP/2 in httpx (only imported when http2=True)
#   QtSvg        → brings the Qt SVG library so the icon/*.svg files render
hiddenimports = ["h2", "hpack", "hyperframe", "PyQt6.QtSvg"]

# Big packages PyDM never uses — keeps the build smaller and cleaner
excludes = ["tkinter", "matplotlib", "numpy", "pandas", "PIL", "scipy",
            "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml",
            "PyQt6.QtQuick", "PyQt6.Qt3DCore", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth"]

# ── Windows version resource (shown in File Properties → Details) ───────────
version_info = None
try:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
        VarStruct, VSVersionInfo)
    v = ".".join(map(str, VERSION))
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=VERSION, prodvers=VERSION, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Iven"),
                StringStruct("FileDescription", "PyDM Download Manager"),
                StringStruct("FileVersion", v),
                StringStruct("InternalName", APP_NAME),
                StringStruct("LegalCopyright", "© 2026 Iven — MIT License"),
                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", v),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ])
except ImportError:
    pass

# ── build ───────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # one-folder build
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX → antivirus false positives
    console=False,                  # GUI app: no black console window
    disable_windowed_traceback=False,
    icon=str(ROOT / "icon" / "app.ico"),
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# ── after the build: put the browser extension next to PyDM.exe ─────────────
# (Chrome needs a plain folder to "Load unpacked", so it isn't bundled inside)
dist_ext = Path(DISTPATH) / APP_NAME / "extension"
shutil.rmtree(dist_ext, ignore_errors=True)
shutil.copytree(ROOT / "extension", dist_ext)
for name in ("README.md", "LICENSE"):
    shutil.copy2(ROOT / name, Path(DISTPATH) / APP_NAME / name)
print(f"\n  Built: {Path(DISTPATH) / APP_NAME / (APP_NAME + ('.exe' if sys.platform == 'win32' else ''))}\n")
