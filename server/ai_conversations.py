from __future__ import annotations

import json
import time

from server.db import Database


class AIConversationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(
        self, user_open_id: str, thread_key: str
    ) -> tuple[list[dict], str | None, list[str]]:
        """Returns (messages, reply_target, reference_files)."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT messages_json, reply_target, reference_files_json"
                " FROM ai_conversations WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            ).fetchone()
        if row is None:
            return [], None, []
        return (
            json.loads(row["messages_json"]),
            row["reply_target"],
            json.loads(row["reference_files_json"] or "[]"),
        )

    def save(
        self,
        user_open_id: str,
        thread_key: str,
        messages: list[dict],
        reply_target: str | None,
        reference_files: list[str],
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO ai_conversations"
                " (user_open_id, thread_key, messages_json, reply_target,"
                "  reference_files_json, updated_at)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(user_open_id, thread_key) DO UPDATE SET"
                "  messages_json=excluded.messages_json,"
                "  reply_target=excluded.reply_target,"
                "  reference_files_json=excluded.reference_files_json,"
                "  updated_at=excluded.updated_at",
                (
                    user_open_id,
                    thread_key,
                    json.dumps(messages, ensure_ascii=False),
                    reply_target,
                    json.dumps(reference_files, ensure_ascii=False),
                    time.time(),
                ),
            )

    def delete(self, user_open_id: str, thread_key: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM ai_conversations WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            )
