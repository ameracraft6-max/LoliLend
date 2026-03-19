from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from lolilend.launcher import APP_MODE_FLAG, LauncherWindow
from lolilend.updater import UpdateState


class LauncherSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_appdata = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._old_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = cls._temp_appdata.name
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = cls._old_appdata
        cls._temp_appdata.cleanup()

    def setUp(self) -> None:
        self.window = LauncherWindow(auto_start_check=False)
        self.window.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self._app.processEvents()

    def test_launcher_main_widgets_exist(self) -> None:
        self.assertIsInstance(self.window.findChild(QPushButton, "LauncherCheckButton"), QPushButton)
        self.assertIsInstance(self.window.findChild(QLineEdit, "LauncherRepoEdit"), QLineEdit)
        self.assertIsInstance(self.window.findChild(QLabel, "LauncherPreviewLabel"), QLabel)
        self.assertEqual(self.window.launch_app_button.text(), "Запустить лаунчер")

    def test_image_controls_are_removed(self) -> None:
        self.assertIsNone(self.window.findChild(QPushButton, "LauncherChooseImageButton"))
        self.assertIsNone(self.window.findChild(QPushButton, "LauncherResetImageButton"))
        self.assertIsNotNone(self.window.preview_label.pixmap())
        labels = [label.text() for label in self.window.findChildren(QLabel)]
        self.assertNotIn("Изображение лаунчера", labels)

    def test_update_state_labels_change(self) -> None:
        self.window._set_update_state(UpdateState.CHECKING, "Проверка...")
        self.assertEqual(self.window.state_chip.text(), "CHECKING")
        self.window._set_update_state(UpdateState.FAILED, "Ошибка")
        self.assertEqual(self.window.state_chip.text(), "FAILED")
        self.assertTrue(self.window.retry_button.isVisible())

    def test_app_launch_command_contains_mode_flag(self) -> None:
        command = self.window._app_launch_command()
        self.assertIn(APP_MODE_FLAG, command)

    def test_child_process_env_resets_pyinstaller_when_frozen(self) -> None:
        with patch("sys.frozen", True, create=True):
            env = self.window._child_process_env()
        self.assertEqual(env.get("PYINSTALLER_RESET_ENVIRONMENT"), "1")


if __name__ == "__main__":
    unittest.main()
