from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest

from lolilend.analytics import AnalyticsStore, GameAnalyticsService, GameClassifier, _UsageDelta, normalize_app_key
from lolilend.monitoring import ProcessSnapshot


def _proc(
    pid: int,
    name: str,
    exe_path: str | None,
    cpu_percent: float = 0.0,
    ram_mb: float = 0.0,
    status: str = "running",
) -> ProcessSnapshot:
    return ProcessSnapshot(
        pid=pid,
        name=name,
        exe_path=exe_path,
        cpu_percent=cpu_percent,
        ram_mb=ram_mb,
        status=status,
    )


class _FakeSource:
    def __init__(self, frames: list[list[ProcessSnapshot]]) -> None:
        self._frames = frames
        self._index = 0

    def poll_processes(self, limit: int = 0) -> list[ProcessSnapshot]:
        del limit
        if not self._frames:
            return []
        index = min(self._index, len(self._frames) - 1)
        self._index += 1
        return list(self._frames[index])


class GameClassifierTests(unittest.TestCase):
    def test_classifies_game_and_launcher_with_default_threshold(self) -> None:
        classifier = GameClassifier(threshold=0.6)

        game_snapshot = _proc(
            pid=10,
            name="dota2.exe",
            exe_path=r"C:\Games\Steam\steamapps\common\dota2.exe",
            cpu_percent=18.0,
            ram_mb=1_200.0,
        )
        launcher_snapshot = _proc(
            pid=11,
            name="steam.exe",
            exe_path=r"C:\Program Files (x86)\Steam\steam.exe",
            cpu_percent=1.0,
            ram_mb=220.0,
        )

        game_result = classifier.classify(game_snapshot)
        launcher_result = classifier.classify(launcher_snapshot)
        self.assertTrue(game_result.is_game)
        self.assertTrue(launcher_result.is_game)
        self.assertGreaterEqual(game_result.confidence, 0.6)
        self.assertGreaterEqual(launcher_result.confidence, 0.6)

    def test_override_priority_and_online_learning(self) -> None:
        classifier = GameClassifier(threshold=0.6)
        snapshot = _proc(
            pid=21,
            name="helper.exe",
            exe_path=r"C:\Tools\helper.exe",
            cpu_percent=0.5,
            ram_mb=120.0,
        )
        default_result = classifier.classify(snapshot)
        override_result = classifier.classify(snapshot, override=True)
        self.assertTrue(override_result.is_game)
        self.assertEqual(override_result.confidence, 1.0)

        before = classifier.export_weights()
        classifier.learn(default_result.features, target=1.0)
        after = classifier.export_weights()
        self.assertNotEqual(before, after)


class AnalyticsStoreTests(unittest.TestCase):
    def test_usage_upsert_top_queries_and_weights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalyticsStore(db_path=Path(temp_dir) / "analytics.sqlite")
            day = datetime.now().date().isoformat()
            now_iso = datetime.now().isoformat(timespec="seconds")

            store.bulk_upsert_usage(
                [
                    _UsageDelta(day, "a.exe", "Game A", 5, 1, now_iso),
                    _UsageDelta(day, "a.exe", "Game A", 15, 0, now_iso),
                    _UsageDelta(day, "b.exe", "Game B", 7, 1, now_iso),
                ]
            )

            start = datetime.now().date()
            total = store.get_total(start, start)
            self.assertEqual(total, 27)

            top = store.get_top(start, start, limit=5)
            self.assertEqual(len(top), 2)
            self.assertEqual(top[0].app_key, "a.exe")
            self.assertEqual(top[0].seconds, 20)
            self.assertEqual(top[0].sessions, 1)

            store.set_override("a.exe", True)
            self.assertEqual(store.load_overrides().get("a.exe"), True)
            store.clear_override("a.exe")
            self.assertNotIn("a.exe", store.load_overrides())

            defaults = {"bias": -1.0, "token_game": 2.0}
            merged = store.load_model_weights(defaults)
            self.assertEqual(merged, defaults)
            store.save_model_weights({"bias": -0.8, "token_game": 2.2})
            updated = store.load_model_weights(defaults)
            self.assertEqual(updated["bias"], -0.8)
            self.assertEqual(updated["token_game"], 2.2)
            store.close()


class GameAnalyticsServiceTests(unittest.TestCase):
    def test_session_aggregation_grace_and_no_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalyticsStore(db_path=Path(temp_dir) / "analytics.sqlite")
            service = GameAnalyticsService(
                process_source=_FakeSource([]),
                store=store,
                sample_interval_seconds=5,
                grace_period_seconds=10,
            )

            now = datetime.now()
            snapshot1 = _proc(1, "dota2.exe", r"C:\Games\dota2.exe", 10.0, 900.0)
            snapshot2 = _proc(2, "dota2.exe", r"C:\Games\dota2.exe", 8.0, 850.0)

            deltas_t1 = service._process_tick([snapshot1, snapshot2], now)
            self.assertEqual(len(deltas_t1), 1)
            self.assertEqual(deltas_t1[0].seconds, 5)
            self.assertEqual(deltas_t1[0].sessions, 1)
            store.bulk_upsert_usage(deltas_t1)

            deltas_t2 = service._process_tick([snapshot1], now + timedelta(seconds=5))
            self.assertEqual(len(deltas_t2), 1)
            self.assertEqual(deltas_t2[0].sessions, 0)
            store.bulk_upsert_usage(deltas_t2)

            service._process_tick([], now + timedelta(seconds=21))
            self.assertEqual(len(service._sessions), 0)

            today = datetime.now().date()
            summary = service.get_summary(days=7)
            self.assertEqual(summary.total_today_seconds, store.get_total(today, today))
            self.assertEqual(summary.total_today_seconds, 10)
            store.close()

    def test_set_override_persists_and_updates_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalyticsStore(db_path=Path(temp_dir) / "analytics.sqlite")
            service = GameAnalyticsService(
                process_source=_FakeSource([]),
                store=store,
                sample_interval_seconds=5,
                grace_period_seconds=10,
            )
            snapshot = _proc(40, "helper.exe", r"C:\Tools\helper.exe", 0.0, 64.0)
            app_key = normalize_app_key(snapshot.exe_path, snapshot.name)

            service._process_tick([snapshot], datetime.now())
            before_weights = service._classifier.export_weights()
            service.set_override(app_key, True)
            after_weights = service._classifier.export_weights()

            self.assertNotEqual(before_weights, after_weights)
            self.assertTrue(store.load_overrides().get(app_key))
            service.clear_override(app_key)
            self.assertNotIn(app_key, store.load_overrides())
            store.close()

    def test_integration_background_loop_updates_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalyticsStore(db_path=Path(temp_dir) / "analytics.sqlite")
            frames = [
                [_proc(100, "dota2.exe", r"C:\Games\dota2.exe", 12.0, 900.0)],
                [
                    _proc(100, "dota2.exe", r"C:\Games\dota2.exe", 9.0, 910.0),
                    _proc(101, "dota2.exe", r"C:\Games\dota2.exe", 7.0, 850.0),
                ],
                [],
                [],
            ]
            service = GameAnalyticsService(
                process_source=_FakeSource(frames),
                store=store,
                sample_interval_seconds=1,
                grace_period_seconds=2,
            )

            service.start()
            time.sleep(3.4)
            service.stop()

            summary = service.get_summary(days=7)
            self.assertGreaterEqual(summary.total_today_seconds, 2)
            self.assertTrue(summary.top_week)
            self.assertEqual(summary.top_week[0].app_key, r"c:/games/dota2.exe")
            store.close()


if __name__ == "__main__":
    unittest.main()
