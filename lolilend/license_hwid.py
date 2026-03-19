from __future__ import annotations

import hashlib
import logging
import os
import uuid

_log = logging.getLogger(__name__)

_cached_hwid: str | None = None


def get_hwid() -> str:
    """Return a stable 32-char hex HWID derived from CPU + Disk + MAC."""
    global _cached_hwid
    if _cached_hwid is not None:
        return _cached_hwid

    parts: list[str] = []

    # CPU ID via WMI
    if os.name == "nt":
        try:
            import wmi

            w = wmi.WMI()
            for cpu in w.Win32_Processor():
                pid = getattr(cpu, "ProcessorId", None)
                if pid:
                    parts.append(pid.strip())
                    break
        except Exception as exc:
            _log.debug("WMI CPU query failed: %s", exc)

    # System disk serial
    if os.name == "nt":
        try:
            import wmi

            w = wmi.WMI()
            for disk in w.Win32_DiskDrive():
                serial = getattr(disk, "SerialNumber", None)
                if serial:
                    parts.append(serial.strip())
                    break
        except Exception as exc:
            _log.debug("WMI Disk query failed: %s", exc)

    # MAC address (fallback-safe)
    try:
        mac = uuid.getnode()
        if mac and (mac >> 40) & 1 == 0:  # not a random MAC
            parts.append(format(mac, "012x"))
    except Exception as exc:
        _log.debug("MAC address retrieval failed: %s", exc)

    if not parts:
        parts.append("fallback-" + os.getlogin())

    raw = "|".join(parts)
    _cached_hwid = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return _cached_hwid
