from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(slots=True)
class TempSnapshot:
    cpu_temp: float | None
    gpu_temp: float | None
    status: str


class TempMonitorService:
    def __init__(self) -> None:
        self._wmi_obj = None
        self._gputil_available = False
        self._psutil_temps = False

        # Try psutil sensors
        try:
            import psutil
            result = psutil.sensors_temperatures()
            self._psutil_temps = bool(result)
        except Exception:
            self._psutil_temps = False

        # Try GPUtil
        try:
            import GPUtil  # noqa: F401
            self._gputil_available = True
        except Exception:
            self._gputil_available = False

        # Try WMI (Windows only)
        if os.name == "nt" and not self._psutil_temps:
            try:
                import wmi
                self._wmi_obj = wmi.WMI(namespace="root/wmi")
            except Exception:
                try:
                    import wmi
                    self._wmi_obj = wmi.WMI()
                except Exception:
                    self._wmi_obj = None

    def get_snapshot(self) -> TempSnapshot:
        cpu = self._read_cpu_temp()
        gpu = self._read_gpu_temp()

        if cpu is None and gpu is None:
            status = "Нет данных"
        elif os.name != "nt" and cpu is None:
            status = "Windows only"
        else:
            status = "OK"

        return TempSnapshot(cpu_temp=cpu, gpu_temp=gpu, status=status)

    def backend_info(self) -> str:
        parts = []
        if self._psutil_temps:
            parts.append("psutil")
        if self._wmi_obj is not None:
            parts.append("WMI")
        if self._gputil_available:
            parts.append("GPUtil")
        return ", ".join(parts) if parts else "Недоступно"

    def close(self) -> None:
        pass

    # --- private ---

    def _read_cpu_temp(self) -> float | None:
        # 1. Try psutil sensors
        if self._psutil_temps:
            try:
                import psutil
                sensors = psutil.sensors_temperatures()
                for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                    if key in sensors and sensors[key]:
                        temps = [e.current for e in sensors[key] if e.current and e.current > 0]
                        if temps:
                            return round(sum(temps) / len(temps), 1)
                # Any available sensor
                for entries in sensors.values():
                    temps = [e.current for e in entries if e.current and e.current > 10]
                    if temps:
                        return round(sum(temps) / len(temps), 1)
            except Exception:
                pass

        # 2. WMI MSAcpi_ThermalZoneTemperature
        if self._wmi_obj is not None:
            try:
                zones = self._wmi_obj.MSAcpi_ThermalZoneTemperature()
                temps = []
                for z in zones:
                    raw = getattr(z, "CurrentTemperature", None)
                    if raw and raw > 2000:  # raw in tenths of Kelvin
                        celsius = raw / 10.0 - 273.15
                        if 0 < celsius < 120:
                            temps.append(celsius)
                if temps:
                    return round(sum(temps) / len(temps), 1)
            except Exception:
                pass

        return None

    def _read_gpu_temp(self) -> float | None:
        # 1. Try GPUtil
        if self._gputil_available:
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    temp = gpus[0].temperature
                    if temp and temp > 0:
                        return float(temp)
            except Exception:
                pass

        # 2. WMI Win32_VideoController (limited support)
        if self._wmi_obj is not None:
            try:
                c = self._wmi_obj
                for vc in c.Win32_VideoController():
                    temp = getattr(vc, "CurrentTemperature", None)
                    if temp and temp > 2000:
                        celsius = temp / 10.0 - 273.15
                        if 0 < celsius < 120:
                            return round(celsius, 1)
            except Exception:
                pass

        return None
