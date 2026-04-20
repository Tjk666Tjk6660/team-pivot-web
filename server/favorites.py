from __future__ import annotations

from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class Favorite:
    user_open_id: str
    thread_key: str
    created_at: float


class FavoriteRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def set(self, user_open_id: str, thread_key: str) -> Favorite:
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO favorites (user_open_id, thread_key, created_at)"
                " VALUES (?,?,?)"
                " ON CONFLICT(user_open_id, thread_key) DO NOTHING",
                (user_open_id, thread_key, now),
            )
            row = conn.execute(
                "SELECT user_open_id, thread_key, created_at"
                " FROM favorites WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            ).fetchone()
        assert row is not None
        return Favorite(
            user_open_id=row["user_open_id"],
            thread_key=row["thread_key"],
            created_at=row["created_at"],
        )

    def delete(self, user_open_id: str, thread_key: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM favorites WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            )

    def has(self, user_open_id: str, thread_key: str) -> bool:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE user_open_id=? AND thread_key=?",
                (user_open_id, thread_key),
            ).fetchone()
        return row is not None

    def all_for_user(self, user_open_id: str) -> set[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT thread_key FROM favorites WHERE user_open_id=?",
                (user_open_id,),
            ).fetchall()
        return {row["thread_key"] for row in rows}
