from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

from lolilend.ai_security import WindowsCredentialStore

_YM_TOKEN_TARGET = "LoliLend.YandexMusic.Token"
_POLL_INTERVAL = 3.0          # seconds between media polls
_LOG_LIMIT = 50
_DISCORD_APP_ID = "1293868893034090526"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TrackInfo:
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    cover_url: str | None = None
    yandex_url: str | None = None

    def key(self) -> str:
        return f"{self.title}::{self.artist}"


@dataclass(slots=True)
class YandexMusicRpcConfig:
    enabled: bool = False
    source: str = "auto"
    discord_app_id: str = _DISCORD_APP_ID
    strong_find: bool = False


@dataclass(slots=True)
class YandexMusicRpcStatus:
    enabled: bool
    running: bool
    discord_connected: bool
    current_track: TrackInfo | None
    error: str | None
    log: list[str]


# ---------------------------------------------------------------------------
# Config store (JSON, no token — token goes to Windows Credential Manager)
# ---------------------------------------------------------------------------

class YandexMusicRpcStore:
    def __init__(self) -> None:
        base = Path(os.getenv("APPDATA", Path.home()))
        self._path = base / "LoliLend" / "yandex_music_rpc.json"
        self._token_store = WindowsCredentialStore(_YM_TOKEN_TARGET)

    def load(self) -> YandexMusicRpcConfig:
        try:
            if self._path.exists():
                raw: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
                cfg = YandexMusicRpcConfig()
                cfg.enabled = bool(raw.get("enabled", cfg.enabled))
                cfg.source = str(raw.get("source", cfg.source))
                cfg.discord_app_id = str(raw.get("discord_app_id", cfg.discord_app_id))
                cfg.strong_find = bool(raw.get("strong_find", cfg.strong_find))
                return cfg
        except Exception:
            pass
        return YandexMusicRpcConfig()

    def save(self, cfg: YandexMusicRpcConfig) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "enabled": cfg.enabled,
                "source": cfg.source,
                "discord_app_id": cfg.discord_app_id,
                "strong_find": cfg.strong_find,
            }
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_token(self) -> str:
        return self._token_store.read() or ""

    def save_token(self, token: str) -> bool:
        return self._token_store.write(token)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class YandexMusicRpcService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store = YandexMusicRpcStore()
        self._config = self._store.load()
        self._running = False
        self._thread: threading.Thread | None = None
        self._discord_connected = False
        self._rpc: Any = None
        self._ym_client: Any = None
        self._current_track: TrackInfo | None = None
        self._last_track_key: str = ""
        self._error: str | None = None
        self._log: list[str] = []
        self._shutdown = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> YandexMusicRpcStatus:
        with self._lock:
            return YandexMusicRpcStatus(
                enabled=self._config.enabled,
                running=self._running,
                discord_connected=self._discord_connected,
                current_track=self._current_track,
                error=self._error,
                log=list(self._log),
            )

    def update_config(self, cfg: YandexMusicRpcConfig) -> None:
        with self._lock:
            was_enabled = self._config.enabled
            self._config = cfg
            self._store.save(cfg)
            if cfg.enabled and not was_enabled:
                self._start_locked()
            elif not cfg.enabled and was_enabled:
                self._stop_locked()

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def shutdown(self) -> None:
        self._shutdown = True
        with self._lock:
            self._stop_locked()

    def reload_ym_client(self) -> None:
        """Force re-initialise the Yandex Music client (e.g. after token update)."""
        with self._lock:
            self._ym_client = None

    # ------------------------------------------------------------------
    # Internal start / stop
    # ------------------------------------------------------------------

    def _start_locked(self) -> None:
        if self._running:
            return
        self._running = True
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="YMRpc-worker")
        self._thread.start()
        self._log_entry("Сервис запущен")

    def _stop_locked(self) -> None:
        self._running = False
        self._clear_discord_rpc()
        self._log_entry("Сервис остановлен")

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break
                config = self._config

            try:
                raw = self._get_media_from_windows()
            except Exception as exc:
                self._set_error(f"Ошибка чтения медиа: {exc}")
                time.sleep(_POLL_INTERVAL)
                continue

            if raw is None:
                # Nothing playing — clear RPC if we had something
                with self._lock:
                    if self._last_track_key:
                        self._last_track_key = ""
                        self._current_track = None
                self._clear_discord_rpc()
                time.sleep(_POLL_INTERVAL)
                continue

            raw_key = f"{raw.get('title', '')}::{raw.get('artist', '')}"
            with self._lock:
                if raw_key == self._last_track_key:
                    time.sleep(_POLL_INTERVAL)
                    continue

            # New track — enrich via Yandex Music
            track = self._enrich_track(raw, config)
            with self._lock:
                self._last_track_key = raw_key
                self._current_track = track
                self._error = None

            self._log_entry(f"Трек: {track.artist} — {track.title}")
            self._update_discord_rpc(track, config)
            time.sleep(_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Windows Media Control
    # ------------------------------------------------------------------

    def _get_media_from_windows(self) -> dict[str, str] | None:
        try:
            return asyncio.run(self._get_media_async())
        except RuntimeError:
            # Event loop already running — create a new one in this thread
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._get_media_async())
            finally:
                loop.close()

    @staticmethod
    async def _get_media_async() -> dict[str, str] | None:
        try:
            import winrt.windows.media.control as wmc  # type: ignore[import]
        except ImportError:
            return None

        try:
            mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
            session = mgr.get_current_session()
            if session is None:
                return None

            props = await session.try_get_media_properties_async()
            title = (props.title or "").strip()
            artist = (props.artist or "").strip()
            album = (props.album_title or "").strip()

            if not title and not artist:
                return None

            return {"title": title, "artist": artist, "album": album}
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Yandex Music enrichment
    # ------------------------------------------------------------------

    def _enrich_track(self, raw: dict[str, str], config: YandexMusicRpcConfig) -> TrackInfo:
        title = raw.get("title", "")
        artist = raw.get("artist", "")
        album = raw.get("album") or None

        base = TrackInfo(title=title, artist=artist, album=album)
        if not title and not artist:
            return base

        try:
            client = self._get_ym_client()
            if client is None:
                return base

            query = f"{artist} {title}".strip()
            results = client.search(query, type_="track", nocorrect=config.strong_find)
            if not results or not results.tracks or not results.tracks.results:
                return base

            track = results.tracks.results[0]
            artists = ", ".join(a.name for a in (track.artists or []))
            albums = track.albums or []
            album_title = albums[0].title if albums else album
            cover_uri = track.cover_uri or (albums[0].cover_uri if albums else None)
            cover_url: str | None = None
            if cover_uri:
                cover_url = "https://" + cover_uri.replace("%%", "200x200")

            yandex_url: str | None = None
            if track.id:
                yandex_url = f"https://music.yandex.ru/track/{track.id}"

            return TrackInfo(
                title=track.title or title,
                artist=artists or artist,
                album=album_title,
                duration_ms=track.duration_ms,
                cover_url=cover_url,
                yandex_url=yandex_url,
            )
        except Exception as exc:
            self._log_entry(f"Яндекс Музыка: {exc}")
            return base

    def _get_ym_client(self) -> Any:
        with self._lock:
            if self._ym_client is not None:
                return self._ym_client

        try:
            from yandex_music import Client  # type: ignore[import]
            token = self._store.load_token() or None
            client = Client(token).init()
            with self._lock:
                self._ym_client = client
            return client
        except ImportError:
            self._set_error("yandex-music не установлен. Запустите: pip install yandex-music")
            return None
        except Exception as exc:
            self._set_error(f"Ошибка подключения к ЯМ: {exc}")
            return None

    # ------------------------------------------------------------------
    # Discord RPC
    # ------------------------------------------------------------------

    def _ensure_discord_connected(self, app_id: str) -> bool:
        with self._lock:
            if self._discord_connected and self._rpc is not None:
                return True

        try:
            from pypresence import Presence  # type: ignore[import]
            rpc = Presence(app_id)
            rpc.connect()
            with self._lock:
                self._rpc = rpc
                self._discord_connected = True
            self._log_entry("Discord RPC подключён")
            return True
        except Exception as exc:
            with self._lock:
                self._discord_connected = False
                self._rpc = None
            self._log_entry(f"Discord RPC недоступен: {exc}")
            return False

    def _update_discord_rpc(self, track: TrackInfo, config: YandexMusicRpcConfig) -> None:
        if not self._ensure_discord_connected(config.discord_app_id):
            return
        try:
            buttons: list[dict[str, str]] = []
            if track.yandex_url:
                buttons.append({"label": "Яндекс Музыка", "url": track.yandex_url})

            with self._lock:
                rpc = self._rpc

            rpc.update(
                details=track.title[:128] if track.title else "Неизвестный трек",
                state=(track.artist[:128] if track.artist else "Неизвестный исполнитель"),
                large_image=track.cover_url or "music",
                large_text=(track.album or track.artist or "")[:128],
                buttons=buttons if buttons else None,
                start=int(time.time()),
            )
        except Exception as exc:
            self._log_entry(f"RPC update ошибка: {exc}")
            with self._lock:
                self._discord_connected = False
                self._rpc = None

    def _clear_discord_rpc(self) -> None:
        with self._lock:
            rpc = self._rpc
            self._rpc = None
            self._discord_connected = False
        if rpc is not None:
            try:
                rpc.clear()
                rpc.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_error(self, msg: str) -> None:
        with self._lock:
            self._error = msg
        self._log_entry(f"[!] {msg}")

    def _log_entry(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self._lock:
            self._log.append(entry)
            if len(self._log) > _LOG_LIMIT:
                self._log = self._log[-_LOG_LIMIT:]
