from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest

from lolilend.telegram_proxy import (
    TelegramProxyConfig,
    TelegramProxyService,
    TelegramProxyStore,
)


class _FakeCore:
    def __init__(self) -> None:
        self.starts = 0
        self.running = False
        self.last_config: tuple[int, str] | None = None

    def parse_dc_ip_list(self, dc_ip_list: list[str]) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for raw in dc_ip_list:
            if ":" not in raw:
                raise ValueError("Invalid --dc-ip format")
            dc, ip = raw.split(":", 1)
            mapping[int(dc)] = ip
        return mapping

    def create_run_coroutine(self, port: int, dc_opt: dict[int, str], stop_event: asyncio.Event, host: str):
        self.starts += 1
        self.last_config = (port, host)

        async def _run() -> None:
            self.running = True
            await stop_event.wait()
            self.running = False

        return _run()


class TelegramProxyConfigTests(unittest.TestCase):
    def test_normalized_uses_defaults_for_empty_values(self) -> None:
        config = TelegramProxyConfig(host="", port=99999, dc_ip=[], verbose=True).normalized()
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 65535)
        self.assertEqual(config.dc_ip, ["2:149.154.167.220", "4:149.154.167.220"])
        self.assertTrue(config.verbose)


class TelegramProxyStoreTests(unittest.TestCase):
    def test_load_and_save_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = TelegramProxyStore(app_name="LoliLendTest")
                defaults = store.load_config()
                self.assertEqual(defaults.host, "127.0.0.1")
                self.assertEqual(defaults.port, 1080)
                self.assertEqual(defaults.dc_ip, ["2:149.154.167.220", "4:149.154.167.220"])

                store.save_config(
                    TelegramProxyConfig(
                        host="127.0.0.1",
                        port=9050,
                        dc_ip=["1:149.154.175.205", "2:149.154.167.220"],
                        verbose=True,
                    )
                )
                loaded = store.load_config()
                self.assertEqual(loaded.port, 9050)
                self.assertEqual(loaded.dc_ip, ["1:149.154.175.205", "2:149.154.167.220"])
                self.assertTrue(Path(store.config_path).exists())
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


class TelegramProxyServiceTests(unittest.TestCase):
    def test_start_stop_restart_with_fake_core(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = TelegramProxyStore(app_name="LoliLendTestService")
                core = _FakeCore()
                service = TelegramProxyService(store=store, core=core)
                config = TelegramProxyConfig(
                    host="127.0.0.1",
                    port=1080,
                    dc_ip=["2:149.154.167.220", "4:149.154.167.220"],
                    verbose=False,
                )

                ok_start, _ = service.start(config)
                self.assertTrue(ok_start)
                self.assertTrue(service.is_running())
                self.assertEqual(core.starts, 1)

                ok_restart, _ = service.restart(config)
                self.assertTrue(ok_restart)
                self.assertTrue(service.is_running())
                self.assertEqual(core.starts, 2)

                ok_stop, _ = service.stop()
                self.assertTrue(ok_stop)
                self.assertFalse(service.is_running())
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_start_rejects_invalid_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                service = TelegramProxyService(
                    store=TelegramProxyStore(app_name="LoliLendTestInvalid"),
                    core=_FakeCore(),
                )
                ok, message = service.start(
                    TelegramProxyConfig(
                        host="bad host",
                        port=1080,
                        dc_ip=["2:149.154.167.220"],
                        verbose=False,
                    )
                )
                self.assertFalse(ok)
                self.assertIn("config error", message.lower())
                self.assertFalse(service.is_running())
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


if __name__ == "__main__":
    unittest.main()
