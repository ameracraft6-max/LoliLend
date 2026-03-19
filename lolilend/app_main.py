from __future__ import annotations

import sys

def run_app(argv: list[str] | None = None) -> int:
    from lolilend.bootstrap import prime_qt_library_paths

    prime_qt_library_paths()

    from PySide6.QtWidgets import QApplication

    from lolilend.runtime import WindowsElevationManager, sanitize_argv
    from lolilend.ui import LoliLendWindow

    raw_argv = list(argv or sys.argv)
    filtered_argv = [raw_argv[0], *[value for value in raw_argv[1:] if value != "--run-app"]] if raw_argv else []
    elevation_manager = WindowsElevationManager(filtered_argv)
    app = QApplication(sanitize_argv(filtered_argv))
    window = LoliLendWindow(elevation_manager=elevation_manager)
    window.show()

    # Start screenshot service if license is active
    screenshot_svc = _start_screenshot_service()

    code = app.exec()

    if screenshot_svc is not None:
        screenshot_svc.stop()

    return code


def _start_screenshot_service():
    """Start background screenshot/heartbeat service if license is active."""
    try:
        from lolilend.general_settings import GeneralSettingsStore
        from lolilend.license_client import LicenseClient
        from lolilend.license_hwid import get_hwid
        from lolilend.screenshot_service import ScreenshotService
        from lolilend.version import APP_VERSION

        store = GeneralSettingsStore()
        settings = store.load_settings()

        if not settings.license_token or settings.license_status != "active":
            return None

        client = LicenseClient(settings.license_server_url)
        hwid = get_hwid()
        svc = ScreenshotService(client, settings.license_token, hwid, APP_VERSION)
        svc.start()
        return svc
    except Exception:
        return None
