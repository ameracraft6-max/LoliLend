from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from lolilend.fps_overlay import WinHotkeyBackend
from lolilend.temperature_monitor import TempSnapshot


class TempOverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._hotkey_backend = WinHotkeyBackend(hotkey_id=4444)
        self._position = "top_right"
        self._alert_celsius = 85

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
        frame.setObjectName("TempOverlayFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(3)

        title = QLabel("ТЕМПЕРАТУРЫ")
        title.setObjectName("TempOverlayTitle")
        frame_layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.cpu_label = QLabel("CPU: N/A")
        self.gpu_label = QLabel("GPU: N/A")
        row.addWidget(self.cpu_label)
        row.addWidget(self.gpu_label)
        frame_layout.addLayout(row)

        self.alert_label = QLabel("")
        self.alert_label.setObjectName("TempOverlayAlert")
        self.alert_label.hide()
        frame_layout.addWidget(self.alert_label)

        self.status_label = QLabel("Status: N/A")
        self.status_label.setObjectName("TempOverlayStatus")
        frame_layout.addWidget(self.status_label)

        root.addWidget(frame)

        self.setStyleSheet("""
QFrame#TempOverlayFrame {
    background: rgba(5, 8, 12, 210);
    border: 1px solid rgba(200, 120, 40, 170);
}
QLabel {
    color: #dce4ef;
    font-family: "Rajdhani Medium", "Segoe UI";
    font-size: 13px;
    font-weight: 600;
}
QLabel#TempOverlayTitle {
    color: #e8a030;
    font-size: 12px;
    font-weight: 700;
}
QLabel#TempOverlayAlert {
    color: #ff4444;
    font-size: 12px;
    font-weight: 700;
}
QLabel#TempOverlayStatus {
    color: #a9b4c2;
    font-size: 11px;
}
""")
        self.resize(210, 88)
        self.setWindowOpacity(0.88)
        self._apply_position()

    def update_snapshot(self, snapshot: TempSnapshot) -> None:
        cpu_text = "N/A" if snapshot.cpu_temp is None else f"{snapshot.cpu_temp:.0f} °C"
        gpu_text = "N/A" if snapshot.gpu_temp is None else f"{snapshot.gpu_temp:.0f} °C"

        self.cpu_label.setText(f"CPU: {cpu_text}")
        self.gpu_label.setText(f"GPU: {gpu_text}")
        self.status_label.setText(f"Status: {snapshot.status}")

        self.cpu_label.setStyleSheet(self._temp_color(snapshot.cpu_temp))
        self.gpu_label.setStyleSheet(self._temp_color(snapshot.gpu_temp))

        overheat = any(
            t is not None and t > self._alert_celsius
            for t in (snapshot.cpu_temp, snapshot.gpu_temp)
        )
        if overheat:
            self.alert_label.setText("⚠ ПЕРЕГРЕВ")
            self.alert_label.show()
        else:
            self.alert_label.hide()

    def _temp_color(self, temp: float | None) -> str:
        if temp is None:
            return "color: #a9b4c2;"
        if temp >= 85:
            return "color: #ff4444;"
        if temp >= 70:
            return "color: #ff9900;"
        return "color: #44dd66;"

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

    def set_alert_threshold(self, celsius: int) -> None:
        self._alert_celsius = celsius

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
