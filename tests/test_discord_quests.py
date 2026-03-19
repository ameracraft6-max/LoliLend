from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from lolilend.discord_quests import (
    DiscordQuestConfig,
    DiscordQuestService,
    DiscordQuestStore,
)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):  # noqa: ANN001
        return self._payload


class _FakeHttp:
    def __init__(self, mirror_payload, discord_payload, mirror_status: int = 200, discord_status: int = 200) -> None:
        self.mirror_payload = mirror_payload
        self.discord_payload = discord_payload
        self.mirror_status = mirror_status
        self.discord_status = discord_status
        self.calls: list[str] = []

    def get(self, url: str, headers=None, timeout=None):  # noqa: ANN001
        del headers, timeout
        self.calls.append(url)
        if "markterence.github.io/discord-quest-completer/detectable.json" in url:
            return _FakeResponse(self.mirror_payload, self.mirror_status)
        if "discord.com/api/applications/detectable" in url or "discord.com/api/v9/applications/detectable" in url:
            return _FakeResponse(self.discord_payload, self.discord_status)
        return _FakeResponse({}, 404)


class _FakePopen:
    _next_pid = 30000

    def __init__(self, command, **kwargs):  # noqa: ANN001
        del command, kwargs
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self._running = True

    def poll(self):  # noqa: ANN001
        return None if self._running else 0

    def terminate(self) -> None:
        self._running = False

    def kill(self) -> None:
        self._running = False

    def wait(self, timeout=None) -> int:  # noqa: ANN001
        del timeout
        self._running = False
        return 0


class _FakeRpc:
    def __init__(self) -> None:
        self.connected = False
        self.updated = False
        self.cleared = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def update(self, **kwargs):  # noqa: ANN003
        del kwargs
        self.updated = True

    def clear(self) -> None:
        self.cleared = True

    def close(self) -> None:
        self.closed = True


def _sample_detectables() -> list[dict]:
    return [
        {
            "id": "111",
            "name": "Test Game",
            "aliases": ["test"],
            "executables": [
                {"name": "Bin/TestGame.exe", "os": "win32", "is_launcher": False},
                {"name": "Game.app", "os": "darwin", "is_launcher": False},
            ],
        }
    ]


class _TestService(DiscordQuestService):
    def __init__(self, games_root: Path, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self._test_games_root = games_root
        super().__init__(*args, **kwargs)

    def _games_root(self) -> Path:  # type: ignore[override]
        return self._test_games_root


class DiscordQuestStoreTests(unittest.TestCase):
    def test_config_roundtrip_and_broken_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestStoreV3Test")
                defaults = store.load_config()
                self.assertFalse(defaults.warning_ack)
                self.assertEqual(defaults.selected_app_ids, [])

                store.save_config(
                    DiscordQuestConfig(
                        warning_ack=True,
                        selected_app_ids=["111", "111", "222"],
                    )
                )
                loaded = store.load_config()
                self.assertTrue(loaded.warning_ack)
                self.assertEqual(loaded.selected_app_ids, ["111", "222"])

                store.config_path.write_text("{broken", encoding="utf-8")
                fallback = store.load_config()
                self.assertFalse(fallback.warning_ack)
                self.assertEqual(fallback.selected_app_ids, [])
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


class DiscordQuestServiceTests(unittest.TestCase):
    def test_catalog_prefers_mirror_then_discord_then_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestSourcePriorityTest")
                mirror = _sample_detectables()
                discord = [
                    {
                        "id": "222",
                        "name": "Discord Source Game",
                        "aliases": [],
                        "executables": [{"name": "DiscordGame.exe", "os": "win32", "is_launcher": False}],
                    }
                ]
                http = _FakeHttp(mirror, discord, mirror_status=200, discord_status=200)
                service = _TestService(Path(temp) / "games", store=store, http_client=http, popen_factory=_FakePopen)

                ok, _msg, games = service.refresh_catalog()
                self.assertTrue(ok)
                self.assertEqual(len(games), 1)
                self.assertEqual(games[0].id, "111")
                self.assertEqual(service.status().source_used, "mirror")
                self.assertTrue(any("markterence.github.io" in call for call in http.calls))
                service.shutdown()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_catalog_falls_back_to_discord(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestDiscordFallbackTest")
                mirror = {}
                discord = _sample_detectables()
                http = _FakeHttp(mirror, discord, mirror_status=500, discord_status=200)
                service = _TestService(Path(temp) / "games", store=store, http_client=http, popen_factory=_FakePopen)

                ok, _msg, games = service.refresh_catalog()
                self.assertTrue(ok)
                self.assertEqual(len(games), 1)
                self.assertEqual(service.status().source_used, "discord_api")
                service.shutdown()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_add_install_play_stop_and_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestFlowTest")
                http = _FakeHttp(_sample_detectables(), _sample_detectables())
                service = _TestService(Path(temp) / "games", store=store, http_client=http, popen_factory=_FakePopen)

                ok, _msg, _games = service.refresh_catalog()
                self.assertTrue(ok)

                ok_add, _ = service.add_game("111")
                self.assertTrue(ok_add)
                selected = service.selected_games()
                self.assertEqual(len(selected), 1)
                game = selected[0]
                self.assertEqual(len(game.executables), 1)
                executable = game.executables[0]

                ok_run, message = service.install_and_play(game.uid, executable.key)
                self.assertTrue(ok_run, message)
                self.assertTrue(service.status().running_map)
                target = Path(temp) / "games" / "111" / "Bin" / "TestGame.exe"
                self.assertTrue(target.exists())

                ok_stop, _ = service.stop(game.uid, executable.key)
                self.assertTrue(ok_stop)
                self.assertFalse(service.status().running_map)

                service.shutdown()
                self.assertFalse(service.status().running_map)
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_rpc_connect_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestRpcTest")
                service = _TestService(Path(temp) / "games", store=store, http_client=_FakeHttp([], []), popen_factory=_FakePopen)
                fake_rpc = _FakeRpc()
                service._create_rpc_client = lambda _app_id: fake_rpc  # type: ignore[method-assign]

                ok_connect, _ = service.rpc_connect("111")
                self.assertTrue(ok_connect)
                status = service.status()
                self.assertTrue(status.rpc_connected)
                self.assertTrue(fake_rpc.connected)
                self.assertTrue(fake_rpc.updated)

                ok_disconnect, _ = service.rpc_disconnect()
                self.assertTrue(ok_disconnect)
                status = service.status()
                self.assertFalse(status.rpc_connected)
                self.assertTrue(fake_rpc.cleared)
                self.assertTrue(fake_rpc.closed)
                service.shutdown()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_cache_roundtrip_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp
            try:
                store = DiscordQuestStore(app_name="LoliLendQuestCacheRoundtrip")
                http = _FakeHttp(_sample_detectables(), _sample_detectables())
                service = _TestService(Path(temp) / "games", store=store, http_client=http, popen_factory=_FakePopen)
                ok, _msg, _games = service.refresh_catalog()
                self.assertTrue(ok)

                cache_path = store.cache_path
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                self.assertIn("detectable_games", raw)
                self.assertIn("111", raw["detectable_games"])
                service.shutdown()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


if __name__ == "__main__":
    unittest.main()
