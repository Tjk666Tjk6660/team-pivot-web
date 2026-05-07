"""Invite-code records for non-feishu users."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class Invite:
    id: str
    token_hash: str
    created_by: str
    created_at: float
    expires_at: float
    used_at: float | None
    used_by_user_id: str | None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_invite(row: sqlite3.Row) -> Invite:
    return Invite(
        id=row["id"],
        token_hash=row["token_hash"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        used_by_user_id=row["used_by_user_id"],
    )


class InviteRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        created_by: str,
        ttl_sec: int = 86400 * 7,
    ) -> tuple[str, Invite]:
        """Returns (plaintext_token, record). Plaintext is returned exactly
        once; only sha256 is persisted."""
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        new_id = uuid.uuid4().hex
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO invite"
                " (id, token_hash, created_by, created_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (new_id, token_hash, created_by, now, now + ttl_sec),
            )
            row = conn.execute(
                "SELECT * FROM invite WHERE id=?", (new_id,)
            ).fetchone()
        assert row is not None
        return token, _row_to_invite(row)

    def get(self, invite_id: str) -> Invite | None:
        """Lookup by invite id (NOT token). Returns the record regardless
        of used / expired status — callers like the admin applications
        list need to display 'invited by X' even after the invite is gone."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM invite WHERE id=?", (invite_id,)
            ).fetchone()
        return _row_to_invite(row) if row else None

    def resolve_token(self, plaintext_token: str) -> Invite | None:
        token_hash = _hash_token(plaintext_token)
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM invite WHERE token_hash=?", (token_hash,)
            ).fetchone()
        if row is None:
            return None
        record = _row_to_invite(row)
        if record.used_at is not None:
            return None
        if record.expires_at < time():
            return None
        return record

    def mark_used(self, *, invite_id: str, used_by_user_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE invite SET used_at=?, used_by_user_id=? WHERE id=?",
                (time(), used_by_user_id, invite_id),
            )

    def revoke(self, *, invite_id: str) -> None:
        # "提前失效" by setting expires_at to past
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE invite SET expires_at=? WHERE id=?",
                (time() - 1, invite_id),
            )

    def list_for_admin(self, *, include_used: bool = True) -> list[Invite]:
        sql = "SELECT * FROM invite WHERE 1=1"
        if not include_used:
            sql += " AND used_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._db.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [_row_to_invite(r) for r in rows]
