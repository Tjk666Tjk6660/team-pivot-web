from __future__ import annotations

from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class ReadState:
    user_open_id: str
    thread_key: str
    last_read_post_filename: str
    updated_at: float


class ReadStateRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, user_open_id: str, thread_key: str) -> ReadState | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM read_state WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            ).fetchone()
        if row is None:
            return None
        return ReadState(
            user_open_id=row["user_open_id"],
            thread_key=row["thread_key"],
            last_read_post_filename=row["last_read_post_filename"],
            updated_at=row["updated_at"],
        )

    def set(self, user_open_id: str, thread_key: str, last_read_post_filename: str) -> ReadState:
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO read_state"
                " (user_open_id, thread_key, last_read_post_filename, updated_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(user_open_id, thread_key) DO UPDATE SET"
                " last_read_post_filename=excluded.last_read_post_filename,"
                " updated_at=excluded.updated_at",
                (user_open_id, thread_key, last_read_post_filename, now),
            )
        return ReadState(
            user_open_id=user_open_id,
            thread_key=thread_key,
            last_read_post_filename=last_read_post_filename,
            updated_at=now,
        )

    def all_for_user(self, user_open_id: str) -> dict[str, str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT thread_key, last_read_post_filename FROM read_state"
                " WHERE user_open_id=?",
                (user_open_id,),
            ).fetchall()
        return {r["thread_key"]: r["last_read_post_filename"] for r in rows}
