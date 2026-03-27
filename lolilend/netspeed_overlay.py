from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from lolilend.fps_overlay import WinHotkeyBackend
from lolilend.monitoring import format_bytes_text
from lolilend.netspeed_monitor import NetSpeedSnapshot


class NetSpeedOverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._hotkey_backend = WinHotkeyBackend(hotkey_id=4646)
        self._position = "bottom_right"

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("NetSpeedOverlayFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(3)

        title = QLabel("СКОРОСТЬ СЕТИ")
        title.setObjectName("NetSpeedOverlayTitle")
        frame_layout.addWidget(title)

        self.down_label = QLabel("↓ —")
        self.up_label = QLabel("↑ —")
        frame_layout.addWidget(self.down_label)
        frame_layout.addWidget(self.up_label)

        root.addWidget(frame)

        self.setStyleSheet("""
QFrame#NetSpeedOverlayFrame {
    background: rgba(5, 8, 12, 210);
    border: 1px solid rgba(40, 200, 140, 170);
}
QLabel {
    color: #dce4ef;
    font-family: "Rajdhani Medium", "Segoe UI";
    font-size: 13px;
    font-weight: 600;
}
QLabel#NetSpeedOverlayTitle {
    color: #22cc88;
    font-size: 12px;
    font-weight: 700;
}
""")
        self.resize(180, 80)
        self.setWindowOpacity(0.88)
        self._apply_position()

    def update_snapshot(self, snapshot: NetSpeedSnapshot) -> None:
        self.down_label.setText(f"↓ {format_bytes_text(snapshot.download_bps)}")
        self.up_label.setText(f"↑ {format_bytes_text(snapshot.upload_bps)}")

    def set_hotkey(self, hotkey: str) -> tuple[bool, str | None]:
        if not hotkey:
            self._hotkey_backend.unregister()
            return True, None
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
        self.setWindowOpacity(max(0.35, min(1.0, value / 100.0)))

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
