from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _int_setting(settings: Mapping[str, object], key: str, default: int, min_value: int, max_value: int) -> int:
    raw = settings.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


@dataclass(frozen=True)
class ThemeSpec:
    # Backgrounds (darkest → lightest)
    bg0: str        # QMainWindow
    bg1: str        # MainFrame / sidebar
    bg2: str        # GroupBox / panels
    bg3: str        # inputs, tables
    bg4: str        # hover states
    # Borders
    border0: str    # subtle (sidebar lines)
    border1: str    # normal (inputs, panels)
    border2: str    # active/hover
    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    # Accents
    accent_primary: str
    accent_bright: str
    accent_deep: str
    accent_dim: str
    accent_muted: str
    # Optional background image filename (relative to assets/)
    bg_image: str = ""
    # Panel transparency (0–255). Lower = more transparent, background shows through.
    main_frame_alpha: int = 228    # QFrame#MainFrame
    sidebar_alpha: int = 245       # QFrame#SidebarFrame
    content_alpha: int = 206       # QFrame#ContentFrame
    # Corner radius applied to buttons, inputs, and panels. 0 keeps the classic sharp look.
    border_radius: int = 0
    # Enables drop-shadow glow on RefPanelBox (cyber-anime aesthetic).
    panel_shadow: bool = False


_THEME_MAP: dict[str, ThemeSpec] = {
    "Dark": ThemeSpec(
        bg0="#020406", bg1="#050709", bg2="#060a0e", bg3="#0d1117", bg4="#1a2029",
        border0="#1e2228", border1="#2a2f36", border2="#3a4452",
        text_primary="#d6d9de", text_secondary="#8a9099", text_muted="#525d6e",
        accent_primary="#c0392b", accent_bright="#e74c3c", accent_deep="#922b21",
        accent_dim="#4a1511", accent_muted="#7b241c",
        bg_image="background_ref.png",
    ),
    "Ocean": ThemeSpec(
        bg0="#02060b", bg1="#020810", bg2="#030c14", bg3="#061525", bg4="#0c2135",
        border0="#0d1f2e", border1="#143248", border2="#1e4a6a",
        text_primary="#ccd8e8", text_secondary="#7a9db8", text_muted="#3d5c74",
        accent_primary="#1a7fa8", accent_bright="#2da8d8", accent_deep="#155f80",
        accent_dim="#0a2e3d", accent_muted="#113349",
        bg_image="bg_ocean.png",
        main_frame_alpha=200, sidebar_alpha=215, content_alpha=180,
    ),
    "Synthwave": ThemeSpec(
        bg0="#060208", bg1="#0a0310", bg2="#0d0416", bg3="#130820", bg4="#1e1030",
        border0="#1a0c28", border1="#2a1040", border2="#3e1a5a",
        text_primary="#e0d0f0", text_secondary="#9978b8", text_muted="#4e2e6e",
        accent_primary="#8b27c2", accent_bright="#a93de8", accent_deep="#6a1a9a",
        accent_dim="#2e0c44", accent_muted="#4a1668",
        bg_image="bg_synthwave.png",
        main_frame_alpha=200, sidebar_alpha=215, content_alpha=180,
    ),
    "D.Va": ThemeSpec(
        bg0="#080408", bg1="#100810", bg2="#140a14", bg3="#1a0e1a", bg4="#261626",
        border0="#2a1028", border1="#3d1840", border2="#5a2060",
        text_primary="#f0d8f0", text_secondary="#c080c0", text_muted="#6a3870",
        accent_primary="#e91e63", accent_bright="#f06292", accent_deep="#c2185b",
        accent_dim="#4a0a28", accent_muted="#7a1040",
        bg_image="bg_dva.png",
        main_frame_alpha=155, sidebar_alpha=170, content_alpha=140,
    ),
    "Neon Anime": ThemeSpec(
        bg0="#07030f", bg1="#0c0518", bg2="#110827", bg3="#190d38", bg4="#241452",
        border0="#1e0c3a", border1="#3a1466", border2="#6a28a8",
        text_primary="#f0e8ff", text_secondary="#b89be0", text_muted="#6a4a8a",
        accent_primary="#ff2e88", accent_bright="#00eaff", accent_deep="#c8106e",
        accent_dim="#3a0a28", accent_muted="#8b1858",
        bg_image="bg_neon_anime.png",
        main_frame_alpha=180, sidebar_alpha=200, content_alpha=160,
        border_radius=12, panel_shadow=True,
    ),
}

# Keep backward compat for code that reads accent_preset names
_LEGACY_ACCENT_MAP: dict[str, str] = {
    "Rose": "Dark",
    "Cyan": "Ocean",
    "Lime": "Dark",
    "Amber": "Dark",
}

VISUAL_THEMES: list[str] = list(_THEME_MAP)


def get_theme(name: str) -> ThemeSpec:
    """Return ThemeSpec for *name*, falling back to 'Dark'."""
    # Migrate legacy accent preset names
    resolved = _LEGACY_ACCENT_MAP.get(name, name)
    return _THEME_MAP.get(resolved, _THEME_MAP["Dark"])


def app_stylesheet(settings: Mapping[str, object] | None = None) -> str:
    raw_settings = settings or {}
    font_size = _int_setting(raw_settings, "font_size", 13, 11, 18)
    table_header_font = max(11, font_size - 1)
    metric_value_font = max(14, font_size + 3)

    # Support both new "visual_theme" and legacy "accent_preset"
    theme_name = str(raw_settings.get("visual_theme") or raw_settings.get("accent_preset") or "Dark")
    t = get_theme(theme_name)

    accent_dim_rgba = _hex_to_rgba(t.accent_dim, 0.20)
    main_frame_bg = _hex_to_rgba(t.bg1, t.main_frame_alpha / 255)
    sidebar_bg = _hex_to_rgba(t.bg0, t.sidebar_alpha / 255)
    content_bg = _hex_to_rgba(t.bg1, t.content_alpha / 255)
    radius = max(0, int(t.border_radius))
    radius_small = max(0, min(radius, 6)) if radius else 4

    return f"""
QWidget {{
    background: transparent;
    color: {t.text_primary};
    font-family: "Rajdhani Medium", "Bahnschrift SemiCondensed", "Arial Narrow", "Segoe UI";
    font-size: {font_size}px;
    selection-background-color: {t.accent_dim};
}}
QMainWindow {{
    background: {t.bg0};
}}
QStatusBar {{
    background: {t.bg1};
    color: {t.text_secondary};
    border-top: 1px solid {t.border0};
    font-size: {max(11, font_size - 1)}px;
}}
QFrame#HudBackgroundSurface {{
    border: none;
}}
QFrame#MainFrame {{
    background: {main_frame_bg};
    border: 1px solid {t.border1};
}}
QFrame#AccentLine {{
    background: {t.accent_primary};
    border: none;
}}
QFrame#ShellBody {{
    background: transparent;
    border: none;
}}
QFrame#SidebarFrame {{
    background: {sidebar_bg};
    border: none;
    border-right: 1px solid {t.border0};
}}
QFrame#ContentFrame {{
    background: {content_bg};
    border: 1px solid {t.border1};
}}
QToolButton#NavButton {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 6px 12px 6px 10px;
    text-align: left;
    color: {t.text_secondary};
    font-size: {font_size}px;
    font-weight: 600;
}}
QToolButton#NavButton:hover {{
    background: rgba(255, 255, 255, 8);
    border-left: 3px solid {t.accent_muted};
    color: #c8cdd6;
}}
QToolButton#NavButton:checked {{
    background: {accent_dim_rgba};
    border-left: 3px solid {t.accent_bright};
    color: #ffffff;
    font-weight: 700;
}}
QFrame#NavSeparator {{
    border: none;
    background: {t.border0};
    margin: 4px 0px;
}}
QFrame#NavProfileSlot {{
    background: rgba(255, 255, 255, 4);
    border: none;
    border-top: 1px solid {t.border0};
}}
QLabel#NavProfileIcon {{
    color: {t.text_secondary};
}}
QLabel#SidebarBrand {{
    color: #ffffff;
    font-size: {max(15, font_size + 3)}px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0px 4px;
}}
QLabel#SidebarBrandSub {{
    color: {t.accent_primary};
    font-size: {max(9, font_size - 3)}px;
    font-weight: 600;
    letter-spacing: 2px;
    padding: 0px 4px;
}}
QFrame#SidebarBrandBlock {{
    border: none;
    border-bottom: 1px solid {t.border0};
    background: transparent;
}}
QGroupBox,
QGroupBox#RefPanelBox {{
    border: 1px solid {t.border1};
    border-radius: {radius}px;
    margin-top: 14px;
    padding: 8px 10px 10px 10px;
    background: rgba(6, 9, 12, 216);
    font-size: {max(13, font_size + 1)}px;
    font-weight: 600;
}}
QGroupBox::title,
QGroupBox#RefPanelBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {t.text_primary};
}}
QLabel[role="ref_section"],
QLabel[role="section"] {{
    color: {t.text_secondary};
    font-size: {max(11, font_size - 1)}px;
}}
QCheckBox {{
    spacing: 8px;
    color: {t.text_primary};
}}
QCheckBox::indicator {{
    width: 10px;
    height: 10px;
    border: 1px solid {t.border2};
    background: {t.bg3};
}}
QCheckBox::indicator:checked {{
    background: {t.accent_primary};
    border: 1px solid {t.accent_bright};
}}
QFrame#RefSwatch {{
    background: #dfe5ef;
    border: 1px solid #666e7a;
}}
QPushButton {{
    min-height: 24px;
    background: {t.bg3};
    border: 1px solid {t.border2};
    border-radius: {radius}px;
    padding: 1px 8px;
    font-size: {font_size}px;
    font-weight: 600;
    color: {t.text_primary};
}}
QPushButton:hover {{
    background: {t.bg4};
    border: 1px solid {t.border2};
}}
QPushButton:pressed {{
    background: {t.bg1};
}}
QPushButton#LinkOpenButton,
QPushButton#LinkCopyButton {{
    min-width: 108px;
}}
QPushButton#PrimaryButton {{
    background: {t.accent_primary};
    border: 1px solid {t.accent_bright};
    border-radius: {radius}px;
    color: #ffffff;
    font-weight: 700;
    min-height: 26px;
    padding: 2px 12px;
}}
QPushButton#PrimaryButton:hover {{
    background: {t.accent_bright};
    border: 1px solid {t.accent_bright};
}}
QPushButton#PrimaryButton:pressed {{
    background: {t.accent_deep};
}}
QMenu {{
    background: {t.bg1};
    border: 1px solid {t.border2};
    color: {t.text_primary};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 20px 5px 10px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {t.bg4};
    color: #eef4ff;
}}
QMenu::separator {{
    height: 1px;
    margin: 5px 2px;
    background: {t.border1};
}}
QToolTip {{
    background: {t.bg1};
    color: {t.text_primary};
    border: 1px solid {t.border2};
    padding: 4px 6px;
}}
QComboBox {{
    min-height: 22px;
    background: {t.bg3};
    border: 1px solid {t.border1};
    border-radius: {radius}px;
    padding: 0 6px;
    color: {t.text_primary};
}}
QComboBox::drop-down {{
    width: 24px;
    border-left: 1px solid {t.border1};
    background: {t.bg4};
}}
QComboBox QAbstractItemView {{
    background: {t.bg3};
    border: 1px solid {t.border2};
    selection-background-color: {t.accent_dim};
    color: {t.text_primary};
}}
QLineEdit {{
    min-height: 22px;
    background: {t.bg3};
    border: 1px solid {t.border1};
    border-radius: {radius}px;
    padding: 0 6px;
    color: {t.text_primary};
}}
QLineEdit:focus {{
    border: 1px solid {t.accent_primary};
}}
QSlider::groove:horizontal {{
    border: 1px solid {t.border1};
    height: 4px;
    background: {t.bg3};
}}
QSlider::sub-page:horizontal {{
    background: {t.accent_primary};
}}
QSlider::add-page:horizontal {{
    background: {t.bg3};
}}
QSlider::handle:horizontal {{
    background: #d6dde8;
    border: 1px solid #f0f4fa;
    width: 9px;
    margin: -5px 0;
}}
QFrame#MonitorCard,
QFrame#SecurityLinkCard {{
    background: rgba(8, 11, 15, 220);
    border: 1px solid {t.border1};
    border-radius: {radius}px;
}}
QLabel[role="metric_title"] {{
    color: {t.text_secondary};
    font-size: {max(11, font_size - 1)}px;
    font-weight: 600;
}}
QLabel[role="metric_value"] {{
    color: {t.text_primary};
    font-size: {metric_value_font}px;
    font-weight: 700;
}}
QLabel[role="metric_note"],
QLabel[role="security_desc"] {{
    color: {t.text_muted};
    font-size: {max(10, font_size - 2)}px;
}}
QLabel[role="security_title"] {{
    color: {t.text_primary};
    font-size: {max(13, font_size + 1)}px;
    font-weight: 700;
}}
QLabel[role="security_url"] {{
    color: {t.accent_bright};
    font-size: {max(10, font_size - 2)}px;
}}
QWidget#HistoryChart {{
    border: 1px solid {t.border1};
    background: {t.bg1};
}}
QTableWidget {{
    background: {t.bg3};
    alternate-background-color: {t.bg4};
    border: 1px solid {t.border1};
    border-radius: {radius}px;
    gridline-color: {t.border0};
    selection-background-color: {t.accent_dim};
    color: {t.text_primary};
}}
QHeaderView::section {{
    background: {t.bg1};
    color: {t.text_primary};
    border: 1px solid {t.border1};
    padding: 2px 5px;
    font-size: {table_header_font}px;
}}
QTableWidget::item:selected {{
    color: #e6ebf3;
}}
QScrollArea {{
    border: none;
}}
QScrollBar:vertical {{
    background: {t.bg1};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t.border1};
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.border2};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QFrame#AiSessionsPanel,
QFrame#AiChatPanel,
QFrame#AiControlsPanel {{
    background: rgba(8, 11, 15, 220);
    border: 1px solid {t.border1};
    border-radius: {radius}px;
}}
QFrame#AiSessionsHeader {{
    background: rgba(4, 6, 9, 180);
    border: none;
    border-bottom: 1px solid {t.border0};
}}
QFrame#AiSessionsDivider {{
    border: none;
    background: {t.border0};
    max-height: 1px;
}}
QToolButton#AiSessionActionButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    color: {t.text_muted};
    font-size: 15px;
    font-weight: 700;
    min-width: 24px;
    min-height: 24px;
    padding: 0px 2px;
}}
QToolButton#AiSessionActionButton:hover {{
    background: rgba(255, 255, 255, 10);
    color: {t.text_primary};
}}
QListWidget#AiSessionsList {{
    background: transparent;
    border: none;
    outline: 0;
    color: {t.text_primary};
    padding: 4px 0px;
}}
QListWidget#AiSessionsList::item {{
    padding: 8px 14px;
    border-left: 3px solid transparent;
    color: {t.text_secondary};
}}
QListWidget#AiSessionsList::item:hover {{
    background: rgba(255, 255, 255, 6);
    color: {t.text_primary};
    border-left: 3px solid {t.accent_muted};
}}
QListWidget#AiSessionsList::item:selected {{
    background: {t.accent_dim};
    color: {t.text_primary};
    border-left: 3px solid {t.accent_primary};
}}
QToolButton#AiSettingsToggle,
QToolButton#AiSysPromptToggle {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {t.border0};
    color: {t.text_secondary};
    font-size: {font_size}px;
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    min-width: 120px;
}}
QToolButton#AiSettingsToggle:hover,
QToolButton#AiSysPromptToggle:hover {{
    color: {t.text_primary};
    background: rgba(255, 255, 255, 4);
}}
QToolButton#AiSettingsToggle:checked,
QToolButton#AiSysPromptToggle:checked {{
    color: {t.accent_bright};
}}
QScrollArea#AiMessagesScroll {{
    border: none;
    background: transparent;
}}
QScrollArea#AiMessagesScroll > QWidget > QWidget {{
    background: {t.bg3};
}}
QFrame#AiMessageBubbleUser {{
    background: {t.accent_dim};
    border: 1px solid {t.accent_muted};
    border-radius: 12px;
    border-bottom-right-radius: 3px;
}}
QFrame#AiMessageBubbleAssistant {{
    background: {t.bg4};
    border: 1px solid {t.border1};
    border-radius: 12px;
    border-bottom-left-radius: 3px;
}}
QLabel#AiMessageDotUser {{
    color: {t.accent_primary};
    font-size: 8px;
}}
QLabel#AiMessageDotAssistant {{
    color: {t.text_muted};
    font-size: 8px;
}}
QFrame#AiComposer {{
    background: rgba(8, 11, 15, 220);
    border: 1px solid {t.border1};
    border-top: 1px solid {t.border2};
}}
QPlainTextEdit#AiInput {{
    background: {t.bg3};
    border: 1px solid transparent;
    border-radius: 4px;
    color: {t.text_primary};
    selection-background-color: {t.accent_dim};
    padding: 4px 6px;
}}
QPlainTextEdit#AiInput:focus {{
    border: 1px solid {t.accent_muted};
}}
QPlainTextEdit#AiSystemPrompt {{
    background: {t.bg3};
    border: 1px solid {t.border1};
    border-radius: 4px;
    color: {t.text_primary};
    selection-background-color: {t.accent_dim};
}}
QPushButton#AiSendButton {{
    background: {t.accent_primary};
    border: 1px solid {t.accent_bright};
    border-radius: 4px;
    color: #ffffff;
    font-weight: 700;
    min-height: 28px;
    padding: 2px 16px;
}}
QPushButton#AiSendButton:hover {{
    background: {t.accent_bright};
}}
QPushButton#AiSendButton:pressed {{
    background: {t.accent_deep};
}}
QPushButton#AiSendButton:disabled {{
    background: {t.bg4};
    border: 1px solid {t.border1};
    color: {t.text_muted};
}}
QPushButton#AiStopButton {{
    background: transparent;
    border: 1px solid {t.border2};
    border-radius: 4px;
    color: {t.text_secondary};
    min-height: 28px;
    padding: 2px 12px;
}}
QPushButton#AiStopButton:hover {{
    border: 1px solid {t.accent_muted};
    color: {t.accent_bright};
}}
QPushButton#AiStopButton:enabled {{
    border: 1px solid {t.accent_muted};
    color: {t.accent_primary};
}}
QTabWidget#AiTaskTabs::pane {{
    border: none;
    border-top: 1px solid {t.border1};
    background: transparent;
}}
QTabWidget#AiTaskTabs > QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {t.text_muted};
    padding: 6px 14px;
    font-size: {font_size}px;
    font-weight: 600;
    min-width: 80px;
}}
QTabWidget#AiTaskTabs > QTabBar::tab:hover {{
    color: {t.text_secondary};
    border-bottom: 2px solid {t.border2};
}}
QTabWidget#AiTaskTabs > QTabBar::tab:selected {{
    color: {t.text_primary};
    border-bottom: 2px solid {t.accent_primary};
}}
"""
