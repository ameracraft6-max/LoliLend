# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from lolilend.version import APP_EXE_NAME


project_root = Path.cwd()
assets_dir = project_root / "lolilend" / "assets"
icon_path = project_root / "installer" / "app.ico"
dlls_dir = Path(sys.base_prefix) / "DLLs"

extra_binaries = []
for module_name in ("_overlapped.pyd", "_asyncio.pyd", "_sqlite3.pyd", "sqlite3.dll"):
    module_path = dlls_dir / module_name
    if module_path.exists():
        extra_binaries.append((str(module_path), "."))


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=extra_binaries,
    datas=[(str(assets_dir), "lolilend/assets")],
    hiddenimports=["lolilend.tg_ws_proxy_core", "_overlapped", "_sqlite3", "asyncio.windows_events"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_EXE_NAME.replace(".exe", ""),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_EXE_NAME.replace(".exe", ""),
)
