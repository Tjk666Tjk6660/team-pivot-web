"""Pivot user master data — replaces server/users.py after migration."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, replace
from time import time
from typing import Iterable

from server.db import Database


@dataclass(frozen=True)
class PivotUser:
    id: str
    display_name: str
    pinyin: str | None
    email: str | None
    avatar_url: str
    github_username: str | None
    role: str
    status: str
    status_note: str | None
    created_at: float
    updated_at: float
    last_login_at: float | None
    status_changed_at: float | None
    status_changed_by: str | None

    @property
    def needs_setup(self) -> bool:
        return not self.pinyin

    @property
    def is_admin_active(self) -> bool:
        return self.role == "admin" and self.status == "active"


def _new_id() -> str:
    return uuid.uuid4().hex


def _row_to_user(row: sqlite3.Row) -> PivotUser:
    return PivotUser(
        id=row["id"],
        display_name=row["display_name"],
        pinyin=row["pinyin"],
        email=row["email"],
        avatar_url=row["avatar_url"] or "",
        github_username=row["github_username"],
        role=row["role"],
        status=row["status"],
        status_note=row["status_note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
        status_changed_at=row["status_changed_at"],
        status_changed_by=row["status_changed_by"],
    )


class PivotUserRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        display_name: str,
        pinyin: str | None,
        email: str | None,
        avatar_url: str,
        role: str = "member",
        github_username: str | None = None,
        id: str | None = None,
    ) -> PivotUser:
        now = time()
        new_id = id or _new_id()
        with self._db.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO pivot_user"
                    " (id, display_name, pinyin, email, avatar_url, github_username,"
                    "  role, status, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id, display_name, pinyin, email, avatar_url, github_username,
                     role, "active", now, now),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self.get(new_id)
        assert got is not None
        return got

    def get(self, user_id: str) -> PivotUser | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user WHERE id=?", (user_id,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> PivotUser | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def update_profile(
        self,
        user_id: str,
        *,
        pinyin: str | None = None,
        github_username: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> PivotUser:
        updates: list[str] = []
        values: list[object] = []
        for col, val in [
            ("pinyin", pinyin),
            ("github_username", github_username),
            ("display_name", display_name),
            ("avatar_url", avatar_url),
        ]:
            if val is not None:
                updates.append(f"{col}=?")
                values.append(val)
        if not updates:
            got = self.get(user_id)
            assert got is not None
            return got
        updates.append("updated_at=?")
        values.append(time())
        values.append(user_id)
        with self._db.connect() as conn:
            try:
                conn.execute(
                    f"UPDATE pivot_user SET {','.join(updates)} WHERE id=?", values
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self.get(user_id)
        assert got is not None
        return got

    def update_status(
        self,
        *,
        user_id: str,
        status: str,
        note: str | None,
        changed_by: str,
    ) -> PivotUser:
        if status not in ("active", "suspended", "deleted"):
            raise ValueError(f"invalid status: {status}")
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET status=?, status_note=?, status_changed_at=?,"
                " status_changed_by=?, updated_at=? WHERE id=?",
                (status, note, now, changed_by, now, user_id),
            )
        got = self.get(user_id)
        assert got is not None
        return got

    def update_role(self, *, user_id: str, role: str) -> PivotUser:
        if role not in ("admin", "member"):
            raise ValueError(f"invalid role: {role}")
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET role=?, updated_at=? WHERE id=?",
                (role, time(), user_id),
            )
        got = self.get(user_id)
        assert got is not None
        return got

    def touch_last_login(self, user_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET last_login_at=? WHERE id=?",
                (time(), user_id),
            )

    def count_active_admins(self) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM pivot_user"
                " WHERE role='admin' AND status='active'"
            ).fetchone()
        return int(row["n"])

    def list_for_admin(
        self,
        *,
        include_deleted: bool = False,
        search: str | None = None,
    ) -> list[PivotUser]:
        sql = "SELECT * FROM pivot_user WHERE 1=1"
        params: list[object] = []
        if not include_deleted:
            sql += " AND status != 'deleted'"
        if search:
            sql += " AND (display_name LIKE ? OR email LIKE ? OR pinyin LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])
        sql += " ORDER BY created_at ASC"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_user(r) for r in rows]
