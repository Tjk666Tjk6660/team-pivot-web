from __future__ import annotations

import logging
import secrets
import sqlite3
from dataclasses import dataclass
from time import time

from server.db import Database

log = logging.getLogger(__name__)


@dataclass
class Session:
    pivot_user_id: str
    expires_at: float
    user_access_token: str | None = None

    # Migration alias: keeps straggler callers using .user_open_id working
    @property
    def user_open_id(self) -> str:
        return self.pivot_user_id


class SessionStore:
    def __init__(self, db: Database, ttl_sec: int = 86400 * 7) -> None:
        self._db = db
        self._ttl = ttl_sec

    def create(
        self,
        pivot_user_id: str,
        *,
        user_access_token: str | None = None,
    ) -> str:
        sid = secrets.token_urlsafe(32)
        now = time()
        with self._db.connect() as conn:
            session_cols = self._session_columns(conn)
            values: dict[str, str | float | None] = {
                "id": sid,
                "expires_at": now + self._ttl,
                "created_at": now,
            }
            if "pivot_user_id" in session_cols:
                values["pivot_user_id"] = pivot_user_id
            if "user_open_id" in session_cols:
                values["user_open_id"] = self._legacy_user_open_id(conn, pivot_user_id)
            if "user_access_token" in session_cols:
                values["user_access_token"] = user_access_token
            columns = list(values)
            conn.execute(
                f"INSERT INTO sessions ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[col] for col in columns),
            )
        log.debug("session created sid=%s... user=%s", sid[:8], pivot_user_id)
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._db.connect() as conn:
            session_cols = self._session_columns(conn)
            user_expr = "pivot_user_id"
            if "pivot_user_id" in session_cols and "user_open_id" in session_cols:
                user_expr = "COALESCE(pivot_user_id, user_open_id)"
            elif "user_open_id" in session_cols:
                user_expr = "user_open_id"
            token_expr = "user_access_token" if "user_access_token" in session_cols else "NULL"
            row = conn.execute(
                f"SELECT {user_expr} AS pivot_user_id, expires_at,"
                f" {token_expr} AS user_access_token"
                " FROM sessions WHERE id=?",
                (sid,),
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < time():
            self.delete(sid)
            return None
        return Session(
            pivot_user_id=row["pivot_user_id"],
            expires_at=row["expires_at"],
            user_access_token=row["user_access_token"],
        )

    @staticmethod
    def _session_columns(conn: sqlite3.Connection) -> set[str]:
        return {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}

    @staticmethod
    def _legacy_user_open_id(conn: sqlite3.Connection, pivot_user_id: str) -> str:
        try:
            row = conn.execute(
                "SELECT external_id FROM external_binding"
                " WHERE pivot_user_id=? AND provider='feishu'"
                " ORDER BY bound_at DESC LIMIT 1",
                (pivot_user_id,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        return row["external_id"] if row is not None else pivot_user_id

    def delete(self, sid: str | None) -> None:
        if not sid:
            return
        with self._db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (sid,))

    def sweep_expired(self) -> int:
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time(),))
            return cur.rowcount
