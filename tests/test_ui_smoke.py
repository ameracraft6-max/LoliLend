from __future__ import annotations

import os
from datetime import datetime
import tempfile
import unittest
import gc
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QToolButton,
    QSystemTrayIcon,
)

from lolilend.fps_monitor import FpsSnapshot, STATUS_NA, STATUS_PERMISSION_REQUIRED, STATUS_RUNNING
from lolilend.general_settings import GeneralSettingsStore
from lolilend.schema import tabs_schema
from lolilend.ui import LoliLendWindow


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_appdata = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._old_appdata = os.environ.get("APPDATA")
        cls._old_ai_autofetch = os.environ.get("LOLILEND_AI_DISABLE_AUTO_FETCH")
        os.environ["APPDATA"] = cls._temp_appdata.name
        os.environ["LOLILEND_AI_DISABLE_AUTO_FETCH"] = "1"
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = cls._old_appdata
        if cls._old_ai_autofetch is None:
            os.environ.pop("LOLILEND_AI_DISABLE_AUTO_FETCH", None)
        else:
            os.environ["LOLILEND_AI_DISABLE_AUTO_FETCH"] = cls._old_ai_autofetch
        try:
            cls._temp_appdata.cleanup()
        except PermissionError:
            pass

    def setUp(self) -> None:
        self.window = LoliLendWindow()
        self.window.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.window._explicit_exit = True
        self.window.close()
        self._app.processEvents()

    def test_window_created_resizable_with_maximize(self) -> None:
        self.assertGreaterEqual(self.window.minimumWidth(), 1000)
        self.assertGreaterEqual(self.window.minimumHeight(), 600)
        self.assertTrue(bool(self.window.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint))
        self.assertGreater(self.window.maximumWidth(), self.window.minimumWidth())
        self.assertGreater(self.window.maximumHeight(), self.window.minimumHeight())

    def test_window_geometry_persists_between_runs(self) -> None:
        self.window.resize(1480, 860)
        self._app.processEvents()
        self.window.close()
        self._app.processEvents()

        reopened = LoliLendWindow()
        reopened.show()
        self._app.processEvents()
        try:
            self.assertEqual(reopened.width(), 1480)
            self.assertEqual(reopened.height(), 860)
        finally:
            reopened.close()
            self._app.processEvents()

    def test_status_bar_hidden_by_default(self) -> None:
        self.assertFalse(self.window.statusBar().isVisible())

    def test_all_tabs_switch_without_errors(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None
        self.assertEqual(len(buttons), len(tabs_schema))

        for index, button in enumerate(buttons):
            button.click()
            self._app.processEvents()
            self.assertEqual(stacked.currentIndex(), index)

    def test_lifecycle_pages_start_and_stop_timers(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        perf_index = tab_index["performance"]
        net_index = tab_index["network"]
        analytics_index = tab_index["analytics"]
        fps_index = tab_index["fps"]
        general_index = tab_index["general"]

        buttons[perf_index].click()
        self._app.processEvents()
        perf_page = stacked.widget(perf_index)
        self.assertTrue(perf_page._monitor_panel._timer.isActive())

        buttons[net_index].click()
        self._app.processEvents()
        net_page = stacked.widget(net_index)
        self.assertFalse(perf_page._monitor_panel._timer.isActive())
        self.assertTrue(net_page._monitor_panel._timer.isActive())

        buttons[analytics_index].click()
        self._app.processEvents()
        analytics_page = stacked.widget(analytics_index)
        self.assertFalse(net_page._monitor_panel._timer.isActive())
        self.assertTrue(analytics_page._timer.isActive())

        buttons[fps_index].click()
        self._app.processEvents()
        fps_page = stacked.widget(fps_index)
        self.assertFalse(analytics_page._timer.isActive())
        self.assertTrue(fps_page._timer.isActive())

        buttons[general_index].click()
        self._app.processEvents()
        self.assertFalse(fps_page._timer.isActive())
        self.assertFalse(analytics_page._timer.isActive())

    def test_fps_tab_buttons_toggle_stub_service_state(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        fps_index = tab_index["fps"]
        buttons[fps_index].click()
        self._app.processEvents()
        fps_page = stacked.widget(fps_index)

        class _StubService:
            def __init__(self) -> None:
                self.running = False

            def start_capture(self):
                self.running = True
                return True, "started"

            def stop_capture(self) -> None:
                self.running = False

            def is_running(self) -> bool:
                return self.running

            def windows_supported(self) -> bool:
                return True

            def latest_snapshot(self) -> FpsSnapshot:
                return FpsSnapshot(
                    timestamp=datetime.now(),
                    status=STATUS_RUNNING if self.running else STATUS_NA,
                    fps=120.0 if self.running else None,
                    frame_time_ms=8.3 if self.running else None,
                    one_percent_low_fps=95.0 if self.running else None,
                    pid=100 if self.running else None,
                    process_name="game.exe" if self.running else None,
                    backend_error=None,
                )

        stub = _StubService()
        fps_page._service = stub
        fps_page._sync_buttons()

        fps_page.capture_start_button.click()
        self._app.processEvents()
        self.assertTrue(stub.is_running())

        fps_page.capture_stop_button.click()
        self._app.processEvents()
        self.assertFalse(stub.is_running())

    def test_fps_permission_error_triggers_elevated_restart(self) -> None:
        self.window.close()
        self._app.processEvents()

        class _StubElevationManager:
            was_relaunched_for_fps = False

            def __init__(self) -> None:
                self.calls = 0

            def can_relaunch_for_fps(self) -> bool:
                return True

            def relaunch_for_fps(self) -> tuple[bool, str]:
                self.calls += 1
                return True, "Restarting LoliLend with administrator privileges"

        class _PermissionService:
            def start_capture(self):
                return False, "PresentMon requires administrator privileges"

            def stop_capture(self) -> None:
                return

            def is_running(self) -> bool:
                return False

            def windows_supported(self) -> bool:
                return True

            def latest_snapshot(self) -> FpsSnapshot:
                return FpsSnapshot(
                    timestamp=datetime.now(),
                    status=STATUS_PERMISSION_REQUIRED,
                    fps=None,
                    frame_time_ms=None,
                    one_percent_low_fps=None,
                    pid=None,
                    process_name=None,
                    backend_error="PresentMon requires administrator privileges or membership in Performance Log Users.",
                    permission_required=True,
                )

        manager = _StubElevationManager()
        self.window = LoliLendWindow(elevation_manager=manager)
        self.window.show()
        self._app.processEvents()

        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        fps_index = tab_index["fps"]
        buttons[fps_index].click()
        self._app.processEvents()
        fps_page = stacked.widget(fps_index)
        fps_page._service = _PermissionService()

        quit_called: list[bool] = []
        fps_page._quit_application = lambda: quit_called.append(True)
        fps_page.capture_start_button.click()
        self._app.processEvents()

        self.assertEqual(manager.calls, 1)
        self.assertTrue(quit_called)
        self.assertTrue(GeneralSettingsStore().load_settings().fps_capture_enabled)

    def test_fps_autostart_clears_setting_after_failed_admin_restart(self) -> None:
        self.window.close()
        self._app.processEvents()

        class _StubElevationManager:
            was_relaunched_for_fps = True

            def can_relaunch_for_fps(self) -> bool:
                return False

            def relaunch_for_fps(self) -> tuple[bool, str]:
                raise AssertionError("relaunch should not be called twice")

        class _PermissionService:
            def start_capture(self):
                return False, "PresentMon requires administrator privileges"

            def stop_capture(self) -> None:
                return

            def is_running(self) -> bool:
                return False

            def windows_supported(self) -> bool:
                return True

            def latest_snapshot(self) -> FpsSnapshot:
                return FpsSnapshot(
                    timestamp=datetime.now(),
                    status=STATUS_PERMISSION_REQUIRED,
                    fps=None,
                    frame_time_ms=None,
                    one_percent_low_fps=None,
                    pid=None,
                    process_name=None,
                    backend_error="PresentMon requires administrator privileges or membership in Performance Log Users.",
                    permission_required=True,
                )

        store = GeneralSettingsStore()
        settings = store.load_settings()
        settings.fps_capture_enabled = True
        store.save_settings(settings)

        self.window = LoliLendWindow(elevation_manager=_StubElevationManager())
        self.window.show()
        self._app.processEvents()

        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        fps_index = tab_index["fps"]
        buttons[fps_index].click()
        self._app.processEvents()
        fps_page = stacked.widget(fps_index)
        fps_page._service = _PermissionService()
        fps_page._attempt_capture_start(auto_start=True)
        self._app.processEvents()

        self.assertFalse(GeneralSettingsStore().load_settings().fps_capture_enabled)

    def test_ai_tab_presence_and_send_control(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        ai_index = tab_index["ai"]
        buttons[ai_index].click()
        self._app.processEvents()
        ai_page = stacked.widget(ai_index)
        self.assertTrue(hasattr(ai_page, "send_button"))
        self.assertFalse(ai_page.send_button.isEnabled())
        self.assertIsInstance(ai_page.root_splitter, QSplitter)
        self.assertIsInstance(ai_page.chat_splitter, QSplitter)
        self.assertIsInstance(ai_page.findChild(QTabWidget, "AiTaskTabs"), QTabWidget)
        self.assertIsInstance(ai_page.findChild(QCheckBox), QCheckBox)

    def test_ai_non_file_panel_optional_inputs_remain_alive(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        ai_index = tab_index["ai"]
        buttons[ai_index].click()
        self._app.processEvents()
        ai_page = stacked.widget(ai_index)

        # Force collection to catch accidental parentless widget destruction.
        gc.collect()
        panel = ai_page.task_panels["text_to_image"]
        self.assertEqual(panel.file_path(), "")
        self.assertEqual(panel.source_language(), "")
        self.assertEqual(panel.target_language(), "")

    def test_ai_task_forms_show_only_relevant_inputs(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        ai_index = tab_index["ai"]
        buttons[ai_index].click()
        self._app.processEvents()
        ai_page = stacked.widget(ai_index)

        text_to_image = ai_page.task_panels["text_to_image"]
        self.assertTrue(text_to_image.file_browse_button.isHidden())
        self.assertTrue(text_to_image.file_path_edit.isHidden())

        image_to_text = ai_page.task_panels["image_to_text"]
        self.assertFalse(image_to_text.file_browse_button.isHidden())
        self.assertFalse(image_to_text.file_path_edit.isHidden())

    def test_telegram_proxy_tab_presence_and_controls(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        proxy_index = tab_index["telegram_proxy"]
        buttons[proxy_index].click()
        self._app.processEvents()
        proxy_page = stacked.widget(proxy_index)

        self.assertIsInstance(proxy_page.findChild(QLineEdit, "TelegramProxyHostEdit"), QLineEdit)
        self.assertIsInstance(proxy_page.findChild(QSpinBox, "TelegramProxyPortSpin"), QSpinBox)
        self.assertIsInstance(proxy_page.findChild(QPlainTextEdit, "TelegramProxyDcText"), QPlainTextEdit)
        self.assertIsInstance(proxy_page.findChild(QCheckBox, "TelegramProxyVerboseCheck"), QCheckBox)
        self.assertIsInstance(proxy_page.findChild(QPushButton, "TelegramProxyStartButton"), QPushButton)
        self.assertIsInstance(proxy_page.findChild(QPushButton, "TelegramProxyStopButton"), QPushButton)
        self.assertIsInstance(proxy_page.findChild(QPushButton, "TelegramProxyRestartButton"), QPushButton)
        self.assertFalse(proxy_page.stop_button.isEnabled())

    def test_discord_quest_tab_presence_and_controls(self) -> None:
        buttons = self.window.findChildren(QToolButton, "NavButton")
        stacked = self.window.findChild(QStackedWidget)
        self.assertIsNotNone(stacked)
        assert stacked is not None

        tab_index = {tab.id: idx for idx, tab in enumerate(tabs_schema)}
        quest_index = tab_index["discord_quest"]
        buttons[quest_index].click()
        self._app.processEvents()
        quest_page = stacked.widget(quest_index)

        self.assertIsInstance(quest_page.findChild(QLineEdit, "DiscordQuestSearchEdit"), QLineEdit)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestRefetchButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QComboBox, "DiscordQuestSearchCombo"), QComboBox)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestAddGameButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestRemoveGameButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QTableWidget, "DiscordQuestGamesTable"), QTableWidget)
        self.assertIsInstance(quest_page.findChild(QComboBox, "DiscordQuestExecutableCombo"), QComboBox)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestInstallPlayButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestPlayButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestStopButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestRpcButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPushButton, "DiscordQuestOpenLogsButton"), QPushButton)
        self.assertIsInstance(quest_page.findChild(QPlainTextEdit, "DiscordQuestLogView"), QPlainTextEdit)

    def _create_window_with_tray(self, tray_available: bool = True) -> None:
        self.window._explicit_exit = True
        self.window.close()
        self._app.processEvents()
        self.window = LoliLendWindow(tray_available=lambda: tray_available)
        self.window.show()
        self._app.processEvents()

    def test_close_button_sends_window_to_tray_when_available(self) -> None:
        self._create_window_with_tray(tray_available=True)
        self.assertIsNotNone(self.window._tray_icon)

        self.window.close()
        self._app.processEvents()

        self.assertFalse(self.window.isVisible())
        assert self.window._tray_icon is not None
        self.assertTrue(self.window._tray_icon.isVisible())

    def test_minimize_sends_window_to_tray_when_available(self) -> None:
        self._create_window_with_tray(tray_available=True)

        self.window.showMinimized()
        self._app.processEvents()
        self._app.processEvents()

        self.assertFalse(self.window.isVisible())

    def test_close_behaves_normally_when_tray_unavailable(self) -> None:
        self._create_window_with_tray(tray_available=False)

        self.window.close()
        self._app.processEvents()

        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window._tray_icon)

    def test_tray_exit_performs_explicit_shutdown(self) -> None:
        self._create_window_with_tray(tray_available=True)
        self.assertIsNotNone(self.window._tray_icon)

        self.window._quit_from_tray()
        self._app.processEvents()

        self.assertTrue(self.window._explicit_exit)
        assert self.window._tray_icon is not None
        self.assertFalse(self.window._tray_icon.isVisible())

    def test_tray_menu_actions_use_bridge_and_update_settings(self) -> None:
        self._create_window_with_tray(tray_available=True)
        bridge = self.window._ui_bridge
        self.assertIsNotNone(bridge)
        assert bridge is not None
        assert self.window._tray_hide_notifications_action is not None
        assert self.window._tray_autostart_action is not None
        assert self.window._tray_fps_capture_action is not None
        assert self.window._tray_fps_overlay_action is not None
        assert self.window._tray_proxy_action is not None

        current_hide = bridge.snapshot().hide_notifications
        self.window._tray_hide_notifications_action.trigger()
        self._app.processEvents()
        self.assertEqual(GeneralSettingsStore().load_settings().hide_notifications, (not current_hide))

        bridge.set_autostart_enabled = Mock(return_value=(True, "ok"))
        expected_autostart = not self.window._tray_autostart_action.isChecked()
        self.window._tray_autostart_action.trigger()
        self._app.processEvents()
        bridge.set_autostart_enabled.assert_called_with(expected_autostart)

        bridge.set_fps_capture_enabled = Mock(return_value=True)
        expected_capture = not self.window._tray_fps_capture_action.isChecked()
        self.window._tray_fps_capture_action.trigger()
        self._app.processEvents()
        bridge.set_fps_capture_enabled.assert_called_with(expected_capture)

        bridge.set_fps_overlay_enabled = Mock()
        expected_overlay = not self.window._tray_fps_overlay_action.isChecked()
        self.window._tray_fps_overlay_action.trigger()
        self._app.processEvents()
        bridge.set_fps_overlay_enabled.assert_called_with(expected_overlay)

        bridge.set_telegram_proxy_enabled = Mock(return_value=True)
        expected_proxy = not self.window._tray_proxy_action.isChecked()
        self.window._tray_proxy_action.trigger()
        self._app.processEvents()
        bridge.set_telegram_proxy_enabled.assert_called_with(expected_proxy)

    def test_tray_icon_click_behaviour(self) -> None:
        self._create_window_with_tray(tray_available=True)
        self.assertTrue(self.window.isVisible())

        self.window._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self._app.processEvents()
        self.assertFalse(self.window.isVisible())

        self.window._on_tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self._app.processEvents()
        self.assertTrue(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
