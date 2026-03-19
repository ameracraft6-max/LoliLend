from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys


FPS_ELEVATION_FLAG = "--lolilend-fps-elevated"


def package_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "lolilend"
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    path = package_root() / "assets"
    for part in parts:
        path = path / part
    return path


def sanitize_argv(argv: Sequence[str] | None = None) -> list[str]:
    raw = list(argv or sys.argv)
    if not raw:
        return []
    return [raw[0], *[value for value in raw[1:] if value != FPS_ELEVATION_FLAG]]


class WindowsElevationManager:
    def __init__(
        self,
        argv: Sequence[str] | None = None,
        shell32: object | None = None,
        executable: str | None = None,
        working_directory: str | Path | None = None,
    ) -> None:
        self._argv = list(argv or sys.argv)
        self._shell32 = shell32
        self._executable = executable
        self._working_directory = str(working_directory or Path.cwd())
        self._was_relaunched_for_fps = FPS_ELEVATION_FLAG in self._argv[1:]

    @property
    def was_relaunched_for_fps(self) -> bool:
        return self._was_relaunched_for_fps

    def can_relaunch_for_fps(self) -> bool:
        return os.name == "nt" and not self._was_relaunched_for_fps

    def relaunch_for_fps(self) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Administrator restart is available on Windows only"
        if self._was_relaunched_for_fps:
            return False, "FPS restart already attempted in this session"

        executable, parameters = self._build_command()
        shell32 = self._shell32
        if shell32 is None:
            try:
                import ctypes

                shell32 = ctypes.windll.shell32
            except Exception as exc:
                return False, f"Administrator restart unavailable: {exc}"

        try:
            result = int(
                shell32.ShellExecuteW(
                    None,
                    "runas",
                    executable,
                    subprocess.list2cmdline(parameters),
                    self._working_directory,
                    1,
                )
            )
        except Exception as exc:
            return False, f"Administrator restart failed: {exc}"

        if result <= 32:
            return False, "Administrator restart was cancelled or denied"
        return True, "Restarting LoliLend with administrator privileges"

    def _build_command(self) -> tuple[str, list[str]]:
        filtered = sanitize_argv(self._argv)
        if getattr(sys, "frozen", False):
            executable = self._executable or sys.executable
            return executable, [*filtered[1:], FPS_ELEVATION_FLAG]

        executable = self._executable or sys.executable
        script_path = Path(filtered[0]).resolve()
        return executable, [str(script_path), *filtered[1:], FPS_ELEVATION_FLAG]
