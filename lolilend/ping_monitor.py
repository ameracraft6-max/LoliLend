from __future__ import annotations

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class PingResult:
    host: str
    label: str
    ms: float | None
    status: str  # "OK" | "Timeout" | "Error"


@dataclass(slots=True)
class PingSnapshot:
    timestamp: datetime
    results: list[PingResult]


class PingMonitorService:
    DEFAULT_HOSTS: list[tuple[str, str]] = [
        ("8.8.8.8", "Google DNS"),
        ("1.1.1.1", "Cloudflare"),
        ("77.88.8.8", "Яндекс"),
    ]

    def __init__(self, hosts: list[tuple[str, str]] | None = None) -> None:
        self._hosts: list[tuple[str, str]] = hosts if hosts is not None else list(self.DEFAULT_HOSTS)
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ping")

    # --- public ---

    def get_snapshot(self) -> PingSnapshot:
        futures = {
            self._executor.submit(self._ping_host, host, label): (host, label)
            for host, label in self._hosts
        }
        results: list[PingResult] = []
        for future in as_completed(futures):
            results.append(future.result())

        # Preserve original order
        order = {host: i for i, (host, _) in enumerate(self._hosts)}
        results.sort(key=lambda r: order.get(r.host, 9999))

        return PingSnapshot(timestamp=datetime.now(), results=results)

    def set_hosts(self, hosts: list[tuple[str, str]]) -> None:
        self._hosts = list(hosts)

    def close(self) -> None:
        self._executor.shutdown(wait=False)

    # --- private ---

    def _ping_host(self, host: str, label: str) -> PingResult:
        ms = self.ping_one(host)
        if ms is None:
            return PingResult(host=host, label=label, ms=None, status="Timeout")
        return PingResult(host=host, label=label, ms=ms, status="OK")

    def ping_one(self, host: str) -> float | None:
        try:
            if os.name == "nt":
                cmd = ["ping", "-n", "1", "-w", "1000", host]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", host]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=_NO_WINDOW,
            )
            return self._parse_ping_output(result.stdout)
        except Exception:
            return None

    @staticmethod
    def _parse_ping_output(output: str) -> float | None:
        # Windows: "Время=12мс" or "время=12 мс" or "Time=12ms" or "time<1ms"
        # Linux/mac: "time=12.3 ms"
        patterns = [
            r"[Вв]ремя[<=]\s*(\d+(?:\.\d+)?)\s*мс",   # Russian Windows
            r"[Tt]ime[<=]\s*(\d+(?:\.\d+)?)\s*ms",      # English
            r"[Tt]ime[<=](\d+(?:\.\d+)?)",               # no unit
        ]
        for pat in patterns:
            m = re.search(pat, output)
            if m:
                return float(m.group(1))

        # Handle "time<1ms" → return 0.5
        if re.search(r"[Tt]ime\s*<\s*1", output):
            return 0.5
        if re.search(r"[Вв]ремя\s*<\s*1", output):
            return 0.5

        return None
