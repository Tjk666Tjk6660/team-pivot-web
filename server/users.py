from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from time import time

from server.db import Database

PINYIN_RE = re.compile(r"^[a-z][a-z0-9._-]{1,39}$")
GITHUB_RE = re.compile(r"^[a-zA-Z0-9-]{1,39}$")


@dataclass(frozen=True)
class User:
    open_id: str
    union_id: str | None
    name: str
    avatar_url: str
    pinyin: str | None
    github_username: str | None
    created_at: float

    @property
    def needs_setup(self) -> bool:
        return not self.pinyin


class UserRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_from_feishu(
        self,
        *,
        open_id: str,
        union_id: str | None,
        name: str,
        avatar_url: str,
    ) -> User:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE open_id=?", (open_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users (open_id, union_id, name, avatar_url, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (open_id, union_id, name, avatar_url, time()),
                )
            else:
                conn.execute(
                    "UPDATE users SET union_id=?, name=?, avatar_url=? WHERE open_id=?",
                    (union_id, name, avatar_url, open_id),
                )
        got = self.get(open_id)
        assert got is not None
        return got

    def get(self, open_id: str) -> User | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE open_id=?", (open_id,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_any_id(self, id_: str) -> User | None:
        if not id_:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE open_id=? OR union_id=?", (id_, id_)
            ).fetchone()
        return _row_to_user(row) if row else None

    def update_profile(
        self,
        open_id: str,
        *,
        pinyin: str | None = None,
        github_username: str | None = None,
    ) -> User | None:
        if pinyin is not None and not PINYIN_RE.match(pinyin):
            raise ValueError(
                "pinyin must start with a letter and contain only a-z, 0-9, . _ -"
            )
        if github_username not in (None, "") and not GITHUB_RE.match(github_username):
            raise ValueError("invalid github username")

        updates: list[str] = []
        values: list[object] = []
        if pinyin is not None:
            updates.append("pinyin=?")
            values.append(pinyin)
        if github_username is not None:
            updates.append("github_username=?")
            values.append(github_username or None)
        if not updates:
            return self.get(open_id)
        values.append(open_id)

        with self._db.connect() as conn:
            try:
                conn.execute(
                    f"UPDATE users SET {','.join(updates)} WHERE open_id=?", values
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        return self.get(open_id)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        open_id=row["open_id"],
        union_id=row["union_id"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        pinyin=row["pinyin"],
        github_username=row["github_username"],
        created_at=row["created_at"],
    )
