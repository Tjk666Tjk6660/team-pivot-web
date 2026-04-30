from __future__ import annotations

import json
import time

from server.db import Database


class AIConversationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(
        self, pivot_user_id: str, thread_key: str
    ) -> tuple[list[dict], str | None]:
        """Returns (messages, reply_target). `reference_files_json` column is
        kept in the schema for back-compat but is no longer read."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT messages_json, reply_target"
                " FROM ai_conversations WHERE pivot_user_id=? AND thread_key=?",
                (pivot_user_id, thread_key),
            ).fetchone()
        if row is None:
            return [], None
        return (
            json.loads(row["messages_json"]),
            row["reply_target"],
        )

    def save(
        self,
        pivot_user_id: str,
        thread_key: str,
        messages: list[dict],
        reply_target: str | None,
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO ai_conversations"
                " (pivot_user_id, thread_key, messages_json, reply_target,"
                "  reference_files_json, updated_at)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(pivot_user_id, thread_key) DO UPDATE SET"
                "  messages_json=excluded.messages_json,"
                "  reply_target=excluded.reply_target,"
                "  reference_files_json=excluded.reference_files_json,"
                "  updated_at=excluded.updated_at",
                (
                    pivot_user_id,
                    thread_key,
                    json.dumps(messages, ensure_ascii=False),
                    reply_target,
                    "[]",
                    time.time(),
                ),
            )

    def delete(self, pivot_user_id: str, thread_key: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM ai_conversations WHERE pivot_user_id=? AND thread_key=?",
                (pivot_user_id, thread_key),
            )

    def clear_all(self) -> int:
        """One-time migration helper: wipe every AI conversation row.
        Returns the number of rows deleted. Threads/posts are untouched —
        they live in Git as .md files."""
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM ai_conversations")
            return cur.rowcount or 0
