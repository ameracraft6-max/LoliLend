from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from lolilend.fps_overlay import WinHotkeyBackend


CROSSHAIR_STYLE_OPTIONS: list[tuple[str, str]] = [
    ("Крест",              "cross"),
    ("Точка",              "dot"),
    ("Круг",               "circle"),
    ("Крест + точка",      "cross_dot"),
    ("Крест + круг",       "cross_circle"),
    ("Точка + круг",       "dot_circle"),
    ("Крест+точка+круг",   "cross_dot_circle"),
    ("T-Крест",            "t_cross"),
    ("X-Крест",            "x_cross"),
    ("Ромб",               "diamond"),
    ("Шеврон",             "chevron"),
    ("Плюс мини",          "plus_small"),
    ("Линии",              "lines_only"),
    ("Свой рисунок",       "custom_image"),
]

CROSSHAIR_STYLES: list[str] = [key for _, key in CROSSHAIR_STYLE_OPTIONS]


@dataclass
class CrosshairConfig:
    style: str = "cross_dot"
    color: str = "#00ff00"
    size: int = 20
    thickness: int = 2
    gap: int = 4
    opacity: int = 90
    outline: bool = True
    offset_x: int = 0
    offset_y: int = 0
    hotkey: str = ""
    custom_image_path: str = ""


def render_crosshair(painter: QPainter, cx: int, cy: int, cfg: CrosshairConfig) -> None:
    color = QColor(cfg.color)
    outline_color = QColor(0, 0, 0, 200)
    t = cfg.thickness
    g = cfg.gap
    s = cfg.size

    def _cross(c: QColor, pw: int) -> None:
        pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx - s - g, cy, cx - g, cy)
        painter.drawLine(cx + g, cy, cx + g + s, cy)
        painter.drawLine(cx, cy - s - g, cx, cy - g)
        painter.drawLine(cx, cy + g, cx, cy + g + s)

    def _dot(c: QColor, r: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(c))
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def _circle(c: QColor, pw: int, r: int) -> None:
        pen = QPen(c, pw, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def _t_cross(c: QColor, pw: int) -> None:
        pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx - s - g, cy, cx - g, cy)
        painter.drawLine(cx + g, cy, cx + g + s, cy)
        painter.drawLine(cx, cy - s - g, cx, cy - g)

    def _x_cross(c: QColor, pw: int) -> None:
        diag = int((s + g) * 0.707)
        gap_d = max(1, int(g * 0.707))
        pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx - diag, cy - diag, cx - gap_d, cy - gap_d)
        painter.drawLine(cx + gap_d, cy + gap_d, cx + diag, cy + diag)
        painter.drawLine(cx + diag, cy - diag, cx + gap_d, cy - gap_d)
        painter.drawLine(cx - gap_d, cy + gap_d, cx - diag, cy + diag)

    def _diamond(c: QColor, pw: int) -> None:
        r = s + g
        pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx, cy - r, cx + r, cy)
        painter.drawLine(cx + r, cy, cx, cy + r)
        painter.drawLine(cx, cy + r, cx - r, cy)
        painter.drawLine(cx - r, cy, cx, cy - r)

    def _chevron(c: QColor, pw: int) -> None:
        pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx - s, cy + g + s // 2, cx, cy - g)
        painter.drawLine(cx, cy - g, cx + s, cy + g + s // 2)

    outline_w = t + 2
    dot_r = max(1, t)

    if cfg.style == "cross":
        if cfg.outline:
            _cross(outline_color, outline_w)
        _cross(color, t)

    elif cfg.style == "dot":
        if cfg.outline:
            _dot(outline_color, dot_r + 1)
        _dot(color, dot_r)

    elif cfg.style == "circle":
        r = s + g
        if cfg.outline:
            _circle(outline_color, outline_w, r)
        _circle(color, t, r)

    elif cfg.style == "cross_dot":
        if cfg.outline:
            _cross(outline_color, outline_w)
            _dot(outline_color, dot_r + 1)
        _cross(color, t)
        _dot(color, dot_r)

    elif cfg.style == "cross_circle":
        r = s + g
        if cfg.outline:
            _cross(outline_color, outline_w)
            _circle(outline_color, outline_w, r)
        _cross(color, t)
        _circle(color, t, r)

    elif cfg.style == "dot_circle":
        r = s + g
        if cfg.outline:
            _dot(outline_color, dot_r + 1)
            _circle(outline_color, outline_w, r)
        _dot(color, dot_r)
        _circle(color, t, r)

    elif cfg.style == "cross_dot_circle":
        r = s + g
        if cfg.outline:
            _cross(outline_color, outline_w)
            _dot(outline_color, dot_r + 1)
            _circle(outline_color, outline_w, r)
        _cross(color, t)
        _dot(color, dot_r)
        _circle(color, t, r)

    elif cfg.style == "t_cross":
        if cfg.outline:
            _t_cross(outline_color, outline_w)
        _t_cross(color, t)

    elif cfg.style == "x_cross":
        if cfg.outline:
            _x_cross(outline_color, outline_w)
        _x_cross(color, t)

    elif cfg.style == "diamond":
        if cfg.outline:
            _diamond(outline_color, outline_w)
        _diamond(color, t)

    elif cfg.style == "chevron":
        if cfg.outline:
            _chevron(outline_color, outline_w)
        _chevron(color, t)

    elif cfg.style == "plus_small":
        ss = max(3, t)
        orig_s, orig_g = s, g
        # temporarily override through local vars captured by closures
        def _plus_h(c: QColor, pw: int) -> None:
            pen = QPen(c, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(cx - ss, cy, cx - 1, cy)
            painter.drawLine(cx + 1, cy, cx + ss, cy)
            painter.drawLine(cx, cy - ss, cx, cy - 1)
            painter.drawLine(cx, cy + 1, cx, cy + ss)
        if cfg.outline:
            _plus_h(outline_color, outline_w)
        _plus_h(color, t)

    elif cfg.style == "lines_only":
        pen = QPen(color, t, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
        if cfg.outline:
            painter.setPen(QPen(outline_color, outline_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawLine(cx - s - g, cy, cx - g, cy)
            painter.drawLine(cx + g, cy, cx + g + s, cy)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(cx - s - g, cy, cx - g, cy)
        painter.drawLine(cx + g, cy, cx + g + s, cy)

    elif cfg.style == "custom_image":
        img_path = cfg.custom_image_path
        if img_path and Path(img_path).is_file():
            pm = QPixmap(img_path)
            if not pm.isNull():
                target_size = max(4, cfg.size * 2)
                pm = pm.scaled(target_size, target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(cx - pm.width() // 2, cy - pm.height() // 2, pm)


class CrosshairOverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._cfg = CrosshairConfig()
        self._hotkey_backend = WinHotkeyBackend(hotkey_id=4343)

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowOpacity(self._cfg.opacity / 100.0)
        self._refresh_geometry()

    def apply_config(self, cfg: CrosshairConfig) -> None:
        self._cfg = cfg
        self.setWindowOpacity(max(0.2, min(1.0, cfg.opacity / 100.0)))
        self._refresh_geometry()
        self.update()

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
        self._refresh_geometry()
        self.show()

    def shutdown(self) -> None:
        self.disable_hotkey()
        try:
            self.hide()
        except RuntimeError:
            pass

    def _canvas_size(self) -> int:
        s = self._cfg.size
        g = self._cfg.gap
        t = self._cfg.thickness
        margin = 10
        return max((s + g + t + margin) * 2, 32)

    def _refresh_geometry(self) -> None:
        sz = self._canvas_size()
        self.setFixedSize(sz, sz)
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        x = geo.left() + geo.width() // 2 - sz // 2 + self._cfg.offset_x
        y = geo.top() + geo.height() // 2 - sz // 2 + self._cfg.offset_y
        self.move(x, y)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        render_crosshair(painter, self.width() // 2, self.height() // 2, self._cfg)
        painter.end()
