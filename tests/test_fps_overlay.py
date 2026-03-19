from __future__ import annotations

import os
from datetime import datetime
import unittest

from PySide6.QtWidgets import QApplication

from lolilend.fps_monitor import FpsSnapshot, STATUS_RUNNING
from lolilend.fps_overlay import FpsOverlayWindow


class _FakeHotkeyBackend:
    def __init__(self) -> None:
        self._callback = None
        self.registered = False
        self.registered_hotkey = ""
        self.unregistered = False

    def register(self, hotkey: str, callback):
        self.registered = True
        self.registered_hotkey = hotkey
        self._callback = callback
        return True, None

    def unregister(self) -> None:
        self.unregistered = True
        self._callback = None

    def trigger(self) -> None:
        if self._callback is not None:
            self._callback()


class FpsOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.hotkey = _FakeHotkeyBackend()
        self.overlay = FpsOverlayWindow(hotkey_backend=self.hotkey)

    def tearDown(self) -> None:
        self.overlay.shutdown()
        self._app.processEvents()

    def test_hotkey_register_and_toggle_visibility(self) -> None:
        ok, error = self.overlay.set_hotkey("Ctrl+Shift+F10")
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertTrue(self.hotkey.registered)

        self.overlay.hide()
        self.hotkey.trigger()
        self._app.processEvents()
        self.assertTrue(self.overlay.isVisible())

        self.hotkey.trigger()
        self._app.processEvents()
        self.assertFalse(self.overlay.isVisible())

    def test_updates_snapshot_text(self) -> None:
        snapshot = FpsSnapshot(
            timestamp=datetime.now(),
            status=STATUS_RUNNING,
            fps=123.4,
            frame_time_ms=8.11,
            one_percent_low_fps=77.7,
            pid=42,
            process_name="game.exe",
            backend_error=None,
        )
        self.overlay.update_snapshot(snapshot)
        self.assertIn("123", self.overlay.fps_label.text())
        self.assertIn("8.11", self.overlay.frametime_label.text())
        self.assertIn("78", self.overlay.one_low_label.text())
        self.assertIn(STATUS_RUNNING, self.overlay.status_label.text())

    def test_scale_and_opacity_applied(self) -> None:
        old_width = self.overlay.width()
        self.overlay.set_overlay_scale(130)
        self.overlay.set_overlay_opacity(70)
        self.assertGreaterEqual(self.overlay.width(), old_width)
        self.assertAlmostEqual(self.overlay.windowOpacity(), 0.7, places=2)


if __name__ == "__main__":
    unittest.main()
