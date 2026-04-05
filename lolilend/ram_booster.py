from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None

PROTECTED_PROCESSES: frozenset[str] = frozenset({
    "explorer.exe", "csrss.exe", "winlogon.exe", "svchost.exe",
    "system", "system idle process", "registry", "smss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "dwm.exe",
    "conhost.exe", "fontdrvhost.exe", "lolilend.exe", "lolilend",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "textinputhost.exe", "sihost.exe", "ctfmon.exe",
})


@dataclass(slots=True)
class RamInfo:
    total_mb: float
    used_mb: float
    free_mb: float
    percent: float


@dataclass(slots=True)
class ProcessEntry:
    pid: int
    name: str
    ram_mb: float
    cpu_percent: float
    status: str
    is_protected: bool


@dataclass(slots=True)
class KillResult:
    freed_mb: float = 0.0
    killed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class RamBoosterService:
    def get_ram_info(self) -> RamInfo:
        if psutil is None:
            return RamInfo(0, 0, 0, 0)
        mem = psutil.virtual_memory()
        return RamInfo(
            total_mb=mem.total / (1024 * 1024),
            used_mb=mem.used / (1024 * 1024),
            free_mb=mem.available / (1024 * 1024),
            percent=mem.percent,
        )

    def get_processes(self, limit: int = 80) -> list[ProcessEntry]:
        if psutil is None:
            return []
        entries: list[ProcessEntry] = []
        my_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "status", "memory_info", "cpu_percent"]):
            try:
                info = proc.info
                pid = info["pid"]
                if pid == 0 or pid == 4 or pid == my_pid:
                    continue
                name = info.get("name") or ""
                mem = info.get("memory_info")
                ram_mb = (mem.rss / (1024 * 1024)) if mem else 0.0
                if ram_mb < 1:
                    continue
                entries.append(ProcessEntry(
                    pid=pid,
                    name=name,
                    ram_mb=round(ram_mb, 1),
                    cpu_percent=round(info.get("cpu_percent") or 0.0, 1),
                    status=info.get("status") or "",
                    is_protected=name.lower() in PROTECTED_PROCESSES,
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        entries.sort(key=lambda e: e.ram_mb, reverse=True)
        return entries[:limit]

    def kill_processes(self, pids: list[int]) -> KillResult:
        result = KillResult()
        if psutil is None:
            return result
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                name = proc.name().lower()
                if name in PROTECTED_PROCESSES:
                    result.errors.append(f"{name}: protected")
                    result.failed += 1
                    continue
                ram_before = proc.memory_info().rss / (1024 * 1024)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                result.freed_mb += ram_before
                result.killed += 1
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                result.errors.append(f"PID {pid}: access denied")
                result.failed += 1
            except Exception as exc:
                result.errors.append(f"PID {pid}: {exc}")
                result.failed += 1
        result.freed_mb = round(result.freed_mb, 1)
        return result
