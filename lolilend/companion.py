"""Animated anime-chibi companion overlay.

Programmatic character — no sprite assets. Rendered via QPainter so it inherits the
active visual theme. A single controller polls existing sensors (temperature, foreground
process, input idle time) and maps them to companion states.

States:
    IDLE     — default, gentle bob, occasional blink
    HAPPY    — smile + sparkles
    WINK     — one eye closed, "Let's play!"
    SCARED   — wide eyes, sweat drop, "CPU hot!"
    SLEEPY   — closed eyes, "zZ"
    EXCITED  — star eyes, "★"
"""
from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass
from enum import Enum

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class CompanionState(str, Enum):
    IDLE = "idle"
    HAPPY = "happy"
    WINK = "wink"
    SCARED = "scared"
    SLEEPY = "sleepy"
    EXCITED = "excited"


STATE_LABELS: dict[CompanionState, str] = {
    CompanionState.IDLE: "Ня~",
    CompanionState.HAPPY: "Поиграем?",
    CompanionState.WINK: "Let's play!",
    CompanionState.SCARED: "CPU горит!",
    CompanionState.SLEEPY: "zZ...",
    CompanionState.EXCITED: "Ура!",
}

# How long the companion stays in a triggered state before drifting back to IDLE.
STATE_DURATION: dict[CompanionState, float] = {
    CompanionState.IDLE: 0.0,  # sticky
    CompanionState.HAPPY: 6.0,
    CompanionState.WINK: 4.0,
    CompanionState.SCARED: 5.0,
    CompanionState.SLEEPY: 10.0,
    CompanionState.EXCITED: 5.0,
}


@dataclass(slots=True)
class CompanionPalette:
    """Colors pulled from the active ThemeSpec."""
    skin: QColor
    hair: QColor
    cheek: QColor
    eye: QColor
    mouth: QColor
    accent: QColor
    bubble_bg: QColor
    bubble_text: QColor

    @staticmethod
    def from_theme(theme_name: str) -> "CompanionPalette":
        from lolilend.theme import get_theme
        t = get_theme(theme_name)

        # Skin derives from a light blend; we pick a near-white that reads well on any bg.
        skin = QColor("#ffe8d6")
        hair = QColor(t.accent_primary)
        cheek = QColor(t.accent_bright)
        cheek.setAlpha(170)
        eye = QColor("#1a1424")
        mouth = QColor(t.accent_deep)
        accent = QColor(t.accent_bright)
        bubble_bg = QColor(t.bg1)
        bubble_bg.setAlpha(235)
        bubble_text = QColor(t.text_primary)
        return CompanionPalette(skin, hair, cheek, eye, mouth, accent, bubble_bg, bubble_text)


def _get_last_input_idle_seconds() -> float:
    """Returns seconds since last keyboard/mouse input via Win32 GetLastInputInfo. 0 off Windows."""
    if os.name != "nt":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick_count = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (tick_count - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


class CompanionCharacter(QWidget):
    """The chibi character itself — draws head, eyes, mouth, bubble. 30 FPS bob/blink animation."""

    FRAME_MS = 33

    # Expected filenames inside a user-provided sprite directory.
    SPRITE_FILES: dict[CompanionState, str] = {
        CompanionState.IDLE: "idle.png",
        CompanionState.HAPPY: "happy.png",
        CompanionState.WINK: "wink.png",
        CompanionState.SCARED: "scared.png",
        CompanionState.SLEEPY: "sleepy.png",
        CompanionState.EXCITED: "excited.png",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._state = CompanionState.IDLE
        self._state_entered = time.monotonic()
        self._palette = CompanionPalette.from_theme("Dark")
        self._bob_phase = 0.0
        self._blink_phase = random.uniform(0, 4)
        self._sparkle_phase = random.uniform(0, 6.28)
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        self._clicked = False
        # Bubble text — overridable via set_bubble_text (e.g. from AI brain).
        self._bubble_override: str | None = None
        # Custom sprite sheet support — if sprites_dir has PNGs, use them instead of procedural drawing.
        self._sprites: dict[CompanionState, QPixmap] = {}
        self._sprites_dir: Path | None = None

    # ---------- api ----------
    def set_palette_from_theme(self, theme_name: str) -> None:
        self._palette = CompanionPalette.from_theme(theme_name)
        self.update()

    def set_state(self, state: CompanionState) -> None:
        if state == self._state:
            self._state_entered = time.monotonic()
            return
        self._state = state
        self._state_entered = time.monotonic()
        self._bubble_override = None  # new state → next bubble should be freshly generated
        self.update()

    def set_bubble_text(self, text: str) -> None:
        self._bubble_override = (text or "").strip() or None
        self.update()

    def set_sprites_dir(self, path: str | Path | None) -> None:
        """Load chibi PNGs from the given directory. Files: idle.png, happy.png, ... — missing = procedural."""
        self._sprites = {}
        self._sprites_dir = None
        if not path:
            self.update()
            return
        directory = Path(path)
        if not directory.is_dir():
            self.update()
            return
        self._sprites_dir = directory
        for state, filename in self.SPRITE_FILES.items():
            candidate = directory / filename
            if candidate.is_file():
                pm = QPixmap(str(candidate))
                if not pm.isNull():
                    self._sprites[state] = pm
        self.update()

    def sprite_states_loaded(self) -> list[CompanionState]:
        return list(self._sprites.keys())

    def state(self) -> CompanionState:
        return self._state

    def state_age(self) -> float:
        return time.monotonic() - self._state_entered

    # ---------- animation ----------
    def _advance(self) -> None:
        self._bob_phase += 0.08
        self._blink_phase += 0.04
        self._sparkle_phase += 0.12
        # Auto-return to IDLE when transient state expires.
        duration = STATE_DURATION.get(self._state, 0.0)
        if duration > 0 and self.state_age() > duration:
            self._state = CompanionState.IDLE
            self._state_entered = time.monotonic()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Click = react with EXCITED — fun!
        self._clicked = True
        self.set_state(CompanionState.EXCITED)
        super().mousePressEvent(event)

    # ---------- rendering ----------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        w = rect.width()
        h = rect.height()
        if w <= 0 or h <= 0:
            return

        # Reserve top third for speech bubble, bottom two thirds for character.
        bubble_h = int(h * 0.24)
        char_top = bubble_h + 2
        char_h = h - char_top
        bob_dy = math.sin(self._bob_phase) * (char_h * 0.015)
        cx = w / 2
        cy = char_top + char_h * 0.55 + bob_dy

        # --- Speech bubble ---
        bubble_text = self._bubble_override or STATE_LABELS.get(self._state, "")
        self._draw_bubble(painter, QRectF(6, 2, w - 12, bubble_h), bubble_text)

        # --- Character ---
        sprite = self._sprites.get(self._state) or self._sprites.get(CompanionState.IDLE)
        if sprite is not None and not sprite.isNull():
            # Draw custom chibi PNG, scaled to fit character region, preserving aspect ratio.
            target_h = int(char_h * 0.92)
            scaled = sprite.scaledToHeight(target_h, Qt.TransformationMode.SmoothTransformation)
            px = int(cx - scaled.width() / 2)
            py = int(char_top + (char_h - scaled.height()) / 2 + bob_dy)
            painter.drawPixmap(px, py, scaled)
        else:
            head_r = char_h * 0.32
            self._draw_hair_back(painter, cx, cy, head_r)
            self._draw_head(painter, cx, cy, head_r)
            self._draw_hair_front(painter, cx, cy, head_r)
            self._draw_cheeks(painter, cx, cy, head_r)
            self._draw_eyes(painter, cx, cy, head_r)
            self._draw_mouth(painter, cx, cy, head_r)
            self._draw_state_decor(painter, cx, cy, head_r)

    def _draw_bubble(self, p: QPainter, rect: QRectF, text: str) -> None:
        if rect.height() < 14 or not text:
            return
        p.save()
        p.setPen(QPen(self._palette.accent, 1.5))
        p.setBrush(QBrush(self._palette.bubble_bg))
        radius = min(12.0, rect.height() * 0.5)
        p.drawRoundedRect(rect, radius, radius)
        # Small pointer
        tip_x = rect.center().x()
        tip_y = rect.bottom() - 1
        path = QPainterPath()
        path.moveTo(tip_x - 5, tip_y)
        path.lineTo(tip_x, tip_y + 6)
        path.lineTo(tip_x + 5, tip_y)
        p.fillPath(path, QBrush(self._palette.bubble_bg))
        p.setPen(QPen(self._palette.accent, 1.5))
        p.drawLine(QPointF(tip_x - 5, tip_y), QPointF(tip_x, tip_y + 6))
        p.drawLine(QPointF(tip_x, tip_y + 6), QPointF(tip_x + 5, tip_y))
        # Text
        font = QFont()
        font.setPointSize(max(7, int(rect.height() * 0.36)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(self._palette.bubble_text))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _draw_hair_back(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        # Longer hair silhouette behind the head — ellipse wider than head.
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._palette.hair))
        p.drawEllipse(QPointF(cx, cy), r * 1.15, r * 1.25)
        p.restore()

    def _draw_head(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        p.save()
        p.setPen(QPen(self._palette.eye, 1.2))
        p.setBrush(QBrush(self._palette.skin))
        p.drawEllipse(QPointF(cx, cy), r, r * 1.05)
        p.restore()

    def _draw_hair_front(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        # Bangs: two curved tufts falling across forehead.
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._palette.hair))
        path = QPainterPath()
        top_y = cy - r * 0.95
        path.moveTo(cx - r * 0.95, top_y + r * 0.1)
        path.quadTo(cx - r * 0.3, cy - r * 0.55, cx + r * 0.15, cy - r * 0.35)
        path.quadTo(cx + r * 0.5, cy - r * 0.5, cx + r * 0.95, top_y + r * 0.1)
        path.quadTo(cx, top_y - r * 0.1, cx - r * 0.95, top_y + r * 0.1)
        p.drawPath(path)
        # Side locks
        side_path = QPainterPath()
        side_path.moveTo(cx - r * 1.08, cy - r * 0.1)
        side_path.quadTo(cx - r * 1.3, cy + r * 0.4, cx - r * 0.95, cy + r * 0.85)
        side_path.quadTo(cx - r * 0.8, cy + r * 0.4, cx - r * 0.85, cy - r * 0.2)
        p.drawPath(side_path)
        side_path2 = QPainterPath()
        side_path2.moveTo(cx + r * 1.08, cy - r * 0.1)
        side_path2.quadTo(cx + r * 1.3, cy + r * 0.4, cx + r * 0.95, cy + r * 0.85)
        side_path2.quadTo(cx + r * 0.8, cy + r * 0.4, cx + r * 0.85, cy - r * 0.2)
        p.drawPath(side_path2)
        p.restore()

    def _draw_cheeks(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._palette.cheek))
        blush_r = r * 0.13
        p.drawEllipse(QPointF(cx - r * 0.45, cy + r * 0.25), blush_r, blush_r * 0.7)
        p.drawEllipse(QPointF(cx + r * 0.45, cy + r * 0.25), blush_r, blush_r * 0.7)
        p.restore()

    def _draw_eyes(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        # Oversized anime-style eyes: wider + taller, double highlight, accent iris.
        eye_y = cy + r * 0.02
        eye_dx = r * 0.38
        eye_rx = r * 0.26
        eye_ry = r * 0.36
        state = self._state
        # Blink only in idle/happy states — closed eyes during SLEEPY is handled below.
        blink = 0.0
        if state in (CompanionState.IDLE, CompanionState.HAPPY, CompanionState.WINK):
            blink_cycle = (math.sin(self._blink_phase) + 1) / 2
            if blink_cycle > 0.95:
                blink = (blink_cycle - 0.95) / 0.05

        def draw_eye(x: float, closed: float, is_wink_right: bool) -> None:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            if state == CompanionState.SLEEPY or closed >= 0.98:
                # Closed curve
                p.setPen(QPen(self._palette.eye, 2))
                p.drawArc(
                    QRectF(x - eye_rx, eye_y - eye_ry * 0.3, eye_rx * 2, eye_ry * 0.6),
                    0 * 16, 180 * 16,
                )
            elif state == CompanionState.EXCITED:
                # Star-shaped eyes
                self._draw_star(p, x, eye_y, eye_rx * 1.1, self._palette.accent)
            elif state == CompanionState.SCARED:
                # Very wide eyes
                p.setBrush(QBrush(QColor("#ffffff")))
                p.setPen(QPen(self._palette.eye, 1.2))
                p.drawEllipse(QPointF(x, eye_y), eye_rx * 1.2, eye_ry * 1.2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(self._palette.eye))
                p.drawEllipse(QPointF(x, eye_y + eye_ry * 0.15), eye_rx * 0.45, eye_ry * 0.45)
            else:
                # Anime-style eye: white sclera → iris in accent color → dark pupil → double highlight
                if closed > 0.01:
                    p.setBrush(QBrush(self._palette.eye))
                    p.drawRoundedRect(
                        QRectF(x - eye_rx, eye_y - eye_ry * (1 - closed) * 0.1, eye_rx * 2, eye_ry * 0.2),
                        3, 3,
                    )
                else:
                    # 1. White sclera (eye whites) — outlined by dark.
                    p.setPen(QPen(self._palette.eye, 1.3))
                    p.setBrush(QBrush(QColor("#ffffff")))
                    p.drawEllipse(QPointF(x, eye_y), eye_rx, eye_ry)
                    # 2. Iris — bright accent color, slightly offset down for that anime look.
                    p.setPen(Qt.PenStyle.NoPen)
                    iris_color = QColor(self._palette.hair)
                    p.setBrush(QBrush(iris_color))
                    p.drawEllipse(QPointF(x, eye_y + eye_ry * 0.05), eye_rx * 0.78, eye_ry * 0.82)
                    # 3. Dark pupil inside iris.
                    p.setBrush(QBrush(self._palette.eye))
                    p.drawEllipse(QPointF(x, eye_y + eye_ry * 0.08), eye_rx * 0.42, eye_ry * 0.5)
                    # 4. Main highlight (upper-left, large round).
                    p.setBrush(QBrush(QColor("#ffffff")))
                    p.drawEllipse(QPointF(x - eye_rx * 0.32, eye_y - eye_ry * 0.38), eye_rx * 0.32, eye_ry * 0.32)
                    # 5. Secondary highlight (small dot bottom-right).
                    p.drawEllipse(QPointF(x + eye_rx * 0.25, eye_y + eye_ry * 0.25), eye_rx * 0.12, eye_ry * 0.12)
                    # 6. Upper eyelid stroke — thick dark line for that expressive manga look.
                    p.setPen(QPen(self._palette.eye, 2.0))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    lid_rect = QRectF(x - eye_rx * 1.05, eye_y - eye_ry * 1.05, eye_rx * 2.1, eye_ry * 1.0)
                    p.drawArc(lid_rect, 0 * 16, 180 * 16)
            p.restore()

        left_closed = blink
        right_closed = blink
        if state == CompanionState.WINK:
            right_closed = 1.0
        draw_eye(cx - eye_dx, left_closed, False)
        draw_eye(cx + eye_dx, right_closed, True)

    def _draw_star(self, p: QPainter, cx: float, cy: float, size: float, color: QColor) -> None:
        path = QPainterPath()
        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = size if i % 2 == 0 else size * 0.45
            points.append(QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        p.fillPath(path, QBrush(color))

    def _draw_mouth(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        p.save()
        state = self._state
        mouth_y = cy + r * 0.45
        mouth_w = r * 0.35
        if state == CompanionState.HAPPY or state == CompanionState.EXCITED:
            p.setPen(QPen(self._palette.mouth, 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx - mouth_w, mouth_y - r * 0.1, mouth_w * 2, r * 0.35)
            p.drawArc(rect, 180 * 16, 180 * 16)
        elif state == CompanionState.WINK:
            p.setPen(QPen(self._palette.mouth, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx - mouth_w * 0.7, mouth_y - r * 0.05, mouth_w * 1.4, r * 0.22)
            p.drawArc(rect, 200 * 16, 140 * 16)
        elif state == CompanionState.SCARED:
            p.setPen(QPen(self._palette.mouth, 1.8))
            p.setBrush(QBrush(QColor("#3a1420")))
            p.drawEllipse(QPointF(cx, mouth_y), r * 0.11, r * 0.14)
        elif state == CompanionState.SLEEPY:
            p.setPen(QPen(self._palette.mouth, 1.8))
            rect = QRectF(cx - mouth_w * 0.35, mouth_y, mouth_w * 0.7, r * 0.12)
            p.drawArc(rect, 0 * 16, 180 * 16)
        else:
            p.setPen(QPen(self._palette.mouth, 2))
            rect = QRectF(cx - mouth_w * 0.6, mouth_y, mouth_w * 1.2, r * 0.2)
            p.drawArc(rect, 200 * 16, 140 * 16)
        p.restore()

    def _draw_state_decor(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        state = self._state
        if state == CompanionState.HAPPY or state == CompanionState.EXCITED:
            # Sparkles around head
            for i, base_angle in enumerate((-1.2, -0.5, 0.2, 1.1)):
                angle = base_angle + math.sin(self._sparkle_phase + i) * 0.15
                dist = r * (1.35 + 0.05 * math.sin(self._sparkle_phase * 2 + i))
                sx = cx + math.cos(angle) * dist
                sy = cy + math.sin(angle) * dist - r * 0.4
                size = r * (0.1 + 0.02 * math.sin(self._sparkle_phase * 3 + i))
                self._draw_star(p, sx, sy, size, self._palette.accent)
        elif state == CompanionState.SCARED:
            # Sweat drop
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#7ecbff")))
            drop_x = cx + r * 0.75
            drop_y = cy - r * 0.35
            path = QPainterPath()
            path.moveTo(drop_x, drop_y - r * 0.18)
            path.quadTo(drop_x + r * 0.13, drop_y, drop_x, drop_y + r * 0.1)
            path.quadTo(drop_x - r * 0.13, drop_y, drop_x, drop_y - r * 0.18)
            p.drawPath(path)
            p.restore()
        elif state == CompanionState.SLEEPY:
            # "z Z" above head
            p.save()
            font = QFont()
            font.setPointSize(max(10, int(r * 0.35)))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(self._palette.accent, 2))
            z_drift = math.sin(self._sparkle_phase) * r * 0.04
            p.drawText(QPointF(cx + r * 0.6, cy - r * 0.6 + z_drift), "z")
            p.drawText(QPointF(cx + r * 0.95, cy - r * 0.95 - z_drift), "Z")
            p.restore()


class CompanionWindow(QWidget):
    """Frameless, always-on-top, transparent overlay holding a CompanionCharacter."""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.character = CompanionCharacter(self)
        self._drag_origin: QPoint | None = None
        self._size = 140
        self.resize(self._size, int(self._size * 1.35))
        self.character.setGeometry(0, 0, self.width(), self.height())

    def set_size(self, size: int) -> None:
        size = max(80, min(400, int(size)))
        self._size = size
        self.resize(size, int(size * 1.35))
        self.character.setGeometry(0, 0, self.width(), self.height())

    def set_opacity_percent(self, percent: int) -> None:
        self.setWindowOpacity(max(0.2, min(1.0, percent / 100.0)))

    def set_anchor(self, anchor: str) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        margin = 20
        x = geom.left() + margin
        y = geom.top() + margin
        if anchor == "top_right":
            x = geom.right() - self.width() - margin
        elif anchor == "bottom_left":
            y = geom.bottom() - self.height() - margin
        elif anchor == "bottom_right":
            x = geom.right() - self.width() - margin
            y = geom.bottom() - self.height() - margin
        self.move(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.closed.emit()
        super().closeEvent(event)


class CompanionController:
    """Polls sensors every few seconds and maps conditions to companion states."""

    POLL_INTERVAL_MS = 2500
    HIGH_TEMP_C = 82.0
    IDLE_SLEEP_SECONDS = 60.0

    def __init__(self, window: CompanionWindow) -> None:
        self._window = window
        self._timer = QTimer()
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._last_process = ""
        self._temp_service = None
        self._started_wave = False
        self._brain = None
        self._last_bubble_state: CompanionState | None = None

    def _lazy_temp(self):
        if self._temp_service is None:
            try:
                from lolilend.temperature_monitor import TempMonitorService
                self._temp_service = TempMonitorService()
            except Exception:
                self._temp_service = False  # sentinel = tried & failed
        return self._temp_service or None

    def attach_brain(self, brain) -> None:
        """Wires a CompanionAiBrain — fresh phrases go into the speech bubble on state change."""
        self._brain = brain

    def start(self) -> None:
        if not self._started_wave:
            self._started_wave = True
            self._window.character.set_state(CompanionState.WINK)
            self._request_phrase(CompanionState.WINK)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _request_phrase(self, state: CompanionState) -> None:
        if self._brain is None:
            return
        self._last_bubble_state = state

        def _on_ready(resolved_state, phrase):
            # Ignore late responses if state already moved on.
            if self._last_bubble_state != resolved_state:
                return
            QTimer.singleShot(0, lambda: self._window.character.set_bubble_text(phrase))

        self._brain.generate_async(state, _on_ready)

    def _transition(self, char, state: CompanionState) -> None:
        char.set_state(state)
        self._request_phrase(state)

    def _tick(self) -> None:
        char = self._window.character
        # Pick up user-triggered transitions (e.g. click → EXCITED) and fetch a fresh phrase.
        if char.state() != self._last_bubble_state and char.state() != CompanionState.IDLE:
            self._request_phrase(char.state())
        # Don't override a still-active transient state (let it run its course).
        if char.state() != CompanionState.IDLE and char.state_age() < STATE_DURATION.get(char.state(), 0):
            return

        # 1. Temperature — priority reaction.
        svc = self._lazy_temp()
        if svc is not None:
            try:
                snap = svc.snapshot() if hasattr(svc, "snapshot") else None
            except Exception:
                snap = None
            if snap is not None:
                cpu = getattr(snap, "cpu_temp", None)
                if cpu is not None and cpu >= self.HIGH_TEMP_C:
                    self._transition(char, CompanionState.SCARED)
                    return

        # 2. Idle input time — sleepy.
        idle = _get_last_input_idle_seconds()
        if idle >= self.IDLE_SLEEP_SECONDS:
            self._transition(char, CompanionState.SLEEPY)
            return

        # 3. Foreground process changed — wink for "new game detected".
        try:
            from lolilend.screenshot_manager import get_foreground_process_name
            current = get_foreground_process_name()
        except Exception:
            current = ""
        if current and current != self._last_process and self._last_process:
            self._last_process = current
            lower = current.lower()
            # Heuristic: only react to likely game processes (skip editors, browsers, shells).
            non_games = {"explorer", "code", "notepad", "chrome", "firefox", "msedge", "devenv", "pycharm64",
                         "discord", "telegram", "obs64", "steam", "epicgameslauncher", "desktop", "unknown"}
            if lower not in non_games:
                self._transition(char, CompanionState.HAPPY)
                return
        elif current:
            self._last_process = current
