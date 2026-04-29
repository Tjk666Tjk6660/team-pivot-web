from __future__ import annotations

import logging
import secrets
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
            conn.execute(
                "INSERT INTO sessions"
                " (id, pivot_user_id, expires_at, created_at, user_access_token)"
                " VALUES (?,?,?,?,?)",
                (sid, pivot_user_id, now + self._ttl, now, user_access_token),
            )
        log.debug("session created sid=%s... user=%s", sid[:8], pivot_user_id)
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT pivot_user_id, expires_at, user_access_token"
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

    def delete(self, sid: str | None) -> None:
        if not sid:
            return
        with self._db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (sid,))

    def sweep_expired(self) -> int:
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time(),))
            return cur.rowcount
