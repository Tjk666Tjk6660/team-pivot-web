"""External identity binding (feishu open_id / invite email / etc) ↔ pivot_user."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class ExternalBinding:
    id: str
    pivot_user_id: str
    provider: str
    external_id: str
    external_union_id: str | None
    raw_profile_json: str | None
    password_hash: str | None
    bound_at: float


def _row_to_binding(row: sqlite3.Row) -> ExternalBinding:
    return ExternalBinding(
        id=row["id"],
        pivot_user_id=row["pivot_user_id"],
        provider=row["provider"],
        external_id=row["external_id"],
        external_union_id=row["external_union_id"],
        raw_profile_json=row["raw_profile"],
        password_hash=row["password_hash"],
        bound_at=row["bound_at"],
    )


class ExternalBindingRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def bind(
        self,
        *,
        pivot_user_id: str,
        provider: str,
        external_id: str,
        external_union_id: str | None,
        raw_profile_json: str | None,
        password_hash: str | None = None,
    ) -> ExternalBinding:
        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM external_binding"
                " WHERE pivot_user_id=? AND provider=?",
                (pivot_user_id, provider),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"user {pivot_user_id} already has a {provider} binding"
                )
            new_id = uuid.uuid4().hex
            try:
                conn.execute(
                    "INSERT INTO external_binding"
                    " (id, pivot_user_id, provider, external_id, external_union_id,"
                    "  raw_profile, password_hash, bound_at) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id, pivot_user_id, provider, external_id, external_union_id,
                     raw_profile_json, password_hash, time()),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self._get(new_id)
        assert got is not None
        return got

    def _get(self, binding_id: str) -> ExternalBinding | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM external_binding WHERE id=?", (binding_id,)
            ).fetchone()
        return _row_to_binding(row) if row else None

    def lookup(
        self, *, provider: str, external_id: str
    ) -> ExternalBinding | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM external_binding WHERE provider=? AND external_id=?",
                (provider, external_id),
            ).fetchone()
        return _row_to_binding(row) if row else None

    def list_for_user(self, pivot_user_id: str) -> list[ExternalBinding]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM external_binding WHERE pivot_user_id=?"
                " ORDER BY bound_at ASC",
                (pivot_user_id,),
            ).fetchall()
        return [_row_to_binding(r) for r in rows]

    def update_password(
        self, *, pivot_user_id: str, new_password_hash: str
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE external_binding SET password_hash=?"
                " WHERE pivot_user_id=? AND provider='invite'",
                (new_password_hash, pivot_user_id),
            )
