from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from time import time


@dataclass
class Session:
    user_open_id: str
    expires_at: float


class SessionStore:
    def __init__(self, ttl_sec: int = 86400 * 7) -> None:
        self._ttl = ttl_sec
        self._store: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user_open_id: str) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._store[sid] = Session(
                user_open_id=user_open_id,
                expires_at=time() + self._ttl,
            )
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._lock:
            s = self._store.get(sid)
            if s is None:
                return None
            if s.expires_at < time():
                self._store.pop(sid, None)
                return None
            return s

    def delete(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            self._store.pop(sid, None)
