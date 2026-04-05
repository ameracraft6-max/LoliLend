from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

try:
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import (
        AudioUtilities,
        IAudioEndpointVolume,
        ISimpleAudioVolume,
    )
    _PYCAW_AVAILABLE = True
except ImportError:
    _PYCAW_AVAILABLE = False

# IAudioMeterInformation GUID for peak level monitoring
_IID_IAudioMeterInformation = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"


@dataclass(slots=True)
class MicDevice:
    device_id: str
    name: str
    volume: float  # 0.0 - 1.0
    is_muted: bool
    is_default: bool
    peak_level: float  # 0.0 - 1.0 (live input level)


@dataclass(slots=True)
class AudioSession:
    pid: int
    name: str
    display_name: str
    volume: float  # 0.0 - 1.0
    is_muted: bool


@dataclass(slots=True)
class AudioDevice:
    id: str
    name: str
    is_default: bool


@dataclass(slots=True)
class SoundPreset:
    name: str
    volumes: dict[str, float] = field(default_factory=dict)
    muted: dict[str, bool] = field(default_factory=dict)


class SoundPresetStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        base = Path(os.getenv("APPDATA", Path.home()))
        self._path = base / app_name / "sound_presets.json"

    def load_presets(self) -> list[SoundPreset]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [
                SoundPreset(
                    name=p.get("name", ""),
                    volumes=p.get("volumes", {}),
                    muted=p.get("muted", {}),
                )
                for p in data
                if isinstance(p, dict)
            ]
        except Exception:
            return []

    def save_presets(self, presets: list[SoundPreset]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"name": p.name, "volumes": p.volumes, "muted": p.muted}
            for p in presets
        ]
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_preset(self, preset: SoundPreset) -> None:
        presets = [p for p in self.load_presets() if p.name != preset.name]
        presets.append(preset)
        self.save_presets(presets)

    def delete_preset(self, name: str) -> None:
        presets = [p for p in self.load_presets() if p.name != name]
        self.save_presets(presets)


class AudioManagerService:
    def __init__(self) -> None:
        self._store = SoundPresetStore()

    @staticmethod
    def available() -> bool:
        return _PYCAW_AVAILABLE

    def get_sessions(self) -> list[AudioSession]:
        if not _PYCAW_AVAILABLE:
            return []
        sessions: list[AudioSession] = []
        try:
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None:
                    continue
                try:
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    volume = vol.GetMasterVolume()
                    muted = bool(vol.GetMute())
                    sessions.append(AudioSession(
                        pid=proc.pid,
                        name=proc.name(),
                        display_name=proc.name().replace(".exe", ""),
                        volume=round(volume, 2),
                        is_muted=muted,
                    ))
                except Exception:
                    continue
        except Exception as exc:
            _log.debug("Get sessions failed: %s", exc)
        return sessions

    def set_session_volume(self, pid: int, volume: float) -> bool:
        if not _PYCAW_AVAILABLE:
            return False
        try:
            for session in AudioUtilities.GetAllSessions():
                if session.Process and session.Process.pid == pid:
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    vol.SetMasterVolume(max(0.0, min(1.0, volume)), None)
                    return True
        except Exception as exc:
            _log.debug("Set volume failed for PID %d: %s", pid, exc)
        return False

    def set_session_mute(self, pid: int, muted: bool) -> bool:
        if not _PYCAW_AVAILABLE:
            return False
        try:
            for session in AudioUtilities.GetAllSessions():
                if session.Process and session.Process.pid == pid:
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    vol.SetMute(int(muted), None)
                    return True
        except Exception as exc:
            _log.debug("Set mute failed for PID %d: %s", pid, exc)
        return False

    def get_master_volume(self) -> float:
        if not _PYCAW_AVAILABLE:
            return 0.0
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return round(volume.GetMasterVolumeLevelScalar(), 2)
        except Exception:
            return 0.0

    def set_master_volume(self, level: float) -> None:
        if not _PYCAW_AVAILABLE:
            return
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level)), None)
        except Exception as exc:
            _log.debug("Set master volume failed: %s", exc)

    def get_presets(self) -> list[SoundPreset]:
        return self._store.load_presets()

    def save_current_as_preset(self, name: str) -> SoundPreset:
        sessions = self.get_sessions()
        preset = SoundPreset(
            name=name,
            volumes={s.name: s.volume for s in sessions},
            muted={s.name: s.is_muted for s in sessions},
        )
        self._store.add_preset(preset)
        return preset

    def apply_preset(self, preset: SoundPreset) -> tuple[int, int]:
        applied = 0
        skipped = 0
        sessions = self.get_sessions()
        session_map = {s.name: s for s in sessions}
        for name, volume in preset.volumes.items():
            s = session_map.get(name)
            if s:
                self.set_session_volume(s.pid, volume)
                if name in preset.muted:
                    self.set_session_mute(s.pid, preset.muted[name])
                applied += 1
            else:
                skipped += 1
        return applied, skipped

    def delete_preset(self, name: str) -> None:
        self._store.delete_preset(name)

    # ------------------------------------------------------------------
    # Microphone / Input device management
    # ------------------------------------------------------------------

    def get_microphones(self) -> list[MicDevice]:
        """Enumerate all capture (input) devices with volume and peak level."""
        if not _PYCAW_AVAILABLE:
            return []
        mics: list[MicDevice] = []
        try:
            enumerator = comtypes.CoCreateInstance(
                comtypes.GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
                None, CLSCTX_ALL,
                comtypes.GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}"),
            )
            # Get default capture device ID
            default_id = ""
            try:
                default_dev = enumerator.GetDefaultAudioEndpoint(1, 0)  # eCapture, eConsole
                prop_store = default_dev.OpenPropertyStore(0)
                default_id = self._get_device_id_raw(default_dev)
            except Exception:
                pass

            # Enumerate capture devices (eCapture=1, DEVICE_STATE_ACTIVE=1)
            collection = enumerator.EnumAudioEndpoints(1, 1)
            count = collection.GetCount()

            for i in range(count):
                try:
                    device = collection.Item(i)
                    dev_id = self._get_device_id_raw(device)
                    name = self._get_device_name(device)

                    # Get volume
                    vol_iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    vol_ctrl = vol_iface.QueryInterface(IAudioEndpointVolume)
                    volume = round(vol_ctrl.GetMasterVolumeLevelScalar(), 2)
                    is_muted = bool(vol_ctrl.GetMute())

                    # Get peak level
                    peak = self._get_device_peak(device)

                    mics.append(MicDevice(
                        device_id=dev_id,
                        name=name,
                        volume=volume,
                        is_muted=is_muted,
                        is_default=(dev_id == default_id),
                        peak_level=peak,
                    ))
                except Exception as exc:
                    _log.debug("Mic enumeration error at index %d: %s", i, exc)
                    continue
        except Exception as exc:
            _log.debug("Microphone enumeration failed: %s", exc)
        return mics

    def set_mic_volume(self, device_id: str, volume: float) -> bool:
        device = self._find_capture_device(device_id)
        if device is None:
            return False
        try:
            iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            ctrl = iface.QueryInterface(IAudioEndpointVolume)
            ctrl.SetMasterVolumeLevelScalar(max(0.0, min(1.0, volume)), None)
            return True
        except Exception as exc:
            _log.debug("Set mic volume failed: %s", exc)
            return False

    def set_mic_mute(self, device_id: str, muted: bool) -> bool:
        device = self._find_capture_device(device_id)
        if device is None:
            return False
        try:
            iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            ctrl = iface.QueryInterface(IAudioEndpointVolume)
            ctrl.SetMute(int(muted), None)
            return True
        except Exception as exc:
            _log.debug("Set mic mute failed: %s", exc)
            return False

    def get_mic_peak(self, device_id: str) -> float:
        """Get real-time input peak level (0.0-1.0)."""
        device = self._find_capture_device(device_id)
        if device is None:
            return 0.0
        return self._get_device_peak(device)

    # ------------------------------------------------------------------
    # Internal helpers for device access
    # ------------------------------------------------------------------

    @staticmethod
    def _get_device_peak(device) -> float:
        """Get peak meter value from a device."""
        try:
            meter_iface = device.Activate(
                comtypes.GUID(_IID_IAudioMeterInformation), CLSCTX_ALL, None
            )
            # IAudioMeterInformation::GetPeakValue is at vtable index 3
            import ctypes
            get_peak = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.POINTER(ctypes.c_float))(3, "GetPeakValue")
            peak = ctypes.c_float()
            get_peak(meter_iface, ctypes.byref(peak))
            return round(max(0.0, min(1.0, peak.value)), 3)
        except Exception:
            return 0.0

    @staticmethod
    def _get_device_id_raw(device) -> str:
        try:
            return device.GetId()
        except Exception:
            return ""

    @staticmethod
    def _get_device_name(device) -> str:
        """Get friendly device name from property store."""
        try:
            prop_store = device.OpenPropertyStore(0)
            # PKEY_Device_FriendlyName = {A45C254E-DF1C-4EFD-8020-67D146A850E0}, 14
            from comtypes import GUID as _GUID
            import ctypes

            class _PROPERTYKEY(ctypes.Structure):
                _fields_ = [("fmtid", comtypes.GUID), ("pid", ctypes.c_ulong)]

            pkey = _PROPERTYKEY()
            pkey.fmtid = _GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}")
            pkey.pid = 14

            prop = prop_store.GetValue(ctypes.byref(pkey))
            name = str(prop)
            # Clean up PROPVARIANT string
            if name and name != "None":
                return name
        except Exception:
            pass
        return "Unknown Device"

    def _find_capture_device(self, device_id: str):
        """Find a capture device by ID."""
        if not _PYCAW_AVAILABLE:
            return None
        try:
            enumerator = comtypes.CoCreateInstance(
                comtypes.GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
                None, CLSCTX_ALL,
                comtypes.GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}"),
            )
            collection = enumerator.EnumAudioEndpoints(1, 1)  # eCapture, active
            for i in range(collection.GetCount()):
                device = collection.Item(i)
                if self._get_device_id_raw(device) == device_id:
                    return device
        except Exception:
            pass
        return None
