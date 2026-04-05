from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import (
        AudioUtilities,
        IAudioEndpointVolume,
        ISimpleAudioVolume,
    )
    _PYCAW_AVAILABLE = True
except ImportError:
    _PYCAW_AVAILABLE = False


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
