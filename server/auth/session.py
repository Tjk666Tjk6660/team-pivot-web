from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from time import time

from server.db import Database

log = logging.getLogger(__name__)


@dataclass
class Session:
    user_open_id: str
    expires_at: float


class SessionStore:
    def __init__(self, db: Database, ttl_sec: int = 86400 * 7) -> None:
        self._db = db
        self._ttl = ttl_sec

    def create(self, user_open_id: str) -> str:
        sid = secrets.token_urlsafe(32)
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_open_id, expires_at, created_at)"
                " VALUES (?,?,?,?)",
                (sid, user_open_id, now + self._ttl, now),
            )
        log.debug("session created sid=%s... user=%s", sid[:8], user_open_id)
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT user_open_id, expires_at FROM sessions WHERE id=?", (sid,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < time():
            self.delete(sid)
            return None
        return Session(
            user_open_id=row["user_open_id"],
            expires_at=row["expires_at"],
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
