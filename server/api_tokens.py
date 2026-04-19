"""Personal Access Token storage. We never store the plaintext token —
only sha256(token). The plaintext is shown to the user exactly once at
creation time.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from time import time

from server.db import Database

TOKEN_PREFIX = "pvt_"
DEFAULT_TTL_DAYS = 90
MIN_TTL_DAYS = 1
MAX_TTL_DAYS = 365


@dataclass(frozen=True)
class ApiToken:
    token_hash: str
    user_open_id: str
    name: str
    created_at: float
    last_used_at: float | None
    expires_at: float

    @property
    def short_id(self) -> str:
        return self.token_hash[:8]


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


class ApiTokenRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        user_open_id: str,
        name: str,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> tuple[str, ApiToken]:
        """Returns (plaintext_token, ApiToken). Plaintext is only available here."""
        ttl = max(MIN_TTL_DAYS, min(MAX_TTL_DAYS, ttl_days))
        token = generate_token()
        h = hash_token(token)
        now = time()
        expires = now + ttl * 86400
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO api_tokens"
                " (token_hash, user_open_id, name, created_at, last_used_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (h, user_open_id, name, now, None, expires),
            )
        return token, ApiToken(
            token_hash=h,
            user_open_id=user_open_id,
            name=name,
            created_at=now,
            last_used_at=None,
            expires_at=expires,
        )

    def list_for_user(self, user_open_id: str) -> list[ApiToken]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_tokens WHERE user_open_id=? ORDER BY created_at DESC",
                (user_open_id,),
            ).fetchall()
        return [_row(r) for r in rows]

    def lookup_by_plaintext(self, token: str) -> ApiToken | None:
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        h = hash_token(token)
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_tokens WHERE token_hash=?", (h,)
            ).fetchone()
        if row is None:
            return None
        tok = _row(row)
        if tok.expires_at <= time():
            return None
        return tok

    def touch_last_used(self, token_hash: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE api_tokens SET last_used_at=? WHERE token_hash=?",
                (time(), token_hash),
            )

    def delete_by_short_id(self, user_open_id: str, short_id: str) -> bool:
        if not short_id or len(short_id) < 4:
            return False
        with self._db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM api_tokens WHERE user_open_id=? AND substr(token_hash,1,8)=?",
                (user_open_id, short_id),
            )
            return cur.rowcount > 0

    def sweep_expired(self) -> int:
        with self._db.connect() as conn:
            cur = conn.execute("DELETE FROM api_tokens WHERE expires_at <= ?", (time(),))
            return cur.rowcount


def _row(row) -> ApiToken:
    return ApiToken(
        token_hash=row["token_hash"],
        user_open_id=row["user_open_id"],
        name=row["name"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
    )
