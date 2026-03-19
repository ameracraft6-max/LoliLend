from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from lolilend.ai_history import AiHistoryStore


class AiHistoryStoreTests(unittest.TestCase):
    def test_sessions_and_messages_crud(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp_dir
            try:
                store = AiHistoryStore(app_name="LoliLendTest")
                created = store.create_session("Demo")
                self.assertGreater(created.id, 0)

                sessions = store.list_sessions()
                self.assertEqual(len(sessions), 1)
                self.assertEqual(sessions[0].title, "Demo")

                user = store.add_message(created.id, "user", "hello")
                assistant = store.add_message(created.id, "assistant", "hi", status="streaming")
                messages = store.get_messages(created.id)
                self.assertEqual([m.id for m in messages], [user.id, assistant.id])
                self.assertEqual(messages[1].status, "streaming")

                store.update_message(assistant.id, "hi there", status="complete")
                messages = store.get_messages(created.id)
                self.assertEqual(messages[1].content, "hi there")
                self.assertEqual(messages[1].status, "complete")

                store.rename_session(created.id, "Renamed")
                sessions = store.list_sessions()
                self.assertEqual(sessions[0].title, "Renamed")

                store.delete_session(created.id)
                self.assertEqual(store.list_sessions(), [])
                store.close()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_migrates_mojibake_history_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp_dir
            try:
                base = Path(temp_dir) / "LoliLendTest"
                base.mkdir(parents=True, exist_ok=True)
                db_path = base / "ai_history.sqlite"
                conn = sqlite3.connect(str(db_path))
                conn.executescript(
                    """
                    CREATE TABLE chat_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE chat_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'complete',
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (1, 'Demo', datetime('now'), datetime('now'))"
                )
                conn.execute(
                    "INSERT INTO chat_messages (session_id, role, content, status, created_at) VALUES (1, 'assistant', ?, 'complete', datetime('now'))",
                    ("РџСЂРёРІРµС‚",),
                )
                conn.commit()
                conn.close()

                reopened = AiHistoryStore(app_name="LoliLendTest")
                messages = reopened.get_messages(1)
                self.assertEqual(messages[0].content, "Привет")
                marker = reopened._get_meta("ai_history_mojibake_repair_v1")
                self.assertEqual(marker, "done")
                reopened.close()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata

    def test_task_runs_and_assets_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = temp_dir
            try:
                source = Path(temp_dir) / "input.png"
                source.write_bytes(b"input-bytes")

                store = AiHistoryStore(app_name="LoliLendTest")
                session = store.create_session("Tasks")
                input_path = store.copy_input_asset(session.id, "image_to_text", str(source))
                output_path = store.save_output_asset(session.id, "text_to_speech", b"audio-data", ".mp3", "output")
                created = store.add_task_run(
                    session.id,
                    "image_to_text",
                    "@cf/llava-hf/llava-1.5-7b-hf",
                    request_text="describe",
                    response_text="done",
                    input_asset_path=input_path,
                    output_asset_path="",
                    metadata={"output_kind": "text"},
                )
                runs = store.list_task_runs(session.id, "image_to_text")
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0].id, created.id)
                self.assertTrue(store.resolve_asset_path(input_path).exists())
                self.assertTrue(store.resolve_asset_path(output_path).exists())
                self.assertEqual(store.task_run_metadata(runs[0])["output_kind"], "text")
                store.close()
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata


if __name__ == "__main__":
    unittest.main()
