from __future__ import annotations

import os
from pathlib import Path
import sys


APP_MODE_FLAG = "--run-app"

_QT_ENV_CONFIGURED = False
_DLL_DIR_HANDLES: list[object] = []


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _pyside_root() -> Path:
    frozen_root = _runtime_root() / "PySide6"
    if frozen_root.exists():
        return frozen_root

    try:
        import PySide6
    except Exception:
        return Path()

    return Path(PySide6.__file__).resolve().parent


def configure_qt_environment() -> None:
    global _QT_ENV_CONFIGURED
    if _QT_ENV_CONFIGURED:
        return

    pyside_root = _pyside_root()
    if not pyside_root.exists():
        _QT_ENV_CONFIGURED = True
        return

    plugins_dir = pyside_root / "plugins"
    platforms_dir = plugins_dir / "platforms"

    for variable_name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        os.environ.pop(variable_name, None)

    os.environ["QT_PLUGIN_PATH"] = str(plugins_dir)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)

    path_entries = [str(pyside_root), str(_runtime_root())]
    existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*path_entries, existing_path]) if existing_path else os.pathsep.join(path_entries)

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for candidate in (_runtime_root(), pyside_root, plugins_dir, platforms_dir):
            if candidate.exists():
                try:
                    _DLL_DIR_HANDLES.append(add_dll_directory(str(candidate)))
                except OSError:
                    continue

    _QT_ENV_CONFIGURED = True


def prime_qt_library_paths() -> None:
    configure_qt_environment()

    pyside_root = _pyside_root()
    if not pyside_root.exists():
        return

    plugins_dir = pyside_root / "plugins"
    if not plugins_dir.exists():
        return

    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setLibraryPaths([str(plugins_dir)])
