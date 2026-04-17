"""Floating neon particle overlay for the Neon Anime theme."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget


@dataclass(slots=True)
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    sprite_idx: int
    scale: float
    alpha: float
    twinkle_phase: float


def _make_glow_sprite(color: QColor, size: int = 48) -> QPixmap:
    """Pre-render a glowing dot once, reuse via drawPixmap every frame (~10× faster than QRadialGradient per particle)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = QPointF(size / 2, size / 2)
    gradient = QRadialGradient(center, size / 2)
    core = QColor(color)
    core.setAlphaF(1.0)
    mid = QColor(color)
    mid.setAlphaF(0.28)
    edge = QColor(color)
    edge.setAlphaF(0.0)
    gradient.setColorAt(0.0, core)
    gradient.setColorAt(0.35, mid)
    gradient.setColorAt(1.0, edge)
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return pm


class NeonParticleOverlay(QWidget):
    """Semi-transparent layer that drifts glowing dots upwards behind the UI.

    Activates only while the active theme is Neon Anime. Uses a single 20 FPS
    QTimer and blits pre-rendered glow sprites — CPU impact ~0.5-1%.
    """

    PARTICLE_COUNT = 28
    FRAME_INTERVAL_MS = 50  # 20 FPS — plenty for slow drift, halves CPU vs 30 FPS

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sprites: list[QPixmap] = []
        self._particles: list[_Particle] = []
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)
        self._rebuild_sprites(QColor("#ff2e88"), QColor("#00eaff"))
        self.hide()

    def set_palette(self, primary: str, bright: str) -> None:
        self._rebuild_sprites(QColor(primary), QColor(bright))

    def _rebuild_sprites(self, primary: QColor, bright: QColor) -> None:
        self._sprites = [_make_glow_sprite(primary), _make_glow_sprite(bright)]

    def start(self) -> None:
        if not self._particles:
            self._spawn_all()
        if not self._timer.isActive():
            self._timer.start()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        if self._particles:
            self._spawn_all()

    def _spawn_all(self) -> None:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        self._particles = [self._make_particle(w, h, random.random() * h) for _ in range(self.PARTICLE_COUNT)]

    def _make_particle(self, w: int, h: int, y_start: float | None = None) -> _Particle:
        return _Particle(
            x=random.uniform(0, w),
            y=y_start if y_start is not None else h + random.uniform(5, 60),
            vx=random.uniform(-0.15, 0.15),
            vy=random.uniform(-0.6, -0.2),
            sprite_idx=random.randint(0, 1),
            scale=random.uniform(0.35, 0.95),
            alpha=random.uniform(0.4, 0.9),
            twinkle_phase=random.uniform(0, 6.283),
        )

    def _advance(self) -> None:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        for p in self._particles:
            p.x += p.vx
            p.y += p.vy
            p.twinkle_phase += 0.07
            if p.y < -10 or p.x < -20 or p.x > w + 20:
                p.x = random.uniform(0, w)
                p.y = h + random.uniform(5, 30)
                p.sprite_idx = random.randint(0, 1)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        if not self._particles or not self._sprites:
            return
        painter = QPainter(self)
        # No Antialiasing hint — drawPixmap on transparent backgrounds is already smooth.
        for p in self._particles:
            twinkle = 0.6 + 0.4 * math.sin(p.twinkle_phase)
            painter.setOpacity(max(0.0, min(1.0, p.alpha * twinkle)))
            sprite = self._sprites[p.sprite_idx]
            size = int(sprite.width() * p.scale)
            painter.drawPixmap(int(p.x - size / 2), int(p.y - size / 2), size, size, sprite)
