from __future__ import annotations

from collections.abc import Mapping


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


_ACCENT_MAP: dict[str, tuple[str, str, str, str, str]] = {
    "Rose":  ("#c0392b", "#e74c3c", "#922b21", "#4a1511", "#7b241c"),
    "Cyan":  ("#1a7fa8", "#2da8d8", "#155f80", "#0a2e3d", "#113349"),
    "Lime":  ("#9db35a", "#b8cc72", "#7a8e40", "#2a3518", "#394a1e"),
    "Amber": ("#c97a1e", "#e8922a", "#9a5c12", "#3d2508", "#5a3510"),
}


def app_stylesheet(settings: Mapping[str, object] | None = None) -> str:
    raw_settings = settings or {}
    font_size = _int_setting(raw_settings, "font_size", 13, 11, 18)
    table_header_font = max(11, font_size - 1)
    metric_value_font = max(14, font_size + 3)

    _accent = _ACCENT_MAP.get(str(raw_settings.get("accent_preset", "Rose")), _ACCENT_MAP["Rose"])
    accent_primary, accent_bright, accent_deep, accent_dim, accent_muted = _accent
    accent_dim_rgba = _hex_to_rgba(accent_dim, 0.20)

    return f"""
QWidget {{
    background: transparent;
    color: #d6d9de;
    font-family: "Rajdhani Medium", "Bahnschrift SemiCondensed", "Arial Narrow", "Segoe UI";
    font-size: {font_size}px;
    selection-background-color: {accent_dim};
}}
QMainWindow {{
    background: #020406;
}}
QStatusBar {{
    background: #050709;
    color: #89919f;
    border-top: 1px solid #232831;
    font-size: {max(11, font_size - 1)}px;
}}
QFrame#HudBackgroundSurface {{
    border: none;
}}
QFrame#MainFrame {{
    background: rgba(6, 8, 11, 228);
    border: 1px solid #2a2f36;
}}
QFrame#AccentLine {{
    background: {accent_primary};
    border: none;
}}
QFrame#ShellBody {{
    background: transparent;
    border: none;
}}
QFrame#SidebarFrame {{
    background: rgba(4, 6, 9, 245);
    border: none;
    border-right: 1px solid #1e2228;
}}
QFrame#ContentFrame {{
    background: rgba(5, 7, 10, 206);
    border: 1px solid #262b31;
}}
QToolButton#NavButton {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 6px 12px 6px 10px;
    text-align: left;
    color: #8a9099;
    font-size: {font_size}px;
    font-weight: 600;
}}
QToolButton#NavButton:hover {{
    background: rgba(255, 255, 255, 8);
    border-left: 3px solid {accent_muted};
    color: #c8cdd6;
}}
QToolButton#NavButton:checked {{
    background: {accent_dim_rgba};
    border-left: 3px solid {accent_bright};
    color: #ffffff;
    font-weight: 700;
}}
QFrame#NavSeparator {{
    border: none;
    background: #1a1f26;
    margin: 4px 0px;
}}
QFrame#NavProfileSlot {{
    background: rgba(255, 255, 255, 4);
    border: none;
    border-top: 1px solid #1e2228;
}}
QLabel#NavProfileIcon {{
    color: #8f98a8;
}}
QLabel#SidebarBrand {{
    color: #ffffff;
    font-size: {max(15, font_size + 3)}px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0px 4px;
}}
QLabel#SidebarBrandSub {{
    color: {accent_primary};
    font-size: {max(9, font_size - 3)}px;
    font-weight: 600;
    letter-spacing: 2px;
    padding: 0px 4px;
}}
QFrame#SidebarBrandBlock {{
    border: none;
    border-bottom: 1px solid #1e2228;
    background: transparent;
}}
QGroupBox,
QGroupBox#RefPanelBox {{
    border: 1px solid #292e35;
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
    color: #d6d9de;
}}
QLabel[role="ref_section"],
QLabel[role="section"] {{
    color: #8e96a4;
    font-size: {max(11, font_size - 1)}px;
}}
QCheckBox {{
    spacing: 8px;
    color: #d6d9de;
}}
QCheckBox::indicator {{
    width: 10px;
    height: 10px;
    border: 1px solid #3a414b;
    background: #0b1016;
}}
QCheckBox::indicator:checked {{
    background: {accent_primary};
    border: 1px solid {accent_bright};
}}
QFrame#RefSwatch {{
    background: #dfe5ef;
    border: 1px solid #666e7a;
}}
QPushButton {{
    min-height: 24px;
    background: #10141b;
    border: 1px solid #313846;
    border-radius: 0px;
    padding: 1px 8px;
    font-size: {font_size}px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: #1a2029;
    border: 1px solid #5d6877;
}}
QPushButton:pressed {{
    background: #0d1117;
}}
QPushButton#LinkOpenButton,
QPushButton#LinkCopyButton {{
    min-width: 108px;
}}
QPushButton#PrimaryButton {{
    background: {accent_primary};
    border: 1px solid {accent_bright};
    color: #ffffff;
    font-weight: 700;
    min-height: 26px;
    padding: 2px 12px;
}}
QPushButton#PrimaryButton:hover {{
    background: {accent_bright};
    border: 1px solid {accent_bright};
}}
QPushButton#PrimaryButton:pressed {{
    background: {accent_deep};
}}
QMenu {{
    background: #0c1016;
    border: 1px solid #2f3742;
    color: #d6d9de;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 20px 5px 10px;
    background: transparent;
}}
QMenu::item:selected {{
    background: #1d2430;
    color: #eef4ff;
}}
QMenu::separator {{
    height: 1px;
    margin: 5px 2px;
    background: #2a323d;
}}
QToolTip {{
    background: #0c1016;
    color: #d6d9de;
    border: 1px solid #2f3742;
    padding: 4px 6px;
}}
QComboBox {{
    min-height: 22px;
    background: #0d1117;
    border: 1px solid #313846;
    padding: 0 6px;
}}
QComboBox::drop-down {{
    width: 24px;
    border-left: 1px solid #313846;
    background: #131923;
}}
QComboBox QAbstractItemView {{
    background: #0d1117;
    border: 1px solid #404957;
    selection-background-color: {accent_dim};
}}
QLineEdit {{
    min-height: 22px;
    background: #0d1117;
    border: 1px solid #313846;
    padding: 0 6px;
}}
QLineEdit:focus {{
    border: 1px solid {accent_primary};
}}
QSlider::groove:horizontal {{
    border: 1px solid #323844;
    height: 4px;
    background: #0f141b;
}}
QSlider::sub-page:horizontal {{
    background: {accent_primary};
}}
QSlider::add-page:horizontal {{
    background: #0f141b;
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
    border: 1px solid #2d333d;
    border-radius: 0;
}}
QLabel[role="metric_title"] {{
    color: #9aa2b1;
    font-size: {max(11, font_size - 1)}px;
    font-weight: 600;
}}
QLabel[role="metric_value"] {{
    color: #dde4ef;
    font-size: {metric_value_font}px;
    font-weight: 700;
}}
QLabel[role="metric_note"],
QLabel[role="security_desc"] {{
    color: #8d95a4;
    font-size: {max(10, font_size - 2)}px;
}}
QLabel[role="security_title"] {{
    color: #dde4ef;
    font-size: {max(13, font_size + 1)}px;
    font-weight: 700;
}}
QLabel[role="security_url"] {{
    color: #6ebad5;
    font-size: {max(10, font_size - 2)}px;
}}
QWidget#HistoryChart {{
    border: 1px solid #2f3640;
    background: #08111a;
}}
QTableWidget {{
    background: #0d1117;
    alternate-background-color: #101621;
    border: 1px solid #313846;
    gridline-color: #222a34;
    selection-background-color: {accent_dim};
}}
QHeaderView::section {{
    background: #121922;
    color: #d6d9de;
    border: 1px solid #313846;
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
    background: #0b1016;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #2f3643;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #46505f;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QFrame#AiSessionsPanel,
QFrame#AiChatPanel,
QFrame#AiControlsPanel,
QFrame#AiComposer {{
    background: rgba(8, 11, 15, 220);
    border: 1px solid #2d333d;
}}
QListWidget#AiSessionsList {{
    background: #0d1117;
    border: 1px solid #313846;
    outline: 0;
}}
QListWidget#AiSessionsList::item {{
    padding: 6px 8px;
}}
QListWidget#AiSessionsList::item:selected {{
    background: {accent_dim};
}}
QScrollArea#AiMessagesScroll {{
    border: 1px solid #313846;
    background: #0d1117;
}}
QFrame#AiMessageBubbleUser {{
    background: {accent_dim};
    border: 1px solid {accent_muted};
}}
QFrame#AiMessageBubbleAssistant {{
    background: #131a24;
    border: 1px solid #334150;
}}
QPlainTextEdit#AiInput,
QPlainTextEdit#AiSystemPrompt {{
    background: #0d1117;
    border: 1px solid #313846;
    color: #d6d9de;
    selection-background-color: {accent_dim};
}}
"""
