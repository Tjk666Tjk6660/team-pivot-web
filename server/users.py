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
    markdown_style: str | None
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
                "SELECT * FROM users WHERE open_id=? OR union_id=? OR pinyin=?",
                (id_, id_, id_),
            ).fetchone()
        return _row_to_user(row) if row else None

    def all(self) -> list[User]:
        """Return all registered users. Used by relevance writer / scanner to
        iterate candidates for compute_relevance against each timeline item.
        """
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
        return [_row_to_user(r) for r in rows]

    def list_all(self) -> list[User]:
        """All registered Pivot users, ordered by name. Used by the daily
        report to enumerate everyone (including those without activity in
        the window, who land in the 'today: 0 activity' bucket)."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY name"
            ).fetchall()
        return [_row_to_user(r) for r in rows]

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

    def update_markdown_style(self, open_id: str, markdown_style: str) -> User | None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE users SET markdown_style=? WHERE open_id=?",
                (markdown_style, open_id),
            )
        return self.get(open_id)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        open_id=row["open_id"],
        union_id=row["union_id"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        pinyin=row["pinyin"],
        github_username=row["github_username"],
        markdown_style=row["markdown_style"],
        created_at=row["created_at"],
    )


# --------------------------------------------------------------------------- #
# Read-only view (for dev preview / migration scripts)                        #
# --------------------------------------------------------------------------- #


class ReadOnlyUserView:
    """Read-only minimal view of the `users` table — safe to point at a
    snapshot / live production data.db.

    **Why this exists:** `UserRepo(Database(path))` calls `Database.__init__`
    which runs `CREATE TABLE IF NOT EXISTS` + `_migrate(conn)` — both can
    perform DDL/DML against the file. If you point that at a snapshot or
    production db whose schema lags the current code, those writes would
    clobber it.

    This view bypasses `Database` entirely, opens the SQLite via the
    `file:...?mode=ro` URI (sqlite3 errors on any DDL/DML attempt), and
    exposes only the read methods the daily-report runner needs:
    `list_all()` and `get_by_any_id()`.

    Used by:
    - `scripts/preview_daily_report.py` — dev-time card preview
    - `server/daily_report/runner.py` when `users_db_path` is set
      (server boots with .env DAILY_REPORT_USERS_DB_PATH pointing here)

    Pattern follows `scripts/migrate_index_schema.py::_ReadOnlyUserView`.
    """

    def __init__(self, db_path) -> None:
        from pathlib import Path
        # Resolve to absolute, sqlite URI requires forward slashes
        abs_path = Path(db_path).resolve().as_posix()
        self._uri = f"file:{abs_path}?mode=ro"
        # Probe-connect once to fail fast on missing file / unreadable DB
        # (mode=ro errors instead of creating, unlike default sqlite3.connect).
        conn = sqlite3.connect(self._uri, uri=True)
        conn.close()

    def list_all(self) -> list[User]:
        """All registered users, ordered by name. Mirrors `UserRepo.list_all`."""
        conn = sqlite3.connect(self._uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM users ORDER BY name"
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_user(r) for r in rows]

    def get_by_any_id(self, id_: str) -> User | None:
        if not id_:
            return None
        conn = sqlite3.connect(self._uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE open_id=? OR union_id=? OR pinyin=?",
                (id_, id_, id_),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_user(row) if row else None
