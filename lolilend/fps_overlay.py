from __future__ import annotations

from collections.abc import Callable
import os
from typing import Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from lolilend.fps_monitor import FpsSnapshot


class HotkeyBackend(Protocol):
    def register(self, hotkey: str, callback: Callable[[], None]) -> tuple[bool, str | None]: ...

    def unregister(self) -> None: ...


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312

    def __init__(self, hotkey_id: int, callback: Callable[[], None], ctypes_module: object, msg_type: object) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback
        self._ctypes = ctypes_module
        self._msg_type = msg_type

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt naming
        if event_type not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = self._msg_type.from_address(int(message))
        except Exception:
            return False, 0
        if int(msg.message) == self.WM_HOTKEY and int(msg.wParam) == self._hotkey_id:
            self._callback()
            return True, 0
        return False, 0


class WinHotkeyBackend:
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008

    def __init__(self, hotkey_id: int = 4242) -> None:
        self._hotkey_id = hotkey_id
        self._registered = False
        self._filter: _WinHotkeyFilter | None = None
        self._user32 = None
        self._ctypes = None
        self._msg_type = None

        if os.name != "nt":
            return

        try:
            import ctypes
            from ctypes import wintypes

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt_x", ctypes.c_long),
                    ("pt_y", ctypes.c_long),
                    ("lPrivate", wintypes.DWORD),
                ]

            self._ctypes = ctypes
            self._msg_type = MSG
            self._user32 = ctypes.windll.user32
        except Exception:
            self._user32 = None

    def register(self, hotkey: str, callback: Callable[[], None]) -> tuple[bool, str | None]:
        if self._user32 is None:
            return False, "Windows hotkey backend unavailable"

        mods_vk = self._parse_hotkey(hotkey)
        if mods_vk is None:
            return False, f"Unsupported hotkey: {hotkey}"
        mods, vk = mods_vk

        self.unregister()
        ok = bool(self._user32.RegisterHotKey(None, self._hotkey_id, mods, vk))
        if not ok:
            return False, f"RegisterHotKey failed for {hotkey}"

        app = QCoreApplication.instance()
        if app is None:
            self._user32.UnregisterHotKey(None, self._hotkey_id)
            return False, "QCoreApplication instance not found"

        self._filter = _WinHotkeyFilter(self._hotkey_id, callback, self._ctypes, self._msg_type)
        app.installNativeEventFilter(self._filter)
        self._registered = True
        return True, None

    def unregister(self) -> None:
        if self._user32 is None:
            return

        app = QCoreApplication.instance()
        if app is not None and self._filter is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None

        if self._registered:
            try:
                self._user32.UnregisterHotKey(None, self._hotkey_id)
            except Exception:
                pass
            self._registered = False

    @classmethod
    def _parse_hotkey(cls, hotkey: str) -> tuple[int, int] | None:
        parts = [part.strip().upper() for part in hotkey.split("+") if part.strip()]
        if not parts:
            return None

        modifiers = 0
        key_token = ""
        for token in parts:
            if token == "CTRL":
                modifiers |= cls.MOD_CONTROL
            elif token == "SHIFT":
                modifiers |= cls.MOD_SHIFT
            elif token == "ALT":
                modifiers |= cls.MOD_ALT
            elif token in ("WIN", "META"):
                modifiers |= cls.MOD_WIN
            else:
                key_token = token

        if not key_token:
            return None

        vk = cls._key_to_vk(key_token)
        if vk is None:
            return None
        return modifiers, vk

    @staticmethod
    def _key_to_vk(token: str) -> int | None:
        if len(token) == 1 and token.isalnum():
            return ord(token)

        if token.startswith("F") and token[1:].isdigit():
            number = int(token[1:])
            if 1 <= number <= 24:
                return 0x70 + (number - 1)

        named = {
            "TAB": 0x09,
            "SPACE": 0x20,
            "INSERT": 0x2D,
            "DELETE": 0x2E,
            "HOME": 0x24,
            "END": 0x23,
            "PGUP": 0x21,
            "PGDN": 0x22,
        }
        return named.get(token)


class FpsOverlayWindow(QWidget):
    def __init__(self, hotkey_backend: HotkeyBackend | None = None) -> None:
        super().__init__(None)
        self._hotkey_backend = hotkey_backend or WinHotkeyBackend()
        self._hotkey = "Ctrl+Shift+F10"
        self._position = "top_left"
        self._scale_percent = 100

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("FpsOverlayFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(3)

        title = QLabel("FPS MONITOR")
        title.setObjectName("FpsOverlayTitle")
        frame_layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.fps_label = QLabel("FPS: N/A")
        self.frametime_label = QLabel("Frametime: N/A")
        self.one_low_label = QLabel("1% Low: N/A")
        self.status_label = QLabel("Status: N/A")
        self.status_label.setObjectName("FpsOverlayStatus")

        row.addWidget(self.fps_label)
        row.addWidget(self.frametime_label)
        row.addWidget(self.one_low_label)
        frame_layout.addLayout(row)
        frame_layout.addWidget(self.status_label)

        root.addWidget(frame)

        self.setStyleSheet(
            """
QFrame#FpsOverlayFrame {
    background: rgba(5, 8, 12, 210);
    border: 1px solid rgba(141, 170, 71, 170);
}
QLabel {
    color: #dce4ef;
    font-family: "Rajdhani Medium", "Segoe UI";
    font-size: 13px;
    font-weight: 600;
}
QLabel#FpsOverlayTitle {
    color: #95b24e;
    font-size: 12px;
    font-weight: 700;
}
QLabel#FpsOverlayStatus {
    color: #a9b4c2;
    font-size: 12px;
}
"""
        )

        self.resize(355, 84)
        self.setWindowOpacity(0.88)
        self._apply_position()

    def update_snapshot(self, snapshot: FpsSnapshot) -> None:
        fps_text = "N/A" if snapshot.fps is None else f"{snapshot.fps:.0f}"
        frametime_text = "N/A" if snapshot.frame_time_ms is None else f"{snapshot.frame_time_ms:.2f} ms"
        low_text = "N/A" if snapshot.one_percent_low_fps is None else f"{snapshot.one_percent_low_fps:.0f}"

        self.fps_label.setText(f"FPS: {fps_text}")
        self.frametime_label.setText(f"Frametime: {frametime_text}")
        self.one_low_label.setText(f"1% Low: {low_text}")
        self.status_label.setText(f"Status: {snapshot.status}")

    def set_hotkey(self, hotkey: str) -> tuple[bool, str | None]:
        self._hotkey = hotkey
        return self._hotkey_backend.register(hotkey, self.toggle_overlay_visibility)

    def disable_hotkey(self) -> None:
        self._hotkey_backend.unregister()

    def toggle_overlay_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_overlay()

    def show_overlay(self) -> None:
        self._apply_position()
        self.show()

    def set_overlay_position(self, position: str) -> None:
        self._position = position
        self._apply_position()

    def set_overlay_opacity(self, value: int) -> None:
        clamped = max(35, min(100, int(value)))
        self.setWindowOpacity(clamped / 100.0)

    def set_overlay_scale(self, value: int) -> None:
        self._scale_percent = max(80, min(140, int(value)))
        scale = self._scale_percent / 100.0
        font_size = max(10, int(13 * scale))

        for label in (self.fps_label, self.frametime_label, self.one_low_label, self.status_label):
            font = QFont(label.font())
            font.setPointSize(font_size)
            label.setFont(font)

        self.resize(max(300, int(355 * scale)), max(70, int(84 * scale)))
        self._apply_position()

    def _apply_position(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        bounds = screen.availableGeometry()
        margin = 16
        x = bounds.left() + margin
        y = bounds.top() + margin

        if self._position == "top_right":
            x = bounds.right() - self.width() - margin
        elif self._position == "bottom_left":
            y = bounds.bottom() - self.height() - margin
        elif self._position == "bottom_right":
            x = bounds.right() - self.width() - margin
            y = bounds.bottom() - self.height() - margin

        self.move(max(bounds.left(), x), max(bounds.top(), y))

    def shutdown(self) -> None:
        self.disable_hotkey()
        try:
            self.hide()
        except RuntimeError:
            pass

