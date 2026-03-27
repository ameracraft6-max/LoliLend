from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

try:
    import psutil as _psutil
except ImportError:
    _psutil = None  # type: ignore[assignment]

from lolilend.monitoring import compute_counter_rate


@dataclass(slots=True)
class NetSpeedSnapshot:
    download_bps: float
    upload_bps: float
    timestamp: datetime


class NetSpeedService:
    def __init__(self) -> None:
        self._prev_bytes_recv: int | None = None
        self._prev_bytes_sent: int | None = None
        self._prev_time: float = time.monotonic()

        if _psutil is not None:
            try:
                counters = _psutil.net_io_counters()
                self._prev_bytes_recv = counters.bytes_recv
                self._prev_bytes_sent = counters.bytes_sent
            except Exception:
                pass

    def get_snapshot(self) -> NetSpeedSnapshot:
        if _psutil is None:
            return NetSpeedSnapshot(0.0, 0.0, datetime.now())

        try:
            counters = _psutil.net_io_counters()
        except Exception:
            return NetSpeedSnapshot(0.0, 0.0, datetime.now())

        now = time.monotonic()
        elapsed = max(now - self._prev_time, 0.01)

        download_bps = compute_counter_rate(self._prev_bytes_recv, counters.bytes_recv, elapsed)
        upload_bps = compute_counter_rate(self._prev_bytes_sent, counters.bytes_sent, elapsed)

        self._prev_bytes_recv = counters.bytes_recv
        self._prev_bytes_sent = counters.bytes_sent
        self._prev_time = now

        return NetSpeedSnapshot(
            download_bps=download_bps,
            upload_bps=upload_bps,
            timestamp=datetime.now(),
        )

    def close(self) -> None:
        pass
