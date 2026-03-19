from __future__ import annotations

import io
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lolilend.license_client import LicenseClient

_log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds


class ScreenshotService:
    """Background service that sends heartbeats and handles screenshot requests.

    Runs as a daemon thread. On each heartbeat cycle:
    1. Sends heartbeat to license server
    2. If server returns a screenshot request, captures screen and uploads it
    3. Shows a notification to the user when a screenshot is taken
    """

    def __init__(
        self,
        license_client: LicenseClient,
        token: str,
        hwid: str,
        app_version: str,
    ) -> None:
        self._client = license_client
        self._token = token
        self._hwid = hwid
        self._version = app_version
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            name="screenshot-service",
            daemon=True,
        )
        self._thread.start()
        _log.info("ScreenshotService started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        _log.info("ScreenshotService stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._client.heartbeat(
                    self._token, self._hwid, self._version
                )
                if result.ok and result.screenshot_request_id:
                    self._handle_screenshot(result.screenshot_request_id)
            except Exception as exc:
                _log.debug("Heartbeat failed: %s", exc)

            # Wait for next cycle, checking stop every second
            for _ in range(HEARTBEAT_INTERVAL):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

    def _handle_screenshot(self, request_id: str) -> None:
        """Capture screen and upload to server."""
        _log.info("Screenshot requested: %s", request_id)
        try:
            image_data = self._capture_screen()
            if image_data:
                self._client.upload_screenshot(request_id, image_data)
                _log.info("Screenshot uploaded: %s", request_id)
                self._show_notification()
        except Exception as exc:
            _log.warning("Screenshot capture/upload failed: %s", exc)

    @staticmethod
    def _capture_screen() -> bytes | None:
        """Capture the primary screen as JPEG bytes."""
        try:
            from PySide6.QtCore import QBuffer, QIODevice
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return None

            screen = app.primaryScreen()
            if screen is None:
                return None

            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                return None

            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "JPEG", 70)
            return bytes(buffer.data())
        except Exception as exc:
            _log.warning("Screen capture error: %s", exc)
            return None

    @staticmethod
    def _show_notification() -> None:
        """Show a brief notification that a screenshot was taken."""
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return

            tray = getattr(app, "_tray_icon", None)
            if tray is not None and hasattr(tray, "showMessage"):
                tray.showMessage(
                    "LoliLend",
                    "Был сделан скриншот экрана",
                    tray.MessageIcon.Information,
                    3000,
                )
        except Exception:
            pass
