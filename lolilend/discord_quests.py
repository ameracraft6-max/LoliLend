
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Protocol

import requests

from lolilend.runtime import asset_path


DISCORD_DETECTABLE_ENDPOINTS = (
    "https://discord.com/api/applications/detectable",
    "https://discord.com/api/v9/applications/detectable",
)
DETECTABLE_MIRROR_URL = "https://markterence.github.io/discord-quest-completer/detectable.json"
DETECTABLE_SNAPSHOT_PATH = asset_path("runtime", "discord_quest", "detectable.snapshot.json")
RUNNER_TEMPLATE_PATH = asset_path("runtime", "discord_quest", "runner_template.exe")
_LOGGER_NAME = "discord-quests"
_ILLEGAL_WIN_PATH_CHARS = re.compile(r'[<>:"|?*]')


@dataclass(slots=True)
class DiscordQuestConfig:
    warning_ack: bool = False
    selected_app_ids: list[str] = field(default_factory=list)

    def normalized(self) -> "DiscordQuestConfig":
        seen: set[str] = set()
        values: list[str] = []
        for app_id in self.selected_app_ids:
            value = str(app_id).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        return DiscordQuestConfig(
            warning_ack=bool(self.warning_ack),
            selected_app_ids=values,
        )


@dataclass(slots=True)
class DetectableExecutable:
    name: str
    os: str
    is_launcher: bool = False

    @property
    def key(self) -> str:
        return f"{self.os}:{self.name}"


@dataclass(slots=True)
class DetectableGame:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    executables: list[DetectableExecutable] = field(default_factory=list)


@dataclass(slots=True)
class DiscordQuestExecutable:
    name: str
    os: str
    key: str
    path: str
    filename: str
    segments: int
    is_installed: bool = False
    is_running: bool = False


@dataclass(slots=True)
class DiscordQuestGame:
    uid: str
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    executables: list[DiscordQuestExecutable] = field(default_factory=list)
    is_installed: bool = False
    is_running: bool = False


@dataclass(slots=True)
class DiscordQuestStatus:
    running_map: dict[str, bool]
    last_error: str
    last_refresh: str
    source_used: str
    log_path: str
    rpc_connected: bool
    rpc_connecting: bool


@dataclass(slots=True)
class DiscordQuestLogEntry:
    timestamp: str
    level: str
    message: str


@dataclass(slots=True)
class _RunningProcess:
    run_key: str
    game_uid: str
    executable_key: str
    pid: int
    path: Path
    executable_name: str
    process: subprocess.Popen[Any]


class RpcClientProtocol(Protocol):
    def connect(self) -> None: ...

    def update(self, **kwargs: Any) -> None: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


class DiscordQuestStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        appdata = os.getenv("APPDATA")
        if appdata:
            base = Path(appdata) / app_name
        else:
            base = Path.home() / f".{app_name.lower()}"
        self.base_dir = base
        self.config_path = base / "discord_quest.json"
        self.cache_path = base / "discord_quest_cache.json"
        self.log_path = base / "discord_quest.log"

    def load_config(self) -> DiscordQuestConfig:
        raw = self._load_json_file(self.config_path)
        selected = raw.get("selected_app_ids", [])
        if not isinstance(selected, list):
            selected = []
        config = DiscordQuestConfig(
            warning_ack=bool(raw.get("warning_ack", False)),
            selected_app_ids=[str(item).strip() for item in selected if str(item).strip()],
        )
        return config.normalized()

    def save_config(self, config: DiscordQuestConfig) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "warning_ack": bool(config.warning_ack),
            "selected_app_ids": list(config.selected_app_ids),
        }
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_cache(self) -> tuple[dict[str, DetectableGame], str, str]:
        raw = self._load_json_file(self.cache_path)
        source = str(raw.get("source", "none"))
        last_refresh = str(raw.get("last_refresh", ""))
        detectable_raw = raw.get("detectable_games", {})
        result: dict[str, DetectableGame] = {}
        if isinstance(detectable_raw, dict):
            for app_id, item in detectable_raw.items():
                if not isinstance(item, dict):
                    continue
                executables: list[DetectableExecutable] = []
                for ex in item.get("executables", []) if isinstance(item.get("executables"), list) else []:
                    if not isinstance(ex, dict):
                        continue
                    name = str(ex.get("name", "")).strip()
                    os_name = str(ex.get("os", "")).strip()
                    if not name:
                        continue
                    executables.append(
                        DetectableExecutable(
                            name=name,
                            os=os_name,
                            is_launcher=bool(ex.get("is_launcher", False)),
                        )
                    )
                app_key = str(app_id).strip()
                if not app_key:
                    continue
                result[app_key] = DetectableGame(
                    id=app_key,
                    name=str(item.get("name", "")).strip() or app_key,
                    aliases=[str(alias) for alias in item.get("aliases", []) if str(alias).strip()],
                    executables=executables,
                )
        return result, source, last_refresh

    def save_cache(self, detectable_games: dict[str, DetectableGame], source: str, last_refresh: str) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": str(source),
            "last_refresh": str(last_refresh),
            "detectable_games": {
                app_id: {
                    "id": game.id,
                    "name": game.name,
                    "aliases": list(game.aliases),
                    "executables": [asdict(executable) for executable in game.executables],
                }
                for app_id, game in detectable_games.items()
            },
        }
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _load_json_file(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}


class DiscordQuestService:
    def __init__(
        self,
        store: DiscordQuestStore | None = None,
        http_client: Any | None = None,
        popen_factory: Any | None = None,
    ) -> None:
        self._store = store or DiscordQuestStore()
        self._http = http_client or requests
        self._popen_factory = popen_factory or subprocess.Popen
        self._lock = threading.RLock()
        self._detectable_by_id: dict[str, DetectableGame] = {}
        self._selected_games: list[DiscordQuestGame] = []
        self._running: dict[str, _RunningProcess] = {}
        self._last_error = ""
        self._last_refresh = ""
        self._source_used = "none"
        self._event_logs: list[DiscordQuestLogEntry] = []
        self._rpc_client: RpcClientProtocol | None = None
        self._rpc_connected = False
        self._rpc_connecting = False

        self._logger = logging.getLogger(_LOGGER_NAME)
        self._configure_logging()

        self._config = self._store.load_config()
        cache, source, last_refresh = self._store.load_cache()
        self._detectable_by_id = cache
        self._source_used = source or "none"
        self._last_refresh = last_refresh
        self._sync_selected_games(self._config.selected_app_ids)

    def load_config(self) -> DiscordQuestConfig:
        with self._lock:
            return DiscordQuestConfig(
                warning_ack=self._config.warning_ack,
                selected_app_ids=list(self._config.selected_app_ids),
            )

    def save_config(self, config: DiscordQuestConfig) -> None:
        normalized = config.normalized()
        with self._lock:
            self._config = normalized
        self._store.save_config(normalized)

    def refresh_catalog(self) -> tuple[bool, str, list[DetectableGame]]:
        try:
            by_id, source = self._fetch_detectable_games()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = str(exc)
            self._add_log("error", f"Catalog refresh failed: {exc}")
            with self._lock:
                games = self.catalog_games()
            if games:
                return False, f"Catalog refresh failed: {exc}. Using cached catalog.", games
            return False, f"Catalog refresh failed: {exc}", []

        last_refresh = _now_iso()
        with self._lock:
            self._detectable_by_id = by_id
            self._source_used = source
            self._last_refresh = last_refresh
            self._last_error = ""
            selected_ids = list(self._config.selected_app_ids)
        self._store.save_cache(by_id, source, last_refresh)
        self._sync_selected_games(selected_ids)
        self._add_log("info", f"Catalog refreshed from {source}: {len(by_id)} games")
        return True, f"Catalog refreshed ({len(by_id)} games).", self.catalog_games()

    def catalog_games(self) -> list[DetectableGame]:
        values: list[DetectableGame] = []
        with self._lock:
            for game in self._detectable_by_id.values():
                executables = [
                    DetectableExecutable(
                        name=executable.name,
                        os=executable.os,
                        is_launcher=bool(executable.is_launcher),
                    )
                    for executable in game.executables
                ]
                values.append(
                    DetectableGame(
                        id=game.id,
                        name=game.name,
                        aliases=list(game.aliases),
                        executables=executables,
                    )
                )
        values.sort(key=lambda item: item.name.lower())
        return values

    def selected_games(self) -> list[DiscordQuestGame]:
        values: list[DiscordQuestGame] = []
        with self._lock:
            for game in self._selected_games:
                executables = [
                    DiscordQuestExecutable(
                        name=value.name,
                        os=value.os,
                        key=value.key,
                        path=value.path,
                        filename=value.filename,
                        segments=int(value.segments),
                        is_installed=bool(value.is_installed),
                        is_running=bool(value.is_running),
                    )
                    for value in game.executables
                ]
                values.append(
                    DiscordQuestGame(
                        uid=game.uid,
                        id=game.id,
                        name=game.name,
                        aliases=list(game.aliases),
                        executables=executables,
                        is_installed=bool(game.is_installed),
                        is_running=bool(game.is_running),
                    )
                )
        return values

    def add_game(self, app_id: str) -> tuple[bool, str]:
        target = str(app_id).strip()
        if not target:
            return False, "Game id is required."
        with self._lock:
            detectable = self._detectable_by_id.get(target)
            if detectable is None:
                return False, "Game is not found in detectable catalog."
            for game in self._selected_games:
                if game.id == target:
                    return True, "Game is already added."
            selected = self._build_selected_game(detectable)
            self._selected_games.append(selected)
            self._config.selected_app_ids = [value.id for value in self._selected_games]
            config = self._config.normalized()
            self._config = config
        self._store.save_config(config)
        self._add_log("info", f"Added game: {selected.name}")
        return True, f"Added game: {selected.name}"

    def remove_game(self, uid: str) -> tuple[bool, str]:
        target = str(uid).strip()
        if not target:
            return False, "Game uid is required."
        self._stop_by_uid(target)
        removed_name = ""
        with self._lock:
            updated: list[DiscordQuestGame] = []
            for game in self._selected_games:
                if game.uid == target:
                    removed_name = game.name
                    continue
                updated.append(game)
            if not removed_name:
                return False, "Selected game is not found."
            self._selected_games = updated
            self._config.selected_app_ids = [value.id for value in self._selected_games]
            config = self._config.normalized()
            self._config = config
        self._store.save_config(config)
        self._add_log("info", f"Removed game: {removed_name}")
        return True, f"Removed game: {removed_name}"

    def install_and_play(self, uid: str, executable_key: str) -> tuple[bool, str]:
        ok, message = self._ensure_installed(uid, executable_key)
        if not ok:
            return False, message
        return self.play(uid, executable_key)

    def play(self, uid: str, executable_key: str) -> tuple[bool, str]:
        game, executable = self._resolve_game_and_executable(uid, executable_key)
        if game is None or executable is None:
            return False, "Game/executable selection is invalid."

        with self._lock:
            run_key = self._make_run_key(game.uid, executable.key)
            running = self._running.get(run_key)
            if running is not None and running.process.poll() is None:
                return True, "Executable is already running."

        target_path = self._target_executable_path(game.id, executable.path, executable.filename)
        if not target_path.exists():
            return False, "Dummy executable is missing. Use Install & Play first."

        process = self._spawn_process(target_path, game.name)
        if process is None:
            with self._lock:
                self._last_error = "Failed to launch executable."
            self._add_log("error", f"Failed to launch executable: {target_path}")
            return False, "Failed to launch executable."

        with self._lock:
            self._running[run_key] = _RunningProcess(
                run_key=run_key,
                game_uid=game.uid,
                executable_key=executable.key,
                pid=int(process.pid),
                path=target_path.resolve(),
                executable_name=executable.filename,
                process=process,
            )
            self._mark_runtime_state_locked(game.uid, executable.key, running=True)
            self._last_error = ""
        self._add_log("info", f"Started: {game.name} ({executable.filename})")
        return True, f"Started: {executable.filename}"

    def stop(self, uid: str, executable_key: str) -> tuple[bool, str]:
        game, executable = self._resolve_game_and_executable(uid, executable_key)
        if game is None or executable is None:
            return False, "Game/executable selection is invalid."

        run_key = self._make_run_key(game.uid, executable.key)
        with self._lock:
            entry = self._running.get(run_key)
        if entry is None:
            with self._lock:
                self._mark_runtime_state_locked(game.uid, executable.key, running=False)
            return True, "Executable is not running."

        ok, message = self._stop_entry(entry)
        with self._lock:
            self._running.pop(run_key, None)
            self._mark_runtime_state_locked(game.uid, executable.key, running=False)
            if not ok:
                self._last_error = message
        if ok:
            self._add_log("info", f"Stopped: {game.name} ({executable.filename})")
        else:
            self._add_log("error", f"Failed to stop {game.name}: {message}")
        return ok, message

    def rpc_connect(self, app_id: str) -> tuple[bool, str]:
        target = str(app_id).strip()
        if not target:
            return False, "App id is required for RPC."
        with self._lock:
            if self._rpc_connected:
                return True, "RPC is already connected."
            self._rpc_connecting = True

        try:
            client = self._create_rpc_client(target)
            client.connect()
            client.update(details="Playing via LoliLend", state="Discord Quest", start=int(time.time()))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._rpc_connecting = False
                self._rpc_connected = False
                self._rpc_client = None
                self._last_error = str(exc)
            self._add_log("error", f"RPC connect failed: {exc}")
            return False, f"RPC connect failed: {exc}"

        with self._lock:
            self._rpc_client = client
            self._rpc_connected = True
            self._rpc_connecting = False
            self._last_error = ""
        self._add_log("info", f"RPC connected for app id {target}")
        return True, "RPC connected."

    def rpc_disconnect(self) -> tuple[bool, str]:
        with self._lock:
            client = self._rpc_client
            self._rpc_client = None
            self._rpc_connected = False
            self._rpc_connecting = False
        if client is not None:
            try:
                client.clear()
            except Exception:  # noqa: BLE001
                pass
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        self._add_log("info", "RPC disconnected")
        return True, "RPC disconnected."

    def event_logs(self) -> list[DiscordQuestLogEntry]:
        with self._lock:
            return [
                DiscordQuestLogEntry(
                    timestamp=item.timestamp,
                    level=item.level,
                    message=item.message,
                )
                for item in self._event_logs
            ]

    def status(self) -> DiscordQuestStatus:
        with self._lock:
            running_map: dict[str, bool] = {}
            stale_keys: list[str] = []
            for run_key, entry in self._running.items():
                active = entry.process.poll() is None
                if active:
                    running_map[run_key] = True
                else:
                    stale_keys.append(run_key)
            for run_key in stale_keys:
                stale = self._running.pop(run_key, None)
                if stale is not None:
                    self._mark_runtime_state_locked(stale.game_uid, stale.executable_key, running=False)
            return DiscordQuestStatus(
                running_map=running_map,
                last_error=self._last_error,
                last_refresh=self._last_refresh,
                source_used=self._source_used,
                log_path=str(self._store.log_path),
                rpc_connected=self._rpc_connected,
                rpc_connecting=self._rpc_connecting,
            )

    def shutdown(self) -> None:
        for run_key in list(self.status().running_map.keys()):
            with self._lock:
                entry = self._running.get(run_key)
            if entry is None:
                continue
            _ok, _message = self._stop_entry(entry)
            with self._lock:
                self._running.pop(run_key, None)
                self._mark_runtime_state_locked(entry.game_uid, entry.executable_key, running=False)
        self.rpc_disconnect()
        self._close_logging_handlers()

    def ensure_dummy_executable(self, app_id: str, executable_path: str, executable_name: str) -> Path:
        if not RUNNER_TEMPLATE_PATH.exists():
            raise RuntimeError(f"Runner template is missing: {RUNNER_TEMPLATE_PATH}")

        target_path = self._target_executable_path(app_id, executable_path, executable_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        template_size = RUNNER_TEMPLATE_PATH.stat().st_size
        if not target_path.exists() or target_path.stat().st_size != template_size:
            shutil.copy2(RUNNER_TEMPLATE_PATH, target_path)
        return target_path

    def _sync_selected_games(self, selected_app_ids: list[str]) -> None:
        with self._lock:
            previous_by_id = {game.id: game for game in self._selected_games}
            synced: list[DiscordQuestGame] = []
            for app_id in selected_app_ids:
                detectable = self._detectable_by_id.get(app_id)
                if detectable is None:
                    continue
                previous = previous_by_id.get(app_id)
                synced.append(self._build_selected_game(detectable, previous=previous))
            self._selected_games = synced
            self._config.selected_app_ids = [value.id for value in self._selected_games]

    def _ensure_installed(self, uid: str, executable_key: str) -> tuple[bool, str]:
        game, executable = self._resolve_game_and_executable(uid, executable_key)
        if game is None or executable is None:
            return False, "Game/executable selection is invalid."
        if executable.os.lower() in {"linux", "darwin"}:
            return False, "Only Windows/Android executables are supported in v1."

        target_path = self.ensure_dummy_executable(
            app_id=game.id,
            executable_path=executable.path,
            executable_name=executable.filename,
        )
        installed = target_path.exists()
        with self._lock:
            self._mark_install_state_locked(game.uid, executable.key, installed)
        if installed:
            self._add_log("info", f"Installed dummy executable: {target_path.name}")
            return True, f"Installed: {target_path.name}"
        return False, "Failed to install dummy executable."

    def _resolve_game_and_executable(self, uid: str, executable_key: str) -> tuple[DiscordQuestGame | None, DiscordQuestExecutable | None]:
        uid_value = str(uid).strip()
        key_value = str(executable_key).strip()
        if not uid_value or not key_value:
            return None, None
        with self._lock:
            for game in self._selected_games:
                if game.uid != uid_value:
                    continue
                for executable in game.executables:
                    if executable.key == key_value:
                        return game, executable
        return None, None

    def _make_run_key(self, uid: str, executable_key: str) -> str:
        return f"{uid}|{executable_key}"

    def _stop_by_uid(self, uid: str) -> None:
        target = str(uid).strip()
        if not target:
            return
        with self._lock:
            entries = [entry for entry in self._running.values() if entry.game_uid == target]
        for entry in entries:
            _ok, _msg = self._stop_entry(entry)
            with self._lock:
                self._running.pop(entry.run_key, None)
                self._mark_runtime_state_locked(entry.game_uid, entry.executable_key, running=False)

    def _stop_entry(self, entry: _RunningProcess) -> tuple[bool, str]:
        process = entry.process
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.5)
            except Exception:  # noqa: BLE001
                pass

        if process.poll() is None:
            try:
                completed = subprocess.run(
                    ["taskkill", "/F", "/IM", entry.executable_name],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            except Exception as exc:  # noqa: BLE001
                return False, f"taskkill failed: {exc}"
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                stdout = (completed.stdout or "").strip()
                details = stderr or stdout or f"exit={completed.returncode}"
                return False, f"Unable to stop process: {details}"

        return True, "Process stopped."

    def _target_executable_path(self, app_id: str, executable_path: str, executable_name: str) -> Path:
        segments = _normalize_relative_path(executable_path)
        app_segment = _sanitize_filename(app_id) or "unknown"
        filename = _sanitize_filename(executable_name) or "game.exe"
        if not filename.lower().endswith(".exe"):
            filename = f"{filename}.exe"
        folder = self._games_root() / app_segment
        for segment in segments:
            folder = folder / segment
        return folder / filename

    def _games_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "games"
        return Path.cwd() / "games"

    def _spawn_process(self, executable_path: Path, game_name: str) -> subprocess.Popen[Any] | None:
        command = [str(executable_path), "--title", game_name]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        kwargs: dict[str, Any] = {
            "cwd": str(executable_path.parent),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if creation_flags:
            kwargs["creationflags"] = creation_flags
        try:
            return self._popen_factory(command, **kwargs)
        except TypeError:
            try:
                return self._popen_factory(command, cwd=str(executable_path.parent))
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None

    def _build_selected_game(
        self,
        detectable: DetectableGame,
        previous: DiscordQuestGame | None = None,
    ) -> DiscordQuestGame:
        previous_exec: dict[str, DiscordQuestExecutable] = {}
        if previous is not None:
            previous_exec = {value.key: value for value in previous.executables}

        executables: list[DiscordQuestExecutable] = []
        for raw_executable in detectable.executables:
            if not _is_valid_executable_name(raw_executable.name):
                continue
            if str(raw_executable.os).lower() in {"linux", "darwin"}:
                continue
            path_part, filename = _split_executable_name(raw_executable.name)
            key = raw_executable.key
            target_path = self._target_executable_path(detectable.id, path_part, filename)
            prior = previous_exec.get(key)
            executable = DiscordQuestExecutable(
                name=raw_executable.name,
                os=raw_executable.os,
                key=key,
                path=path_part,
                filename=filename,
                segments=max(1, len(_normalize_relative_path(raw_executable.name))),
                is_installed=target_path.exists(),
                is_running=(prior.is_running if prior is not None else False),
            )
            if prior is not None:
                executable.is_installed = executable.is_installed or prior.is_installed
            executables.append(executable)

        uid = previous.uid if previous is not None else secrets.token_hex(8)
        game = DiscordQuestGame(
            uid=uid,
            id=detectable.id,
            name=detectable.name,
            aliases=list(detectable.aliases),
            executables=executables,
            is_installed=any(value.is_installed for value in executables),
            is_running=any(value.is_running for value in executables),
        )
        return game

    def _mark_install_state_locked(self, uid: str, executable_key: str, installed: bool) -> None:
        for game in self._selected_games:
            if game.uid != uid:
                continue
            for executable in game.executables:
                if executable.key == executable_key:
                    executable.is_installed = bool(installed)
            game.is_installed = any(value.is_installed for value in game.executables)

    def _mark_runtime_state_locked(self, uid: str, executable_key: str, running: bool) -> None:
        for game in self._selected_games:
            if game.uid != uid:
                continue
            for executable in game.executables:
                if executable.key == executable_key:
                    executable.is_running = bool(running)
            game.is_running = any(value.is_running for value in game.executables)

    def _fetch_detectable_games(self) -> tuple[dict[str, DetectableGame], str]:
        sources = [
            ("mirror", (DETECTABLE_MIRROR_URL,)),
            ("discord_api", DISCORD_DETECTABLE_ENDPOINTS),
            ("snapshot", (str(DETECTABLE_SNAPSHOT_PATH),)),
        ]
        last_error = "Unknown error"
        for source_name, endpoints in sources:
            for endpoint in endpoints:
                try:
                    payload = self._load_payload(endpoint, source_name)
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    continue
                parsed = _parse_detectable_games(payload)
                if parsed:
                    return {item.id: item for item in parsed}, source_name
        raise RuntimeError(f"Unable to fetch detectable games: {last_error}")

    def _load_payload(self, endpoint: str, source_name: str) -> Any:
        if source_name == "snapshot":
            path = Path(endpoint)
            if not path.exists():
                raise RuntimeError(f"Snapshot is missing: {path}")
            return json.loads(path.read_text(encoding="utf-8"))
        response = self._http.get(
            endpoint,
            headers={"Accept": "application/json", "User-Agent": "LoliLend/2.0"},
            timeout=30,
        )
        status_code = int(getattr(response, "status_code", 0))
        if status_code >= 400:
            raise RuntimeError(f"{source_name} endpoint returned {status_code}")
        return response.json()

    def _create_rpc_client(self, app_id: str) -> RpcClientProtocol:
        try:
            from pypresence import Presence
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "RPC dependency is missing. Install `pypresence` to use Test RPC."
            ) from exc
        return Presence(app_id)

    def _configure_logging(self) -> None:
        self._store.base_dir.mkdir(parents=True, exist_ok=True)
        self._close_logging_handlers()
        handler = logging.FileHandler(self._store.log_path, encoding="utf-8")
        handler._lolilend_discord_quest_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

    def _close_logging_handlers(self) -> None:
        for handler in list(self._logger.handlers):
            if not getattr(handler, "_lolilend_discord_quest_handler", False):
                continue
            self._logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    def _add_log(self, level: str, message: str) -> None:
        value_level = str(level or "info").lower()
        value_message = str(message or "").strip()
        if not value_message:
            return
        timestamp = _now_iso()
        with self._lock:
            self._event_logs.append(
                DiscordQuestLogEntry(
                    timestamp=timestamp,
                    level=value_level,
                    message=value_message,
                )
            )
            if len(self._event_logs) > 300:
                self._event_logs = self._event_logs[-300:]
        log_method = {
            "debug": self._logger.debug,
            "warning": self._logger.warning,
            "error": self._logger.error,
        }.get(value_level, self._logger.info)
        log_method(value_message)


def _parse_detectable_games(payload: Any) -> list[DetectableGame]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("applications"), list):
            raw_items = payload.get("applications", [])
        elif isinstance(payload.get("data"), list):
            raw_items = payload.get("data", [])
        else:
            raw_items = []
    else:
        raw_items = []

    result: list[DetectableGame] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        app_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        if not app_id or not name:
            continue

        executables_raw = raw.get("executables", [])
        executables: list[DetectableExecutable] = []
        if isinstance(executables_raw, list):
            for executable in executables_raw:
                if not isinstance(executable, dict):
                    continue
                executable_name = str(executable.get("name", "")).strip()
                executable_os = str(executable.get("os", "")).strip()
                if not executable_name:
                    continue
                executables.append(
                    DetectableExecutable(
                        name=executable_name,
                        os=executable_os,
                        is_launcher=bool(executable.get("is_launcher", False)),
                    )
                )

        result.append(
            DetectableGame(
                id=app_id,
                name=name,
                aliases=[str(alias) for alias in raw.get("aliases", []) if str(alias).strip()],
                executables=executables,
            )
        )

    result.sort(key=lambda item: item.name.lower())
    return result


def _normalize_relative_path(raw_path: str) -> list[str]:
    text = str(raw_path or "").replace("\\", "/").strip("/")
    if not text:
        return []
    segments: list[str] = []
    for raw_segment in text.split("/"):
        segment = _sanitize_filename(raw_segment)
        if not segment or segment in {".", ".."}:
            continue
        segments.append(segment)
    return segments


def _split_executable_name(executable: str) -> tuple[str, str]:
    normalized = str(executable or "").replace("\\", "/").strip("/")
    if not normalized:
        return "", "game.exe"
    parts = [value for value in normalized.split("/") if value]
    if not parts:
        return "", "game.exe"
    filename = _sanitize_filename(parts[-1]) or "game.exe"
    directory = "/".join(_sanitize_filename(part) for part in parts[:-1] if _sanitize_filename(part))
    return directory, filename


def _sanitize_filename(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    value = _ILLEGAL_WIN_PATH_CHARS.sub("", value)
    value = value.rstrip(". ")
    return value


def _is_valid_executable_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if _ILLEGAL_WIN_PATH_CHARS.search(text):
        return False
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
