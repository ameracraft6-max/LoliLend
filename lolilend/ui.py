from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Protocol

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPen, QPolygonF, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lolilend.ai_ui import AiTabPage
from lolilend.analytics import AnalyticsSummary, GameAnalyticsService, LiveGameEntry, TopGameEntry, format_duration
from lolilend.discord_quests import DiscordQuestService
from lolilend.yandex_music_rpc import YandexMusicRpcConfig, YandexMusicRpcService, YandexMusicRpcStore
from lolilend.fps_monitor import FpsMonitorService, FpsSnapshot, STATUS_WINDOWS_ONLY
from lolilend.fps_overlay import FpsOverlayWindow
from lolilend.general_settings import GeneralSettings, GeneralSettingsStore
from lolilend.monitoring import (
    HistoryBuffer,
    MonitorService,
    ProcessSnapshot,
    SystemSnapshot,
    format_bitrate_auto,
    format_bitrate_text,
    format_bytes_text,
)
from lolilend.runtime import WindowsElevationManager, asset_path
from lolilend.schema import ControlSpec, SectionSpec, TabSpec, tabs_schema
from lolilend.telegram_proxy import TelegramProxyConfig, TelegramProxyService, TelegramProxyStore
from lolilend.theme import app_stylesheet
from lolilend.ui_state import decode_qbytearray, encode_qbytearray
from lolilend.version import APP_NAME


_ASSETS_DIR = asset_path()
_ICON_DIR = _ASSETS_DIR / "icons"
_FONT_PATH = _ASSETS_DIR / "fonts" / "Rajdhani-Medium.ttf"
_BACKGROUND_PATH = _ASSETS_DIR / "background_ref.png"
_TRAY_ICON_PATH = _ICON_DIR / "general.svg"
_FONT_REGISTERED = False


class _LifecyclePage(Protocol):
    def on_shown(self) -> None: ...

    def on_hidden(self) -> None: ...


class _ElevationManagerProtocol(Protocol):
    @property
    def was_relaunched_for_fps(self) -> bool: ...

    def can_relaunch_for_fps(self) -> bool: ...

    def relaunch_for_fps(self) -> tuple[bool, str]: ...


@dataclass(slots=True)
class SecurityLinkItem:
    title: str
    description: str
    url: str
    group: str


@dataclass(slots=True)
class UiRuntimeState:
    hide_notifications: bool = False
    smooth_animation: bool = True
    hints_enabled: bool = True
    active_ai: str = "AI LOLILEND"
    visual_theme: str = "Dark"
    accent_preset: str = "Dark"  # legacy alias
    interface_scale: int = 100
    font_size: int = 13
    panel_opacity: int = 86
    sidebar_width: int = 102
    compact_mode: bool = False
    show_status_bar: bool = True

    @classmethod
    def from_settings(cls, settings: GeneralSettings) -> "UiRuntimeState":
        runtime = cls()
        runtime.update_from_settings(settings)
        return runtime

    def update_from_settings(self, settings: GeneralSettings) -> None:
        self.hide_notifications = settings.hide_notifications
        self.smooth_animation = settings.smooth_animation
        self.hints_enabled = settings.show_hints
        self.active_ai = settings.active_ai
        self.visual_theme = settings.visual_theme
        self.accent_preset = settings.visual_theme  # legacy alias
        self.interface_scale = settings.interface_scale
        self.font_size = settings.font_size
        self.panel_opacity = settings.panel_opacity
        self.sidebar_width = settings.sidebar_width
        self.compact_mode = settings.compact_mode
        self.show_status_bar = settings.show_status_bar


@dataclass(slots=True)
class UiTrayState:
    profiles: list[str]
    active_profile: str
    hide_notifications: bool
    autostart_enabled: bool
    fps_capture_enabled: bool
    fps_overlay_enabled: bool
    telegram_proxy_enabled: bool


@dataclass(slots=True)
class UiBridge:
    snapshot: Callable[[], UiTrayState]
    available_profiles: Callable[[], list[str]]
    activate_profile: Callable[[str], bool]
    set_hide_notifications: Callable[[bool], None]
    set_autostart_enabled: Callable[[bool], tuple[bool, str]]
    set_fps_capture_enabled: Callable[[bool], bool]
    set_fps_overlay_enabled: Callable[[bool], None]
    set_telegram_proxy_enabled: Callable[[bool], bool]
    set_theme: Callable[[str], None] = lambda _: None


_SECURITY_TITLE = "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438"
_SECURITY_SUBTITLE = "\u0410\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b\u0435 \u0441\u0441\u044b\u043b\u043a\u0438 \u0438 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b"
_GROUP_TOOLS = "\u0410\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b"
_GROUP_COMMUNITY = "\u0421\u043e\u043e\u0431\u0449\u0435\u0441\u0442\u0432\u043e"
_GROUP_CREATOR = "\u0421\u043e\u0437\u0434\u0430\u0442\u0435\u043b\u044c"
_BTN_OPEN = "\u041e\u0442\u043a\u0440\u044b\u0442\u044c"
_BTN_COPY = "\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c"
_STATUS_OPENED = "\u041e\u0442\u043a\u0440\u044b\u0442\u0430 \u0441\u0441\u044b\u043b\u043a\u0430"
_STATUS_OPEN_FAILED = "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u0441\u0441\u044b\u043b\u043a\u0443"
_STATUS_COPIED = "\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u043e \u0432 \u0431\u0443\u0444\u0435\u0440"
_DISCORD_SERVER_TITLE = "Discord \u0441\u0435\u0440\u0432\u0435\u0440"
_DISCORD_CREATOR = "Discord: shuutl"
_DISCORD_CREATOR_HINT = "\u041d\u0438\u043a \u0441\u043e\u0437\u0434\u0430\u0442\u0435\u043b\u044f \u0434\u043b\u044f \u0441\u0432\u044f\u0437\u0438"


_SECURITY_LINKS: list[SecurityLinkItem] = [
    SecurityLinkItem(
        title="zapret-discord-youtube",
        description="\u041e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u0430\u044f \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0445 \u0440\u0435\u043b\u0438\u0437\u043e\u0432.",
        url="https://github.com/Flowseal/zapret-discord-youtube/releases/latest",
        group="tools",
    ),
    SecurityLinkItem(
        title="discord-quest-completer",
        description="\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0441\u0442\u0430\u0431\u0438\u043b\u044c\u043d\u044b\u0439 \u0440\u0435\u043b\u0438\u0437 \u043d\u0430 GitHub.",
        url="https://github.com/markterence/discord-quest-completer/releases/latest",
        group="tools",
    ),
    SecurityLinkItem(
        title="AyuGram Desktop",
        description="\u0421\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u0430\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b\u0445 \u0441\u0431\u043e\u0440\u043e\u043a.",
        url="https://github.com/AyuGram/AyuGramDesktop/releases/latest",
        group="tools",
    ),
    SecurityLinkItem(
        title="Happ",
        description="\u041e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u0441\u0430\u0439\u0442 \u043f\u0440\u043e\u0435\u043a\u0442\u0430.",
        url="https://www.happ.su/main/ru",
        group="tools",
    ),
    SecurityLinkItem(
        title=_DISCORD_SERVER_TITLE,
        description="\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u0435\u043b\u044c\u043d\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430 \u0432 \u0441\u043e\u043e\u0431\u0449\u0435\u0441\u0442\u0432\u043e.",
        url="https://discord.gg/XegeMFpCCw",
        group="community",
    ),
]


def _install_hud_font() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    _FONT_REGISTERED = True
    if not _FONT_PATH.exists():
        return
    QFontDatabase.addApplicationFont(str(_FONT_PATH))


class HudBackgroundSurface(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("HudBackgroundSurface")
        self._pixmap = QPixmap(str(_BACKGROUND_PATH)) if _BACKGROUND_PATH.exists() else QPixmap()

    def set_theme_background(self, theme_name: str) -> None:
        """Reload background image for the given theme."""
        from lolilend.theme import get_theme
        from lolilend.runtime import asset_path
        spec = get_theme(theme_name)
        if spec.bg_image:
            path = asset_path(spec.bg_image)
            if path.exists():
                self._pixmap = QPixmap(str(path))
                self.update()
                return
        # No image for this theme — use gradient fallback
        self._pixmap = QPixmap()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            offset_x = (scaled.width() - rect.width()) // 2
            offset_y = (scaled.height() - rect.height()) // 2
            painter.drawPixmap(0, 0, scaled, offset_x, offset_y, rect.width(), rect.height())
        else:
            gradient = QLinearGradient(0, 0, 0, rect.height())
            gradient.setColorAt(0.0, QColor("#232933"))
            gradient.setColorAt(0.55, QColor("#1b1f27"))
            gradient.setColorAt(1.0, QColor("#0f1218"))
            painter.fillRect(rect, gradient)

        painter.fillRect(rect, QColor(4, 6, 10, 178))
        painter.fillRect(0, 0, rect.width(), 60, QColor(0, 0, 0, 44))
        painter.fillRect(0, rect.height() - 90, rect.width(), 90, QColor(0, 0, 0, 54))

        painter.setPen(QPen(QColor(255, 255, 255, 10), 1))
        step = 3
        for y in range(0, rect.height(), step):
            painter.drawLine(0, y, rect.width(), y)

        font = QFont("Rajdhani Medium", 26)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(245, 245, 245, 80))
        painter.drawText(rect.adjusted(0, 0, -30, -18), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), "LOLILEND")
        painter.setPen(QColor(30, 34, 42, 220))
        painter.drawText(rect.adjusted(-2, -2, -32, -20), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), "LOLILEND")


class RefPanelBox(QGroupBox):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setObjectName("RefPanelBox")


class RefSectionHeader(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "ref_section")


class RefToggleRow(QWidget):
    def __init__(self, text: str, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.checkbox = QCheckBox(text)
        self.checkbox.setChecked(checked)
        layout.addWidget(self.checkbox, 1)
        self.swatch = QFrame()
        self.swatch.setObjectName("RefSwatch")
        self.swatch.setFixedSize(14, 8)
        layout.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class RefSelectRow(QWidget):
    def __init__(
        self,
        title: str,
        items: Sequence[str],
        default: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(RefSectionHeader(title))
        self.combo = QComboBox()
        self.combo.addItems([str(item) for item in items])
        if default is not None:
            self.combo.setCurrentText(str(default))
        layout.addWidget(self.combo)


class RefSliderRow(QWidget):
    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(RefSectionHeader(title))

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(8)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setValue(value)
        slider_row.addWidget(self.slider, 1)

        self.value_label = QLabel(f"{value}{suffix}")
        self.value_label.setMinimumWidth(46)
        slider_row.addWidget(self.value_label)
        layout.addLayout(slider_row)

        def _sync_label(new_value: int) -> None:
            self.value_label.setText(f"{new_value}{suffix}")

        self.slider.valueChanged.connect(_sync_label)


class RefActionRow(QWidget):
    def __init__(self, label: str, callback: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)


def _resolve_icon(widget: QWidget, icon_key: str):
    custom_icon = _ICON_DIR / f"{icon_key}.svg"
    if custom_icon.exists():
        return QIcon(str(custom_icon))

    icon_map = {
        "general": QStyle.StandardPixmap.SP_DesktopIcon,
        "performance": QStyle.StandardPixmap.SP_ComputerIcon,
        "fps": QStyle.StandardPixmap.SP_MediaPlay,
        "analytics": QStyle.StandardPixmap.SP_DialogApplyButton,
        "ai": QStyle.StandardPixmap.SP_MessageBoxInformation,
        "network": QStyle.StandardPixmap.SP_DriveNetIcon,
        "telegram_proxy": QStyle.StandardPixmap.SP_DriveNetIcon,
        "discord_quest": QStyle.StandardPixmap.SP_MessageBoxInformation,
        "security": QStyle.StandardPixmap.SP_MessageBoxWarning,
        "profiles": QStyle.StandardPixmap.SP_DirHomeIcon,
    }
    pixmap = icon_map.get(icon_key, QStyle.StandardPixmap.SP_FileIcon)
    return widget.style().standardIcon(pixmap)


def _application_icon(widget: QWidget) -> QIcon:
    if _TRAY_ICON_PATH.exists():
        return QIcon(str(_TRAY_ICON_PATH))
    return _resolve_icon(widget, "general")


def _build_slider_control(spec: ControlSpec) -> QWidget:
    minimum = int(spec.options.get("min", 0))
    maximum = int(spec.options.get("max", 100))
    initial = int(spec.default if spec.default is not None else minimum)
    suffix = str(spec.options.get("suffix", ""))
    return RefSliderRow(spec.label, minimum, maximum, initial, suffix)


def _build_combo_control(spec: ControlSpec) -> QWidget:
    items = [str(item) for item in spec.options.get("items", [])]
    default = str(spec.default) if spec.default is not None else None
    return RefSelectRow(spec.label, items, default)


def _build_button_control(spec: ControlSpec, tab_title: str, on_status: Callable[[str], None]) -> QWidget:
    def on_click() -> None:
        on_status(f"{tab_title}: {spec.label} (placeholder v1)")

    return RefActionRow(spec.label, on_click)


def _build_control(spec: ControlSpec, tab_title: str, on_status: Callable[[str], None]) -> QWidget:
    if spec.type == "checkbox":
        return RefToggleRow(spec.label, bool(spec.default))
    if spec.type == "slider":
        return _build_slider_control(spec)
    if spec.type == "combo":
        return _build_combo_control(spec)
    if spec.type == "button":
        return _build_button_control(spec, tab_title, on_status)

    unknown = QLabel(f"Unsupported control type: {spec.type}")
    unknown.setProperty("role", "section")
    return unknown


def _build_section(tab: TabSpec, section: SectionSpec, on_status: Callable[[str], None]) -> QGroupBox:
    box = RefPanelBox(section.title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(12, 16, 12, 10)
    layout.setSpacing(7)

    for control in section.controls:
        layout.addWidget(_build_control(control, tab.title, on_status))

    layout.addStretch(1)
    return box


def _build_tab_page(tab: TabSpec, on_status: Callable[[str], None]) -> QWidget:
    page = QWidget()
    root = QVBoxLayout(page)
    root.setContentsMargins(4, 4, 4, 4)
    root.setSpacing(0)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    root.addWidget(splitter, 1)

    main_section = tab.sections[0] if tab.sections else SectionSpec("Main", [])
    left_block = _build_section(tab, main_section, on_status)
    splitter.addWidget(left_block)

    right_frame = QWidget()
    right_column = QVBoxLayout(right_frame)
    right_column.setContentsMargins(0, 0, 0, 0)
    right_column.setSpacing(0)
    settings_section = tab.sections[1] if len(tab.sections) > 1 else SectionSpec("Settings", [])
    presets_section = tab.sections[2] if len(tab.sections) > 2 else SectionSpec("Presets", [])
    right_splitter = QSplitter(Qt.Orientation.Vertical)
    right_splitter.setChildrenCollapsible(False)
    right_column.addWidget(right_splitter, 1)
    right_splitter.addWidget(_build_section(tab, settings_section, on_status))
    right_splitter.addWidget(_build_section(tab, presets_section, on_status))
    splitter.addWidget(right_frame)
    splitter.setSizes([760, 460])
    right_splitter.setSizes([240, 320])
    return page


class GeneralTabPage(QWidget):
    def __init__(
        self,
        tab: TabSpec,
        emit_status: Callable[[str, bool], None],
        runtime: UiRuntimeState,
        refresh_hints: Callable[[], None],
    ) -> None:
        super().__init__()
        self._tab = tab
        self._emit_status = emit_status
        self._runtime = runtime
        self._refresh_hints = refresh_hints
        self._store = GeneralSettingsStore()
        self._is_loading = False
        self._presets: dict[str, dict[str, object]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._root_splitter.setChildrenCollapsible(False)
        root.addWidget(self._root_splitter, 1)

        main_section = tab.sections[0]
        params_section = tab.sections[1]
        presets_section = tab.sections[2]

        left_box = RefPanelBox(main_section.title)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(12, 16, 12, 10)
        left_layout.setSpacing(7)

        brightness_spec = main_section.controls[0]
        self.brightness_slider, self.brightness_value_label = self._create_slider_control(brightness_spec, left_layout)

        self.hints_checkbox = QCheckBox(main_section.controls[1].label)
        left_layout.addWidget(self.hints_checkbox)

        self.animation_checkbox = QCheckBox(main_section.controls[2].label)
        left_layout.addWidget(self.animation_checkbox)

        launch_spec = main_section.controls[3]
        launch_title = QLabel(launch_spec.label)
        launch_title.setProperty("role", "ref_section")
        left_layout.addWidget(launch_title)
        self.launch_mode_combo = QComboBox()
        self.launch_mode_combo.addItems([str(item) for item in launch_spec.options.get("items", [])])
        left_layout.addWidget(self.launch_mode_combo)

        self.apply_template_button = QPushButton(main_section.controls[4].label)
        left_layout.addWidget(self.apply_template_button)

        self.clear_temp_button = QPushButton(main_section.controls[5].label)
        left_layout.addWidget(self.clear_temp_button)
        left_layout.addStretch(1)

        root.addWidget(left_box, 3)

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(10)

        params_box = RefPanelBox(params_section.title)
        params_layout = QVBoxLayout(params_box)
        params_layout.setContentsMargins(12, 16, 12, 10)
        params_layout.setSpacing(7)
        self.protected_checkbox = QCheckBox(params_section.controls[0].label)
        self.hide_notifications_checkbox = QCheckBox(params_section.controls[1].label)
        self.autostart_checkbox = QCheckBox(params_section.controls[2].label)
        params_layout.addWidget(self.protected_checkbox)
        params_layout.addWidget(self.hide_notifications_checkbox)
        params_layout.addWidget(self.autostart_checkbox)
        params_layout.addStretch(1)
        right_column.addWidget(params_box, 1)

        presets_box = RefPanelBox(presets_section.title)
        presets_layout = QVBoxLayout(presets_box)
        presets_layout.setContentsMargins(12, 16, 12, 10)
        presets_layout.setSpacing(7)

        profile_spec = presets_section.controls[0]
        profile_title = QLabel(profile_spec.label)
        profile_title.setProperty("role", "ref_section")
        presets_layout.addWidget(profile_title)
        self.profile_combo = QComboBox()
        profile_items = [str(item) for item in profile_spec.options.get("items", [])]
        self.profile_combo.addItems(profile_items)
        presets_layout.addWidget(self.profile_combo)

        self.load_button = QPushButton(presets_section.controls[1].label)
        self.save_button = QPushButton(presets_section.controls[2].label)
        self.reset_button = QPushButton(presets_section.controls[3].label)
        self.export_button = QPushButton(presets_section.controls[4].label)
        presets_layout.addWidget(self.load_button)
        presets_layout.addWidget(self.save_button)
        presets_layout.addWidget(self.reset_button)
        presets_layout.addWidget(self.export_button)
        presets_layout.addStretch(1)

        right_column.addWidget(presets_box, 2)
        root.addLayout(right_column, 2)

        self._wire_events()
        self._load_initial_state()

    def _create_slider_control(self, spec: ControlSpec, parent_layout: QVBoxLayout) -> tuple[QSlider, QLabel]:
        slider_control = RefSliderRow(
            spec.label,
            int(spec.options.get("min", 0)),
            int(spec.options.get("max", 100)),
            int(spec.default if spec.default is not None else spec.options.get("min", 0)),
            str(spec.options.get("suffix", "")),
        )
        parent_layout.addWidget(slider_control)
        return slider_control.slider, slider_control.value_label

    def _wire_events(self) -> None:
        self.brightness_slider.valueChanged.connect(self._on_value_changed)
        self.hints_checkbox.toggled.connect(self._on_value_changed)
        self.animation_checkbox.toggled.connect(self._on_value_changed)
        self.launch_mode_combo.currentIndexChanged.connect(self._on_value_changed)
        self.protected_checkbox.toggled.connect(self._on_value_changed)
        self.hide_notifications_checkbox.toggled.connect(self._on_value_changed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        self.apply_template_button.clicked.connect(self._apply_base_template)
        self.clear_temp_button.clicked.connect(self._clear_temp_data)
        self.load_button.clicked.connect(self._load_profile)
        self.save_button.clicked.connect(self._save_profile)
        self.reset_button.clicked.connect(self._reset_settings)
        self.export_button.clicked.connect(self._export_profile)
        self._root_splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())
        self._right_splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

    def _load_initial_state(self) -> None:
        self._is_loading = True
        settings = self._store.load_settings()
        profile_names = [self.profile_combo.itemText(i) for i in range(self.profile_combo.count())]
        self._presets = self._store.load_profiles(profile_names)

        startup_enabled = self._store.is_autostart_enabled()
        settings.autostart_windows = startup_enabled
        self._store.save_settings(settings)

        self.brightness_slider.setValue(settings.brightness)
        self.hints_checkbox.setChecked(settings.show_hints)
        self.animation_checkbox.setChecked(settings.smooth_animation)
        self.launch_mode_combo.setCurrentText(settings.launch_mode)
        self.protected_checkbox.setChecked(settings.protected_mode)
        self.hide_notifications_checkbox.setChecked(settings.hide_notifications)
        self.autostart_checkbox.setChecked(settings.autostart_windows)
        if settings.profile_name in profile_names:
            self.profile_combo.setCurrentText(settings.profile_name)
        payload = _load_splitter_payload(settings.general_splitter_state)
        if payload.get("root"):
            self._root_splitter.restoreState(decode_qbytearray(payload["root"]))
        else:
            self._root_splitter.setSizes([760, 460])
        if payload.get("right"):
            self._right_splitter.restoreState(decode_qbytearray(payload["right"]))
        else:
            self._right_splitter.setSizes([360, 280])
        self._is_loading = False

        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()

    def _current_values(self) -> dict[str, object]:
        return {
            "brightness": int(self.brightness_slider.value()),
            "show_hints": bool(self.hints_checkbox.isChecked()),
            "smooth_animation": bool(self.animation_checkbox.isChecked()),
            "launch_mode": str(self.launch_mode_combo.currentText()),
            "protected_mode": bool(self.protected_checkbox.isChecked()),
            "hide_notifications": bool(self.hide_notifications_checkbox.isChecked()),
            "autostart_windows": bool(self.autostart_checkbox.isChecked()),
        }

    def _save_settings(self) -> None:
        values = self._current_values()
        current = self._store.load_settings()
        settings = GeneralSettings(
            brightness=int(values["brightness"]),
            show_hints=bool(values["show_hints"]),
            smooth_animation=bool(values["smooth_animation"]),
            launch_mode=str(values["launch_mode"]),
            protected_mode=bool(values["protected_mode"]),
            hide_notifications=bool(values["hide_notifications"]),
            autostart_windows=bool(values["autostart_windows"]),
            visual_theme=current.visual_theme,
            accent_preset=current.visual_theme,
            interface_scale=current.interface_scale,
            font_size=current.font_size,
            panel_opacity=current.panel_opacity,
            sidebar_width=current.sidebar_width,
            compact_mode=current.compact_mode,
            show_status_bar=current.show_status_bar,
            active_ai=current.active_ai,
            ai_protocol=current.ai_protocol,
            ai_model=current.ai_model,
            ai_system_prompt=current.ai_system_prompt,
            ai_temperature=current.ai_temperature,
            ai_max_tokens=current.ai_max_tokens,
            ai_streaming_enabled=current.ai_streaming_enabled,
            ai_last_session_id=current.ai_last_session_id,
            window_geometry=current.window_geometry,
            window_maximized=current.window_maximized,
            main_splitter_state=current.main_splitter_state,
            general_splitter_state=current.general_splitter_state,
            performance_splitter_state=current.performance_splitter_state,
            network_splitter_state=current.network_splitter_state,
            analytics_splitter_state=current.analytics_splitter_state,
            security_splitter_state=current.security_splitter_state,
            ai_splitter_state=current.ai_splitter_state,
            fps_overlay_enabled=current.fps_overlay_enabled,
            fps_capture_enabled=current.fps_capture_enabled,
            fps_overlay_hotkey=current.fps_overlay_hotkey,
            fps_overlay_position=current.fps_overlay_position,
            fps_overlay_opacity=current.fps_overlay_opacity,
            fps_overlay_scale=current.fps_overlay_scale,
            github_repo=current.github_repo,
            auto_update_enabled=current.auto_update_enabled,
            release_asset_pattern=current.release_asset_pattern,
            launcher_custom_image_path=current.launcher_custom_image_path,
            profile_name=self.profile_combo.currentText(),
        )
        self._store.save_settings(settings)

    def _apply_runtime_state(self) -> None:
        self._runtime.hints_enabled = self.hints_checkbox.isChecked()
        self._runtime.smooth_animation = self.animation_checkbox.isChecked()
        self._runtime.hide_notifications = self.hide_notifications_checkbox.isChecked()

        brightness = self.brightness_slider.value()
        opacity = 0.74 + (max(0, min(100, brightness)) / 100.0) * 0.26
        host = self.window()
        if host is not None:
            host.setWindowOpacity(max(0.74, min(1.0, opacity)))

    def _sync_protected_mode(self) -> None:
        locked = self.protected_checkbox.isChecked()
        self.clear_temp_button.setEnabled(not locked)
        self.reset_button.setEnabled(not locked)

    def _on_value_changed(self) -> None:
        if self._is_loading:
            return
        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()
        self._save_settings()
        self._emit_status("Настройки обновлены.", False)

    def _on_profile_changed(self) -> None:
        if self._is_loading:
            return
        self._save_settings()

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._is_loading:
            return
        if not self._sync_autostart_registry(checked, notify=True):
            return
        self._save_settings()

    def _sync_autostart_registry(self, enabled: bool, notify: bool) -> bool:
        current_enabled = self._store.is_autostart_enabled()
        if current_enabled == enabled:
            return True

        success, message = self._store.set_autostart(enabled)
        if not success:
            self._is_loading = True
            self.autostart_checkbox.setChecked(current_enabled)
            self._is_loading = False
            self._emit_status(message, True)
            return False

        if notify:
            self._emit_status(message, True)
        return True

    def _apply_base_template(self) -> None:
        base = dict(self._presets.get("Стандарт", {}))
        if not base:
            return
        self._apply_values(base)
        self._emit_status("Применен базовый шаблон.", False)

    def _clear_temp_data(self) -> None:
        if self.protected_checkbox.isChecked():
            self._emit_status("Защищенный режим: очистка временных данных отключена.", True)
            return
        removed = self._store.clear_temp_data()
        self._emit_status(f"Очищено временных элементов: {removed}", True)

    def _load_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._presets.get(name)
        if not values:
            self._emit_status("Профиль не найден.", True)
            return
        self._apply_values(values)
        self._emit_status(f"Профиль загружен: {name}", False)

    def _save_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._current_values()
        self._store.save_profile(name, values)
        self._presets[name] = dict(values)
        self._emit_status(f"Профиль сохранен: {name}", True)

    def _reset_settings(self) -> None:
        if self.protected_checkbox.isChecked():
            self._emit_status("Защищенный режим: сброс отключен.", True)
            return
        defaults = self._presets.get("Стандарт", {})
        if not defaults:
            return
        self._apply_values(defaults)
        self._emit_status("Настройки сброшены к стандартным.", True)

    def _export_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._presets.get(name, self._current_values())
        output = self._store.export_profile(name, dict(values))
        self._emit_status(f"Профиль выгружен: {output}", True)

    def _apply_values(self, values: dict[str, object]) -> None:
        self._is_loading = True
        self.brightness_slider.setValue(int(values.get("brightness", self.brightness_slider.value())))
        self.hints_checkbox.setChecked(bool(values.get("show_hints", self.hints_checkbox.isChecked())))
        self.animation_checkbox.setChecked(bool(values.get("smooth_animation", self.animation_checkbox.isChecked())))
        launch_mode = str(values.get("launch_mode", self.launch_mode_combo.currentText()))
        self.launch_mode_combo.setCurrentText(launch_mode)
        self.protected_checkbox.setChecked(bool(values.get("protected_mode", self.protected_checkbox.isChecked())))
        self.hide_notifications_checkbox.setChecked(bool(values.get("hide_notifications", self.hide_notifications_checkbox.isChecked())))
        self.autostart_checkbox.setChecked(bool(values.get("autostart_windows", self.autostart_checkbox.isChecked())))
        self._is_loading = False
        self._sync_autostart_registry(self.autostart_checkbox.isChecked(), notify=False)
        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()
        self._save_settings()


class AdvancedGeneralTabPage(QWidget):
    def __init__(
        self,
        tab: TabSpec,
        emit_status: Callable[[str, bool], None],
        runtime: UiRuntimeState,
        refresh_hints: Callable[[], None],
        apply_settings: Callable[[GeneralSettings], None],
    ) -> None:
        super().__init__()
        self._tab = tab
        self._emit_status = emit_status
        self._runtime = runtime
        self._refresh_hints = refresh_hints
        self._apply_settings = apply_settings
        self._store = GeneralSettingsStore()
        self._is_loading = False
        self._presets: dict[str, dict[str, object]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._root_splitter.setChildrenCollapsible(False)
        root.addWidget(self._root_splitter, 1)

        main_section = tab.sections[0]
        params_section = tab.sections[1]
        presets_section = tab.sections[2]

        left_box = RefPanelBox(main_section.title)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(12, 16, 12, 10)
        left_layout.setSpacing(7)
        self.brightness_slider, self.brightness_value_label = self._create_slider_control("Яркость интерфейса", "%", 0, 100, left_layout)
        self.interface_scale_slider, self.interface_scale_value_label = self._create_slider_control("Масштаб интерфейса", "%", 85, 130, left_layout)
        self.font_size_slider, self.font_size_value_label = self._create_slider_control("Размер шрифта", "px", 11, 18, left_layout)
        self.panel_opacity_slider, self.panel_opacity_value_label = self._create_slider_control("Насыщенность панелей", "%", 60, 100, left_layout)
        self.sidebar_width_slider, self.sidebar_width_value_label = self._create_slider_control("Ширина боковой панели", "px", 140, 260, left_layout)

        accent_title = QLabel("Дизайн / Тема")
        accent_title.setProperty("role", "ref_section")
        left_layout.addWidget(accent_title)
        self.accent_combo = QComboBox()
        self.accent_combo.addItems(["Dark", "Ocean", "Synthwave", "D.Va"])
        left_layout.addWidget(self.accent_combo)

        self.compact_mode_checkbox = QCheckBox("Компактный режим")
        self.show_status_bar_checkbox = QCheckBox("Показывать строку состояния")
        left_layout.addWidget(self.compact_mode_checkbox)
        left_layout.addWidget(self.show_status_bar_checkbox)

        self.apply_template_button = QPushButton("Применить базовый шаблон")
        self.clear_temp_button = QPushButton("Очистить временные данные")
        left_layout.addWidget(self.apply_template_button)
        left_layout.addWidget(self.clear_temp_button)
        left_layout.addStretch(1)
        self._root_splitter.addWidget(left_box)

        right_frame = QWidget()
        right_column = QVBoxLayout(right_frame)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(0)
        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.setChildrenCollapsible(False)
        right_column.addWidget(self._right_splitter, 1)

        params_box = RefPanelBox(params_section.title)
        params_layout = QVBoxLayout(params_box)
        params_layout.setContentsMargins(12, 16, 12, 10)
        params_layout.setSpacing(7)
        self.protected_checkbox = QCheckBox("Защищенный режим")
        self.hide_notifications_checkbox = QCheckBox("Скрывать уведомления")
        self.minimize_to_tray_checkbox = QCheckBox("Сворачивать в трей")
        self.close_to_tray_checkbox = QCheckBox("Кнопка закрытия отправляет в трей")
        self.autostart_checkbox = QCheckBox("Автозапуск с Windows")
        self.hints_checkbox = QCheckBox("Показывать подсказки")
        self.animation_checkbox = QCheckBox("Плавная анимация")
        params_layout.addWidget(self.protected_checkbox)
        params_layout.addWidget(self.hide_notifications_checkbox)
        params_layout.addWidget(self.minimize_to_tray_checkbox)
        params_layout.addWidget(self.close_to_tray_checkbox)
        params_layout.addWidget(self.autostart_checkbox)
        params_layout.addWidget(self.hints_checkbox)
        params_layout.addWidget(self.animation_checkbox)

        launch_title = QLabel("Режим запуска")
        launch_title.setProperty("role", "ref_section")
        params_layout.addWidget(launch_title)
        self.launch_mode_combo = QComboBox()
        self.launch_mode_combo.addItems(["Стандартный", "Быстрый", "Тихий"])
        params_layout.addWidget(self.launch_mode_combo)

        ai_title = QLabel("Активный AI")
        ai_title.setProperty("role", "ref_section")
        params_layout.addWidget(ai_title)
        self.active_ai_combo = QComboBox()
        self.active_ai_combo.addItems(["AI LOLILEND", "Cloudflare Workers AI"])
        params_layout.addWidget(self.active_ai_combo)

        ai_hint = QLabel("Сейчас доступен только AI LOLILEND. Эта настройка уже готова для будущих AI-моделей.")
        ai_hint.setWordWrap(True)
        ai_hint.setProperty("role", "ref_section")
        params_layout.addWidget(ai_hint)
        params_layout.addStretch(1)
        self._right_splitter.addWidget(params_box)

        presets_box = RefPanelBox(presets_section.title)
        presets_layout = QVBoxLayout(presets_box)
        presets_layout.setContentsMargins(12, 16, 12, 10)
        presets_layout.setSpacing(7)

        profile_spec = presets_section.controls[0]
        profile_title = QLabel(profile_spec.label)
        profile_title.setProperty("role", "ref_section")
        presets_layout.addWidget(profile_title)
        self.profile_combo = QComboBox()
        profile_items = [str(item) for item in profile_spec.options.get("items", [])]
        self.profile_combo.addItems(profile_items)
        presets_layout.addWidget(self.profile_combo)

        self.load_button = QPushButton(presets_section.controls[1].label)
        self.save_button = QPushButton(presets_section.controls[2].label)
        self.reset_button = QPushButton(presets_section.controls[3].label)
        self.export_button = QPushButton(presets_section.controls[4].label)
        presets_layout.addWidget(self.load_button)
        presets_layout.addWidget(self.save_button)
        presets_layout.addWidget(self.reset_button)
        presets_layout.addWidget(self.export_button)
        presets_layout.addStretch(1)
        self._right_splitter.addWidget(presets_box)
        self._root_splitter.addWidget(right_frame)

        self._wire_events()
        self._load_initial_state()

    def _create_slider_control(
        self,
        title_text: str,
        suffix: str,
        minimum: int,
        maximum: int,
        parent_layout: QVBoxLayout,
    ) -> tuple[QSlider, QLabel]:
        slider_control = RefSliderRow(title_text, minimum, maximum, minimum, suffix)
        parent_layout.addWidget(slider_control)
        return slider_control.slider, slider_control.value_label

    def _wire_events(self) -> None:
        self.brightness_slider.valueChanged.connect(self._on_value_changed)
        self.interface_scale_slider.valueChanged.connect(self._on_value_changed)
        self.font_size_slider.valueChanged.connect(self._on_value_changed)
        self.panel_opacity_slider.valueChanged.connect(self._on_value_changed)
        self.sidebar_width_slider.valueChanged.connect(self._on_value_changed)
        self.accent_combo.currentIndexChanged.connect(self._on_value_changed)
        self.compact_mode_checkbox.toggled.connect(self._on_value_changed)
        self.show_status_bar_checkbox.toggled.connect(self._on_value_changed)
        self.hints_checkbox.toggled.connect(self._on_value_changed)
        self.animation_checkbox.toggled.connect(self._on_value_changed)
        self.launch_mode_combo.currentIndexChanged.connect(self._on_value_changed)
        self.active_ai_combo.currentIndexChanged.connect(self._on_value_changed)
        self.protected_checkbox.toggled.connect(self._on_value_changed)
        self.hide_notifications_checkbox.toggled.connect(self._on_value_changed)
        self.minimize_to_tray_checkbox.toggled.connect(self._on_value_changed)
        self.close_to_tray_checkbox.toggled.connect(self._on_value_changed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        self.apply_template_button.clicked.connect(self._apply_base_template)
        self.clear_temp_button.clicked.connect(self._clear_temp_data)
        self.load_button.clicked.connect(self._load_profile)
        self.save_button.clicked.connect(self._save_profile)
        self.reset_button.clicked.connect(self._reset_settings)
        self.export_button.clicked.connect(self._export_profile)

    def _load_initial_state(self) -> None:
        self._is_loading = True
        settings = self._store.load_settings()
        profile_names = [self.profile_combo.itemText(i) for i in range(self.profile_combo.count())]
        self._presets = self._store.load_profiles(profile_names)

        startup_enabled = self._store.is_autostart_enabled()
        settings.autostart_windows = startup_enabled
        self._store.save_settings(settings)

        self.brightness_slider.setValue(settings.brightness)
        self.interface_scale_slider.setValue(settings.interface_scale)
        self.font_size_slider.setValue(settings.font_size)
        self.panel_opacity_slider.setValue(settings.panel_opacity)
        self.sidebar_width_slider.setValue(settings.sidebar_width)
        self.accent_combo.setCurrentText(settings.visual_theme)
        self.compact_mode_checkbox.setChecked(settings.compact_mode)
        self.show_status_bar_checkbox.setChecked(settings.show_status_bar)
        self.hints_checkbox.setChecked(settings.show_hints)
        self.animation_checkbox.setChecked(settings.smooth_animation)
        self.launch_mode_combo.setCurrentText(settings.launch_mode)
        self.active_ai_combo.setCurrentText(settings.active_ai)
        self.protected_checkbox.setChecked(settings.protected_mode)
        self.hide_notifications_checkbox.setChecked(settings.hide_notifications)
        self.minimize_to_tray_checkbox.setChecked(settings.minimize_to_tray)
        self.close_to_tray_checkbox.setChecked(settings.close_to_tray)
        self.autostart_checkbox.setChecked(settings.autostart_windows)
        if settings.profile_name in profile_names:
            self.profile_combo.setCurrentText(settings.profile_name)
        self._is_loading = False

        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()

    def _current_values(self) -> dict[str, object]:
        return {
            "brightness": int(self.brightness_slider.value()),
            "interface_scale": int(self.interface_scale_slider.value()),
            "font_size": int(self.font_size_slider.value()),
            "panel_opacity": int(self.panel_opacity_slider.value()),
            "sidebar_width": int(self.sidebar_width_slider.value()),
            "visual_theme": str(self.accent_combo.currentText()),
            "accent_preset": str(self.accent_combo.currentText()),
            "compact_mode": bool(self.compact_mode_checkbox.isChecked()),
            "show_status_bar": bool(self.show_status_bar_checkbox.isChecked()),
            "show_hints": bool(self.hints_checkbox.isChecked()),
            "smooth_animation": bool(self.animation_checkbox.isChecked()),
            "launch_mode": str(self.launch_mode_combo.currentText()),
            "active_ai": str(self.active_ai_combo.currentText()),
            "protected_mode": bool(self.protected_checkbox.isChecked()),
            "hide_notifications": bool(self.hide_notifications_checkbox.isChecked()),
            "minimize_to_tray": bool(self.minimize_to_tray_checkbox.isChecked()),
            "close_to_tray": bool(self.close_to_tray_checkbox.isChecked()),
            "autostart_windows": bool(self.autostart_checkbox.isChecked()),
        }

    def _build_settings(self) -> GeneralSettings:
        values = self._current_values()
        current = self._store.load_settings()
        return GeneralSettings(
            brightness=int(values["brightness"]),
            show_hints=bool(values["show_hints"]),
            smooth_animation=bool(values["smooth_animation"]),
            launch_mode=str(values["launch_mode"]),
            protected_mode=bool(values["protected_mode"]),
            hide_notifications=bool(values["hide_notifications"]),
            minimize_to_tray=bool(values["minimize_to_tray"]),
            close_to_tray=bool(values["close_to_tray"]),
            autostart_windows=bool(values["autostart_windows"]),
            visual_theme=str(values.get("visual_theme", values["accent_preset"])),
            accent_preset=str(values.get("visual_theme", values["accent_preset"])),
            interface_scale=int(values["interface_scale"]),
            font_size=int(values["font_size"]),
            panel_opacity=int(values["panel_opacity"]),
            sidebar_width=int(values["sidebar_width"]),
            compact_mode=bool(values["compact_mode"]),
            show_status_bar=bool(values["show_status_bar"]),
            active_ai=str(values["active_ai"]),
            ai_protocol=current.ai_protocol,
            ai_model=current.ai_model,
            ai_active_task=current.ai_active_task,
            ai_popular_only=current.ai_popular_only,
            ai_system_prompt=current.ai_system_prompt,
            ai_temperature=current.ai_temperature,
            ai_max_tokens=current.ai_max_tokens,
            ai_streaming_enabled=current.ai_streaming_enabled,
            ai_last_session_id=current.ai_last_session_id,
            window_geometry=current.window_geometry,
            window_maximized=current.window_maximized,
            main_splitter_state=current.main_splitter_state,
            general_splitter_state=current.general_splitter_state,
            performance_splitter_state=current.performance_splitter_state,
            network_splitter_state=current.network_splitter_state,
            analytics_splitter_state=current.analytics_splitter_state,
            security_splitter_state=current.security_splitter_state,
            ai_splitter_state=current.ai_splitter_state,
            fps_overlay_enabled=current.fps_overlay_enabled,
            fps_capture_enabled=current.fps_capture_enabled,
            fps_overlay_hotkey=current.fps_overlay_hotkey,
            fps_overlay_position=current.fps_overlay_position,
            fps_overlay_opacity=current.fps_overlay_opacity,
            fps_overlay_scale=current.fps_overlay_scale,
            github_repo=current.github_repo,
            auto_update_enabled=current.auto_update_enabled,
            release_asset_pattern=current.release_asset_pattern,
            launcher_custom_image_path=current.launcher_custom_image_path,
            profile_name=self.profile_combo.currentText(),
        )

    def _save_settings(self) -> None:
        self._store.save_settings(self._build_settings())

    def _save_splitter_state(self) -> None:
        if self._is_loading:
            return
        settings = self._store.load_settings()
        settings.general_splitter_state = json.dumps(
            {
                "root": encode_qbytearray(self._root_splitter.saveState()),
                "right": encode_qbytearray(self._right_splitter.saveState()),
            },
            ensure_ascii=True,
        )
        self._store.save_settings(settings)

    def _apply_runtime_state(self) -> None:
        settings = self._build_settings()
        self._runtime.update_from_settings(settings)

        brightness = self.brightness_slider.value()
        opacity = 0.74 + (max(0, min(100, brightness)) / 100.0) * 0.26
        host = self.window()
        if host is not None:
            host.setWindowOpacity(max(0.74, min(1.0, opacity)))

        self._apply_settings(settings)

    def _sync_protected_mode(self) -> None:
        locked = self.protected_checkbox.isChecked()
        self.clear_temp_button.setEnabled(not locked)
        self.reset_button.setEnabled(not locked)

    def _on_value_changed(self) -> None:
        if self._is_loading:
            return
        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()
        self._save_settings()
        self._emit_status(f"Настройки обновлены. Активный AI: {self.active_ai_combo.currentText()}.", False)

    def _on_profile_changed(self) -> None:
        if self._is_loading:
            return
        self._save_settings()

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._is_loading:
            return
        if not self._sync_autostart_registry(checked, notify=True):
            return
        self._save_settings()

    def _sync_autostart_registry(self, enabled: bool, notify: bool) -> bool:
        current_enabled = self._store.is_autostart_enabled()
        if current_enabled == enabled:
            return True

        success, message = self._store.set_autostart(enabled)
        if not success:
            self._is_loading = True
            self.autostart_checkbox.setChecked(current_enabled)
            self._is_loading = False
            self._emit_status(message, True)
            return False

        if notify:
            self._emit_status(message, True)
        return True

    def _apply_base_template(self) -> None:
        base = dict(self._presets.get("Стандарт", {}))
        if not base:
            return
        self._apply_values(base)
        self._emit_status("Применен базовый шаблон.", False)

    def _clear_temp_data(self) -> None:
        if self.protected_checkbox.isChecked():
            self._emit_status("Защищенный режим: очистка временных данных отключена.", True)
            return
        removed = self._store.clear_temp_data()
        self._emit_status(f"Очищено временных элементов: {removed}", True)

    def _load_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._presets.get(name)
        if not values:
            self._emit_status("Профиль не найден.", True)
            return
        self._apply_values(values)
        self._emit_status(f"Профиль загружен: {name}", False)

    def _save_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._current_values()
        self._store.save_profile(name, values)
        self._presets[name] = dict(values)
        self._emit_status(f"Профиль сохранен: {name}", True)

    def _reset_settings(self) -> None:
        if self.protected_checkbox.isChecked():
            self._emit_status("Защищенный режим: сброс отключен.", True)
            return
        defaults = self._presets.get("Стандарт", {})
        if not defaults:
            return
        self._apply_values(defaults)
        self._emit_status("Настройки сброшены к стандартным.", True)

    def _export_profile(self) -> None:
        name = self.profile_combo.currentText()
        values = self._presets.get(name, self._current_values())
        output = self._store.export_profile(name, dict(values))
        self._emit_status(f"Профиль выгружен: {output}", True)

    def _apply_values(self, values: dict[str, object]) -> None:
        self._is_loading = True
        self.brightness_slider.setValue(int(values.get("brightness", self.brightness_slider.value())))
        self.interface_scale_slider.setValue(int(values.get("interface_scale", self.interface_scale_slider.value())))
        self.font_size_slider.setValue(int(values.get("font_size", self.font_size_slider.value())))
        self.panel_opacity_slider.setValue(int(values.get("panel_opacity", self.panel_opacity_slider.value())))
        self.sidebar_width_slider.setValue(int(values.get("sidebar_width", self.sidebar_width_slider.value())))
        self.accent_combo.setCurrentText(str(values.get("visual_theme", values.get("accent_preset", self.accent_combo.currentText()))))
        self.compact_mode_checkbox.setChecked(bool(values.get("compact_mode", self.compact_mode_checkbox.isChecked())))
        self.show_status_bar_checkbox.setChecked(bool(values.get("show_status_bar", self.show_status_bar_checkbox.isChecked())))
        self.hints_checkbox.setChecked(bool(values.get("show_hints", self.hints_checkbox.isChecked())))
        self.animation_checkbox.setChecked(bool(values.get("smooth_animation", self.animation_checkbox.isChecked())))
        self.launch_mode_combo.setCurrentText(str(values.get("launch_mode", self.launch_mode_combo.currentText())))
        self.active_ai_combo.setCurrentText(str(values.get("active_ai", self.active_ai_combo.currentText())))
        self.protected_checkbox.setChecked(bool(values.get("protected_mode", self.protected_checkbox.isChecked())))
        self.hide_notifications_checkbox.setChecked(bool(values.get("hide_notifications", self.hide_notifications_checkbox.isChecked())))
        self.minimize_to_tray_checkbox.setChecked(bool(values.get("minimize_to_tray", self.minimize_to_tray_checkbox.isChecked())))
        self.close_to_tray_checkbox.setChecked(bool(values.get("close_to_tray", self.close_to_tray_checkbox.isChecked())))
        self.autostart_checkbox.setChecked(bool(values.get("autostart_windows", self.autostart_checkbox.isChecked())))
        self._is_loading = False
        self._sync_autostart_registry(self.autostart_checkbox.isChecked(), notify=False)
        self._apply_runtime_state()
        self._sync_protected_mode()
        self._refresh_hints()
        self._save_settings()

    def available_profiles(self) -> list[str]:
        return [self.profile_combo.itemText(i) for i in range(self.profile_combo.count())]

    def current_profile(self) -> str:
        return self.profile_combo.currentText()

    def activate_profile(self, name: str) -> bool:
        values = self._presets.get(name)
        if not values:
            return False
        if self.profile_combo.currentText() != name:
            self.profile_combo.setCurrentText(name)
        self._apply_values(values)
        self._emit_status(f"Профиль загружен: {name}", False)
        return True

    def hide_notifications_enabled(self) -> bool:
        return bool(self.hide_notifications_checkbox.isChecked())

    def set_hide_notifications_enabled(self, enabled: bool) -> None:
        if self.hide_notifications_checkbox.isChecked() == enabled:
            return
        self.hide_notifications_checkbox.setChecked(bool(enabled))

    def autostart_enabled(self) -> bool:
        return bool(self.autostart_checkbox.isChecked())

    def set_autostart_enabled(self, enabled: bool) -> tuple[bool, str]:
        current_enabled = self._store.is_autostart_enabled()
        if current_enabled == enabled:
            self._is_loading = True
            self.autostart_checkbox.setChecked(enabled)
            self._is_loading = False
            self._save_settings()
            return True, "Состояние автозапуска уже применено."

        success, message = self._store.set_autostart(enabled)
        if not success:
            self._is_loading = True
            self.autostart_checkbox.setChecked(current_enabled)
            self._is_loading = False
            self._emit_status(message, True)
            return False, message

        self._is_loading = True
        self.autostart_checkbox.setChecked(enabled)
        self._is_loading = False
        self._save_settings()
        self._emit_status(message, True)
        return True, message

class MetricCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MonitorCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setProperty("role", "metric_title")
        layout.addWidget(title_label)

        self.value_label = QLabel("0")
        self.value_label.setProperty("role", "metric_value")
        layout.addWidget(self.value_label)

        self.note_label = QLabel("")
        self.note_label.setProperty("role", "metric_note")
        layout.addWidget(self.note_label)

    def set_value(self, text: str, note: str = "") -> None:
        self.value_label.setText(text)
        self.note_label.setText(note)


class LineHistoryChart(QWidget):
    def __init__(self, max_points: int = 60, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryChart")
        self._max_points = max_points
        self._series: list[tuple[str, QColor, list[float]]] = []
        self._y_limit: float | None = None
        self.setMinimumHeight(170)

    def set_series(
        self,
        series: list[tuple[str, QColor, Sequence[float]]],
        y_limit: float | None = None,
    ) -> None:
        self._series = [
            (name, color, [float(value) for value in values][-self._max_points :])
            for name, color, values in series
        ]
        self._y_limit = y_limit
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(12, 14, -12, -22)
        painter.fillRect(self.rect(), QColor("#08111a"))
        painter.setPen(QPen(QColor("#243949"), 1))
        painter.drawRect(rect)

        grid_color = QColor("#1a2b3a")
        for index in range(1, 5):
            y = rect.top() + (rect.height() * index / 5.0)
            painter.setPen(QPen(grid_color, 1))
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        max_value = self._y_limit or 1.0
        for _, _, values in self._series:
            if values:
                max_value = max(max_value, max(values))
        max_value = max(max_value, 1.0)

        for _, color, values in self._series:
            if len(values) < 2:
                continue
            step = rect.width() / max(1, len(values) - 1)
            points: list[QPointF] = []
            for index, value in enumerate(values):
                x = rect.left() + (index * step)
                y_ratio = max(0.0, min(value / max_value, 1.0))
                y = rect.bottom() - (y_ratio * rect.height())
                points.append(QPointF(x, y))

            painter.setPen(QPen(color, 2))
            painter.drawPolyline(QPolygonF(points))

        legend_x = rect.left() + 8
        legend_y = rect.top() + 8
        for name, color, _ in self._series:
            painter.setPen(QPen(color, 2))
            painter.drawLine(int(legend_x), int(legend_y + 6), int(legend_x + 12), int(legend_y + 6))
            painter.setPen(QPen(QColor("#a6bbce"), 1))
            painter.drawText(int(legend_x + 16), int(legend_y + 11), name)
            legend_y += 15


def _make_number_item(value: float | int, text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setData(Qt.ItemDataRole.EditRole, value)
    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
    return item


def _format_progress(progress_seconds: float, target_seconds: float) -> str:
    progress = max(0.0, float(progress_seconds))
    target = max(0.0, float(target_seconds))
    if target <= 0:
        return f"{int(progress)}s"
    pct = min(100.0, (progress / target) * 100.0) if target > 0 else 0.0
    return f"{int(progress)}/{int(target)}s ({pct:.0f}%)"


def _format_expiry(expires_at: str) -> str:
    raw = str(expires_at or "").strip()
    if not raw:
        return "-"
    value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M")


class SecurityLinkCard(QFrame):
    def __init__(self, item: SecurityLinkItem, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self._item = item
        self._on_status = on_status
        self.setObjectName("SecurityLinkCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_label = QLabel(item.title)
        title_label.setProperty("role", "security_title")
        layout.addWidget(title_label)

        description_label = QLabel(item.description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", "security_desc")
        layout.addWidget(description_label)

        url_label = QLabel(item.url)
        url_label.setProperty("role", "security_url")
        url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(url_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        open_button = QPushButton(_BTN_OPEN)
        open_button.setObjectName("LinkOpenButton")
        open_button.clicked.connect(self._open_link)
        action_row.addWidget(open_button)
        layout.addLayout(action_row)

    def _open_link(self) -> None:
        opened = QDesktopServices.openUrl(QUrl(self._item.url))
        if opened:
            self._on_status(f"{_STATUS_OPENED}: {self._item.title}")
            return
        self._on_status(f"{_STATUS_OPEN_FAILED}: {self._item.url}")


class SecurityLinksPage(QWidget):
    def __init__(self, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self._on_status = on_status
        self._store = GeneralSettingsStore()

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        root.addWidget(self._splitter, 1)

        left_frame = QWidget()
        left_column = QVBoxLayout(left_frame)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(10)
        right_frame = QWidget()
        right_column = QVBoxLayout(right_frame)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(10)

        header_box = RefPanelBox(_SECURITY_TITLE)
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(12, 16, 12, 10)
        subtitle = QLabel(_SECURITY_SUBTITLE)
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "ref_section")
        header_layout.addWidget(subtitle)
        left_column.addWidget(header_box)
        left_column.addWidget(self._build_links_group(_GROUP_TOOLS, "tools"), 1)
        left_column.addStretch(1)

        right_column.addWidget(self._build_links_group(_GROUP_COMMUNITY, "community"), 2)
        right_column.addWidget(self._build_creator_group(), 1)
        right_column.addStretch(1)

        self._splitter.addWidget(left_frame)
        self._splitter.addWidget(right_frame)
        settings = self._store.load_settings()
        if settings.security_splitter_state:
            self._splitter.restoreState(decode_qbytearray(settings.security_splitter_state))
        else:
            self._splitter.setSizes([740, 520])
        self._splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

    def _build_links_group(self, title: str, group_name: str) -> QGroupBox:
        box = RefPanelBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(8)

        for item in _SECURITY_LINKS:
            if item.group != group_name:
                continue
            layout.addWidget(SecurityLinkCard(item, self._on_status))

        return box

    def _build_creator_group(self) -> QGroupBox:
        box = RefPanelBox(_GROUP_CREATOR)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(8)

        card = QFrame()
        card.setObjectName("SecurityLinkCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        title_label = QLabel(_DISCORD_CREATOR)
        title_label.setProperty("role", "security_title")
        card_layout.addWidget(title_label)

        hint_label = QLabel(_DISCORD_CREATOR_HINT)
        hint_label.setProperty("role", "security_desc")
        hint_label.setWordWrap(True)
        card_layout.addWidget(hint_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        copy_button = QPushButton(_BTN_COPY)
        copy_button.setObjectName("LinkCopyButton")
        copy_button.clicked.connect(self._copy_creator_discord)
        action_row.addWidget(copy_button)
        card_layout.addLayout(action_row)

        layout.addWidget(card)
        return box

    def _copy_creator_discord(self) -> None:
        QApplication.clipboard().setText("shuutl")
        self._on_status(f"{_STATUS_COPIED}: shuutl")

    def _save_splitter_state(self) -> None:
        settings = self._store.load_settings()
        settings.security_splitter_state = encode_qbytearray(self._splitter.saveState())
        self._store.save_settings(settings)


class TelegramProxyTabPage(QWidget):
    def __init__(self, on_status: Callable[[str], None], service: TelegramProxyService) -> None:
        super().__init__()
        self._on_status = on_status
        self._service = service
        self._store = TelegramProxyStore()
        self._is_loading = False

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(10)

        left_box = RefPanelBox("Telegram Proxy")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(12, 16, 12, 10)
        left_layout.setSpacing(8)

        host_label = QLabel("Host")
        host_label.setProperty("role", "ref_section")
        left_layout.addWidget(host_label)
        self.host_edit = QLineEdit()
        self.host_edit.setObjectName("TelegramProxyHostEdit")
        left_layout.addWidget(self.host_edit)

        port_label = QLabel("Port")
        port_label.setProperty("role", "ref_section")
        left_layout.addWidget(port_label)
        self.port_spin = QSpinBox()
        self.port_spin.setObjectName("TelegramProxyPortSpin")
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(1080)
        left_layout.addWidget(self.port_spin)

        dc_label = QLabel("DC mappings (DC:IP, one per line)")
        dc_label.setProperty("role", "ref_section")
        left_layout.addWidget(dc_label)
        self.dc_text = QPlainTextEdit()
        self.dc_text.setObjectName("TelegramProxyDcText")
        self.dc_text.setPlaceholderText("2:149.154.167.220\n4:149.154.167.220")
        self.dc_text.setMinimumHeight(140)
        left_layout.addWidget(self.dc_text)

        self.verbose_checkbox = QCheckBox("Verbose logging")
        self.verbose_checkbox.setObjectName("TelegramProxyVerboseCheck")
        left_layout.addWidget(self.verbose_checkbox)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("TelegramProxyStartButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("TelegramProxyStopButton")
        self.restart_button = QPushButton("Restart")
        self.restart_button.setObjectName("TelegramProxyRestartButton")
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.restart_button)
        left_layout.addLayout(action_row)

        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(8)
        self.open_tg_button = QPushButton("Open in Telegram")
        self.open_tg_button.setObjectName("TelegramProxyOpenTgButton")
        self.open_logs_button = QPushButton("Open logs")
        self.open_logs_button.setObjectName("TelegramProxyOpenLogsButton")
        utility_row.addWidget(self.open_tg_button)
        utility_row.addWidget(self.open_logs_button)
        left_layout.addLayout(utility_row)
        left_layout.addStretch(1)

        right_box = RefPanelBox("Status")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(12, 16, 12, 10)
        right_layout.setSpacing(8)

        self.status_value = QLabel("Status: stopped")
        self.status_value.setProperty("role", "ref_section")
        self.endpoint_value = QLabel("Endpoint: 127.0.0.1:1080")
        self.endpoint_value.setProperty("role", "ref_section")
        self.error_value = QLabel("Last error: -")
        self.error_value.setProperty("role", "ref_section")
        self.error_value.setWordWrap(True)
        self.log_path_value = QLabel(f"Log file: {self._store.log_path}")
        self.log_path_value.setProperty("role", "ref_section")
        self.log_path_value.setWordWrap(True)

        right_layout.addWidget(self.status_value)
        right_layout.addWidget(self.endpoint_value)
        right_layout.addWidget(self.error_value)
        right_layout.addWidget(self.log_path_value)
        right_layout.addStretch(1)

        root.addWidget(left_box, 3)
        root.addWidget(right_box, 2)

        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._refresh_status)

        self._wire_events()
        self._load_initial_state()
        self._refresh_status()

    def on_shown(self) -> None:
        self._refresh_status()
        self._timer.start()

    def on_hidden(self) -> None:
        self._timer.stop()
        self._save_config()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        self._save_config()
        super().closeEvent(event)

    def _wire_events(self) -> None:
        self.host_edit.textChanged.connect(self._save_config)
        self.port_spin.valueChanged.connect(self._save_config)
        self.dc_text.textChanged.connect(self._save_config)
        self.verbose_checkbox.toggled.connect(self._save_config)
        self.start_button.clicked.connect(self._start_proxy)
        self.stop_button.clicked.connect(self._stop_proxy)
        self.restart_button.clicked.connect(self._restart_proxy)
        self.open_tg_button.clicked.connect(self._open_in_telegram)
        self.open_logs_button.clicked.connect(self._open_logs)

    def _load_initial_state(self) -> None:
        self._is_loading = True
        config = self._store.load_config()
        self.host_edit.setText(config.host)
        self.port_spin.setValue(config.port)
        self.dc_text.setPlainText("\n".join(config.dc_ip or []))
        self.verbose_checkbox.setChecked(config.verbose)
        self._is_loading = False

    def _current_config(self) -> TelegramProxyConfig:
        dc_lines = [line.strip() for line in self.dc_text.toPlainText().splitlines() if line.strip()]
        return TelegramProxyConfig(
            host=self.host_edit.text().strip(),
            port=int(self.port_spin.value()),
            dc_ip=dc_lines,
            verbose=self.verbose_checkbox.isChecked(),
        ).normalized()

    def _save_config(self) -> None:
        if self._is_loading:
            return
        self._store.save_config(self._current_config())
        self._refresh_status()

    def _start_proxy(self) -> None:
        config = self._current_config()
        ok, message = self._service.start(config)
        if ok:
            self._store.save_config(config)
        self._on_status(message)
        self._refresh_status()

    def _stop_proxy(self) -> None:
        _ok, message = self._service.stop()
        self._on_status(message)
        self._refresh_status()

    def _restart_proxy(self) -> None:
        config = self._current_config()
        ok, message = self._service.restart(config)
        if ok:
            self._store.save_config(config)
        self._on_status(message)
        self._refresh_status()

    def _open_in_telegram(self) -> None:
        config = self._current_config()
        url = self._service.telegram_proxy_url(config)
        opened = QDesktopServices.openUrl(QUrl(url))
        if opened:
            self._on_status(f"Opening Telegram proxy link: {url}")
        else:
            self._on_status(f"Unable to open Telegram link: {url}")

    def _open_logs(self) -> None:
        if not self._store.log_path.exists():
            self._store.log_path.write_text("", encoding="utf-8")
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._store.log_path)))
        if not opened:
            self._on_status("Unable to open Telegram Proxy log file.")

    def _refresh_status(self) -> None:
        status = self._service.status()
        self.status_value.setText("Status: running" if status.running else "Status: stopped")
        self.endpoint_value.setText(f"Endpoint: {status.endpoint}")
        self.error_value.setText(f"Last error: {status.last_error or '-'}")
        self.log_path_value.setText(f"Log file: {status.log_path}")
        self.start_button.setEnabled(not status.running)
        self.stop_button.setEnabled(status.running)

    def proxy_enabled(self) -> bool:
        return self._service.is_running()

    def set_proxy_enabled(self, enabled: bool) -> bool:
        if enabled:
            self._start_proxy()
            return self._service.is_running()
        self._stop_proxy()
        return not self._service.is_running()



class YandexMusicRpcTabPage(QWidget):
    def __init__(self, on_status: Callable[[str], None], service: YandexMusicRpcService) -> None:
        super().__init__()
        self._on_status = on_status
        self._service = service
        self._store = YandexMusicRpcStore()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        # ---- Left panel: controls ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(260)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(10)
        left_scroll.setWidget(left_widget)

        # Enable toggle
        enable_box = QGroupBox("Discord RPC")
        enable_layout = QVBoxLayout(enable_box)
        self._enable_cb = QCheckBox("Включить отображение трека в Discord")
        enable_layout.addWidget(self._enable_cb)
        left_layout.addWidget(enable_box)

        # Yandex Music token
        ym_box = QGroupBox("Яндекс Музыка")
        ym_layout = QVBoxLayout(ym_box)
        ym_layout.addWidget(QLabel("Токен (опционально — для обложек и ссылок):"))
        self._token_edit = QLineEdit()
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setPlaceholderText("y0_AgAA...")
        ym_layout.addWidget(self._token_edit)
        token_save_btn = QPushButton("Сохранить токен")
        token_save_btn.clicked.connect(self._save_token)
        ym_layout.addWidget(token_save_btn)
        hint_label = QLabel(
            "Как получить токен: откройте music.yandex.ru,\n"
            "затем в консоли браузера выполните:\n"
            "document.cookie.match(/Session_id=([^;]+)/)[1]"
        )
        hint_label.setWordWrap(True)
        hint_label.setProperty("role", "metric_note")
        ym_layout.addWidget(hint_label)
        left_layout.addWidget(ym_box)

        # Settings
        settings_box = QGroupBox("Настройки")
        settings_layout = QVBoxLayout(settings_box)
        settings_layout.addWidget(QLabel("Источник звука:"))
        self._source_combo = QComboBox()
        self._source_combo.addItem("Авто (любой источник)", "auto")
        settings_layout.addWidget(self._source_combo)

        settings_layout.addWidget(QLabel("Тип активности в Discord:"))
        self._activity_type_combo = QComboBox()
        self._activity_type_combo.addItem("Listening to (слушает)", 2)
        self._activity_type_combo.addItem("Playing (играет)", 0)
        settings_layout.addWidget(self._activity_type_combo)

        settings_layout.addWidget(QLabel("Кнопки трека:"))
        self._button_mode_combo = QComboBox()
        self._button_mode_combo.addItem("Веб-ссылка", "web")
        self._button_mode_combo.addItem("В приложении", "app")
        self._button_mode_combo.addItem("Оба варианта", "both")
        self._button_mode_combo.addItem("Без кнопок", "none")
        settings_layout.addWidget(self._button_mode_combo)

        pause_row = QHBoxLayout()
        pause_row.addWidget(QLabel("Очистить RPC при паузе (сек):"))
        self._pause_timeout_spin = QSpinBox()
        self._pause_timeout_spin.setRange(30, 600)
        self._pause_timeout_spin.setValue(300)
        self._pause_timeout_spin.setSingleStep(30)
        pause_row.addWidget(self._pause_timeout_spin)
        settings_layout.addLayout(pause_row)

        self._strong_find_cb = QCheckBox("Строгий поиск (только Яндекс Музыка)")
        self._strong_find_cb.setToolTip(
            "Если включено, поиск выполняется без автокоррекции.\n"
            "Полезно когда играет только ЯМ."
        )
        settings_layout.addWidget(self._strong_find_cb)
        apply_btn = QPushButton("Применить настройки")
        apply_btn.clicked.connect(self._apply_settings)
        settings_layout.addWidget(apply_btn)
        left_layout.addWidget(settings_box)

        left_layout.addStretch(1)

        # ---- Right panel: status ----
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(10)
        right_scroll.setWidget(right_widget)

        # Current track
        track_box = QGroupBox("Текущий трек")
        track_layout = QVBoxLayout(track_box)
        self._track_title = QLabel("—")
        self._track_title.setProperty("role", "metric_value")
        self._track_title.setWordWrap(True)
        track_layout.addWidget(self._track_title)
        self._track_artist = QLabel("—")
        track_layout.addWidget(self._track_artist)
        self._track_album = QLabel("")
        self._track_album.setProperty("role", "metric_note")
        self._track_album.setWordWrap(True)
        track_layout.addWidget(self._track_album)
        self._track_playback = QLabel("")
        self._track_playback.setProperty("role", "metric_note")
        track_layout.addWidget(self._track_playback)
        self._track_url = QLabel("")
        self._track_url.setProperty("role", "security_url")
        self._track_url.setWordWrap(True)
        track_layout.addWidget(self._track_url)
        right_layout.addWidget(track_box)

        # Discord status
        discord_box = QGroupBox("Discord RPC")
        discord_layout = QVBoxLayout(discord_box)
        self._discord_status = QLabel("Отключён")
        discord_layout.addWidget(self._discord_status)
        right_layout.addWidget(discord_box)

        # Error label
        self._error_label = QLabel("")
        self._error_label.setProperty("role", "metric_note")
        self._error_label.setWordWrap(True)
        right_layout.addWidget(self._error_label)

        # Log
        log_box = QGroupBox("Журнал")
        log_layout = QVBoxLayout(log_box)
        self._log_list = QListWidget()
        self._log_list.setMaximumHeight(200)
        self._log_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        log_layout.addWidget(self._log_list)
        right_layout.addWidget(log_box)
        right_layout.addStretch(1)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_scroll)
        splitter.setSizes([300, 500])

        # Timer
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)

        # Wire signals
        self._enable_cb.toggled.connect(self._on_enable_toggled)

        # Load initial state
        self._load_ui_state()
        self._refresh()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_shown(self) -> None:
        self._refresh()
        self._timer.start()

    def on_hidden(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def _load_ui_state(self) -> None:
        cfg = self._store.load()
        self._enable_cb.blockSignals(True)
        self._enable_cb.setChecked(cfg.enabled)
        self._enable_cb.blockSignals(False)
        self._strong_find_cb.setChecked(cfg.strong_find)
        # Activity type
        idx = self._activity_type_combo.findData(cfg.activity_type)
        if idx >= 0:
            self._activity_type_combo.setCurrentIndex(idx)
        # Button mode
        idx = self._button_mode_combo.findData(cfg.button_mode)
        if idx >= 0:
            self._button_mode_combo.setCurrentIndex(idx)
        # Pause timeout
        self._pause_timeout_spin.setValue(cfg.pause_timeout_sec)
        # Load token (masked)
        token = self._store.load_token()
        if token:
            self._token_edit.setPlaceholderText("Токен сохранён (введите новый для замены)")

    def _on_enable_toggled(self, checked: bool) -> None:
        cfg = self._store.load()
        cfg.enabled = checked
        self._service.update_config(cfg)
        self._on_status("Яндекс Музыка RPC " + ("включён" if checked else "отключён"))
        self._refresh()

    def _save_token(self) -> None:
        token = self._token_edit.text().strip()
        if not token:
            self._on_status("Токен не введён")
            return
        ok = self._store.save_token(token)
        self._service.reload_ym_client()
        self._token_edit.clear()
        self._token_edit.setPlaceholderText("Токен сохранён (введите новый для замены)")
        self._on_status("Токен ЯМ сохранён" if ok else "Ошибка сохранения токена")

    def _apply_settings(self) -> None:
        cfg = self._store.load()
        cfg.enabled = self._enable_cb.isChecked()
        cfg.source = self._source_combo.currentData() or "auto"
        cfg.strong_find = self._strong_find_cb.isChecked()
        cfg.activity_type = int(self._activity_type_combo.currentData() or 2)
        cfg.button_mode = str(self._button_mode_combo.currentData() or "web")
        cfg.pause_timeout_sec = self._pause_timeout_spin.value()
        self._service.update_config(cfg)
        self._on_status("Настройки Яндекс Музыка RPC применены")
        self._refresh()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        status = self._service.status()

        # Error
        self._error_label.setText(status.error or "")

        # Discord status
        if not status.enabled:
            self._discord_status.setText("Отключён")
        elif status.discord_connected:
            self._discord_status.setText("Подключён")
        else:
            self._discord_status.setText("Ожидание Discord...")

        # Track
        track = status.current_track
        if track:
            self._track_title.setText(track.title or "—")
            self._track_artist.setText(track.artist or "—")
            self._track_album.setText(track.album or "")
            pb = track.playback_status
            self._track_playback.setText("▶ Играет" if pb == "Playing" else "⏸ На паузе" if pb == "Paused" else "")
            self._track_url.setText(track.yandex_url or "")
        else:
            self._track_title.setText("Ничего не играет")
            self._track_artist.setText("—")
            self._track_album.setText("")
            self._track_playback.setText("")
            self._track_url.setText("")

        # Log
        log = status.log
        current_count = self._log_list.count()
        if len(log) != current_count:
            self._log_list.clear()
            for entry in log:
                self._log_list.addItem(entry)
            self._log_list.scrollToBottom()


class DiscordQuestTabPage(QWidget):
    def __init__(self, on_status: Callable[[str], None], service: DiscordQuestService) -> None:
        super().__init__()
        self._on_status = on_status
        self._service = service
        self._config = service.load_config()
        self._catalog: list[object] = []
        self._selected_games: list[object] = []
        self._last_log_render = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(10)

        left_box = RefPanelBox("Discord Quest")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(12, 16, 12, 10)
        left_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("DiscordQuestSearchEdit")
        self.search_edit.setPlaceholderText("Search Discord-detectable games...")
        self.refetch_button = QPushButton("Refetch Game List")
        self.refetch_button.setObjectName("DiscordQuestRefetchButton")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.refetch_button)
        left_layout.addLayout(search_row)

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(8)
        self.search_combo = QComboBox()
        self.search_combo.setObjectName("DiscordQuestSearchCombo")
        self.add_game_button = QPushButton("Add game to list")
        self.add_game_button.setObjectName("DiscordQuestAddGameButton")
        add_row.addWidget(self.search_combo, 1)
        add_row.addWidget(self.add_game_button)
        left_layout.addLayout(add_row)

        self.games_table = QTableWidget(0, 3)
        self.games_table.setObjectName("DiscordQuestGamesTable")
        self.games_table.setHorizontalHeaderLabels(["Game", "ID", "State"])
        self.games_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.games_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.games_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.games_table.verticalHeader().setVisible(False)
        games_header = self.games_table.horizontalHeader()
        games_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        games_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        games_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.games_table, 1)

        remove_row = QHBoxLayout()
        remove_row.setContentsMargins(0, 0, 0, 0)
        remove_row.setSpacing(8)
        self.remove_game_button = QPushButton("Remove selected")
        self.remove_game_button.setObjectName("DiscordQuestRemoveGameButton")
        remove_row.addWidget(self.remove_game_button)
        remove_row.addStretch(1)
        left_layout.addLayout(remove_row)

        right_box = RefPanelBox("Game Actions")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(12, 16, 12, 10)
        right_layout.setSpacing(8)

        self.detail_game_label = QLabel("Name: -")
        self.detail_game_label.setProperty("role", "ref_section")
        self.detail_app_label = QLabel("App ID: -")
        self.detail_app_label.setProperty("role", "ref_section")
        self.detail_state_label = QLabel("State: -")
        self.detail_state_label.setProperty("role", "ref_section")

        self.exec_combo = QComboBox()
        self.exec_combo.setObjectName("DiscordQuestExecutableCombo")
        self.install_play_button = QPushButton("Install & Play")
        self.install_play_button.setObjectName("DiscordQuestInstallPlayButton")
        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("DiscordQuestPlayButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DiscordQuestStopButton")
        self.rpc_button = QPushButton("Test RPC")
        self.rpc_button.setObjectName("DiscordQuestRpcButton")
        self.open_logs_button = QPushButton("Open logs")
        self.open_logs_button.setObjectName("DiscordQuestOpenLogsButton")

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addWidget(self.install_play_button)
        button_row.addWidget(self.play_button)
        button_row.addWidget(self.stop_button)

        rpc_row = QHBoxLayout()
        rpc_row.setContentsMargins(0, 0, 0, 0)
        rpc_row.setSpacing(8)
        rpc_row.addWidget(self.rpc_button)
        rpc_row.addWidget(self.open_logs_button)
        rpc_row.addStretch(1)

        self.currently_playing_label = QLabel("Currently playing: -")
        self.currently_playing_label.setProperty("role", "ref_section")
        self.detail_error_label = QLabel("Last error: -")
        self.detail_error_label.setProperty("role", "ref_section")
        self.detail_error_label.setWordWrap(True)
        self.detail_refresh_label = QLabel("Last refresh: -")
        self.detail_refresh_label.setProperty("role", "ref_section")
        self.detail_source_label = QLabel("Source: -")
        self.detail_source_label.setProperty("role", "ref_section")
        self.detail_rpc_label = QLabel("RPC: disconnected")
        self.detail_rpc_label.setProperty("role", "ref_section")
        logs_label = QLabel("Action logs")
        logs_label.setProperty("role", "ref_section")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("DiscordQuestLogView")
        self.log_view.setReadOnly(True)

        right_layout.addWidget(self.detail_game_label)
        right_layout.addWidget(self.detail_app_label)
        right_layout.addWidget(self.detail_state_label)
        right_layout.addWidget(self.exec_combo)
        right_layout.addLayout(button_row)
        right_layout.addLayout(rpc_row)
        right_layout.addWidget(self.currently_playing_label)
        right_layout.addWidget(self.detail_error_label)
        right_layout.addWidget(self.detail_refresh_label)
        right_layout.addWidget(self.detail_source_label)
        right_layout.addWidget(self.detail_rpc_label)
        right_layout.addWidget(logs_label)
        right_layout.addWidget(self.log_view, 1)
        right_layout.addStretch(1)

        root.addWidget(left_box, 3)
        root.addWidget(right_box, 2)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh_status)

        self._wire_events()
        self._rebuild_search_combo()
        self._reload_selected_games()
        self._refresh_status()

    def on_shown(self) -> None:
        self._timer.start()
        self._refresh_catalog()

    def on_hidden(self) -> None:
        self._timer.stop()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)

    def _wire_events(self) -> None:
        self.refetch_button.clicked.connect(self._refresh_catalog)
        self.search_edit.textChanged.connect(self._rebuild_search_combo)
        self.add_game_button.clicked.connect(self._add_selected_game)
        self.remove_game_button.clicked.connect(self._remove_selected_game)
        self.games_table.itemSelectionChanged.connect(self._on_game_selection_changed)
        self.install_play_button.clicked.connect(self._install_and_play_selected)
        self.play_button.clicked.connect(self._play_selected)
        self.stop_button.clicked.connect(self._stop_selected)
        self.rpc_button.clicked.connect(self._toggle_rpc)
        self.open_logs_button.clicked.connect(self._open_logs)

    def _refresh_catalog(self) -> None:
        ok, message, games = self._service.refresh_catalog()
        self._catalog = list(games)
        self._rebuild_search_combo()
        self._reload_selected_games()
        self._refresh_status()
        self._on_status(message)
        if not ok:
            QMessageBox.warning(self, "Discord Quest", message)

    def _rebuild_search_combo(self) -> None:
        query = self.search_edit.text().strip().lower()
        self.search_combo.clear()
        items = []
        for game in self._catalog:
            name = str(getattr(game, "name", ""))
            aliases = [str(value) for value in getattr(game, "aliases", [])]
            full = " ".join([name, *aliases]).lower()
            if query and query not in full:
                continue
            items.append(game)
        for game in items[:120]:
            title = f"{getattr(game, 'name', '-')}"
            app_id = str(getattr(game, "id", "")).strip()
            self.search_combo.addItem(title, app_id)

    def _reload_selected_games(self) -> None:
        previous_uid = self._selected_game_uid()
        self._selected_games = list(self._service.selected_games())
        self.games_table.setRowCount(len(self._selected_games))
        for row, game in enumerate(self._selected_games):
            state = "Running" if bool(getattr(game, "is_running", False)) else ("Installed" if bool(getattr(game, "is_installed", False)) else "Ready")
            self.games_table.setItem(row, 0, QTableWidgetItem(str(getattr(game, "name", "-"))))
            self.games_table.setItem(row, 1, QTableWidgetItem(str(getattr(game, "id", "-"))))
            self.games_table.setItem(row, 2, QTableWidgetItem(state))
            self.games_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, getattr(game, "uid", ""))
        if self._selected_games:
            row_to_select = 0
            for idx, game in enumerate(self._selected_games):
                if str(getattr(game, "uid", "")) == previous_uid:
                    row_to_select = idx
                    break
            self.games_table.selectRow(row_to_select)
        self._on_game_selection_changed()

    def _selected_game_uid(self) -> str:
        row = self.games_table.currentRow()
        if row < 0:
            return ""
        item = self.games_table.item(row, 0)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _selected_game(self):
        uid = self._selected_game_uid()
        if not uid:
            return None
        for game in self._selected_games:
            if str(getattr(game, "uid", "")) == uid:
                return game
        return None

    def _on_game_selection_changed(self) -> None:
        game = self._selected_game()
        self.exec_combo.clear()
        if game is None:
            self.detail_game_label.setText("Name: -")
            self.detail_app_label.setText("App ID: -")
            self.detail_state_label.setText("State: -")
            self.install_play_button.setEnabled(False)
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.rpc_button.setEnabled(False)
            self.remove_game_button.setEnabled(False)
            return

        self.detail_game_label.setText(f"Name: {getattr(game, 'name', '-')}")
        self.detail_app_label.setText(f"App ID: {getattr(game, 'id', '-')}")
        state_text = "Running" if bool(getattr(game, "is_running", False)) else ("Installed" if bool(getattr(game, "is_installed", False)) else "Ready")
        self.detail_state_label.setText(f"State: {state_text}")
        for executable in getattr(game, "executables", []):
            label = str(getattr(executable, "name", "-"))
            key = str(getattr(executable, "key", ""))
            self.exec_combo.addItem(label, key)

        has_executable = self.exec_combo.count() > 0
        self.install_play_button.setEnabled(has_executable)
        self.play_button.setEnabled(has_executable and not bool(getattr(game, "is_running", False)))
        self.stop_button.setEnabled(has_executable and bool(getattr(game, "is_running", False)))
        self.rpc_button.setEnabled(True)
        self.remove_game_button.setEnabled(True)

    def _selected_executable_key(self) -> str:
        return str(self.exec_combo.currentData() or "").strip()

    def _ensure_warning_ack(self, rpc: bool = False) -> bool:
        if self._config.warning_ack:
            return True
        text = (
            "This feature may violate Discord terms and can lead to account risk. Continue?"
            if not rpc
            else "RPC mode is experimental and may flag your account as suspicious. Continue?"
        )
        answer = QMessageBox.question(
            self,
            "Discord Quest warning",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._config.warning_ack = True
        self._service.save_config(self._config)
        return True

    def _install_and_play_selected(self) -> None:
        game = self._selected_game()
        key = self._selected_executable_key()
        if game is None or not key:
            self._on_status("Discord Quest: select a game and executable first.")
            return
        if not self._ensure_warning_ack():
            self._on_status("Discord Quest action cancelled.")
            return
        ok, message = self._service.install_and_play(str(getattr(game, "uid", "")), key)
        self._on_status(message)
        self._reload_selected_games()
        self._refresh_status()
        if not ok:
            QMessageBox.warning(self, "Discord Quest", message)

    def _play_selected(self) -> None:
        game = self._selected_game()
        key = self._selected_executable_key()
        if game is None or not key:
            self._on_status("Discord Quest: select a game and executable first.")
            return
        if not self._ensure_warning_ack():
            self._on_status("Discord Quest action cancelled.")
            return
        ok, message = self._service.play(str(getattr(game, "uid", "")), key)
        self._on_status(message)
        self._reload_selected_games()
        self._refresh_status()
        if not ok:
            QMessageBox.warning(self, "Discord Quest", message)

    def _stop_selected(self) -> None:
        game = self._selected_game()
        key = self._selected_executable_key()
        if game is None or not key:
            self._on_status("Discord Quest: select a game and executable first.")
            return
        _ok, message = self._service.stop(str(getattr(game, "uid", "")), key)
        self._on_status(message)
        self._reload_selected_games()
        self._refresh_status()

    def _add_selected_game(self) -> None:
        app_id = str(self.search_combo.currentData() or "").strip()
        if not app_id:
            self._on_status("Discord Quest: no game selected from search results.")
            return
        ok, message = self._service.add_game(app_id)
        self._on_status(message)
        if ok:
            self._reload_selected_games()
            self._refresh_status()

    def _remove_selected_game(self) -> None:
        game = self._selected_game()
        if game is None:
            self._on_status("Discord Quest: select a game in the list first.")
            return
        ok, message = self._service.remove_game(str(getattr(game, "uid", "")))
        self._on_status(message)
        if ok:
            self._reload_selected_games()
            self._refresh_status()

    def _toggle_rpc(self) -> None:
        status = self._service.status()
        if status.rpc_connected:
            _ok, message = self._service.rpc_disconnect()
            self._on_status(message)
            self._refresh_status()
            return
        game = self._selected_game()
        if game is None:
            self._on_status("Discord Quest RPC: select a game first.")
            return
        if not self._ensure_warning_ack(rpc=True):
            self._on_status("Discord Quest RPC cancelled.")
            return
        ok, message = self._service.rpc_connect(str(getattr(game, "id", "")))
        self._on_status(message)
        self._refresh_status()
        if not ok:
            QMessageBox.warning(self, "Discord Quest RPC", message)

    def _open_logs(self) -> None:
        log_path = Path(self._service.status().log_path)
        if not log_path.exists():
            log_path.write_text("", encoding="utf-8")
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        if not opened:
            self._on_status("Discord Quest: unable to open log file.")

    def _refresh_status(self) -> None:
        status = self._service.status()
        self.detail_error_label.setText(f"Last error: {status.last_error or '-'}")
        self.detail_refresh_label.setText(f"Last refresh: {status.last_refresh or '-'}")
        self.detail_source_label.setText(f"Source: {status.source_used or '-'}")
        if status.rpc_connecting:
            rpc_text = "RPC: connecting..."
        elif status.rpc_connected:
            rpc_text = "RPC: connected"
        else:
            rpc_text = "RPC: disconnected"
        self.detail_rpc_label.setText(rpc_text)
        self.rpc_button.setText("Disconnect RPC" if status.rpc_connected else "Test RPC")

        playing_name = "-"
        for game in self._service.selected_games():
            if bool(getattr(game, "is_running", False)):
                playing_name = str(getattr(game, "name", "-"))
                break
        self.currently_playing_label.setText(f"Currently playing: {playing_name}")
        self._render_logs()

    def _render_logs(self) -> None:
        entries = self._service.event_logs()
        tail = entries[-120:]
        text = "\n".join(f"[{entry.timestamp}] {entry.level.upper():5s} {entry.message}" for entry in tail)
        if text == self._last_log_render:
            return
        self._last_log_render = text
        self.log_view.setPlainText(text)


class PerformanceLivePanel(QWidget):
    def __init__(self, service: MonitorService, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self._service = service
        self._on_status = on_status
        self._last_error_time = 0.0
        self._did_initial_sort = False
        self._last_filter_query = ""
        self._tick_counter = 0
        self._process_interval_ticks = 4
        self._process_limit = 40
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lolilend-perf")
        self._system_future: Future[SystemSnapshot] | None = None
        self._process_future: Future[list[ProcessSnapshot]] | None = None

        self._cpu_history = HistoryBuffer(60)
        self._ram_history = HistoryBuffer(60)
        self._gpu_history = HistoryBuffer(60)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        box = RefPanelBox("Performance Monitor")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(12, 16, 12, 10)
        box_layout.setSpacing(8)

        cards = QGridLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setHorizontalSpacing(8)
        cards.setVerticalSpacing(8)

        self.cpu_card = MetricCard("CPU")
        self.ram_card = MetricCard("RAM")
        self.gpu_card = MetricCard("GPU")
        self.disk_card = MetricCard("Disk")
        self.net_card = MetricCard("Network")
        cards.addWidget(self.cpu_card, 0, 0)
        cards.addWidget(self.ram_card, 0, 1)
        cards.addWidget(self.gpu_card, 0, 2)
        cards.addWidget(self.disk_card, 0, 3)
        cards.addWidget(self.net_card, 0, 4)
        box_layout.addLayout(cards)

        self.chart = LineHistoryChart(max_points=60)
        box_layout.addWidget(self.chart)

        process_header = QHBoxLayout()
        process_label = QLabel("Processes")
        process_label.setProperty("role", "ref_section")
        process_header.addWidget(process_label)
        process_header.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by process name / PID...")
        self.search_edit.textChanged.connect(self._apply_process_filter)
        process_header.addWidget(self.search_edit, 1)
        box_layout.addLayout(process_header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["PID", "Name", "CPU %", "RAM (MB)", "Status"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        box_layout.addWidget(self.table)

        root.addWidget(box)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh)
        self.destroyed.connect(lambda _=None: self._shutdown_executor())

    def start(self) -> None:
        self._queue_system_poll()
        self._queue_process_poll(force=True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._collect_futures()

    def _refresh(self) -> None:
        self._tick_counter += 1
        self._collect_futures()
        self._queue_system_poll()
        self._queue_process_poll()

    def _collect_futures(self) -> None:
        if self._system_future is not None and self._system_future.done():
            future = self._system_future
            self._system_future = None
            try:
                system_snapshot = future.result()
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self._report_error(exc)
            else:
                self._update_system_widgets(system_snapshot)

        if self._process_future is not None and self._process_future.done():
            future = self._process_future
            self._process_future = None
            try:
                process_snapshots = future.result()
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self._report_error(exc)
            else:
                self._update_process_table(process_snapshots)

    def _queue_system_poll(self) -> None:
        if self._system_future is None:
            self._system_future = self._executor.submit(self._service.poll_system)

    def _queue_process_poll(self, force: bool = False) -> None:
        if self._process_future is not None:
            return
        if not force and (self._tick_counter % self._process_interval_ticks != 0):
            return
        self._process_future = self._executor.submit(self._service.poll_processes, self._process_limit, False)

    def _shutdown_executor(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _report_error(self, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_error_time >= 10:
            self._last_error_time = now
            self._on_status(f"Monitoring error: {exc}")

    def _update_system_widgets(self, snapshot: SystemSnapshot) -> None:
        self.cpu_card.set_value(f"{snapshot.cpu_percent:.1f}%", "Total CPU load")
        self.ram_card.set_value(f"{snapshot.ram_percent:.1f}%", "Physical memory")
        gpu_text = "N/A" if snapshot.gpu_percent is None else f"{snapshot.gpu_percent:.1f}%"
        self.gpu_card.set_value(gpu_text, "Windows performance counters")

        disk_note = f"Read {format_bytes_text(snapshot.disk_read_bps)} / Write {format_bytes_text(snapshot.disk_write_bps)}"
        self.disk_card.set_value(format_bytes_text(snapshot.disk_read_bps + snapshot.disk_write_bps), disk_note)
        net_note = f"Down {format_bitrate_text(snapshot.net_down_bps)} / Up {format_bitrate_text(snapshot.net_up_bps)}"
        self.net_card.set_value(format_bitrate_text(snapshot.net_down_bps + snapshot.net_up_bps), net_note)

        self._cpu_history.push(snapshot.cpu_percent)
        self._ram_history.push(snapshot.ram_percent)
        self._gpu_history.push(snapshot.gpu_percent if snapshot.gpu_percent is not None else 0.0)
        self.chart.set_series(
            [
                ("CPU", QColor("#87d629"), self._cpu_history.values()),
                ("RAM", QColor("#4ec6ff"), self._ram_history.values()),
                ("GPU", QColor("#f4c542"), self._gpu_history.values()),
            ],
            y_limit=100.0,
        )

    def _update_process_table(self, processes: list[ProcessSnapshot]) -> None:
        query = self.search_edit.text().strip().lower()
        had_filter = bool(self._last_filter_query)
        has_filter = bool(query)

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(processes))
        for row, proc in enumerate(processes):
            pid_item = _make_number_item(proc.pid, str(proc.pid))
            pid_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(row, 0, pid_item)
            self.table.setItem(row, 1, QTableWidgetItem(proc.name))
            self.table.setItem(row, 2, _make_number_item(proc.cpu_percent, f"{proc.cpu_percent:.1f}"))
            self.table.setItem(row, 3, _make_number_item(proc.ram_mb, f"{proc.ram_mb:.1f}"))
            self.table.setItem(row, 4, QTableWidgetItem(proc.status))
        self.table.setSortingEnabled(True)

        if not self._did_initial_sort:
            self._did_initial_sort = True
            self.table.sortItems(2, Qt.SortOrder.DescendingOrder)
        if has_filter:
            self._apply_process_filter(query)
        elif had_filter:
            for row in range(self.table.rowCount()):
                self.table.setRowHidden(row, False)
        self._last_filter_query = query
        self.table.setUpdatesEnabled(True)

    def _apply_process_filter(self, value: str | None = None) -> None:
        query = value if value is not None else self.search_edit.text().strip().lower()
        self._last_filter_query = query
        for row in range(self.table.rowCount()):
            pid_item = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            if pid_item is None or name_item is None:
                self.table.setRowHidden(row, False)
                continue
            haystack = f"{pid_item.text()} {name_item.text()}".lower()
            self.table.setRowHidden(row, bool(query and query not in haystack))


class NetworkLivePanel(QWidget):
    def __init__(self, service: MonitorService, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self._service = service
        self._on_status = on_status
        self._last_error_time = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lolilend-net")
        self._system_future: Future[SystemSnapshot] | None = None

        self._down_history = HistoryBuffer(60)
        self._up_history = HistoryBuffer(60)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        box = RefPanelBox("Live network traffic (PC total)")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(12, 16, 12, 10)
        box_layout.setSpacing(8)

        cards = QHBoxLayout()
        cards.setSpacing(8)
        self.down_card = MetricCard("Download")
        self.up_card = MetricCard("Upload")
        cards.addWidget(self.down_card)
        cards.addWidget(self.up_card)
        box_layout.addLayout(cards)

        self.chart = LineHistoryChart(max_points=60)
        box_layout.addWidget(self.chart)

        info = QLabel("History window: 60 seconds, refresh: 1 second")
        info.setProperty("role", "ref_section")
        box_layout.addWidget(info)

        root.addWidget(box)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh)
        self.destroyed.connect(lambda _=None: self._shutdown_executor())

    def start(self) -> None:
        self._queue_system_poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._collect_future()

    def _refresh(self) -> None:
        self._collect_future()
        self._queue_system_poll()

    def _collect_future(self) -> None:
        if self._system_future is None or not self._system_future.done():
            return
        future = self._system_future
        self._system_future = None
        try:
            snapshot = future.result()
        except Exception as exc:  # pragma: no cover - defensive runtime path
            now = time.monotonic()
            if now - self._last_error_time >= 10:
                self._last_error_time = now
                self._on_status(f"Network monitoring error: {exc}")
            return

        self.down_card.set_value(format_bitrate_text(snapshot.net_down_bps), "Incoming")
        self.up_card.set_value(format_bitrate_text(snapshot.net_up_bps), "Outgoing")

        down_mbps, down_unit = format_bitrate_auto(snapshot.net_down_bps)
        up_mbps, up_unit = format_bitrate_auto(snapshot.net_up_bps)
        if down_unit == "Kbps":
            down_mbps /= 1_000
        if up_unit == "Kbps":
            up_mbps /= 1_000
        self._down_history.push(down_mbps)
        self._up_history.push(up_mbps)

        self.chart.set_series(
            [
                ("Download", QColor("#63d5ff"), self._down_history.values()),
                ("Upload", QColor("#ff8f66"), self._up_history.values()),
            ],
            y_limit=None,
        )

    def _queue_system_poll(self) -> None:
        if self._system_future is None:
            self._system_future = self._executor.submit(self._service.poll_system)

    def _shutdown_executor(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class PerformanceTabPage(QWidget):
    def __init__(self, tab: TabSpec, on_status: Callable[[str], None], service: MonitorService) -> None:
        super().__init__()
        self._store = GeneralSettingsStore()
        self._monitor_panel = PerformanceLivePanel(service, on_status)
        self._legacy_panel = _build_tab_page(tab, on_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        root.addWidget(self._splitter, 1)
        self._splitter.addWidget(self._monitor_panel)
        self._splitter.addWidget(self._legacy_panel)
        settings = self._store.load_settings()
        if settings.performance_splitter_state:
            self._splitter.restoreState(decode_qbytearray(settings.performance_splitter_state))
        else:
            self._splitter.setSizes([760, 500])
        self._splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

    def on_shown(self) -> None:
        self._monitor_panel.start()

    def on_hidden(self) -> None:
        self._monitor_panel.stop()
        self._save_splitter_state()

    def _save_splitter_state(self) -> None:
        settings = self._store.load_settings()
        settings.performance_splitter_state = encode_qbytearray(self._splitter.saveState())
        self._store.save_settings(settings)


class NetworkTabPage(QWidget):
    def __init__(self, tab: TabSpec, on_status: Callable[[str], None], service: MonitorService) -> None:
        super().__init__()
        self._store = GeneralSettingsStore()
        self._monitor_panel = NetworkLivePanel(service, on_status)
        self._legacy_panel = _build_tab_page(tab, on_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        root.addWidget(self._splitter, 1)
        self._splitter.addWidget(self._monitor_panel)
        self._splitter.addWidget(self._legacy_panel)
        settings = self._store.load_settings()
        if settings.network_splitter_state:
            self._splitter.restoreState(decode_qbytearray(settings.network_splitter_state))
        else:
            self._splitter.setSizes([720, 540])
        self._splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

    def on_shown(self) -> None:
        self._monitor_panel.start()

    def on_hidden(self) -> None:
        self._monitor_panel.stop()
        self._save_splitter_state()

    def _save_splitter_state(self) -> None:
        settings = self._store.load_settings()
        settings.network_splitter_state = encode_qbytearray(self._splitter.saveState())
        self._store.save_settings(settings)


class FpsTabPage(QWidget):
    def __init__(
        self,
        on_status: Callable[[str], None],
        service: FpsMonitorService,
        overlay: FpsOverlayWindow,
        elevation_manager: _ElevationManagerProtocol | None = None,
        quit_application: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_status = on_status
        self._service = service
        self._overlay = overlay
        self._elevation_manager = elevation_manager
        self._quit_application = quit_application or (lambda: QApplication.instance().quit() if QApplication.instance() is not None else None)
        self._store = GeneralSettingsStore()
        self._is_loading = False

        self._fps_history = HistoryBuffer(120)
        self._frametime_history = HistoryBuffer(120)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(10)

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(10)

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(10)

        metrics_box = RefPanelBox("FPS монитор")
        metrics_layout = QVBoxLayout(metrics_box)
        metrics_layout.setContentsMargins(12, 16, 12, 10)
        metrics_layout.setSpacing(8)

        cards = QGridLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setHorizontalSpacing(8)
        cards.setVerticalSpacing(8)
        self.fps_card = MetricCard("FPS")
        self.frametime_card = MetricCard("Frametime")
        self.one_low_card = MetricCard("1% Low")
        cards.addWidget(self.fps_card, 0, 0)
        cards.addWidget(self.frametime_card, 0, 1)
        cards.addWidget(self.one_low_card, 0, 2)
        metrics_layout.addLayout(cards)

        self.chart = LineHistoryChart(max_points=120)
        metrics_layout.addWidget(self.chart)

        hint = QLabel("Auto target: active foreground window")
        hint.setProperty("role", "ref_section")
        metrics_layout.addWidget(hint)
        left_column.addWidget(metrics_box, 3)

        control_box = RefPanelBox("Управление захватом")
        control_layout = QVBoxLayout(control_box)
        control_layout.setContentsMargins(12, 16, 12, 10)
        control_layout.setSpacing(7)

        capture_actions = QHBoxLayout()
        capture_actions.setContentsMargins(0, 0, 0, 0)
        capture_actions.setSpacing(8)
        self.capture_start_button = QPushButton("Запустить FPS захват")
        self.capture_start_button.setObjectName("FpsCaptureStartButton")
        self.capture_stop_button = QPushButton("Остановить FPS захват")
        self.capture_stop_button.setObjectName("FpsCaptureStopButton")
        capture_actions.addWidget(self.capture_start_button)
        capture_actions.addWidget(self.capture_stop_button)
        control_layout.addLayout(capture_actions)

        overlay_actions = QHBoxLayout()
        overlay_actions.setContentsMargins(0, 0, 0, 0)
        overlay_actions.setSpacing(8)
        self.overlay_start_button = QPushButton("Запустить overlay")
        self.overlay_start_button.setObjectName("FpsOverlayStartButton")
        self.overlay_stop_button = QPushButton("Остановить overlay")
        self.overlay_stop_button.setObjectName("FpsOverlayStopButton")
        overlay_actions.addWidget(self.overlay_start_button)
        overlay_actions.addWidget(self.overlay_stop_button)
        control_layout.addLayout(overlay_actions)

        hotkey_row = RefSelectRow("Hotkey overlay", ["Ctrl+Shift+F10", "F10", "Ctrl+F"], "Ctrl+Shift+F10")
        self.hotkey_combo = hotkey_row.combo
        self.hotkey_combo.setObjectName("FpsOverlayHotkeyCombo")
        control_layout.addWidget(hotkey_row)

        position_row = RefSelectRow("Позиция overlay", ["top_left", "top_right", "bottom_left", "bottom_right"], "top_left")
        self.position_combo = position_row.combo
        self.position_combo.setObjectName("FpsOverlayPositionCombo")
        control_layout.addWidget(position_row)

        opacity_row = RefSliderRow("Прозрачность overlay", 35, 100, 88, "%")
        self.opacity_slider = opacity_row.slider
        self.opacity_slider.setObjectName("FpsOverlayOpacitySlider")
        control_layout.addWidget(opacity_row)

        scale_row = RefSliderRow("Масштаб overlay", 80, 140, 100, "%")
        self.scale_slider = scale_row.slider
        self.scale_slider.setObjectName("FpsOverlayScaleSlider")
        control_layout.addWidget(scale_row)

        right_column.addWidget(control_box, 2)

        diagnostics_box = RefPanelBox("Диагностика")
        diagnostics_layout = QVBoxLayout(diagnostics_box)
        diagnostics_layout.setContentsMargins(12, 16, 12, 10)
        diagnostics_layout.setSpacing(7)

        self.status_value = QLabel("Status: N/A")
        self.target_value = QLabel("Target: N/A")
        self.backend_value = QLabel("Backend: N/A")
        self.platform_value = QLabel("Platform: Windows only")
        self.path_value = QLabel(f"PresentMon: {self._service.presentmon_path}")

        for label in (self.status_value, self.target_value, self.backend_value, self.platform_value, self.path_value):
            label.setProperty("role", "ref_section")
            label.setWordWrap(True)
            diagnostics_layout.addWidget(label)

        right_column.addWidget(diagnostics_box, 1)
        right_column.addStretch(1)

        root.addLayout(left_column, 3)
        root.addLayout(right_column, 2)

        self.capture_start_button.clicked.connect(self._start_capture)
        self.capture_stop_button.clicked.connect(self._stop_capture)
        self.overlay_start_button.clicked.connect(self._start_overlay)
        self.overlay_stop_button.clicked.connect(self._stop_overlay)
        self.hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
        self.position_combo.currentTextChanged.connect(self._on_position_changed)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)

        self._load_initial_state()
        self._refresh()

    def on_shown(self) -> None:
        self._refresh()
        self._timer.start()

    def on_hidden(self) -> None:
        self._timer.stop()

    def _load_initial_state(self) -> None:
        self._is_loading = True
        settings = self._store.load_settings()

        self.hotkey_combo.setCurrentText(settings.fps_overlay_hotkey)
        self.position_combo.setCurrentText(settings.fps_overlay_position)
        self.opacity_slider.setValue(settings.fps_overlay_opacity)
        self.scale_slider.setValue(settings.fps_overlay_scale)

        self._overlay.set_overlay_position(settings.fps_overlay_position)
        self._overlay.set_overlay_opacity(settings.fps_overlay_opacity)
        self._overlay.set_overlay_scale(settings.fps_overlay_scale)
        hotkey_ok, hotkey_error = self._overlay.set_hotkey(settings.fps_overlay_hotkey)
        if not hotkey_ok and hotkey_error:
            self._on_status(hotkey_error)

        if settings.fps_overlay_enabled:
            self._overlay.show_overlay()
        else:
            self._overlay.hide()

        if settings.fps_capture_enabled:
            self._attempt_capture_start(auto_start=True)

        self._is_loading = False
        self._sync_buttons()

    def _persist_settings(self, **updates: object) -> None:
        settings = self._store.load_settings()
        for key, value in updates.items():
            setattr(settings, key, value)
        self._store.save_settings(settings)

    def _start_capture(self) -> None:
        self._attempt_capture_start(auto_start=False)

    def _stop_capture(self) -> None:
        self._service.stop_capture()
        self._persist_settings(fps_capture_enabled=False)
        self._on_status("FPS capture stopped")
        self._sync_buttons()

    def _start_overlay(self) -> None:
        self._overlay.show_overlay()
        self._persist_settings(fps_overlay_enabled=True)
        self._sync_buttons()

    def _stop_overlay(self) -> None:
        self._overlay.hide()
        self._persist_settings(fps_overlay_enabled=False)
        self._sync_buttons()

    def _on_hotkey_changed(self, value: str) -> None:
        if self._is_loading:
            return
        ok, error = self._overlay.set_hotkey(value)
        if ok:
            self._persist_settings(fps_overlay_hotkey=value)
            return
        if error:
            self._on_status(error)

    def _on_position_changed(self, value: str) -> None:
        self._overlay.set_overlay_position(value)
        if not self._is_loading:
            self._persist_settings(fps_overlay_position=value)

    def _on_opacity_changed(self, value: int) -> None:
        self._overlay.set_overlay_opacity(value)
        if not self._is_loading:
            self._persist_settings(fps_overlay_opacity=int(value))

    def _on_scale_changed(self, value: int) -> None:
        self._overlay.set_overlay_scale(value)
        if not self._is_loading:
            self._persist_settings(fps_overlay_scale=int(value))

    def _sync_buttons(self) -> None:
        running = self._service.is_running()
        can_run = self._service.windows_supported()
        self.capture_start_button.setEnabled(can_run and not running)
        self.capture_stop_button.setEnabled(can_run and running)
        self.overlay_start_button.setEnabled(not self._overlay.isVisible())
        self.overlay_stop_button.setEnabled(self._overlay.isVisible())

    def capture_enabled(self) -> bool:
        return self._service.is_running()

    def set_capture_enabled(self, enabled: bool) -> bool:
        if enabled:
            return self._attempt_capture_start(auto_start=False)
        self._stop_capture()
        return True

    def overlay_enabled(self) -> bool:
        return self._overlay.isVisible()

    def set_overlay_enabled(self, enabled: bool) -> None:
        if enabled:
            self._start_overlay()
            return
        self._stop_overlay()

    def _refresh(self) -> None:
        snapshot = self._service.latest_snapshot()
        self._overlay.update_snapshot(snapshot)

        fps_text = "N/A" if snapshot.fps is None else f"{snapshot.fps:.0f}"
        frametime_text = "N/A" if snapshot.frame_time_ms is None else f"{snapshot.frame_time_ms:.2f} ms"
        one_low_text = "N/A" if snapshot.one_percent_low_fps is None else f"{snapshot.one_percent_low_fps:.0f}"

        self.fps_card.set_value(fps_text, "Foreground app")
        self.frametime_card.set_value(frametime_text, "Average")
        self.one_low_card.set_value(one_low_text, "Rolling 20s")

        self._fps_history.push(snapshot.fps if snapshot.fps is not None else 0.0)
        self._frametime_history.push(snapshot.frame_time_ms if snapshot.frame_time_ms is not None else 0.0)
        self.chart.set_series(
            [
                ("FPS", QColor("#e74c3c"), self._fps_history.values()),
                ("Frametime", QColor("#6fbad8"), self._frametime_history.values()),
            ],
            y_limit=None,
        )

        target_name = snapshot.process_name or (f"PID {snapshot.pid}" if snapshot.pid is not None else "N/A")
        backend = snapshot.backend_error or "OK"
        self.status_value.setText(f"Status: {snapshot.status}")
        self.target_value.setText(f"Target: {target_name}")
        self.backend_value.setText(f"Backend: {backend}")
        self.platform_value.setText(f"Platform: {STATUS_WINDOWS_ONLY if not self._service.windows_supported() else 'Windows'}")
        self._sync_buttons()

    def _attempt_capture_start(self, auto_start: bool) -> bool:
        started, message = self._service.start_capture()
        self._on_status(message)
        if started:
            self._persist_settings(fps_capture_enabled=True)
            self._sync_buttons()
            return True

        snapshot = self._service.latest_snapshot()
        if snapshot.permission_required and self._handle_permission_required():
            return False

        if auto_start:
            self._persist_settings(fps_capture_enabled=False)
        self._sync_buttons()
        return False

    def _handle_permission_required(self) -> bool:
        manager = self._elevation_manager
        if manager is None:
            return False
        if manager.was_relaunched_for_fps:
            self._persist_settings(fps_capture_enabled=False)
            self._on_status("FPS capture is still blocked after administrator restart")
            self._sync_buttons()
            return False
        if not manager.can_relaunch_for_fps():
            return False

        self._persist_settings(fps_capture_enabled=True)
        relaunched, message = manager.relaunch_for_fps()
        self._on_status(message)
        if not relaunched:
            self._persist_settings(fps_capture_enabled=False)
            self._sync_buttons()
            return False

        self._quit_application()
        return True


class AnalyticsTabPage(QWidget):
    def __init__(self, on_status: Callable[[str], None], service: GameAnalyticsService) -> None:
        super().__init__()
        self._on_status = on_status
        self._service = service
        self._store = GeneralSettingsStore()
        self._window_days = 7

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        root.addWidget(self._splitter, 1)

        live_frame = QWidget()
        live_column = QVBoxLayout(live_frame)
        live_column.setContentsMargins(0, 0, 0, 0)
        live_column.setSpacing(10)
        summary_frame = QWidget()
        summary_column = QVBoxLayout(summary_frame)
        summary_column.setContentsMargins(0, 0, 0, 0)
        summary_column.setSpacing(10)

        live_box = RefPanelBox("Now Playing")
        live_layout = QVBoxLayout(live_box)
        live_layout.setContentsMargins(12, 16, 12, 10)
        live_layout.setSpacing(8)

        self.live_table = QTableWidget(0, 4)
        self.live_table.setHorizontalHeaderLabels(["Game", "Session", "Confidence", "PIDs"])
        self._setup_table(self.live_table)
        live_layout.addWidget(self.live_table)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)
        actions_row.addStretch(1)

        self.mark_game_button = QPushButton("Mark as game")
        self.mark_non_game_button = QPushButton("Mark as non-game")
        self.clear_override_button = QPushButton("Clear override")
        self.mark_game_button.clicked.connect(lambda: self._set_override(True))
        self.mark_non_game_button.clicked.connect(lambda: self._set_override(False))
        self.clear_override_button.clicked.connect(self._clear_override)
        actions_row.addWidget(self.mark_game_button)
        actions_row.addWidget(self.mark_non_game_button)
        actions_row.addWidget(self.clear_override_button)
        live_layout.addLayout(actions_row)
        live_column.addWidget(live_box, 2)

        summary_box = RefPanelBox("Game Time Summary")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(12, 16, 12, 10)
        summary_layout.setSpacing(8)

        totals_row = QHBoxLayout()
        totals_row.setContentsMargins(0, 0, 0, 0)
        totals_row.setSpacing(16)
        self.total_today_label = QLabel("Today: 0s")
        self.total_today_label.setProperty("role", "metric_value")
        self.total_week_label = QLabel("7 days: 0s")
        self.total_week_label.setProperty("role", "metric_value")
        totals_row.addWidget(self.total_today_label)
        totals_row.addWidget(self.total_week_label)
        totals_row.addStretch(1)
        summary_layout.addLayout(totals_row)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        today_box = RefPanelBox("Top 5 Today")
        today_layout = QVBoxLayout(today_box)
        today_layout.setContentsMargins(10, 14, 10, 8)
        today_layout.setSpacing(8)
        self.today_table = QTableWidget(0, 3)
        self.today_table.setHorizontalHeaderLabels(["Game", "Time", "Sessions"])
        self._setup_table(self.today_table)
        today_layout.addWidget(self.today_table)
        top_row.addWidget(today_box, 1)

        week_box = RefPanelBox("Top 5 (7 days)")
        week_layout = QVBoxLayout(week_box)
        week_layout.setContentsMargins(10, 14, 10, 8)
        week_layout.setSpacing(8)
        self.week_table = QTableWidget(0, 3)
        self.week_table.setHorizontalHeaderLabels(["Game", "Time", "Sessions"])
        self._setup_table(self.week_table)
        week_layout.addWidget(self.week_table)
        top_row.addWidget(week_box, 1)

        summary_layout.addLayout(top_row, 2)

        self.week_chart = LineHistoryChart(max_points=7)
        summary_layout.addWidget(self.week_chart, 1)
        chart_hint = QLabel("Last 7 days (hours)")
        chart_hint.setProperty("role", "ref_section")
        summary_layout.addWidget(chart_hint)

        summary_column.addWidget(summary_box, 1)
        self._splitter.addWidget(live_frame)
        self._splitter.addWidget(summary_frame)

        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)
        settings = self._store.load_settings()
        if settings.analytics_splitter_state:
            self._splitter.restoreState(decode_qbytearray(settings.analytics_splitter_state))
        else:
            self._splitter.setSizes([460, 760])
        self._splitter.splitterMoved.connect(lambda *_: self._save_splitter_state())

    def on_shown(self) -> None:
        self._service.start()
        self._refresh()
        self._timer.start()

    def on_hidden(self) -> None:
        self._timer.stop()
        self._service.stop()
        self._save_splitter_state()

    @staticmethod
    def _setup_table(table: QTableWidget) -> None:
        table.setSortingEnabled(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    def _refresh(self) -> None:
        live = self._service.get_live_games(limit=3)
        summary = self._service.get_summary(days=self._window_days)
        self._update_live_table(live)
        self._update_summary(summary)

    def _update_live_table(self, live: list[LiveGameEntry]) -> None:
        self.live_table.setRowCount(len(live))
        for row, entry in enumerate(live):
            game_item = QTableWidgetItem(entry.display_name)
            game_item.setData(Qt.ItemDataRole.UserRole, entry.app_key)
            self.live_table.setItem(row, 0, game_item)
            self.live_table.setItem(row, 1, QTableWidgetItem(format_duration(entry.session_seconds)))
            self.live_table.setItem(row, 2, QTableWidgetItem(f"{entry.confidence * 100:.0f}%"))
            self.live_table.setItem(row, 3, _make_number_item(entry.pid_count, str(entry.pid_count)))

    def _update_summary(self, summary: AnalyticsSummary) -> None:
        self.total_today_label.setText(f"Today: {format_duration(summary.total_today_seconds)}")
        self.total_week_label.setText(f"7 days: {format_duration(summary.total_week_seconds)}")
        self._update_top_table(self.today_table, summary.top_today)
        self._update_top_table(self.week_table, summary.top_week)

        hour_values = [point.seconds / 3600.0 for point in summary.daily_series]
        self.week_chart.set_series(
            [("Hours", QColor("#63d5ff"), hour_values)],
            y_limit=None,
        )

    def _update_top_table(self, table: QTableWidget, entries: list[TopGameEntry]) -> None:
        table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            game_item = QTableWidgetItem(entry.display_name)
            game_item.setData(Qt.ItemDataRole.UserRole, entry.app_key)
            table.setItem(row, 0, game_item)
            table.setItem(row, 1, QTableWidgetItem(format_duration(entry.seconds)))
            table.setItem(row, 2, _make_number_item(entry.sessions, str(entry.sessions)))

    def _selected_app(self) -> tuple[str, str] | None:
        focused_tables = [table for table in (self.live_table, self.today_table, self.week_table) if table.hasFocus()]
        for table in focused_tables + [self.live_table, self.today_table, self.week_table]:
            selected = self._extract_selected_row(table)
            if selected is not None:
                return selected
        return None

    @staticmethod
    def _extract_selected_row(table: QTableWidget) -> tuple[str, str] | None:
        row = table.currentRow()
        if row < 0:
            selected_items = table.selectedItems()
            if not selected_items:
                return None
            row = selected_items[0].row()
        app_item = table.item(row, 0)
        if app_item is None:
            return None
        app_key_raw = app_item.data(Qt.ItemDataRole.UserRole)
        if app_key_raw is None:
            return None
        return str(app_key_raw), app_item.text()

    def _set_override(self, is_game: bool) -> None:
        selected = self._selected_app()
        if selected is None:
            self._on_status("Analytics: select a game row first.")
            return
        app_key, display_name = selected
        self._service.set_override(app_key, is_game)
        verdict = "game" if is_game else "non-game"
        self._on_status(f"Analytics override: {display_name} -> {verdict}")
        self._refresh()

    def _clear_override(self) -> None:
        selected = self._selected_app()
        if selected is None:
            self._on_status("Analytics: select a game row first.")
            return
        app_key, display_name = selected
        self._service.clear_override(app_key)
        self._on_status(f"Analytics override cleared: {display_name}")
        self._refresh()

    def _save_splitter_state(self) -> None:
        settings = self._store.load_settings()
        settings.analytics_splitter_state = encode_qbytearray(self._splitter.saveState())
        self._store.save_settings(settings)


def _animate_page_fade(page: QWidget) -> None:
    effect = QGraphicsOpacityEffect(page)
    page.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", page)
    animation.setDuration(170)
    animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.finished.connect(lambda: page.setGraphicsEffect(None))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def _load_splitter_payload(raw_state: str) -> dict[str, str]:
    try:
        payload = json.loads(raw_state) if raw_state else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def build_ui(
    schema: Sequence[TabSpec],
    on_status: Callable[[str], None] | None = None,
    initial_settings: GeneralSettings | None = None,
    apply_window_settings: Callable[[GeneralSettings], None] | None = None,
    elevation_manager: _ElevationManagerProtocol | None = None,
    bridge_sink: Callable[[UiBridge], None] | None = None,
) -> QWidget:
    base_status = on_status if on_status is not None else (lambda _: None)
    settings = initial_settings or GeneralSettingsStore().load_settings()
    runtime = UiRuntimeState.from_settings(settings)

    def emit_status(message: str, force: bool = False) -> None:
        if force or not runtime.hide_notifications:
            base_status(message)

    root = QWidget()
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    background = HudBackgroundSurface()
    background_layout = QVBoxLayout(background)
    background_layout.setContentsMargins(18, 18, 18, 18)
    background_layout.setSpacing(0)
    root_layout.addWidget(background)

    shell = QFrame()
    shell.setObjectName("MainFrame")
    shell.setMinimumSize(940, 560)
    shell_layout = QVBoxLayout(shell)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    accent_line = QFrame()
    accent_line.setObjectName("AccentLine")
    accent_line.setFixedHeight(2)
    shell_layout.addWidget(accent_line)

    shell_body = QFrame()
    shell_body.setObjectName("ShellBody")
    layout = QHBoxLayout(shell_body)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    shell_layout.addWidget(shell_body, 1)

    background_layout.addWidget(shell, 1)

    sidebar = QFrame()
    sidebar.setObjectName("SidebarFrame")
    sidebar.setMinimumWidth(140)
    sidebar.setMaximumWidth(260)
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setContentsMargins(0, 0, 0, 0)
    sidebar_layout.setSpacing(0)

    content = QFrame()
    content.setObjectName("ContentFrame")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(8, 8, 8, 8)
    content_layout.setSpacing(6)

    stacked = QStackedWidget()
    content_layout.addWidget(stacked)
    main_splitter = QSplitter(Qt.Orientation.Horizontal)
    main_splitter.setObjectName("MainShellSplitter")
    main_splitter.setChildrenCollapsible(False)
    layout.addWidget(main_splitter, 1)

    group = QButtonGroup(shell)
    group.setExclusive(True)

    performance_service = MonitorService()
    network_service = MonitorService()
    analytics_service = GameAnalyticsService()
    fps_service = FpsMonitorService()
    fps_overlay = FpsOverlayWindow()
    telegram_proxy_service = TelegramProxyService()
    discord_quest_service = DiscordQuestService()
    yandex_music_rpc_service = YandexMusicRpcService()
    root.destroyed.connect(lambda _=None: analytics_service.stop())
    root.destroyed.connect(lambda _=None: fps_service.close())
    root.destroyed.connect(lambda _=None: fps_overlay.shutdown())
    root.destroyed.connect(lambda _=None: telegram_proxy_service.shutdown())
    root.destroyed.connect(lambda _=None: discord_quest_service.shutdown())
    root.destroyed.connect(lambda _=None: yandex_music_rpc_service.shutdown())
    lifecycle_pages: dict[int, _LifecyclePage] = {}
    current_index = -1
    nav_titles: dict[QToolButton, str] = {}
    general_page: AdvancedGeneralTabPage | None = None
    fps_page: FpsTabPage | None = None
    telegram_proxy_page: TelegramProxyTabPage | None = None

    def apply_runtime_settings(current_settings: GeneralSettings) -> None:
        runtime.update_from_settings(current_settings)
        sidebar.setMaximumWidth(max(260, current_settings.sidebar_width + 32))
        if apply_window_settings is not None:
            apply_window_settings(current_settings)
        refresh_nav_hints()

    def refresh_nav_hints() -> None:
        for button, title in nav_titles.items():
            button.setToolTip(title if runtime.hints_enabled else "")

    brand_container = QFrame()
    brand_container.setObjectName("SidebarBrandBlock")
    brand_vbox = QVBoxLayout(brand_container)
    brand_vbox.setContentsMargins(14, 14, 8, 10)
    brand_vbox.setSpacing(1)
    brand_label = QLabel("LOLILEND")
    brand_label.setObjectName("SidebarBrand")
    brand_sub = QLabel("GAMING PORTAL")
    brand_sub.setObjectName("SidebarBrandSub")
    brand_vbox.addWidget(brand_label)
    brand_vbox.addWidget(brand_sub)
    sidebar_layout.addWidget(brand_container)

    for index, tab in enumerate(schema):
        if tab.id in {"analytics", "security"}:
            separator = QFrame()
            separator.setObjectName("NavSeparator")
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setFixedHeight(1)
            sidebar_layout.addWidget(separator)

        button = QToolButton()
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setToolTip(tab.title)
        button.setIcon(_resolve_icon(button, tab.icon))
        button.setIconSize(QSize(18, 18))
        button.setText(tab.title)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(40)
        sidebar_layout.addWidget(button)
        group.addButton(button, index)
        nav_titles[button] = tab.title

        if tab.id == "performance":
            page = PerformanceTabPage(tab, lambda message: emit_status(message, False), performance_service)
            lifecycle_pages[index] = page
        elif tab.id == "fps":
            page = FpsTabPage(
                lambda message: emit_status(message, False),
                fps_service,
                fps_overlay,
                elevation_manager=elevation_manager,
            )
            lifecycle_pages[index] = page
            fps_page = page
        elif tab.id == "analytics":
            page = AnalyticsTabPage(lambda message: emit_status(message, False), analytics_service)
            lifecycle_pages[index] = page
        elif tab.id == "network":
            page = NetworkTabPage(tab, lambda message: emit_status(message, False), network_service)
            lifecycle_pages[index] = page
        elif tab.id == "telegram_proxy":
            page = TelegramProxyTabPage(
                lambda message: emit_status(message, False),
                telegram_proxy_service,
            )
            lifecycle_pages[index] = page
            telegram_proxy_page = page
        elif tab.id == "discord_quest":
            page = DiscordQuestTabPage(
                lambda message: emit_status(message, False),
                discord_quest_service,
            )
            lifecycle_pages[index] = page
        elif tab.id == "yandex_music_rpc":
            page = YandexMusicRpcTabPage(
                lambda message: emit_status(message, False),
                yandex_music_rpc_service,
            )
            lifecycle_pages[index] = page
        elif tab.id == "general":
            page = AdvancedGeneralTabPage(tab, emit_status, runtime, refresh_nav_hints, apply_runtime_settings)
            general_page = page
        elif tab.id == "security":
            page = SecurityLinksPage(lambda message: emit_status(message, False))
        elif tab.id == "ai":
            page = AiTabPage(lambda message: emit_status(message, False))
            lifecycle_pages[index] = page
        else:
            page = _build_tab_page(tab, lambda message: emit_status(message, False))

        stacked.addWidget(page)

        def on_switch(checked: bool, i: int = index, title: str = tab.title) -> None:
            nonlocal current_index
            if not checked:
                return

            if current_index == i:
                return

            previous_page = lifecycle_pages.get(current_index)
            if previous_page is not None:
                previous_page.on_hidden()

            stacked.setCurrentIndex(i)
            if runtime.smooth_animation:
                _animate_page_fade(stacked.currentWidget())
            current_index = i
            emit_status(f"Opened tab: {title}", False)

            next_page = lifecycle_pages.get(i)
            if next_page is not None:
                next_page.on_shown()

        button.toggled.connect(on_switch)

    sidebar_layout.addStretch(1)
    profile_slot = QFrame()
    profile_slot.setObjectName("NavProfileSlot")
    profile_slot.setFixedHeight(52)
    profile_slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    profile_layout = QVBoxLayout(profile_slot)
    profile_layout.setContentsMargins(0, 0, 0, 0)
    profile_layout.setSpacing(0)
    profile_icon = QLabel()
    profile_icon.setObjectName("NavProfileIcon")
    profile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    profile_icon.setPixmap(_resolve_icon(profile_icon, "profiles").pixmap(20, 20))
    profile_layout.addWidget(profile_icon)
    sidebar_layout.addWidget(profile_slot)

    apply_runtime_settings(settings)
    refresh_nav_hints()
    if group.buttons():
        group.button(0).setChecked(True)

    main_splitter.addWidget(sidebar)
    main_splitter.addWidget(content)
    if settings.main_splitter_state:
        main_splitter.restoreState(decode_qbytearray(settings.main_splitter_state))
        if main_splitter.sizes() and main_splitter.sizes()[0] < 140:
            main_splitter.setSizes([175, 1180])
    else:
        main_splitter.setSizes([settings.sidebar_width, 1180])

    def persist_main_splitter_state() -> None:
        current_settings = GeneralSettingsStore().load_settings()
        sizes = main_splitter.sizes()
        if sizes:
            current_settings.sidebar_width = max(140, min(260, int(sizes[0])))
        current_settings.main_splitter_state = encode_qbytearray(main_splitter.saveState())
        GeneralSettingsStore().save_settings(current_settings)

    main_splitter.splitterMoved.connect(lambda *_: persist_main_splitter_state())

    if bridge_sink is not None:
        def snapshot() -> UiTrayState:
            settings_now = GeneralSettingsStore().load_settings()
            profiles = general_page.available_profiles() if general_page is not None else ["Стандарт", "Работа", "Тихий режим"]
            active_profile = general_page.current_profile() if general_page is not None else settings_now.profile_name
            hide_notifications = general_page.hide_notifications_enabled() if general_page is not None else settings_now.hide_notifications
            autostart_enabled = general_page.autostart_enabled() if general_page is not None else settings_now.autostart_windows
            fps_capture_enabled = fps_page.capture_enabled() if fps_page is not None else settings_now.fps_capture_enabled
            fps_overlay_enabled = fps_page.overlay_enabled() if fps_page is not None else settings_now.fps_overlay_enabled
            telegram_proxy_enabled = telegram_proxy_page.proxy_enabled() if telegram_proxy_page is not None else False
            return UiTrayState(
                profiles=profiles,
                active_profile=active_profile,
                hide_notifications=hide_notifications,
                autostart_enabled=autostart_enabled,
                fps_capture_enabled=fps_capture_enabled,
                fps_overlay_enabled=fps_overlay_enabled,
                telegram_proxy_enabled=telegram_proxy_enabled,
            )

        def available_profiles() -> list[str]:
            if general_page is None:
                return ["Стандарт", "Работа", "Тихий режим"]
            return general_page.available_profiles()

        def activate_profile(name: str) -> bool:
            if general_page is None:
                return False
            return general_page.activate_profile(name)

        def set_hide_notifications(enabled: bool) -> None:
            if general_page is None:
                return
            general_page.set_hide_notifications_enabled(enabled)

        def set_autostart_enabled(enabled: bool) -> tuple[bool, str]:
            if general_page is None:
                return False, "Страница настроек не инициализирована."
            return general_page.set_autostart_enabled(enabled)

        def set_fps_capture_enabled(enabled: bool) -> bool:
            if fps_page is None:
                return False
            return fps_page.set_capture_enabled(enabled)

        def set_fps_overlay_enabled(enabled: bool) -> None:
            if fps_page is None:
                return
            fps_page.set_overlay_enabled(enabled)

        def set_telegram_proxy_enabled(enabled: bool) -> bool:
            if telegram_proxy_page is None:
                return False
            return telegram_proxy_page.set_proxy_enabled(enabled)

        def set_theme(theme_name: str) -> None:
            background.set_theme_background(theme_name)

        bridge_sink(
            UiBridge(
                snapshot=snapshot,
                available_profiles=available_profiles,
                activate_profile=activate_profile,
                set_hide_notifications=set_hide_notifications,
                set_autostart_enabled=set_autostart_enabled,
                set_fps_capture_enabled=set_fps_capture_enabled,
                set_fps_overlay_enabled=set_fps_overlay_enabled,
                set_telegram_proxy_enabled=set_telegram_proxy_enabled,
                set_theme=set_theme,
            )
        )

    return root


class LoliLendWindow(QMainWindow):
    def __init__(
        self,
        elevation_manager: WindowsElevationManager | None = None,
        tray_available: Callable[[], bool] | None = None,
        tray_icon_factory: Callable[[QIcon, QWidget], QSystemTrayIcon] | None = None,
    ) -> None:
        super().__init__()
        _install_hud_font()
        self._settings_store = GeneralSettingsStore()
        self._settings = self._settings_store.load_settings()
        self._elevation_manager = elevation_manager
        self._ui_bridge: UiBridge | None = None
        self._tray_available = tray_available or QSystemTrayIcon.isSystemTrayAvailable
        self._tray_icon_factory = tray_icon_factory or (lambda icon, parent: QSystemTrayIcon(icon, parent))
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_profiles_menu: QMenu | None = None
        self._tray_profile_actions: dict[str, QAction] = {}
        self._tray_header_action: QAction | None = None
        self._tray_toggle_action: QAction | None = None
        self._tray_hide_notifications_action: QAction | None = None
        self._tray_autostart_action: QAction | None = None
        self._tray_fps_capture_action: QAction | None = None
        self._tray_fps_overlay_action: QAction | None = None
        self._tray_proxy_action: QAction | None = None
        self._explicit_exit = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(_application_icon(self))
        self.setMinimumSize(1100, 680)
        self.resize(1366, 768)
        self.setStyleSheet(app_stylesheet(asdict(self._settings)))
        self.setCentralWidget(
            build_ui(
                tabs_schema,
                self._show_status,
                self._settings,
                self._apply_window_settings,
                elevation_manager=self._elevation_manager,
                bridge_sink=self._set_ui_bridge,
            )
        )
        self._apply_window_settings(self._settings)
        self._restore_window_state()
        self._init_tray_controller()
        self.statusBar().showMessage(f"{self._settings.active_ai}: settings and monitoring ready", 5000)
        self._update_tray_tooltip()

    def _set_ui_bridge(self, bridge: UiBridge) -> None:
        self._ui_bridge = bridge

    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 4000)
        self._update_tray_tooltip()

    def _apply_window_settings(self, settings: GeneralSettings) -> None:
        self._settings = settings
        self.setStyleSheet(app_stylesheet(asdict(settings)))
        opacity = 0.74 + (max(0, min(100, settings.brightness)) / 100.0) * 0.26
        self.setWindowOpacity(max(0.74, min(1.0, opacity)))
        self.statusBar().setVisible(settings.show_status_bar)
        self._update_tray_menu_actions()
        self._update_tray_tooltip()
        if self._ui_bridge is not None:
            self._ui_bridge.set_theme(settings.visual_theme)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.WindowStateChange:
            if self._should_minimize_to_tray() and self.isMinimized():
                QTimer.singleShot(0, lambda: self._hide_to_tray("Окно свернуто в трей."))
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._persist_window_state()
        if not self._explicit_exit and self._should_close_to_tray():
            event.ignore()
            self._hide_to_tray("Приложение продолжает работу в трее.")
            return
        tray_icon = self._tray_icon
        if tray_icon is not None:
            tray_icon.hide()
        super().closeEvent(event)

    def _tray_supported(self) -> bool:
        try:
            return bool(self._tray_available())
        except Exception:
            return False

    def _should_minimize_to_tray(self) -> bool:
        return self._tray_supported() and bool(self._settings.minimize_to_tray)

    def _should_close_to_tray(self) -> bool:
        return self._tray_supported() and bool(self._settings.close_to_tray)

    def _init_tray_controller(self) -> None:
        if not self._tray_supported():
            return
        tray_icon = self._tray_icon_factory(self.windowIcon(), self)
        tray_menu = QMenu(self)
        tray_menu.aboutToShow.connect(self._refresh_tray_menu)

        header_action = QAction(APP_NAME, self)
        header_action.setEnabled(False)
        tray_menu.addAction(header_action)
        tray_menu.addSeparator()

        toggle_action = QAction("Открыть окно", self)
        toggle_action.triggered.connect(self._toggle_main_window_visibility)
        tray_menu.addAction(toggle_action)

        profiles_menu = tray_menu.addMenu("Профиль")
        tray_menu.addSeparator()

        hide_notifications_action = QAction("Скрывать уведомления", self)
        hide_notifications_action.setCheckable(True)
        hide_notifications_action.triggered.connect(self._on_tray_hide_notifications_changed)
        tray_menu.addAction(hide_notifications_action)

        autostart_action = QAction("Автозапуск с Windows", self)
        autostart_action.setCheckable(True)
        autostart_action.triggered.connect(self._on_tray_autostart_changed)
        tray_menu.addAction(autostart_action)

        fps_capture_action = QAction("FPS захват", self)
        fps_capture_action.setCheckable(True)
        fps_capture_action.triggered.connect(self._on_tray_fps_capture_changed)
        tray_menu.addAction(fps_capture_action)

        fps_overlay_action = QAction("FPS overlay", self)
        fps_overlay_action.setCheckable(True)
        fps_overlay_action.triggered.connect(self._on_tray_fps_overlay_changed)
        tray_menu.addAction(fps_overlay_action)

        proxy_action = QAction("Telegram Proxy", self)
        proxy_action.setCheckable(True)
        proxy_action.triggered.connect(self._on_tray_proxy_changed)
        tray_menu.addAction(proxy_action)

        tray_menu.addSeparator()
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self._quit_from_tray)
        tray_menu.addAction(exit_action)

        tray_icon.setContextMenu(tray_menu)
        tray_icon.activated.connect(self._on_tray_activated)
        tray_icon.show()

        self._tray_icon = tray_icon
        self._tray_menu = tray_menu
        self._tray_profiles_menu = profiles_menu
        self._tray_header_action = header_action
        self._tray_toggle_action = toggle_action
        self._tray_hide_notifications_action = hide_notifications_action
        self._tray_autostart_action = autostart_action
        self._tray_fps_capture_action = fps_capture_action
        self._tray_fps_overlay_action = fps_overlay_action
        self._tray_proxy_action = proxy_action

        self._rebuild_tray_profiles_menu()
        self._update_tray_menu_actions()
        self._update_tray_tooltip()

    def _rebuild_tray_profiles_menu(self) -> None:
        menu = self._tray_profiles_menu
        bridge = self._ui_bridge
        if menu is None or bridge is None:
            return
        menu.clear()
        self._tray_profile_actions.clear()
        active_profile = bridge.snapshot().active_profile
        for profile_name in bridge.available_profiles():
            action = QAction(profile_name, self)
            action.setCheckable(True)
            action.setChecked(profile_name == active_profile)
            action.triggered.connect(lambda checked, name=profile_name: self._on_tray_profile_selected(name, checked))
            menu.addAction(action)
            self._tray_profile_actions[profile_name] = action

    def _tray_snapshot(self) -> UiTrayState | None:
        bridge = self._ui_bridge
        if bridge is None:
            return None
        return bridge.snapshot()

    def _refresh_tray_menu(self) -> None:
        self._rebuild_tray_profiles_menu()
        self._update_tray_menu_actions()

    def _update_tray_menu_actions(self) -> None:
        snapshot = self._tray_snapshot()
        if snapshot is None:
            return

        if self._tray_header_action is not None:
            self._tray_header_action.setText(f"{APP_NAME} · Профиль: {snapshot.active_profile}")
        if self._tray_toggle_action is not None:
            should_open = not self.isVisible() or self.isMinimized()
            self._tray_toggle_action.setText("Открыть окно" if should_open else "Скрыть окно")
        if self._tray_hide_notifications_action is not None:
            self._tray_hide_notifications_action.blockSignals(True)
            self._tray_hide_notifications_action.setChecked(snapshot.hide_notifications)
            self._tray_hide_notifications_action.blockSignals(False)
        if self._tray_autostart_action is not None:
            self._tray_autostart_action.blockSignals(True)
            self._tray_autostart_action.setChecked(snapshot.autostart_enabled)
            self._tray_autostart_action.blockSignals(False)
        if self._tray_fps_capture_action is not None:
            self._tray_fps_capture_action.blockSignals(True)
            self._tray_fps_capture_action.setChecked(snapshot.fps_capture_enabled)
            self._tray_fps_capture_action.blockSignals(False)
        if self._tray_fps_overlay_action is not None:
            self._tray_fps_overlay_action.blockSignals(True)
            self._tray_fps_overlay_action.setChecked(snapshot.fps_overlay_enabled)
            self._tray_fps_overlay_action.blockSignals(False)
        if self._tray_proxy_action is not None:
            self._tray_proxy_action.blockSignals(True)
            self._tray_proxy_action.setChecked(snapshot.telegram_proxy_enabled)
            self._tray_proxy_action.blockSignals(False)

    def _tray_tooltip_text(self) -> str:
        snapshot = self._tray_snapshot()
        if snapshot is None:
            return APP_NAME
        fps_capture = "вкл" if snapshot.fps_capture_enabled else "выкл"
        fps_overlay = "вкл" if snapshot.fps_overlay_enabled else "выкл"
        proxy = "вкл" if snapshot.telegram_proxy_enabled else "выкл"
        return "\n".join(
            [
                APP_NAME,
                f"Профиль: {snapshot.active_profile}",
                f"FPS: {fps_capture} | Overlay: {fps_overlay}",
                f"Telegram Proxy: {proxy}",
            ]
        )

    def _update_tray_tooltip(self) -> None:
        tray_icon = self._tray_icon
        if tray_icon is None:
            return
        tray_icon.setToolTip(self._tray_tooltip_text())

    def _show_from_tray(self) -> None:
        if self._settings.window_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._update_tray_menu_actions()

    def _hide_to_tray(self, notification: str | None = None) -> None:
        if not self._tray_supported():
            return
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.hide()
        self._update_tray_menu_actions()
        self._update_tray_tooltip()
        tray_icon = self._tray_icon
        if tray_icon is None:
            return
        if notification and not self._settings.hide_notifications:
            tray_icon.showMessage(APP_NAME, notification, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _toggle_main_window_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self._hide_to_tray(None)
            return
        self._show_from_tray()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_main_window_visibility()
            return
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _on_tray_profile_selected(self, profile_name: str, checked: bool) -> None:
        if not checked:
            return
        bridge = self._ui_bridge
        if bridge is None:
            return
        if not bridge.activate_profile(profile_name):
            self._show_status(f"Не удалось активировать профиль: {profile_name}")
            return
        self._show_status(f"Профиль активирован: {profile_name}")
        self._update_tray_menu_actions()

    def _on_tray_hide_notifications_changed(self, checked: bool) -> None:
        bridge = self._ui_bridge
        if bridge is None:
            return
        bridge.set_hide_notifications(bool(checked))
        self._show_status("Параметр уведомлений обновлен.")
        self._update_tray_menu_actions()

    def _on_tray_autostart_changed(self, checked: bool) -> None:
        bridge = self._ui_bridge
        if bridge is None:
            return
        success, message = bridge.set_autostart_enabled(bool(checked))
        self._show_status(message if message else "Параметр автозапуска обновлен.")
        if not success:
            self._update_tray_menu_actions()

    def _on_tray_fps_capture_changed(self, checked: bool) -> None:
        bridge = self._ui_bridge
        if bridge is None:
            return
        success = bridge.set_fps_capture_enabled(bool(checked))
        if not success and checked:
            self._show_status("Не удалось запустить FPS захват.")
        else:
            self._show_status("Параметр FPS захвата обновлен.")
        self._update_tray_menu_actions()

    def _on_tray_fps_overlay_changed(self, checked: bool) -> None:
        bridge = self._ui_bridge
        if bridge is None:
            return
        bridge.set_fps_overlay_enabled(bool(checked))
        self._show_status("Параметр FPS overlay обновлен.")
        self._update_tray_menu_actions()

    def _on_tray_proxy_changed(self, checked: bool) -> None:
        bridge = self._ui_bridge
        if bridge is None:
            return
        success = bridge.set_telegram_proxy_enabled(bool(checked))
        if not success and checked:
            self._show_status("Не удалось запустить Telegram Proxy.")
        else:
            self._show_status("Параметр Telegram Proxy обновлен.")
        self._update_tray_menu_actions()

    def _quit_from_tray(self) -> None:
        self._explicit_exit = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _restore_window_state(self) -> None:
        if self._settings.window_geometry:
            try:
                parsed = json.loads(self._settings.window_geometry)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                encoded = str(parsed.get("qt", ""))
                if encoded:
                    self.restoreGeometry(decode_qbytearray(encoded))
                width = int(parsed.get("width", 0) or 0)
                height = int(parsed.get("height", 0) or 0)
                if width > 0 and height > 0:
                    self.resize(width, height)
            else:
                self.restoreGeometry(decode_qbytearray(self._settings.window_geometry))
        if self._settings.window_maximized:
            self.showMaximized()

    def _persist_window_state(self) -> None:
        settings = self._settings_store.load_settings()
        settings.window_geometry = json.dumps(
            {
                "qt": encode_qbytearray(self.saveGeometry()),
                "width": int(self.width()),
                "height": int(self.height()),
            },
            ensure_ascii=True,
        )
        settings.window_maximized = self.isMaximized()
        self._settings_store.save_settings(settings)


