from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from lolilend.ai_metadata import TEXT_GENERATION


LAUNCH_MODES = {"Стандартный", "Быстрый", "Тихий"}
ACCENT_PRESETS = {"Rose", "Cyan", "Lime", "Amber"}
ACTIVE_AI_OPTIONS = {"AI LOLILEND", "Cloudflare Workers AI"}
AI_PROTOCOL_OPTIONS = {"openai_compatible", "workers_ai_run"}
DEFAULT_GITHUB_REPO = "LoliLend/LoliLend"
DEFAULT_RELEASE_ASSET_PATTERN = "LoliLend-Setup-*.exe"


@dataclass(slots=True)
class GeneralSettings:
    brightness: int = 72
    show_hints: bool = True
    smooth_animation: bool = True
    launch_mode: str = "Стандартный"
    protected_mode: bool = True
    hide_notifications: bool = False
    minimize_to_tray: bool = True
    close_to_tray: bool = True
    autostart_windows: bool = False
    accent_preset: str = "Rose"
    interface_scale: int = 100
    font_size: int = 13
    panel_opacity: int = 86
    sidebar_width: int = 102
    compact_mode: bool = False
    show_status_bar: bool = False
    active_ai: str = "AI LOLILEND"
    ai_protocol: str = "openai_compatible"
    ai_model: str = "@cf/meta/llama-3.2-3b-instruct"
    ai_active_task: str = TEXT_GENERATION
    ai_popular_only: bool = False
    ai_system_prompt: str = ""
    ai_temperature: float = 0.7
    ai_max_tokens: int = 1024
    ai_streaming_enabled: bool = True
    ai_last_session_id: str = ""
    window_geometry: str = ""
    window_maximized: bool = False
    main_splitter_state: str = ""
    general_splitter_state: str = ""
    performance_splitter_state: str = ""
    network_splitter_state: str = ""
    analytics_splitter_state: str = ""
    security_splitter_state: str = ""
    ai_splitter_state: str = ""
    fps_overlay_enabled: bool = False
    fps_capture_enabled: bool = False
    fps_overlay_hotkey: str = "Ctrl+Shift+F10"
    fps_overlay_position: str = "top_left"
    fps_overlay_opacity: int = 88
    fps_overlay_scale: int = 100
    github_repo: str = DEFAULT_GITHUB_REPO
    auto_update_enabled: bool = True
    release_asset_pattern: str = DEFAULT_RELEASE_ASSET_PATTERN
    launcher_custom_image_path: str = ""
    profile_name: str = "Стандарт"


BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "Стандарт": {
        "brightness": 72,
        "show_hints": True,
        "smooth_animation": True,
        "launch_mode": "Стандартный",
        "protected_mode": True,
        "hide_notifications": False,
        "minimize_to_tray": True,
        "close_to_tray": True,
        "autostart_windows": False,
        "accent_preset": "Rose",
        "interface_scale": 100,
        "font_size": 13,
        "panel_opacity": 86,
        "sidebar_width": 102,
        "compact_mode": False,
        "show_status_bar": False,
        "active_ai": "AI LOLILEND",
        "ai_protocol": "openai_compatible",
        "ai_model": "@cf/meta/llama-3.2-3b-instruct",
        "ai_active_task": TEXT_GENERATION,
        "ai_popular_only": False,
        "ai_system_prompt": "",
        "ai_temperature": 0.7,
        "ai_max_tokens": 1024,
        "ai_streaming_enabled": True,
        "ai_last_session_id": "",
        "fps_overlay_enabled": False,
        "fps_capture_enabled": False,
        "fps_overlay_hotkey": "Ctrl+Shift+F10",
        "fps_overlay_position": "top_left",
        "fps_overlay_opacity": 88,
        "fps_overlay_scale": 100,
        "github_repo": DEFAULT_GITHUB_REPO,
        "auto_update_enabled": True,
        "release_asset_pattern": DEFAULT_RELEASE_ASSET_PATTERN,
        "launcher_custom_image_path": "",
    },
    "Работа": {
        "brightness": 62,
        "show_hints": False,
        "smooth_animation": False,
        "launch_mode": "Быстрый",
        "protected_mode": True,
        "hide_notifications": True,
        "minimize_to_tray": True,
        "close_to_tray": True,
        "autostart_windows": True,
        "accent_preset": "Cyan",
        "interface_scale": 96,
        "font_size": 12,
        "panel_opacity": 80,
        "sidebar_width": 94,
        "compact_mode": True,
        "show_status_bar": False,
        "active_ai": "AI LOLILEND",
        "ai_protocol": "openai_compatible",
        "ai_model": "@cf/meta/llama-3.2-3b-instruct",
        "ai_active_task": TEXT_GENERATION,
        "ai_popular_only": False,
        "ai_system_prompt": "",
        "ai_temperature": 0.7,
        "ai_max_tokens": 1024,
        "ai_streaming_enabled": True,
        "ai_last_session_id": "",
        "fps_overlay_enabled": False,
        "fps_capture_enabled": False,
        "fps_overlay_hotkey": "Ctrl+Shift+F10",
        "fps_overlay_position": "top_left",
        "fps_overlay_opacity": 84,
        "fps_overlay_scale": 96,
        "github_repo": DEFAULT_GITHUB_REPO,
        "auto_update_enabled": True,
        "release_asset_pattern": DEFAULT_RELEASE_ASSET_PATTERN,
        "launcher_custom_image_path": "",
    },
    "Тихий режим": {
        "brightness": 50,
        "show_hints": False,
        "smooth_animation": False,
        "launch_mode": "Тихий",
        "protected_mode": True,
        "hide_notifications": True,
        "minimize_to_tray": True,
        "close_to_tray": True,
        "autostart_windows": False,
        "accent_preset": "Amber",
        "interface_scale": 92,
        "font_size": 12,
        "panel_opacity": 74,
        "sidebar_width": 90,
        "compact_mode": True,
        "show_status_bar": False,
        "active_ai": "AI LOLILEND",
        "ai_protocol": "openai_compatible",
        "ai_model": "@cf/meta/llama-3.2-3b-instruct",
        "ai_active_task": TEXT_GENERATION,
        "ai_popular_only": False,
        "ai_system_prompt": "",
        "ai_temperature": 0.7,
        "ai_max_tokens": 1024,
        "ai_streaming_enabled": True,
        "ai_last_session_id": "",
        "fps_overlay_enabled": False,
        "fps_capture_enabled": False,
        "fps_overlay_hotkey": "Ctrl+Shift+F10",
        "fps_overlay_position": "top_left",
        "fps_overlay_opacity": 80,
        "fps_overlay_scale": 92,
        "github_repo": DEFAULT_GITHUB_REPO,
        "auto_update_enabled": True,
        "release_asset_pattern": DEFAULT_RELEASE_ASSET_PATTERN,
        "launcher_custom_image_path": "",
    },
}


class GeneralSettingsStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        base = Path(os.getenv("APPDATA", Path.home()))
        self.base_dir = base / app_name
        self.temp_dir = self.base_dir / "temp"
        self.export_dir = self.base_dir / "exports"
        self.launcher_dir = self.base_dir / "launcher"
        self._config_path = self.base_dir / "general_config.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.launcher_dir.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> GeneralSettings:
        raw = self._load_raw()
        settings_raw = raw.get("settings", {})
        settings = GeneralSettings()
        settings.brightness = self._clamp_int(settings_raw.get("brightness", settings.brightness), 0, 100)
        settings.show_hints = bool(settings_raw.get("show_hints", settings.show_hints))
        settings.smooth_animation = bool(settings_raw.get("smooth_animation", settings.smooth_animation))
        settings.launch_mode = str(settings_raw.get("launch_mode", settings.launch_mode))
        if settings.launch_mode not in LAUNCH_MODES:
            settings.launch_mode = "Стандартный"
        settings.protected_mode = bool(settings_raw.get("protected_mode", settings.protected_mode))
        settings.hide_notifications = bool(settings_raw.get("hide_notifications", settings.hide_notifications))
        settings.minimize_to_tray = bool(settings_raw.get("minimize_to_tray", settings.minimize_to_tray))
        settings.close_to_tray = bool(settings_raw.get("close_to_tray", settings.close_to_tray))
        settings.autostart_windows = bool(settings_raw.get("autostart_windows", settings.autostart_windows))
        settings.accent_preset = str(settings_raw.get("accent_preset", settings.accent_preset))
        if settings.accent_preset not in ACCENT_PRESETS:
            settings.accent_preset = "Rose"
        settings.interface_scale = self._clamp_int(settings_raw.get("interface_scale", settings.interface_scale), 85, 130)
        settings.font_size = self._clamp_int(settings_raw.get("font_size", settings.font_size), 11, 18)
        settings.panel_opacity = self._clamp_int(settings_raw.get("panel_opacity", settings.panel_opacity), 60, 100)
        settings.sidebar_width = self._clamp_int(settings_raw.get("sidebar_width", settings.sidebar_width), 82, 160)
        settings.compact_mode = bool(settings_raw.get("compact_mode", settings.compact_mode))
        settings.show_status_bar = bool(settings_raw.get("show_status_bar", settings.show_status_bar))
        settings.active_ai = str(settings_raw.get("active_ai", settings.active_ai))
        if settings.active_ai not in ACTIVE_AI_OPTIONS:
            settings.active_ai = "AI LOLILEND"
        settings.ai_protocol = str(settings_raw.get("ai_protocol", settings.ai_protocol))
        if settings.ai_protocol not in AI_PROTOCOL_OPTIONS:
            settings.ai_protocol = "openai_compatible"
        settings.ai_model = str(settings_raw.get("ai_model", settings.ai_model)).strip() or "@cf/meta/llama-3.2-3b-instruct"
        settings.ai_active_task = str(settings_raw.get("ai_active_task", settings.ai_active_task)).strip() or TEXT_GENERATION
        if settings.ai_active_task not in {
            "text_generation",
            "text_embeddings",
            "text_classification",
            "text_to_image",
            "text_to_speech",
            "automatic_speech_recognition",
            "image_to_text",
            "image_classification",
            "translation",
            "summarization",
        }:
            settings.ai_active_task = TEXT_GENERATION
        settings.ai_popular_only = bool(settings_raw.get("ai_popular_only", settings.ai_popular_only))
        settings.ai_system_prompt = str(settings_raw.get("ai_system_prompt", settings.ai_system_prompt))
        settings.ai_temperature = self._clamp_float(settings_raw.get("ai_temperature", settings.ai_temperature), 0.0, 2.0)
        settings.ai_max_tokens = self._clamp_int(settings_raw.get("ai_max_tokens", settings.ai_max_tokens), 64, 8192)
        settings.ai_streaming_enabled = bool(settings_raw.get("ai_streaming_enabled", settings.ai_streaming_enabled))
        settings.ai_last_session_id = str(settings_raw.get("ai_last_session_id", settings.ai_last_session_id))
        settings.window_geometry = str(settings_raw.get("window_geometry", settings.window_geometry))
        settings.window_maximized = bool(settings_raw.get("window_maximized", settings.window_maximized))
        settings.main_splitter_state = str(settings_raw.get("main_splitter_state", settings.main_splitter_state))
        settings.general_splitter_state = str(settings_raw.get("general_splitter_state", settings.general_splitter_state))
        settings.performance_splitter_state = str(settings_raw.get("performance_splitter_state", settings.performance_splitter_state))
        settings.network_splitter_state = str(settings_raw.get("network_splitter_state", settings.network_splitter_state))
        settings.analytics_splitter_state = str(settings_raw.get("analytics_splitter_state", settings.analytics_splitter_state))
        settings.security_splitter_state = str(settings_raw.get("security_splitter_state", settings.security_splitter_state))
        settings.ai_splitter_state = str(settings_raw.get("ai_splitter_state", settings.ai_splitter_state))
        settings.fps_overlay_enabled = bool(settings_raw.get("fps_overlay_enabled", settings.fps_overlay_enabled))
        settings.fps_capture_enabled = bool(settings_raw.get("fps_capture_enabled", settings.fps_capture_enabled))
        settings.fps_overlay_hotkey = str(settings_raw.get("fps_overlay_hotkey", settings.fps_overlay_hotkey)).strip() or "Ctrl+Shift+F10"
        settings.fps_overlay_position = str(settings_raw.get("fps_overlay_position", settings.fps_overlay_position))
        if settings.fps_overlay_position not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            settings.fps_overlay_position = "top_left"
        settings.fps_overlay_opacity = self._clamp_int(settings_raw.get("fps_overlay_opacity", settings.fps_overlay_opacity), 35, 100)
        settings.fps_overlay_scale = self._clamp_int(settings_raw.get("fps_overlay_scale", settings.fps_overlay_scale), 80, 140)
        settings.github_repo = self._sanitize_github_repo(str(settings_raw.get("github_repo", settings.github_repo)))
        settings.auto_update_enabled = bool(settings_raw.get("auto_update_enabled", settings.auto_update_enabled))
        settings.release_asset_pattern = str(settings_raw.get("release_asset_pattern", settings.release_asset_pattern)).strip() or DEFAULT_RELEASE_ASSET_PATTERN
        settings.launcher_custom_image_path = str(settings_raw.get("launcher_custom_image_path", settings.launcher_custom_image_path))
        settings.profile_name = str(settings_raw.get("profile_name", settings.profile_name))
        return settings

    def save_settings(self, settings: GeneralSettings) -> None:
        raw = self._load_raw()
        raw["settings"] = asdict(settings)
        self._write_raw(raw)

    def load_profiles(self, profile_names: list[str]) -> dict[str, dict[str, Any]]:
        raw = self._load_raw()
        user_profiles = raw.get("profiles", {})
        profiles: dict[str, dict[str, Any]] = {}
        for name in profile_names:
            base = dict(BUILTIN_PROFILES.get(name, BUILTIN_PROFILES["Стандарт"]))
            override = user_profiles.get(name, {})
            if isinstance(override, dict):
                base.update(override)
            profiles[name] = self._sanitize_profile_values(base)
        return profiles

    def save_profile(self, name: str, values: dict[str, Any]) -> None:
        raw = self._load_raw()
        profiles = raw.setdefault("profiles", {})
        profiles[name] = self._sanitize_profile_values(values)
        self._write_raw(raw)

    def export_profile(self, name: str, values: dict[str, Any]) -> Path:
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "profile"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = self.export_dir / f"{safe_name}_{timestamp}.json"
        payload = {
            "profile": name,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "settings": self._sanitize_profile_values(values),
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    def clear_temp_data(self) -> int:
        deleted = 0
        if not self.temp_dir.exists():
            return deleted
        for path in self.temp_dir.iterdir():
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                    deleted += 1
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    deleted += 1
            except OSError:
                continue
        return deleted

    def is_autostart_enabled(self) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg
        except OSError:
            return False

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, "LoliLend")
                return bool(value)
        except OSError:
            return False

    def set_autostart(self, enabled: bool) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Автозапуск поддерживается только на Windows."

        try:
            import winreg
        except OSError:
            return False, "Модуль winreg недоступен."

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, "LoliLend", 0, winreg.REG_SZ, self._autostart_command())
                    return True, "Автозапуск включен."
                try:
                    winreg.DeleteValue(key, "LoliLend")
                except FileNotFoundError:
                    pass
                return True, "Автозапуск отключен."
        except OSError as exc:
            return False, f"Не удалось изменить автозапуск: {exc}"

    def _autostart_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f"\"{Path(sys.executable).resolve()}\""
        main_script = Path(sys.argv[0]).resolve()
        return f"\"{Path(sys.executable).resolve()}\" \"{main_script}\""

    def _load_raw(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_raw(self, payload: dict[str, Any]) -> None:
        self._config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sanitize_profile_values(self, values: dict[str, Any]) -> dict[str, Any]:
        launch_mode = str(values.get("launch_mode", "Стандартный"))
        if launch_mode not in LAUNCH_MODES:
            launch_mode = "Стандартный"

        accent_preset = str(values.get("accent_preset", "Rose"))
        if accent_preset not in ACCENT_PRESETS:
            accent_preset = "Rose"

        active_ai = str(values.get("active_ai", "AI LOLILEND"))
        if active_ai not in ACTIVE_AI_OPTIONS:
            active_ai = "AI LOLILEND"
        ai_protocol = str(values.get("ai_protocol", "openai_compatible"))
        if ai_protocol not in AI_PROTOCOL_OPTIONS:
            ai_protocol = "openai_compatible"
        ai_model = str(values.get("ai_model", "@cf/meta/llama-3.2-3b-instruct")).strip() or "@cf/meta/llama-3.2-3b-instruct"
        ai_active_task = str(values.get("ai_active_task", TEXT_GENERATION)).strip() or TEXT_GENERATION
        if ai_active_task not in {
            "text_generation",
            "text_embeddings",
            "text_classification",
            "text_to_image",
            "text_to_speech",
            "automatic_speech_recognition",
            "image_to_text",
            "image_classification",
            "translation",
            "summarization",
        }:
            ai_active_task = TEXT_GENERATION

        return {
            "brightness": self._clamp_int(values.get("brightness", 72), 0, 100),
            "show_hints": bool(values.get("show_hints", True)),
            "smooth_animation": bool(values.get("smooth_animation", True)),
            "launch_mode": launch_mode,
            "protected_mode": bool(values.get("protected_mode", True)),
            "hide_notifications": bool(values.get("hide_notifications", False)),
            "minimize_to_tray": bool(values.get("minimize_to_tray", True)),
            "close_to_tray": bool(values.get("close_to_tray", True)),
            "autostart_windows": bool(values.get("autostart_windows", False)),
            "accent_preset": accent_preset,
            "interface_scale": self._clamp_int(values.get("interface_scale", 100), 85, 130),
            "font_size": self._clamp_int(values.get("font_size", 13), 11, 18),
            "panel_opacity": self._clamp_int(values.get("panel_opacity", 86), 60, 100),
            "sidebar_width": self._clamp_int(values.get("sidebar_width", 102), 82, 160),
            "compact_mode": bool(values.get("compact_mode", False)),
            "show_status_bar": bool(values.get("show_status_bar", False)),
            "active_ai": active_ai,
            "ai_protocol": ai_protocol,
            "ai_model": ai_model,
            "ai_active_task": ai_active_task,
            "ai_popular_only": bool(values.get("ai_popular_only", False)),
            "ai_system_prompt": str(values.get("ai_system_prompt", "")),
            "ai_temperature": self._clamp_float(values.get("ai_temperature", 0.7), 0.0, 2.0),
            "ai_max_tokens": self._clamp_int(values.get("ai_max_tokens", 1024), 64, 8192),
            "ai_streaming_enabled": bool(values.get("ai_streaming_enabled", True)),
            "ai_last_session_id": str(values.get("ai_last_session_id", "")),
            "fps_overlay_enabled": bool(values.get("fps_overlay_enabled", False)),
            "fps_capture_enabled": bool(values.get("fps_capture_enabled", False)),
            "fps_overlay_hotkey": str(values.get("fps_overlay_hotkey", "Ctrl+Shift+F10")).strip() or "Ctrl+Shift+F10",
            "fps_overlay_position": str(values.get("fps_overlay_position", "top_left"))
            if str(values.get("fps_overlay_position", "top_left")) in {"top_left", "top_right", "bottom_left", "bottom_right"}
            else "top_left",
            "fps_overlay_opacity": self._clamp_int(values.get("fps_overlay_opacity", 88), 35, 100),
            "fps_overlay_scale": self._clamp_int(values.get("fps_overlay_scale", 100), 80, 140),
            "github_repo": self._sanitize_github_repo(str(values.get("github_repo", DEFAULT_GITHUB_REPO))),
            "auto_update_enabled": bool(values.get("auto_update_enabled", True)),
            "release_asset_pattern": str(values.get("release_asset_pattern", DEFAULT_RELEASE_ASSET_PATTERN)).strip()
            or DEFAULT_RELEASE_ASSET_PATTERN,
            "launcher_custom_image_path": str(values.get("launcher_custom_image_path", "")),
        }

    @staticmethod
    def _sanitize_github_repo(value: str) -> str:
        repo = value.strip().strip("/")
        if "/" not in repo:
            return DEFAULT_GITHUB_REPO
        owner, name = repo.split("/", 1)
        owner = owner.strip()
        name = name.strip()
        if not owner or not name:
            return DEFAULT_GITHUB_REPO
        return f"{owner}/{name}"

    @staticmethod
    def _clamp_int(value: Any, min_value: int, max_value: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = min_value
        return max(min_value, min(max_value, number))

    @staticmethod
    def _clamp_float(value: Any, min_value: float, max_value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = min_value
        return max(min_value, min(max_value, number))
