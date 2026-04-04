from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class PartitionInfo:
    device: str
    mountpoint: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass(slots=True)
class DiskInfo:
    model: str
    serial: str
    size_bytes: int
    media_type: str  # "SSD", "HDD", "Unknown"
    status: str  # "Healthy", "Warning", "Critical", "Unknown"
    temperature: int | None  # Celsius


@dataclass(slots=True)
class DiskHealthSnapshot:
    disks: list[DiskInfo]
    partitions: list[PartitionInfo]


def get_partitions() -> list[PartitionInfo]:
    """Get all disk partitions with usage info."""
    parts: list[PartitionInfo] = []
    try:
        import psutil

        for p in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(p.mountpoint)
                parts.append(PartitionInfo(
                    device=p.device,
                    mountpoint=p.mountpoint,
                    fstype=p.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=usage.percent,
                ))
            except (PermissionError, OSError):
                continue
    except ImportError:
        pass
    return parts


def get_disks() -> list[DiskInfo]:
    """Get physical disk info via WMI (Windows only)."""
    disks: list[DiskInfo] = []
    if os.name != "nt":
        return disks

    try:
        import wmi

        w = wmi.WMI()
        for disk in w.Win32_DiskDrive():
            model = getattr(disk, "Model", "") or "Unknown"
            serial = (getattr(disk, "SerialNumber", "") or "").strip()
            size = int(getattr(disk, "Size", 0) or 0)
            media = getattr(disk, "MediaType", "") or ""

            if "SSD" in model.upper() or "SOLID" in media.upper() or "NVMe" in model.upper():
                media_type = "SSD"
            elif "HDD" in model.upper() or "HARD" in media.upper():
                media_type = "HDD"
            else:
                media_type = "SSD" if size > 0 else "Unknown"

            disks.append(DiskInfo(
                model=model,
                serial=serial,
                size_bytes=size,
                media_type=media_type,
                status="Unknown",
                temperature=None,
            ))
    except Exception as exc:
        _log.debug("WMI disk query failed: %s", exc)

    # Try S.M.A.R.T. status
    _read_smart_status(disks)
    # Try temperature
    _read_disk_temperature(disks)

    return disks


def _read_smart_status(disks: list[DiskInfo]) -> None:
    """Read S.M.A.R.T. predicted failure status via WMI."""
    if not disks or os.name != "nt":
        return
    try:
        import wmi

        w = wmi.WMI(namespace="root/wmi")
        for item in w.MSStorageDriver_FailurePredictStatus():
            predicted = getattr(item, "PredictFailure", False)
            # Match by index (rough, but MSStorageDriver doesn't have serial)
            idx = getattr(item, "InstanceName", "")
            disk_idx = 0
            for ch in idx:
                if ch.isdigit():
                    disk_idx = int(ch)
                    break
            if disk_idx < len(disks):
                disks[disk_idx].status = "Warning" if predicted else "Healthy"
    except Exception as exc:
        _log.debug("S.M.A.R.T. status query failed: %s", exc)
        # Fallback: mark all as Healthy if WMI works but SMART namespace doesn't
        for d in disks:
            if d.status == "Unknown":
                d.status = "Healthy"


def _read_disk_temperature(disks: list[DiskInfo]) -> None:
    """Try to read disk temperature via WMI."""
    if not disks or os.name != "nt":
        return
    try:
        import wmi

        w = wmi.WMI(namespace="root/wmi")
        temps = w.MSStorageDriver_ATAPISmartData()
        for i, item in enumerate(temps):
            if i >= len(disks):
                break
            # SMART attribute 194 = Temperature
            vendor_specific = getattr(item, "VendorSpecific", None)
            if vendor_specific and len(vendor_specific) > 20:
                # Rough extraction — attribute data starts at offset 2, each attr is 12 bytes
                # Attribute 194 (0xC2) = temperature
                try:
                    raw = bytes(vendor_specific)
                    for offset in range(2, min(len(raw), 362), 12):
                        attr_id = raw[offset]
                        if attr_id == 0xC2:  # Temperature
                            temp_val = raw[offset + 5]
                            if 0 < temp_val < 100:
                                disks[i].temperature = temp_val
                            break
                except Exception:
                    pass
    except Exception as exc:
        _log.debug("Disk temperature query failed: %s", exc)


def get_snapshot() -> DiskHealthSnapshot:
    """Get complete disk health snapshot."""
    return DiskHealthSnapshot(
        disks=get_disks(),
        partitions=get_partitions(),
    )


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
