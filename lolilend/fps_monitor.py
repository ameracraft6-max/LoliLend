from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import csv
import math
import os
import subprocess
import threading
import time
from typing import Protocol
from pathlib import Path

from lolilend.runtime import asset_path


STATUS_RUNNING = "Running"
STATUS_NA = "N/A"
STATUS_WINDOWS_ONLY = "Windows only"
STATUS_BACKEND_ERROR = "Backend error"
STATUS_PERMISSION_REQUIRED = "Administrator privileges required"


@dataclass(slots=True)
class FpsSample:
    timestamp: datetime
    pid: int | None
    process_name: str | None
    fps: float | None
    frame_time_ms: float | None


@dataclass(slots=True)
class FpsSnapshot:
    timestamp: datetime
    status: str
    fps: float | None
    frame_time_ms: float | None
    one_percent_low_fps: float | None
    pid: int | None
    process_name: str | None
    backend_error: str | None = None
    permission_required: bool = False


class ForegroundProcessResolver:
    def __init__(self) -> None:
        self._is_windows = os.name == "nt"
        self._user32 = None
        self._ctypes = None
        self._wintypes = None
        if self._is_windows:
            try:
                import ctypes
                from ctypes import wintypes

                self._ctypes = ctypes
                self._wintypes = wintypes
                self._user32 = ctypes.windll.user32
            except Exception:  # pragma: no cover - defensive runtime path
                self._is_windows = False

    def get_foreground_pid(self) -> int | None:
        if not self._is_windows or self._user32 is None or self._ctypes is None or self._wintypes is None:
            return None
        hwnd = self._user32.GetForegroundWindow()
        if hwnd == 0:
            return None
        pid = self._wintypes.DWORD(0)
        self._user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid))
        return int(pid.value) if pid.value > 0 else None


class _RunnerProtocol(Protocol):
    def start(self, executable: Path, on_line: Callable[[str], None]) -> tuple[bool, str | None]: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...

    @property
    def last_error(self) -> str | None: ...


class PresentMonRunner:
    def __init__(self, args: list[str] | None = None) -> None:
        self._args = args or ["--output_stdout", "--v1_metrics", "--no_console_stats", "--stop_existing_session"]
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self, executable: Path, on_line: Callable[[str], None]) -> tuple[bool, str | None]:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return True, None
            self._last_error = None

        command = [str(executable), *self._args]
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
        except OSError as exc:
            message = f"PresentMon launch failed: {exc}"
            with self._lock:
                self._last_error = message
            return False, message

        self._stop_event.clear()
        with self._lock:
            self._process = process

        self._reader_thread = threading.Thread(target=self._read_loop, args=(process, on_line), daemon=True, name="presentmon-reader")
        self._reader_thread.start()
        return True, None

    def stop(self) -> None:
        with self._lock:
            process = self._process
        if process is None:
            return

        self._stop_event.set()
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=0.8)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=0.8)

        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass

        with self._lock:
            self._process = None

    def _read_loop(self, process: subprocess.Popen[str], on_line: Callable[[str], None]) -> None:
        try:
            if process.stdout is not None:
                for raw_line in process.stdout:
                    if self._stop_event.is_set():
                        break
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        on_line(line)
                    except Exception:
                        continue
        finally:
            stderr_text = ""
            if process.stderr is not None:
                try:
                    stderr_text = process.stderr.read().strip()
                except OSError:
                    stderr_text = ""

            return_code = process.poll()
            if return_code not in (None, 0) and not self._stop_event.is_set():
                message = stderr_text or f"PresentMon exited with code {return_code}"
                with self._lock:
                    self._last_error = message


class PresentMonCsvParser:
    def __init__(self) -> None:
        self._header: list[str] | None = None

    def feed_line(self, line: str) -> FpsSample | None:
        text = line.strip()
        if not text:
            return None

        row = self._parse_csv_row(text)
        if not row:
            return None

        if self._header is None and self._looks_like_header(row):
            self._header = [self._normalize_header(cell) for cell in row]
            return None

        if self._header is None:
            return self._parse_without_header(row)
        return self._parse_with_header(row)

    @staticmethod
    def _parse_csv_row(line: str) -> list[str]:
        try:
            parsed = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            return []
        return [cell.strip() for cell in parsed]

    @staticmethod
    def _normalize_header(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    def _looks_like_header(self, row: list[str]) -> bool:
        joined = ",".join(row).lower()
        keywords = ("process", "frametime", "msbetween", "fps", "present")
        return any(word in joined for word in keywords)

    def _parse_without_header(self, row: list[str]) -> FpsSample | None:
        if len(row) < 2:
            return None
        pid = self._to_int(row[0])
        fps = self._to_float(row[1])
        frame_time = self._to_float(row[2]) if len(row) > 2 else None
        if fps is None and frame_time and frame_time > 0:
            fps = 1000.0 / frame_time
        if fps is None and frame_time is None:
            return None
        return FpsSample(datetime.now(), pid, None, fps, frame_time)

    def _parse_with_header(self, row: list[str]) -> FpsSample | None:
        if self._header is None:
            return None

        values = {self._header[index]: row[index] if index < len(row) else "" for index in range(len(self._header))}

        pid = self._pick_int(values, ["processid", "pid", "applicationid"])
        process_name = self._pick_text(values, ["processname", "application", "exe"])
        frame_time = self._pick_float(
            values,
            [
                "frametime",
                "frametimems",
                "msbetweenpresents",
                "msbetweendisplaychange",
                "msbetweenpresentstart",
            ],
        )
        fps = self._pick_float(values, ["fps", "framerate", "displayedfps", "avgfps"])

        if (fps is None or fps <= 0) and frame_time is not None and frame_time > 0:
            fps = 1000.0 / frame_time

        if frame_time is not None and frame_time <= 0:
            frame_time = None
        if fps is not None and fps <= 0:
            fps = None

        if pid is None and not process_name and fps is None and frame_time is None:
            return None

        return FpsSample(
            timestamp=datetime.now(),
            pid=pid,
            process_name=process_name,
            fps=fps,
            frame_time_ms=frame_time,
        )

    @staticmethod
    def _pick_text(values: dict[str, str], keys: list[str]) -> str | None:
        for key in keys:
            raw = values.get(key, "").strip()
            if raw:
                return raw
        return None

    @staticmethod
    def _pick_int(values: dict[str, str], keys: list[str]) -> int | None:
        for key in keys:
            value = PresentMonCsvParser._to_int(values.get(key, ""))
            if value is not None:
                return value
        return None

    @staticmethod
    def _pick_float(values: dict[str, str], keys: list[str]) -> float | None:
        for key in keys:
            value = PresentMonCsvParser._to_float(values.get(key, ""))
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        if raw is None:
            return None
        text = str(raw).strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return value

    @staticmethod
    def _to_int(raw: str | None) -> int | None:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = int(float(text))
        except ValueError:
            return None
        return value if value > 0 else None


class FpsMetricsAggregator:
    def __init__(self, window_seconds: float = 20.0) -> None:
        self._window_seconds = max(window_seconds, 5.0)
        self._samples: deque[tuple[float, FpsSample]] = deque()

    def add(self, sample: FpsSample) -> None:
        now = time.monotonic()
        self._samples.append((now, sample))
        self._prune(now)

    def snapshot_for_pid(self, target_pid: int | None) -> FpsSnapshot:
        now = time.monotonic()
        self._prune(now)

        if not self._samples:
            return FpsSnapshot(datetime.now(), STATUS_NA, None, None, None, None, None)

        recent = [sample for _, sample in self._samples]
        if target_pid is not None:
            filtered = [sample for sample in recent if sample.pid == target_pid]
        else:
            filtered = list(recent)

        if not filtered:
            return FpsSnapshot(datetime.now(), STATUS_NA, None, None, None, target_pid, None)

        latest = filtered[-1]
        frame_times = [value.frame_time_ms for value in filtered if value.frame_time_ms is not None and value.frame_time_ms > 0]
        avg_frametime = sum(frame_times) / len(frame_times) if frame_times else None

        fps_current = latest.fps
        if (fps_current is None or fps_current <= 0) and latest.frame_time_ms and latest.frame_time_ms > 0:
            fps_current = 1000.0 / latest.frame_time_ms

        one_percent_low = None
        if frame_times:
            sorted_values = sorted(frame_times)
            index = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * 0.99) - 1))
            p99_frame = sorted_values[index]
            if p99_frame > 0:
                one_percent_low = 1000.0 / p99_frame

        status = STATUS_RUNNING if fps_current is not None or avg_frametime is not None else STATUS_NA
        return FpsSnapshot(
            timestamp=datetime.now(),
            status=status,
            fps=fps_current,
            frame_time_ms=avg_frametime,
            one_percent_low_fps=one_percent_low,
            pid=latest.pid,
            process_name=latest.process_name,
        )

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


class FpsMonitorService:
    def __init__(
        self,
        presentmon_path: Path | None = None,
        resolver: ForegroundProcessResolver | None = None,
        runner_factory: Callable[[], _RunnerProtocol] | None = None,
        platform_is_windows: bool | None = None,
    ) -> None:
        self._is_windows = (os.name == "nt") if platform_is_windows is None else bool(platform_is_windows)
        self._presentmon_path = presentmon_path or self._default_presentmon_path()
        self._resolver = resolver or ForegroundProcessResolver()
        self._runner_factory = runner_factory or (lambda: PresentMonRunner())
        self._parser = PresentMonCsvParser()
        self._aggregator = FpsMetricsAggregator(window_seconds=20.0)
        self._runner: _RunnerProtocol | None = None
        self._backend_error: str | None = None
        self._permission_required = False
        self._lock = threading.Lock()

    @staticmethod
    def _default_presentmon_path() -> Path:
        return asset_path("runtime", "presentmon", "PresentMon.exe")

    @property
    def presentmon_path(self) -> Path:
        return self._presentmon_path

    def windows_supported(self) -> bool:
        return self._is_windows

    def is_running(self) -> bool:
        runner = self._runner
        return runner is not None and runner.is_running()

    def start_capture(self) -> tuple[bool, str]:
        if not self._is_windows:
            return False, STATUS_WINDOWS_ONLY

        if self.is_running():
            return True, "Capture already running"

        self._backend_error = None
        self._permission_required = False
        if not self._presentmon_path.exists():
            self._backend_error = f"PresentMon not found: {self._presentmon_path}"
            return False, self._backend_error

        runner = self._runner_factory()
        ok, error = runner.start(self._presentmon_path, self._on_runner_line)
        if not ok:
            self._set_backend_error(error or "Failed to start PresentMon")
            return False, self._backend_error

        self._runner = runner
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            if runner.last_error:
                self._set_backend_error(runner.last_error)
                runner.stop()
                self._runner = None
                return False, self._backend_error or "Failed to start PresentMon"
            if not runner.is_running():
                break
            time.sleep(0.05)

        if not runner.is_running():
            self._set_backend_error(runner.last_error or "PresentMon exited before capture started")
            runner.stop()
            self._runner = None
            return False, self._backend_error or "Failed to start PresentMon"

        return True, "FPS capture started"

    def stop_capture(self) -> None:
        runner = self._runner
        if runner is None:
            return
        runner.stop()
        self._runner = None

    def latest_snapshot(self) -> FpsSnapshot:
        if not self._is_windows:
            return FpsSnapshot(datetime.now(), STATUS_WINDOWS_ONLY, None, None, None, None, None)

        runner = self._runner
        if runner is not None and not runner.is_running() and runner.last_error:
            self._set_backend_error(runner.last_error)
            self._runner = None

        foreground_pid = self._resolver.get_foreground_pid()
        with self._lock:
            snapshot = self._aggregator.snapshot_for_pid(foreground_pid)

        if self._backend_error and not self.is_running():
            snapshot.status = STATUS_PERMISSION_REQUIRED if self._permission_required else STATUS_BACKEND_ERROR
            snapshot.backend_error = self._backend_error
            snapshot.permission_required = self._permission_required
            return snapshot

        if self.is_running() and snapshot.status != STATUS_RUNNING:
            snapshot.status = STATUS_NA
            return snapshot

        if not self.is_running() and snapshot.status == STATUS_RUNNING:
            snapshot.status = STATUS_NA

        return snapshot

    def _on_runner_line(self, line: str) -> None:
        sample = self._parser.feed_line(line)
        if sample is None:
            return
        with self._lock:
            self._aggregator.add(sample)

    def close(self) -> None:
        self.stop_capture()

    def _set_backend_error(self, message: str | None) -> None:
        normalized, permission_required = self._normalize_backend_error(message)
        self._backend_error = normalized
        self._permission_required = permission_required

    @staticmethod
    def _normalize_backend_error(message: str | None) -> tuple[str | None, bool]:
        if not message:
            return None, False
        text = str(message).strip()
        lowered = text.lower()
        permission_required = any(
            token in lowered
            for token in (
                "access denied",
                "administrative privileges",
                "administrator privileges",
                "performance log users",
                "run as administrator",
                "restart as administrator",
            )
        )
        if permission_required:
            return (
                "PresentMon requires administrator privileges or membership in Performance Log Users.",
                True,
            )
        return text, False

