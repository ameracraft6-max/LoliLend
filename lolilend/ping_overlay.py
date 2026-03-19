from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from lolilend.fps_overlay import WinHotkeyBackend
from lolilend.ping_monitor import PingSnapshot


class PingOverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._hotkey_backend = WinHotkeyBackend(hotkey_id=4545)
        self._position = "bottom_left"
        self._alert_ms = 80

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

        self._frame = QFrame()
        self._frame.setObjectName("PingOverlayFrame")
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.setContentsMargins(10, 8, 10, 8)
        self._frame_layout.setSpacing(3)

        title = QLabel("ПИНГ")
        title.setObjectName("PingOverlayTitle")
        self._frame_layout.addWidget(title)

        self._row_widgets: list[tuple[QLabel, QLabel]] = []

        root.addWidget(self._frame)

        self.setStyleSheet("""
QFrame#PingOverlayFrame {
    background: rgba(5, 8, 12, 210);
    border: 1px solid rgba(40, 140, 200, 170);
}
QLabel {
    color: #dce4ef;
    font-family: "Rajdhani Medium", "Segoe UI";
    font-size: 13px;
    font-weight: 600;
}
QLabel#PingOverlayTitle {
    color: #30a8e8;
    font-size: 12px;
    font-weight: 700;
}
""")
        self.resize(200, 60)
        self.setWindowOpacity(0.88)
        self._apply_position()

    def update_snapshot(self, snapshot: PingSnapshot) -> None:
        results = snapshot.results

        # Add rows if needed
        while len(self._row_widgets) < len(results):
            name_lbl = QLabel()
            ms_lbl = QLabel()
            ms_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(name_lbl, 1)
            row.addWidget(ms_lbl)
            self._frame_layout.addLayout(row)
            self._row_widgets.append((name_lbl, ms_lbl))

        # Hide extra rows
        for i, (name_lbl, ms_lbl) in enumerate(self._row_widgets):
            visible = i < len(results)
            name_lbl.setVisible(visible)
            ms_lbl.setVisible(visible)

        for i, res in enumerate(results):
            name_lbl, ms_lbl = self._row_widgets[i]
            name_lbl.setText(res.label)
            if res.ms is None:
                ms_lbl.setText("—")
                color = "color: #a9b4c2;"
            else:
                ms_lbl.setText(f"{res.ms:.0f} мс")
                color = self._ms_color(res.ms)
            ms_lbl.setStyleSheet(color)
            name_lbl.setStyleSheet(color)

        # Resize to fit content
        self.adjustSize()
        self._apply_position()

    def _ms_color(self, ms: float) -> str:
        if ms < self._alert_ms:
            return "color: #44dd66;"
        if ms < self._alert_ms * 2:
            return "color: #ff9900;"
        return "color: #ff4444;"

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

    def set_alert_ms(self, ms: int) -> None:
        self._alert_ms = ms

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
