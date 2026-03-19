from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from lolilend.fps_monitor import (
    FpsMetricsAggregator,
    FpsMonitorService,
    FpsSample,
    PresentMonCsvParser,
    PresentMonRunner,
    STATUS_BACKEND_ERROR,
    STATUS_NA,
    STATUS_PERMISSION_REQUIRED,
    STATUS_RUNNING,
    STATUS_WINDOWS_ONLY,
)


class _FakeResolver:
    def __init__(self, pid: int | None) -> None:
        self.pid = pid

    def get_foreground_pid(self) -> int | None:
        return self.pid


class _FakeRunner:
    def __init__(self, lines: list[str], start_ok: bool = True, start_error: str | None = None) -> None:
        self._lines = lines
        self._start_ok = start_ok
        self._start_error = start_error or "runner start failed"
        self._running = False
        self._last_error: str | None = None

    def start(self, executable: Path, on_line):
        del executable
        if not self._start_ok:
            self._last_error = self._start_error
            return False, self._start_error
        self._running = True
        for line in self._lines:
            on_line(line)
        return True, None

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str | None:
        return self._last_error


class _ImmediateExitRunner:
    def __init__(self, error: str) -> None:
        self._error = error

    def start(self, executable: Path, on_line):
        del executable
        del on_line
        return True, None

    def stop(self) -> None:
        return

    def is_running(self) -> bool:
        return False

    @property
    def last_error(self) -> str | None:
        return self._error


class PresentMonParserTests(unittest.TestCase):
    def test_parses_valid_csv_stream(self) -> None:
        parser = PresentMonCsvParser()
        self.assertIsNone(parser.feed_line("ProcessID,ProcessName,FPS,msBetweenPresents"))
        sample = parser.feed_line("1337,game.exe,120.5,8.29")
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.pid, 1337)
        self.assertEqual(sample.process_name, "game.exe")
        self.assertAlmostEqual(sample.fps or 0.0, 120.5, places=2)
        self.assertAlmostEqual(sample.frame_time_ms or 0.0, 8.29, places=2)

    def test_returns_none_for_invalid_lines(self) -> None:
        parser = PresentMonCsvParser()
        self.assertIsNone(parser.feed_line(""))
        self.assertIsNone(parser.feed_line("garbage line"))


class FpsMetricsAggregatorTests(unittest.TestCase):
    def test_calculates_average_frametime_and_one_percent_low(self) -> None:
        aggregator = FpsMetricsAggregator(window_seconds=20)
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for value in values:
            aggregator.add(
                FpsSample(
                    timestamp=datetime.now(),
                    pid=10,
                    process_name="game.exe",
                    fps=1000.0 / value,
                    frame_time_ms=value,
                )
            )

        snapshot = aggregator.snapshot_for_pid(10)
        self.assertEqual(snapshot.status, STATUS_RUNNING)
        self.assertAlmostEqual(snapshot.frame_time_ms or 0.0, 30.0, places=2)
        self.assertAlmostEqual(snapshot.one_percent_low_fps or 0.0, 20.0, places=2)

    def test_returns_na_for_missing_target_pid(self) -> None:
        aggregator = FpsMetricsAggregator(window_seconds=20)
        aggregator.add(FpsSample(datetime.now(), 11, "other.exe", 60.0, 16.6))
        snapshot = aggregator.snapshot_for_pid(99)
        self.assertEqual(snapshot.status, STATUS_NA)
        self.assertIsNone(snapshot.fps)


class FpsMonitorServiceTests(unittest.TestCase):
    def test_presentmon_runner_uses_presentmon_2_cli(self) -> None:
        runner = PresentMonRunner()
        self.assertEqual(
            runner._args,
            ["--output_stdout", "--v1_metrics", "--no_console_stats", "--stop_existing_session"],
        )

    def test_windows_only_fallback(self) -> None:
        service = FpsMonitorService(platform_is_windows=False)
        ok, message = service.start_capture()
        self.assertFalse(ok)
        self.assertEqual(message, STATUS_WINDOWS_ONLY)
        snapshot = service.latest_snapshot()
        self.assertEqual(snapshot.status, STATUS_WINDOWS_ONLY)

    def test_start_stop_with_fake_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            presentmon = Path(temp_dir) / "PresentMon.exe"
            presentmon.write_bytes(b"stub")
            fake_runner = _FakeRunner(
                [
                    "ProcessID,ProcessName,FPS,msBetweenPresents",
                    "100,game.exe,144.0,6.94",
                    "100,game.exe,142.0,7.04",
                ]
            )
            service = FpsMonitorService(
                presentmon_path=presentmon,
                resolver=_FakeResolver(100),
                runner_factory=lambda: fake_runner,
                platform_is_windows=True,
            )

            ok, _ = service.start_capture()
            self.assertTrue(ok)
            self.assertTrue(service.is_running())

            snapshot = service.latest_snapshot()
            self.assertEqual(snapshot.status, STATUS_RUNNING)
            self.assertIsNotNone(snapshot.fps)
            self.assertEqual(snapshot.process_name, "game.exe")

            service.stop_capture()
            self.assertFalse(service.is_running())

    def test_backend_error_for_missing_presentmon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.exe"
            service = FpsMonitorService(
                presentmon_path=missing,
                resolver=_FakeResolver(None),
                platform_is_windows=True,
            )
            ok, _ = service.start_capture()
            self.assertFalse(ok)
            snapshot = service.latest_snapshot()
            self.assertEqual(snapshot.status, STATUS_BACKEND_ERROR)

    def test_permission_error_is_reported_without_false_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            presentmon = Path(temp_dir) / "PresentMon.exe"
            presentmon.write_bytes(b"stub")
            service = FpsMonitorService(
                presentmon_path=presentmon,
                resolver=_FakeResolver(None),
                runner_factory=lambda: _ImmediateExitRunner(
                    "access denied: PresentMon requires administrative privileges"
                ),
                platform_is_windows=True,
            )

            ok, message = service.start_capture()
            self.assertFalse(ok)
            self.assertIn("administrator privileges", message.lower())
            self.assertFalse(service.is_running())

            snapshot = service.latest_snapshot()
            self.assertEqual(snapshot.status, STATUS_PERMISSION_REQUIRED)
            self.assertTrue(snapshot.permission_required)
            self.assertIn("Performance Log Users", snapshot.backend_error or "")


if __name__ == "__main__":
    unittest.main()
