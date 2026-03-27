from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


_RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_RUN_KEY_WOW = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"

_APPDATA = Path(os.environ.get("APPDATA", Path.home()))
_BACKUP_PATH = _APPDATA / "LoliLend" / "autostart_backup.json"

_STARTUP_FOLDERS: list[tuple[Path, str]] = []
try:
    _STARTUP_FOLDERS.append(
        (_APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup", "Папка")
    )
    _pd = os.environ.get("PROGRAMDATA", "")
    if _pd:
        _STARTUP_FOLDERS.append(
            (Path(_pd) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup", "Общая папка")
        )
except Exception:
    pass


@dataclass
class AutostartEntry:
    name: str
    command: str
    source: str   # "HKCU" | "HKLM" | "HKLM32" | "Папка" | "Общая папка"
    enabled: bool


def _load_backup() -> dict[str, str]:
    try:
        if _BACKUP_PATH.exists():
            data = json.loads(_BACKUP_PATH.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_backup(backup: dict[str, str]) -> None:
    try:
        _BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BACKUP_PATH.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class AutostartManager:
    def load_entries(self) -> list[AutostartEntry]:
        entries: list[AutostartEntry] = []
        if os.name != "nt":
            return entries

        try:
            import winreg
        except ImportError:
            return entries

        backup = _load_backup()
        disabled_names = set(backup.keys())

        reg_sources = [
            (winreg.HKEY_CURRENT_USER, _RUN_KEY, "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, _RUN_KEY, "HKLM"),
            (winreg.HKEY_LOCAL_MACHINE, _RUN_KEY_WOW, "HKLM32"),
        ]

        seen: set[str] = set()
        for hive, subkey, source in reg_sources:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, i)
                            uid = f"{source}:{name}"
                            if uid not in seen:
                                seen.add(uid)
                                entries.append(AutostartEntry(
                                    name=str(name),
                                    command=str(value),
                                    source=source,
                                    enabled=True,
                                ))
                            i += 1
                        except OSError:
                            break
            except OSError:
                pass

        # Add disabled entries from backup
        for name, command in backup.items():
            uid = f"disabled:{name}"
            if uid not in seen:
                seen.add(uid)
                entries.append(AutostartEntry(
                    name=name,
                    command=command,
                    source="HKCU",
                    enabled=False,
                ))

        # Startup folders
        for folder, source in _STARTUP_FOLDERS:
            if not folder.exists():
                continue
            for item in folder.iterdir():
                if item.suffix.lower() in {".lnk", ".exe", ".bat", ".cmd"}:
                    uid = f"{source}:{item.name}"
                    if uid not in seen:
                        seen.add(uid)
                        entries.append(AutostartEntry(
                            name=item.stem,
                            command=str(item),
                            source=source,
                            enabled=True,
                        ))
                elif item.suffix.lower() == ".disabled":
                    base = item.with_suffix("")
                    uid = f"{source}:{base.name}"
                    if uid not in seen:
                        seen.add(uid)
                        entries.append(AutostartEntry(
                            name=base.stem,
                            command=str(item),
                            source=source,
                            enabled=False,
                        ))

        return entries

    def disable_entry(self, entry: AutostartEntry) -> tuple[bool, str]:
        if not entry.enabled:
            return False, "Запись уже отключена"
        if os.name != "nt":
            return False, "Только Windows"

        if entry.source in {"HKCU", "HKLM", "HKLM32"}:
            return self._disable_registry(entry)
        return self._disable_folder(entry)

    def enable_entry(self, entry: AutostartEntry) -> tuple[bool, str]:
        if entry.enabled:
            return False, "Запись уже включена"
        if os.name != "nt":
            return False, "Только Windows"

        if entry.source in {"HKCU", "HKLM", "HKLM32"}:
            return self._enable_registry(entry)
        return self._enable_folder(entry)

    def delete_entry(self, entry: AutostartEntry) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Только Windows"

        if entry.source in {"HKCU", "HKLM", "HKLM32"}:
            return self._delete_registry(entry)
        return self._delete_folder(entry)

    # --- Registry ---

    def _disable_registry(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            import winreg
            hive = winreg.HKEY_CURRENT_USER if entry.source == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            subkey = _RUN_KEY_WOW if entry.source == "HKLM32" else _RUN_KEY
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, entry.name)
                except FileNotFoundError:
                    return False, "Запись не найдена в реестре"
                backup = _load_backup()
                backup[entry.name] = str(value)
                _save_backup(backup)
                winreg.DeleteValue(key, entry.name)
            return True, f"'{entry.name}' отключён"
        except OSError as e:
            return False, f"Ошибка реестра: {e}"

    def _enable_registry(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            import winreg
            backup = _load_backup()
            command = backup.get(entry.name, entry.command)
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_WRITE
            ) as key:
                winreg.SetValueEx(key, entry.name, 0, winreg.REG_SZ, command)
            backup.pop(entry.name, None)
            _save_backup(backup)
            return True, f"'{entry.name}' включён"
        except OSError as e:
            return False, f"Ошибка реестра: {e}"

    def _delete_registry(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            import winreg
            hive = winreg.HKEY_CURRENT_USER if entry.source == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            subkey = _RUN_KEY_WOW if entry.source == "HKLM32" else _RUN_KEY
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, entry.name)
            except FileNotFoundError:
                pass
            backup = _load_backup()
            backup.pop(entry.name, None)
            _save_backup(backup)
            return True, f"'{entry.name}' удалён"
        except OSError as e:
            return False, f"Ошибка реестра: {e}"

    # --- Folder ---

    def _disable_folder(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            path = Path(entry.command)
            if not path.exists():
                return False, "Файл не найден"
            path.rename(path.with_suffix(path.suffix + ".disabled"))
            return True, f"'{entry.name}' отключён"
        except OSError as e:
            return False, f"Ошибка: {e}"

    def _enable_folder(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            path = Path(entry.command)
            if not path.exists():
                return False, "Файл не найден"
            if path.suffix == ".disabled":
                path.rename(path.with_suffix(""))
            return True, f"'{entry.name}' включён"
        except OSError as e:
            return False, f"Ошибка: {e}"

    def _delete_folder(self, entry: AutostartEntry) -> tuple[bool, str]:
        try:
            path = Path(entry.command)
            if path.exists():
                path.unlink()
            backup = _load_backup()
            backup.pop(entry.name, None)
            _save_backup(backup)
            return True, f"'{entry.name}' удалён"
        except OSError as e:
            return False, f"Ошибка: {e}"
