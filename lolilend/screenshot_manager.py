"""Screenshot manager backend: capture, disk library, foreground game detection."""
from __future__ import annotations

import datetime
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap


INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True, slots=True)
class ScreenshotEntry:
    path: Path
    game_name: str
    captured_at: datetime.datetime
    size_bytes: int

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(slots=True)
class GameGroup:
    name: str
    count: int = 0
    total_bytes: int = 0
    latest: datetime.datetime | None = None
    entries: list[ScreenshotEntry] = field(default_factory=list)


def _sanitize_name(raw: str) -> str:
    cleaned = INVALID_NAME_CHARS.sub("_", raw).strip().strip(".")
    return cleaned or "Unknown"


def get_foreground_process_name() -> str:
    """Return the executable basename of the currently focused foreground window.

    Falls back to 'Unknown' when detection fails (non-Windows, no permission, etc.).
    """
    if os.name != "nt":
        return "Unknown"
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "Unknown"

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "Unknown"

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return "Unknown"

        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            if not ok:
                return "Unknown"
            exe_path = buf.value or ""
        finally:
            kernel32.CloseHandle(handle)

        basename = Path(exe_path).stem
        if not basename:
            return "Unknown"
        # Skip system shell processes — return "Desktop" so shots don't pollute the list.
        lowered = basename.lower()
        if lowered in {"explorer", "shellexperiencehost", "searchhost", "startmenuexperiencehost"}:
            return "Desktop"
        return basename
    except Exception:
        return "Unknown"


def get_foreground_hwnd() -> int:
    if os.name != "nt":
        return 0
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return int(hwnd) if hwnd else 0
    except Exception:
        return 0


class ScreenshotLibrary(QObject):
    """On-disk index of screenshots grouped by game (folder name)."""

    changed = Signal()

    def __init__(self, root_dir: Path) -> None:
        super().__init__()
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def set_root(self, new_root: Path) -> None:
        new_root = Path(new_root)
        new_root.mkdir(parents=True, exist_ok=True)
        self._root = new_root
        self.changed.emit()

    def save_pixmap(self, pixmap: QPixmap, game_name: str) -> ScreenshotEntry | None:
        if pixmap.isNull():
            return None
        safe = _sanitize_name(game_name)
        folder = self._root / safe
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = folder / f"{safe}_{stamp}.png"
        counter = 1
        while target.exists():
            target = folder / f"{safe}_{stamp}_{counter}.png"
            counter += 1
        ok = pixmap.save(str(target), "PNG")
        if not ok:
            return None
        entry = ScreenshotEntry(
            path=target,
            game_name=safe,
            captured_at=datetime.datetime.now(),
            size_bytes=target.stat().st_size,
        )
        self.changed.emit()
        return entry

    def scan(self) -> list[GameGroup]:
        groups: dict[str, GameGroup] = {}
        if not self._root.exists():
            return []
        for game_dir in sorted(self._root.iterdir()):
            if not game_dir.is_dir():
                continue
            group = GameGroup(name=game_dir.name)
            for file in game_dir.iterdir():
                if not file.is_file():
                    continue
                if file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                    continue
                try:
                    stat = file.stat()
                except OSError:
                    continue
                captured = datetime.datetime.fromtimestamp(stat.st_mtime)
                entry = ScreenshotEntry(
                    path=file,
                    game_name=game_dir.name,
                    captured_at=captured,
                    size_bytes=stat.st_size,
                )
                group.entries.append(entry)
                group.count += 1
                group.total_bytes += stat.st_size
                if group.latest is None or captured > group.latest:
                    group.latest = captured
            if group.count > 0:
                groups[game_dir.name] = group
        return sorted(groups.values(), key=lambda g: (g.latest or datetime.datetime.min), reverse=True)

    def delete(self, entry: ScreenshotEntry) -> bool:
        try:
            entry.path.unlink()
        except OSError:
            return False
        parent = entry.path.parent
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
        self.changed.emit()
        return True

    def delete_group(self, game_name: str) -> int:
        folder = self._root / _sanitize_name(game_name)
        if not folder.is_dir():
            return 0
        removed = 0
        for file in list(folder.iterdir()):
            try:
                file.unlink()
                removed += 1
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass
        self.changed.emit()
        return removed


class ScreenshotCapturer:
    """Captures the active window or full desktop via Qt and hands the result to a library."""

    def __init__(self, library: ScreenshotLibrary) -> None:
        self._library = library

    def capture(
        self,
        mode: str = "window",
        game_name_override: str | None = None,
    ) -> ScreenshotEntry | None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        screen = app.primaryScreen()
        if screen is None:
            return None

        game_name = game_name_override or get_foreground_process_name()

        if mode == "window":
            hwnd = get_foreground_hwnd()
            if hwnd:
                pixmap = screen.grabWindow(hwnd)
            else:
                pixmap = screen.grabWindow(0)
        else:
            pixmap = screen.grabWindow(0)

        if pixmap.isNull():
            return None
        return self._library.save_pixmap(pixmap, game_name)


class ScreenshotHotkeyBinder:
    """Binds a global hotkey to a capture callback. Reuses WinHotkeyBackend."""

    HOTKEY_ID = 4344  # 4242 fps, 4343 crosshair, 4344 screenshots

    def __init__(self, on_triggered: Callable[[], None]) -> None:
        from lolilend.fps_overlay import WinHotkeyBackend

        self._backend = WinHotkeyBackend(hotkey_id=self.HOTKEY_ID)
        self._callback = on_triggered
        self._current: str = ""

    def set_hotkey(self, hotkey: str) -> tuple[bool, str | None]:
        self._backend.unregister()
        self._current = ""
        if not hotkey:
            return True, None
        ok, err = self._backend.register(hotkey, self._callback)
        if ok:
            self._current = hotkey
        return ok, err

    def unbind(self) -> None:
        self._backend.unregister()
        self._current = ""

    @property
    def current(self) -> str:
        return self._current
