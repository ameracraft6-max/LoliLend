from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Protocol

from lolilend.monitoring import MonitorService, ProcessSnapshot


@dataclass(slots=True)
class LiveGameEntry:
    app_key: str
    display_name: str
    confidence: float
    session_seconds: int
    pid_count: int


@dataclass(slots=True)
class TopGameEntry:
    app_key: str
    display_name: str
    seconds: int
    sessions: int


@dataclass(slots=True)
class DailyUsagePoint:
    day_local: str
    seconds: int


@dataclass(slots=True)
class AnalyticsSummary:
    total_today_seconds: int
    total_week_seconds: int
    top_today: list[TopGameEntry]
    top_week: list[TopGameEntry]
    daily_series: list[DailyUsagePoint]


@dataclass(slots=True)
class _UsageDelta:
    day_local: str
    app_key: str
    display_name: str
    seconds: int
    sessions: int
    last_seen: str


@dataclass(slots=True)
class _SessionState:
    app_key: str
    display_name: str
    started_at: datetime
    last_seen: datetime
    confidence: float
    pids: set[int]


@dataclass(slots=True)
class _Classification:
    is_game: bool
    confidence: float
    features: dict[str, float]


@dataclass(slots=True)
class _TickGameAggregate:
    display_name: str
    confidence: float
    pids: set[int]


class ProcessSource(Protocol):
    def poll_processes(self, limit: int = 0, include_exe_path: bool = False) -> list[ProcessSnapshot]: ...


def format_duration(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, sec = divmod(remainder, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m"
    if minutes:
        return f"{minutes:d}m {sec:02d}s"
    return f"{sec:d}s"


def normalize_app_key(exe_path: str | None, process_name: str) -> str:
    if exe_path:
        return exe_path.replace("\\", "/").strip().lower()
    name = process_name.strip().lower() or "unknown"
    return f"name:{name}"


class AnalyticsStore:
    def __init__(self, db_path: Path | None = None, app_name: str = "LoliLend") -> None:
        if db_path is None:
            base_dir = Path(os.getenv("APPDATA", Path.home())) / app_name
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = base_dir / "analytics.sqlite"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day_local TEXT NOT NULL,
                    app_key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    seconds INTEGER NOT NULL DEFAULT 0,
                    sessions INTEGER NOT NULL DEFAULT 0,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (day_local, app_key)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS overrides (
                    app_key TEXT PRIMARY KEY,
                    is_game INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_weights (
                    feature TEXT PRIMARY KEY,
                    weight REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_daily_day_local ON usage_daily(day_local)"
            )

    def bulk_upsert_usage(self, deltas: list[_UsageDelta]) -> None:
        if not deltas:
            return
        payload = [
            (
                delta.day_local,
                delta.app_key,
                delta.display_name,
                int(delta.seconds),
                int(delta.sessions),
                delta.last_seen,
            )
            for delta in deltas
        ]
        with self._lock, self._connection:
            self._connection.executemany(
                """
                INSERT INTO usage_daily (day_local, app_key, display_name, seconds, sessions, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_local, app_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    seconds = usage_daily.seconds + excluded.seconds,
                    sessions = usage_daily.sessions + excluded.sessions,
                    last_seen = excluded.last_seen
                """,
                payload,
            )

    def get_total(self, start_day: date, end_day: date) -> int:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(seconds), 0) AS total_seconds
                FROM usage_daily
                WHERE day_local BETWEEN ? AND ?
                """,
                (start_day.isoformat(), end_day.isoformat()),
            ).fetchone()
        if row is None:
            return 0
        return int(row["total_seconds"])

    def get_top(self, start_day: date, end_day: date, limit: int = 5) -> list[TopGameEntry]:
        query_limit = max(1, int(limit))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT
                    app_key,
                    MAX(display_name) AS display_name,
                    SUM(seconds) AS total_seconds,
                    SUM(sessions) AS total_sessions
                FROM usage_daily
                WHERE day_local BETWEEN ? AND ?
                GROUP BY app_key
                ORDER BY total_seconds DESC, total_sessions DESC, display_name ASC
                LIMIT ?
                """,
                (start_day.isoformat(), end_day.isoformat(), query_limit),
            ).fetchall()

        return [
            TopGameEntry(
                app_key=str(row["app_key"]),
                display_name=str(row["display_name"]),
                seconds=int(row["total_seconds"] or 0),
                sessions=int(row["total_sessions"] or 0),
            )
            for row in rows
        ]

    def get_daily_series(self, days: int, today: date | None = None) -> list[DailyUsagePoint]:
        window = max(1, int(days))
        end_day = today or date.today()
        start_day = end_day - timedelta(days=window - 1)

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT day_local, COALESCE(SUM(seconds), 0) AS total_seconds
                FROM usage_daily
                WHERE day_local BETWEEN ? AND ?
                GROUP BY day_local
                ORDER BY day_local ASC
                """,
                (start_day.isoformat(), end_day.isoformat()),
            ).fetchall()

        by_day = {str(row["day_local"]): int(row["total_seconds"] or 0) for row in rows}
        result: list[DailyUsagePoint] = []
        for index in range(window):
            current_day = start_day + timedelta(days=index)
            key = current_day.isoformat()
            result.append(DailyUsagePoint(day_local=key, seconds=by_day.get(key, 0)))
        return result

    def load_overrides(self) -> dict[str, bool]:
        with self._lock:
            rows = self._connection.execute("SELECT app_key, is_game FROM overrides").fetchall()
        return {str(row["app_key"]): bool(int(row["is_game"])) for row in rows}

    def set_override(self, app_key: str, is_game: bool) -> None:
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO overrides (app_key, is_game, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(app_key) DO UPDATE SET
                    is_game = excluded.is_game,
                    updated_at = excluded.updated_at
                """,
                (app_key, int(bool(is_game)), now_iso),
            )

    def clear_override(self, app_key: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM overrides WHERE app_key = ?", (app_key,))

    def load_model_weights(self, defaults: dict[str, float]) -> dict[str, float]:
        merged = dict(defaults)
        with self._lock:
            rows = self._connection.execute("SELECT feature, weight FROM model_weights").fetchall()
        for row in rows:
            merged[str(row["feature"])] = float(row["weight"])
        return merged

    def save_model_weights(self, weights: dict[str, float]) -> None:
        if not weights:
            return
        now_iso = datetime.now().isoformat(timespec="seconds")
        payload = [(name, float(value), now_iso) for name, value in weights.items()]
        with self._lock, self._connection:
            self._connection.executemany(
                """
                INSERT INTO model_weights (feature, weight, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(feature) DO UPDATE SET
                    weight = excluded.weight,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class GameClassifier:
    _GAME_TOKENS = {
        "game",
        "steamapps",
        "dota",
        "cs2",
        "counter-strike",
        "minecraft",
        "fortnite",
        "valorant",
        "league",
        "riotgames",
        "warzone",
        "overwatch",
        "eldenring",
        "roblox",
        "gta",
        "apex",
    }
    _LAUNCHER_TOKENS = {
        "steam.exe",
        "epicgameslauncher",
        "epic games",
        "battle.net",
        "battlenet",
        "riotclientservices",
        "riot client",
        "ubisoftconnect",
        "origin.exe",
        "eadesktop",
        "gog galaxy",
        "playnite",
        "launcher",
    }

    def __init__(
        self,
        threshold: float = 0.6,
        weights: dict[str, float] | None = None,
        learning_rate: float = 0.12,
    ) -> None:
        self.threshold = float(threshold)
        self.learning_rate = max(0.01, float(learning_rate))
        self.weights = dict(weights or self.default_weights())

    @classmethod
    def default_weights(cls) -> dict[str, float]:
        return {
            "bias": -1.35,
            "token_game": 2.15,
            "token_launcher": 1.7,
            "cpu_signal": 0.75,
            "ram_signal": 0.45,
            "status_running": 0.25,
            "has_exe_path": 0.15,
        }

    def classify(self, snapshot: ProcessSnapshot, override: bool | None = None) -> _Classification:
        features = self.extract_features(snapshot)
        if override is not None:
            return _Classification(is_game=bool(override), confidence=1.0, features=features)
        confidence = self.score(features)
        return _Classification(
            is_game=confidence >= self.threshold,
            confidence=confidence,
            features=features,
        )

    def score(self, features: dict[str, float]) -> float:
        linear = 0.0
        for feature, value in features.items():
            linear += self.weights.get(feature, 0.0) * float(value)
        return 1.0 / (1.0 + math.exp(-linear))

    def learn(self, features: dict[str, float], target: float) -> None:
        target_clamped = max(0.0, min(1.0, float(target)))
        prediction = self.score(features)
        error = target_clamped - prediction
        for feature, value in features.items():
            updated = self.weights.get(feature, 0.0) + (self.learning_rate * error * float(value))
            self.weights[feature] = max(-6.0, min(6.0, updated))

    def export_weights(self) -> dict[str, float]:
        return dict(self.weights)

    def extract_features(self, snapshot: ProcessSnapshot) -> dict[str, float]:
        full_text = f"{snapshot.name} {snapshot.exe_path or ''}".strip().lower()
        status = snapshot.status.strip().lower()
        return {
            "bias": 1.0,
            "token_game": 1.0 if self._contains_any(full_text, self._GAME_TOKENS) else 0.0,
            "token_launcher": 1.0 if self._contains_any(full_text, self._LAUNCHER_TOKENS) else 0.0,
            "cpu_signal": min(max(snapshot.cpu_percent, 0.0) / 20.0, 1.0),
            "ram_signal": min(max(snapshot.ram_mb, 0.0) / 1_500.0, 1.0),
            "status_running": 1.0 if status in {"running", "sleeping"} else 0.0,
            "has_exe_path": 1.0 if snapshot.exe_path else 0.0,
        }

    @staticmethod
    def _contains_any(text: str, tokens: set[str]) -> bool:
        return any(token in text for token in tokens)


class GameAnalyticsService:
    def __init__(
        self,
        process_source: ProcessSource | None = None,
        store: AnalyticsStore | None = None,
        sample_interval_seconds: int = 5,
        grace_period_seconds: int = 10,
        threshold: float = 0.6,
        process_limit: int = 48,
    ) -> None:
        self._process_source = process_source or MonitorService()
        self._store = store or AnalyticsStore()
        self._sample_interval_seconds = max(1, int(sample_interval_seconds))
        self._grace_period_seconds = max(1, int(grace_period_seconds))
        self._process_limit = max(1, int(process_limit))
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionState] = {}
        self._last_features_by_app: dict[str, dict[str, float]] = {}
        self._overrides = self._store.load_overrides()
        self._classifier = GameClassifier(
            threshold=threshold,
            weights=self._store.load_model_weights(GameClassifier.default_weights()),
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="lolilend-analytics", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, float(self._sample_interval_seconds) + 1.0))
        with self._lock:
            self._thread = None

    def get_live_games(self, limit: int = 3) -> list[LiveGameEntry]:
        now = datetime.now()
        with self._lock:
            self._drop_stale_sessions(now)
            entries = [
                LiveGameEntry(
                    app_key=session.app_key,
                    display_name=session.display_name,
                    confidence=max(0.0, min(1.0, session.confidence)),
                    session_seconds=max(0, int((now - session.started_at).total_seconds())),
                    pid_count=max(1, len(session.pids)),
                )
                for session in self._sessions.values()
            ]
        entries.sort(key=lambda item: (item.confidence, item.session_seconds), reverse=True)
        return entries[: max(1, int(limit))]

    def get_summary(self, days: int = 7) -> AnalyticsSummary:
        window = max(1, int(days))
        today = date.today()
        start_day = today - timedelta(days=window - 1)
        return AnalyticsSummary(
            total_today_seconds=self._store.get_total(today, today),
            total_week_seconds=self._store.get_total(start_day, today),
            top_today=self._store.get_top(today, today, limit=5),
            top_week=self._store.get_top(start_day, today, limit=5),
            daily_series=self._store.get_daily_series(window, today=today),
        )

    def set_override(self, app_key: str, is_game: bool) -> None:
        normalized_key = self._normalize_override_key(app_key)
        with self._lock:
            self._overrides[normalized_key] = bool(is_game)
            features = self._last_features_by_app.get(normalized_key)
            if features is not None:
                self._classifier.learn(features, 1.0 if is_game else 0.0)
            weights = self._classifier.export_weights()
        self._store.set_override(normalized_key, is_game)
        self._store.save_model_weights(weights)

    def clear_override(self, app_key: str) -> None:
        normalized_key = self._normalize_override_key(app_key)
        with self._lock:
            self._overrides.pop(normalized_key, None)
        self._store.clear_override(normalized_key)

    def _run_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            now_monotonic = time.monotonic()
            if now_monotonic < next_tick:
                self._stop_event.wait(next_tick - now_monotonic)
                continue

            try:
                snapshots = self._poll_processes()
            except Exception:
                snapshots = []

            now_dt = datetime.now()
            deltas = self._process_tick(snapshots, now_dt)
            if deltas:
                self._store.bulk_upsert_usage(deltas)

            next_tick += self._sample_interval_seconds
            current = time.monotonic()
            if next_tick < current:
                next_tick = current + self._sample_interval_seconds

    def _poll_processes(self) -> list[ProcessSnapshot]:
        try:
            return self._process_source.poll_processes(limit=self._process_limit, include_exe_path=True)
        except TypeError:
            return self._process_source.poll_processes(limit=self._process_limit)

    def _process_tick(self, snapshots: list[ProcessSnapshot], now: datetime) -> list[_UsageDelta]:
        day_local = now.date().isoformat()
        now_iso = now.isoformat(timespec="seconds")
        deltas: list[_UsageDelta] = []

        with self._lock:
            by_app: dict[str, _TickGameAggregate] = {}
            for snapshot in snapshots:
                app_key = normalize_app_key(snapshot.exe_path, snapshot.name)
                override = self._overrides.get(app_key)
                classification = self._classifier.classify(snapshot, override=override)
                self._last_features_by_app[app_key] = classification.features

                if not classification.is_game:
                    continue

                aggregate = by_app.get(app_key)
                if aggregate is None:
                    by_app[app_key] = _TickGameAggregate(
                        display_name=self._display_name(snapshot),
                        confidence=classification.confidence,
                        pids={snapshot.pid},
                    )
                else:
                    aggregate.pids.add(snapshot.pid)
                    if classification.confidence > aggregate.confidence:
                        aggregate.confidence = classification.confidence
                    if snapshot.name:
                        aggregate.display_name = snapshot.name

            for app_key, aggregate in by_app.items():
                session = self._sessions.get(app_key)
                sessions_add = 0
                if session is None:
                    sessions_add = 1
                    session = _SessionState(
                        app_key=app_key,
                        display_name=aggregate.display_name,
                        started_at=now,
                        last_seen=now,
                        confidence=aggregate.confidence,
                        pids=set(aggregate.pids),
                    )
                    self._sessions[app_key] = session
                else:
                    session.last_seen = now
                    session.display_name = aggregate.display_name
                    session.confidence = aggregate.confidence
                    session.pids = set(aggregate.pids)

                deltas.append(
                    _UsageDelta(
                        day_local=day_local,
                        app_key=app_key,
                        display_name=session.display_name,
                        seconds=self._sample_interval_seconds,
                        sessions=sessions_add,
                        last_seen=now_iso,
                    )
                )

            self._drop_stale_sessions(now)

        return deltas

    def _drop_stale_sessions(self, now: datetime) -> None:
        stale_keys = [
            app_key
            for app_key, session in self._sessions.items()
            if (now - session.last_seen).total_seconds() >= self._grace_period_seconds
        ]
        for app_key in stale_keys:
            self._sessions.pop(app_key, None)

    @staticmethod
    def _normalize_override_key(app_key: str) -> str:
        return app_key.replace("\\", "/").strip().lower()

    @staticmethod
    def _display_name(snapshot: ProcessSnapshot) -> str:
        if snapshot.name:
            return snapshot.name
        if snapshot.exe_path:
            return Path(snapshot.exe_path).stem or snapshot.exe_path
        return f"PID {snapshot.pid}"
