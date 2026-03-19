from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lolilend.general_settings import GeneralSettings, GeneralSettingsStore


class GeneralSettingsStoreTests(unittest.TestCase):
    def test_load_and_save_extended_customization_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GeneralSettingsStore(app_name="LoliLendTest")
            store.base_dir = Path(temp_dir)
            store.temp_dir = store.base_dir / "temp"
            store.export_dir = store.base_dir / "exports"
            store._config_path = store.base_dir / "general_config.json"
            store.base_dir.mkdir(parents=True, exist_ok=True)
            store.temp_dir.mkdir(parents=True, exist_ok=True)
            store.export_dir.mkdir(parents=True, exist_ok=True)

            settings = GeneralSettings(
                brightness=80,
                show_hints=False,
                smooth_animation=False,
                launch_mode="Быстрый",
                protected_mode=True,
                hide_notifications=True,
                minimize_to_tray=False,
                close_to_tray=False,
                autostart_windows=False,
                accent_preset="Cyan",
                interface_scale=112,
                font_size=15,
                panel_opacity=78,
                sidebar_width=128,
                compact_mode=True,
                show_status_bar=False,
                active_ai="AI LOLILEND",
                ai_protocol="workers_ai_run",
                ai_model="@cf/openai/gpt-oss-20b",
                ai_active_task="translation",
                ai_popular_only=True,
                ai_system_prompt="You are LoliLend AI.",
                ai_temperature=1.1,
                ai_max_tokens=2048,
                ai_streaming_enabled=True,
                ai_last_session_id="42",
                window_geometry="abc",
                window_maximized=True,
                main_splitter_state="main",
                general_splitter_state="general",
                performance_splitter_state="performance",
                network_splitter_state="network",
                analytics_splitter_state="analytics",
                security_splitter_state="security",
                ai_splitter_state="ai",
                fps_overlay_enabled=True,
                fps_capture_enabled=True,
                fps_overlay_hotkey="Ctrl+Shift+F10",
                fps_overlay_position="bottom_right",
                fps_overlay_opacity=77,
                fps_overlay_scale=111,
                github_repo="Acme/LoliLend",
                auto_update_enabled=True,
                release_asset_pattern="LoliLend-Setup-*.exe",
                launcher_custom_image_path="C:/temp/preview.png",
                profile_name="Работа",
            )
            store.save_settings(settings)

            loaded = store.load_settings()
            self.assertEqual(loaded.accent_preset, "Cyan")
            self.assertEqual(loaded.interface_scale, 112)
            self.assertEqual(loaded.font_size, 15)
            self.assertEqual(loaded.panel_opacity, 78)
            self.assertEqual(loaded.sidebar_width, 128)
            self.assertTrue(loaded.compact_mode)
            self.assertFalse(loaded.show_status_bar)
            self.assertEqual(loaded.active_ai, "AI LOLILEND")
            self.assertEqual(loaded.ai_protocol, "workers_ai_run")
            self.assertEqual(loaded.ai_model, "@cf/openai/gpt-oss-20b")
            self.assertEqual(loaded.ai_active_task, "translation")
            self.assertTrue(loaded.ai_popular_only)
            self.assertEqual(loaded.ai_system_prompt, "You are LoliLend AI.")
            self.assertAlmostEqual(loaded.ai_temperature, 1.1)
            self.assertEqual(loaded.ai_max_tokens, 2048)
            self.assertTrue(loaded.ai_streaming_enabled)
            self.assertEqual(loaded.ai_last_session_id, "42")
            self.assertFalse(loaded.minimize_to_tray)
            self.assertFalse(loaded.close_to_tray)
            self.assertEqual(loaded.window_geometry, "abc")
            self.assertTrue(loaded.window_maximized)
            self.assertEqual(loaded.main_splitter_state, "main")
            self.assertEqual(loaded.general_splitter_state, "general")
            self.assertEqual(loaded.performance_splitter_state, "performance")
            self.assertEqual(loaded.network_splitter_state, "network")
            self.assertEqual(loaded.analytics_splitter_state, "analytics")
            self.assertEqual(loaded.security_splitter_state, "security")
            self.assertEqual(loaded.ai_splitter_state, "ai")
            self.assertTrue(loaded.fps_overlay_enabled)
            self.assertTrue(loaded.fps_capture_enabled)
            self.assertEqual(loaded.fps_overlay_hotkey, "Ctrl+Shift+F10")
            self.assertEqual(loaded.fps_overlay_position, "bottom_right")
            self.assertEqual(loaded.fps_overlay_opacity, 77)
            self.assertEqual(loaded.fps_overlay_scale, 111)
            self.assertEqual(loaded.github_repo, "Acme/LoliLend")
            self.assertTrue(loaded.auto_update_enabled)
            self.assertEqual(loaded.release_asset_pattern, "LoliLend-Setup-*.exe")
            self.assertEqual(loaded.launcher_custom_image_path, "C:/temp/preview.png")

    def test_save_profile_includes_customization_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GeneralSettingsStore(app_name="LoliLendTest")
            store.base_dir = Path(temp_dir)
            store.temp_dir = store.base_dir / "temp"
            store.export_dir = store.base_dir / "exports"
            store._config_path = store.base_dir / "general_config.json"
            store.base_dir.mkdir(parents=True, exist_ok=True)
            store.temp_dir.mkdir(parents=True, exist_ok=True)
            store.export_dir.mkdir(parents=True, exist_ok=True)

            store.save_profile(
                "Стандарт",
                {
                    "brightness": 66,
                    "show_hints": True,
                    "smooth_animation": True,
                    "launch_mode": "Стандартный",
                    "protected_mode": True,
                    "hide_notifications": False,
                    "minimize_to_tray": False,
                    "close_to_tray": False,
                    "autostart_windows": False,
                    "accent_preset": "Lime",
                    "interface_scale": 105,
                    "font_size": 14,
                    "panel_opacity": 88,
                    "sidebar_width": 110,
                    "compact_mode": False,
                    "show_status_bar": True,
                    "active_ai": "AI LOLILEND",
                    "ai_protocol": "openai_compatible",
                    "ai_model": "@cf/meta/llama-3.2-3b-instruct",
                    "ai_active_task": "text_to_image",
                    "ai_popular_only": True,
                    "ai_system_prompt": "short",
                    "ai_temperature": 0.35,
                    "ai_max_tokens": 1536,
                    "ai_streaming_enabled": True,
                    "ai_last_session_id": "7",
                    "fps_overlay_enabled": True,
                    "fps_capture_enabled": True,
                    "fps_overlay_hotkey": "Ctrl+Shift+F10",
                    "fps_overlay_position": "top_right",
                    "fps_overlay_opacity": 91,
                    "fps_overlay_scale": 120,
                    "github_repo": "Acme/LoliLend",
                    "auto_update_enabled": True,
                    "release_asset_pattern": "LoliLend-Setup-*.exe",
                    "launcher_custom_image_path": "C:/temp/preview.png",
                },
            )

            profiles = store.load_profiles(["Стандарт"])
            saved = profiles["Стандарт"]
            self.assertEqual(saved["accent_preset"], "Lime")
            self.assertEqual(saved["interface_scale"], 105)
            self.assertEqual(saved["font_size"], 14)
            self.assertEqual(saved["panel_opacity"], 88)
            self.assertEqual(saved["sidebar_width"], 110)
            self.assertEqual(saved["active_ai"], "AI LOLILEND")
            self.assertEqual(saved["ai_protocol"], "openai_compatible")
            self.assertEqual(saved["ai_model"], "@cf/meta/llama-3.2-3b-instruct")
            self.assertEqual(saved["ai_active_task"], "text_to_image")
            self.assertTrue(saved["ai_popular_only"])
            self.assertEqual(saved["ai_system_prompt"], "short")
            self.assertAlmostEqual(saved["ai_temperature"], 0.35)
            self.assertEqual(saved["ai_max_tokens"], 1536)
            self.assertTrue(saved["ai_streaming_enabled"])
            self.assertEqual(saved["ai_last_session_id"], "7")
            self.assertFalse(saved["minimize_to_tray"])
            self.assertFalse(saved["close_to_tray"])
            self.assertTrue(saved["fps_overlay_enabled"])
            self.assertTrue(saved["fps_capture_enabled"])
            self.assertEqual(saved["fps_overlay_hotkey"], "Ctrl+Shift+F10")
            self.assertEqual(saved["fps_overlay_position"], "top_right")
            self.assertEqual(saved["fps_overlay_opacity"], 91)
            self.assertEqual(saved["fps_overlay_scale"], 120)
            self.assertEqual(saved["github_repo"], "Acme/LoliLend")
            self.assertTrue(saved["auto_update_enabled"])
            self.assertEqual(saved["release_asset_pattern"], "LoliLend-Setup-*.exe")
            self.assertEqual(saved["launcher_custom_image_path"], "C:/temp/preview.png")

    def test_new_tray_settings_default_to_true(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GeneralSettingsStore(app_name="LoliLendTest")
            store.base_dir = Path(temp_dir)
            store.temp_dir = store.base_dir / "temp"
            store.export_dir = store.base_dir / "exports"
            store._config_path = store.base_dir / "general_config.json"
            store.base_dir.mkdir(parents=True, exist_ok=True)
            store.temp_dir.mkdir(parents=True, exist_ok=True)
            store.export_dir.mkdir(parents=True, exist_ok=True)

            loaded = store.load_settings()
            self.assertTrue(loaded.minimize_to_tray)
            self.assertTrue(loaded.close_to_tray)


if __name__ == "__main__":
    unittest.main()
