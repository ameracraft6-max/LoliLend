from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import heapq
from platform import system
import subprocess
import time
from typing import Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency for the app
    psutil = None


@dataclass(slots=True)
class SystemSnapshot:
    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    disk_read_bps: float
    disk_write_bps: float
    net_up_bps: float
    net_down_bps: float
    gpu_percent: float | None


@dataclass(slots=True)
class ProcessSnapshot:
    pid: int
    name: str
    exe_path: str | None
    cpu_percent: float
    ram_mb: float
    status: str


class HistoryBuffer:
    """Fixed-size numeric history used by charts."""

    def __init__(self, max_points: int = 60) -> None:
        if max_points <= 0:
            raise ValueError("max_points must be positive")
        self.max_points = max_points
        self._values: deque[float] = deque(maxlen=max_points)

    def push(self, value: float) -> None:
        self._values.append(float(value))

    def values(self, fill: float = 0.0) -> list[float]:
        values = list(self._values)
        if len(values) < self.max_points:
            return [fill] * (self.max_points - len(values)) + values
        return values

    def __len__(self) -> int:
        return len(self._values)


def compute_counter_rate(previous: int | None, current: int | None, elapsed_seconds: float) -> float:
    if previous is None or current is None or elapsed_seconds <= 0:
        return 0.0
    delta = current - previous
    if delta <= 0:
        return 0.0
    return delta / elapsed_seconds


def format_bitrate_auto(bytes_per_second: float) -> tuple[float, str]:
    """Convert bytes/sec to auto bits/sec units for UI (Kbps/Mbps)."""
    bits_per_second = max(bytes_per_second, 0.0) * 8.0
    if bits_per_second >= 1_000_000:
        return bits_per_second / 1_000_000, "Mbps"
    return bits_per_second / 1_000, "Kbps"


def format_bitrate_text(bytes_per_second: float) -> str:
    value, unit = format_bitrate_auto(bytes_per_second)
    precision = 1 if value < 100 else 0
    return f"{value:.{precision}f} {unit}"


def format_bytes_text(bytes_per_second: float) -> str:
    value = max(bytes_per_second, 0.0)
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB/s"
    if value >= 1024:
        return f"{value / 1024:.1f} KB/s"
    return f"{value:.0f} B/s"


class MonitorService:
    def __init__(self, gpu_probe_interval_seconds: float = 10.0, prime_process_cpu: bool = False) -> None:
        if psutil is None:
            raise RuntimeError("psutil is required for live monitoring")

        self._gpu_probe_interval_seconds = max(gpu_probe_interval_seconds, 1.0)
        self._last_poll_monotonic = time.monotonic()
        self._last_disk = psutil.disk_io_counters()
        self._last_net = psutil.net_io_counters()
        self._cached_gpu: float | None = None
        self._next_gpu_probe = 0.0
        self._is_windows = system().lower() == "windows"
        self._exe_cache_ttl_seconds = 30.0
        self._exe_path_cache: dict[int, tuple[str | None, float]] = {}
        self._last_exe_cache_cleanup = 0.0

        # Warm-up for accurate non-blocking percent values.
        psutil.cpu_percent(interval=None)
        if prime_process_cpu:
            self._prime_process_cpu_percent()

    def poll_system(self) -> SystemSnapshot:
        now_monotonic = time.monotonic()
        elapsed = max(now_monotonic - self._last_poll_monotonic, 1e-6)
        self._last_poll_monotonic = now_monotonic

        cpu_percent = float(psutil.cpu_percent(interval=None))
        ram_percent = float(psutil.virtual_memory().percent)

        disk_now = psutil.disk_io_counters()
        disk_read_bps = compute_counter_rate(
            self._counter_value(self._last_disk, "read_bytes"),
            self._counter_value(disk_now, "read_bytes"),
            elapsed,
        )
        disk_write_bps = compute_counter_rate(
            self._counter_value(self._last_disk, "write_bytes"),
            self._counter_value(disk_now, "write_bytes"),
            elapsed,
        )
        self._last_disk = disk_now

        net_now = psutil.net_io_counters()
        net_up_bps = compute_counter_rate(
            self._counter_value(self._last_net, "bytes_sent"),
            self._counter_value(net_now, "bytes_sent"),
            elapsed,
        )
        net_down_bps = compute_counter_rate(
            self._counter_value(self._last_net, "bytes_recv"),
            self._counter_value(net_now, "bytes_recv"),
            elapsed,
        )
        self._last_net = net_now

        gpu_percent = self._poll_gpu_percent(now_monotonic)
        return SystemSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu_percent,
            ram_percent=ram_percent,
            disk_read_bps=disk_read_bps,
            disk_write_bps=disk_write_bps,
            net_up_bps=net_up_bps,
            net_down_bps=net_down_bps,
            gpu_percent=gpu_percent,
        )

    def poll_processes(self, limit: int = 120, include_exe_path: bool = False) -> list[ProcessSnapshot]:
        now_monotonic = time.monotonic()
        if include_exe_path:
            self._cleanup_exe_path_cache(now_monotonic)

        processes: list[ProcessSnapshot] = []
        process_heap: list[tuple[float, float, int, ProcessSnapshot]] = []
        for proc in psutil.process_iter(["pid", "name", "status", "memory_info", "cpu_percent"]):
            try:
                info = proc.info
                pid = int(info.get("pid", 0))
                if pid <= 0:
                    continue
                name = str(info.get("name") or f"PID {pid}")
                if name.lower() == "system idle process":
                    continue
                status = str(info.get("status") or "unknown")
                cpu_percent = float(info.get("cpu_percent") or 0.0)
                memory_info = info.get("memory_info")
                ram_mb = float(memory_info.rss / (1024 * 1024)) if memory_info else 0.0
                exe_path = self._resolve_exe_path(proc, pid, now_monotonic) if include_exe_path else None
                snapshot = ProcessSnapshot(
                    pid=pid,
                    name=name,
                    exe_path=exe_path,
                    cpu_percent=cpu_percent,
                    ram_mb=ram_mb,
                    status=status,
                )
                if limit > 0:
                    score = (snapshot.cpu_percent, snapshot.ram_mb, -snapshot.pid)
                    if len(process_heap) < limit:
                        heapq.heappush(process_heap, (score[0], score[1], score[2], snapshot))
                    else:
                        heapq.heappushpop(process_heap, (score[0], score[1], score[2], snapshot))
                else:
                    processes.append(snapshot)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if limit > 0:
            process_heap.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            return [item[3] for item in process_heap]
        processes.sort(key=lambda item: (item.cpu_percent, item.ram_mb), reverse=True)
        return processes

    def _cleanup_exe_path_cache(self, now_monotonic: float) -> None:
        if now_monotonic - self._last_exe_cache_cleanup < self._exe_cache_ttl_seconds:
            return
        self._last_exe_cache_cleanup = now_monotonic
        stale = [pid for pid, (_, expires_at) in self._exe_path_cache.items() if expires_at <= now_monotonic]
        for pid in stale:
            self._exe_path_cache.pop(pid, None)

    def _resolve_exe_path(self, proc: object, pid: int, now_monotonic: float) -> str | None:
        cached = self._exe_path_cache.get(pid)
        if cached is not None:
            value, expires_at = cached
            if expires_at > now_monotonic:
                return value

        exe_path: str | None = None
        try:
            proc_exe = proc.exe()  # type: ignore[attr-defined]
            if proc_exe:
                exe_path = str(proc_exe)
        except (AttributeError, psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            exe_path = None

        self._exe_path_cache[pid] = (exe_path, now_monotonic + self._exe_cache_ttl_seconds)
        return exe_path

    @staticmethod
    def _counter_value(counter: object, attr: str) -> int | None:
        if counter is None:
            return None
        value = getattr(counter, attr, None)
        if value is None:
            return None
        return int(value)

    def _prime_process_cpu_percent(self) -> None:
        for proc in psutil.process_iter():
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def _poll_gpu_percent(self, now_monotonic: float) -> float | None:
        if not self._is_windows:
            return None
        if now_monotonic < self._next_gpu_probe:
            return self._cached_gpu

        self._next_gpu_probe = now_monotonic + self._gpu_probe_interval_seconds
        self._cached_gpu = self._read_gpu_from_windows_perf()
        return self._cached_gpu

    def _read_gpu_from_windows_perf(self) -> float | None:
        # GPU counter can be unavailable on some systems; fail softly.
        command = (
            "$ErrorActionPreference='Stop';"
            "$samples=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage').CounterSamples;"
            "$samples | ForEach-Object { $_.CookedValue }"
        )

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=0.25,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0:
            return None

        values = list(self._parse_float_lines(completed.stdout))
        if not values:
            return None

        gpu_percent = max(values)
        return max(0.0, min(100.0, round(gpu_percent, 1)))

    @staticmethod
    def _parse_float_lines(raw_output: str) -> Iterable[float]:
        for line in raw_output.splitlines():
            candidate = line.strip().replace(",", ".")
            if not candidate:
                continue
            try:
                value = float(candidate)
            except ValueError:
                continue
            if value >= 0:
                yield value
