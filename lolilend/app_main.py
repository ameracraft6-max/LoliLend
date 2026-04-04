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
    return app.exec()
