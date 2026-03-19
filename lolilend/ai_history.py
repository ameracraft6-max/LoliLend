from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from lolilend.ai_text import normalize_ai_text, repair_mojibake_text


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(slots=True)
class ChatSession:
    id: int
    title: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ChatMessage:
    id: int
    session_id: int
    role: str
    content: str
    status: str
    created_at: str


@dataclass(slots=True)
class AiTaskRun:
    id: int
    session_id: int
    task_key: str
    model_name: str
    request_text: str
    response_text: str
    input_asset_path: str
    output_asset_path: str
    metadata_json: str
    status: str
    created_at: str


class AiHistoryStore:
    def __init__(self, app_name: str = "LoliLend") -> None:
        base = Path(os.getenv("APPDATA", Path.home())) / app_name
        base.mkdir(parents=True, exist_ok=True)
        self._db_path = base / "ai_history.sqlite"
        self._assets_dir = base / "ai_assets"
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._run_migrations()

    def close(self) -> None:
        self._conn.close()

    def list_sessions(self) -> list[ChatSession]:
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [
            ChatSession(
                id=int(row["id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def create_session(self, title: str = "New Chat") -> ChatSession:
        now = _now_iso()
        cursor = self._conn.execute(
            "INSERT INTO chat_sessions (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title.strip() or "New Chat", now, now),
        )
        self._conn.commit()
        session_id = int(cursor.lastrowid)
        return ChatSession(id=session_id, title=title.strip() or "New Chat", created_at=now, updated_at=now)

    def rename_session(self, session_id: int, title: str) -> None:
        self._conn.execute(
            "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
            (title.strip() or "New Chat", _now_iso(), int(session_id)),
        )
        self._conn.commit()

    def delete_session(self, session_id: int) -> None:
        self._conn.execute("DELETE FROM chat_sessions WHERE id=?", (int(session_id),))
        self._conn.commit()

    def get_messages(self, session_id: int) -> list[ChatMessage]:
        rows = self._conn.execute(
            "SELECT id, session_id, role, content, status, created_at FROM chat_messages WHERE session_id=? ORDER BY id ASC",
            (int(session_id),),
        ).fetchall()
        return [
            ChatMessage(
                id=int(row["id"]),
                session_id=int(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def add_message(self, session_id: int, role: str, content: str, status: str = "complete") -> ChatMessage:
        now = _now_iso()
        clean_content = normalize_ai_text(content)
        cursor = self._conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (int(session_id), role, clean_content, status, now),
        )
        self._conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, int(session_id)))
        self._conn.commit()
        return ChatMessage(
            id=int(cursor.lastrowid),
            session_id=int(session_id),
            role=role,
            content=clean_content,
            status=status,
            created_at=now,
        )

    def update_message(self, message_id: int, content: str, status: str | None = None) -> None:
        clean_content = normalize_ai_text(content)
        if status is None:
            self._conn.execute("UPDATE chat_messages SET content=? WHERE id=?", (clean_content, int(message_id)))
        else:
            self._conn.execute("UPDATE chat_messages SET content=?, status=? WHERE id=?", (clean_content, status, int(message_id)))
        self._conn.commit()

    def list_task_runs(self, session_id: int, task_key: str) -> list[AiTaskRun]:
        rows = self._conn.execute(
            """
            SELECT id, session_id, task_key, model_name, request_text, response_text, input_asset_path, output_asset_path,
                   metadata_json, status, created_at
            FROM ai_task_runs
            WHERE session_id=? AND task_key=?
            ORDER BY id DESC
            """,
            (int(session_id), str(task_key)),
        ).fetchall()
        return [
            AiTaskRun(
                id=int(row["id"]),
                session_id=int(row["session_id"]),
                task_key=str(row["task_key"]),
                model_name=str(row["model_name"]),
                request_text=str(row["request_text"]),
                response_text=str(row["response_text"]),
                input_asset_path=str(row["input_asset_path"]),
                output_asset_path=str(row["output_asset_path"]),
                metadata_json=str(row["metadata_json"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def add_task_run(
        self,
        session_id: int,
        task_key: str,
        model_name: str,
        request_text: str,
        response_text: str,
        input_asset_path: str = "",
        output_asset_path: str = "",
        metadata: dict | None = None,
        status: str = "complete",
    ) -> AiTaskRun:
        now = _now_iso()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        cursor = self._conn.execute(
            """
            INSERT INTO ai_task_runs (
                session_id, task_key, model_name, request_text, response_text, input_asset_path, output_asset_path,
                metadata_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(session_id),
                str(task_key),
                str(model_name),
                normalize_ai_text(request_text),
                normalize_ai_text(response_text),
                str(input_asset_path),
                str(output_asset_path),
                metadata_json,
                str(status),
                now,
            ),
        )
        self._conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, int(session_id)))
        self._conn.commit()
        return AiTaskRun(
            id=int(cursor.lastrowid),
            session_id=int(session_id),
            task_key=str(task_key),
            model_name=str(model_name),
            request_text=normalize_ai_text(request_text),
            response_text=normalize_ai_text(response_text),
            input_asset_path=str(input_asset_path),
            output_asset_path=str(output_asset_path),
            metadata_json=metadata_json,
            status=str(status),
            created_at=now,
        )

    def copy_input_asset(self, session_id: int, task_key: str, source_path: str) -> str:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            return ""
        return self._store_asset_bytes(session_id, task_key, source.read_bytes(), source.suffix or ".bin", "input")

    def save_output_asset(self, session_id: int, task_key: str, data: bytes, suffix: str, kind: str) -> str:
        blob = bytes(data)
        if not blob:
            return ""
        safe_suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ".bin"
        return self._store_asset_bytes(session_id, task_key, blob, safe_suffix, kind)

    def resolve_asset_path(self, relative_path: str) -> Path | None:
        raw = str(relative_path).strip()
        if not raw:
            return None
        path = self._assets_dir / raw
        return path if path.exists() else None

    def task_run_metadata(self, run: AiTaskRun) -> dict:
        try:
            payload = json.loads(run.metadata_json) if run.metadata_json else {}
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'complete',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ai_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                task_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                request_text TEXT NOT NULL,
                response_text TEXT NOT NULL,
                input_asset_path TEXT NOT NULL DEFAULT '',
                output_asset_path TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'complete',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );
            """
        )
        self._conn.commit()

    def _run_migrations(self) -> None:
        if self._get_meta("ai_history_mojibake_repair_v1") == "done":
            return

        rows = self._conn.execute("SELECT id, content FROM chat_messages").fetchall()
        updates: list[tuple[str, int]] = []
        for row in rows:
            content = str(row["content"])
            repaired, changed = repair_mojibake_text(content)
            if not changed:
                continue
            updates.append((normalize_ai_text(repaired), int(row["id"])))

        if updates:
            self._conn.executemany("UPDATE chat_messages SET content=? WHERE id=?", updates)
        self._set_meta("ai_history_mojibake_repair_v1", "done")
        self._conn.commit()

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )

    def _store_asset_bytes(self, session_id: int, task_key: str, data: bytes, suffix: str, kind: str) -> str:
        task_folder = self._assets_dir / str(task_key)
        task_folder.mkdir(parents=True, exist_ok=True)
        filename = f"s{int(session_id)}_{kind}_{uuid4().hex}{suffix}"
        path = task_folder / filename
        path.write_bytes(data)
        return str(path.relative_to(self._assets_dir)).replace("\\", "/")
