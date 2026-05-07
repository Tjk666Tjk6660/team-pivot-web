"""Pivot user master data — replaces server/users.py after migration."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, replace
from time import time
from typing import Iterable

from server.db import Database

PINYIN_RE_PATTERN = r"^[a-z][a-z0-9._-]{1,39}$"


@dataclass(frozen=True)
class PivotUser:
    id: str
    display_name: str
    pinyin: str | None
    email: str | None
    avatar_url: str
    github_username: str | None
    role: str
    roles: list[str]
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
        return "admin" in self.roles and self.status == "active"

    # ── Backward-compat aliases ──────────────────────────────────────────
    # Legacy routes / repos written before the migration read `user.open_id`
    # and `user.name`. Post-migration the canonical reference is the ULID
    # `id` (carried in PK of every downstream table) and the display field
    # is `display_name`. Aliasing here keeps drafts / read_state / inbox /
    # matters / publish working without rewriting every call site —
    # individual files can be migrated to the new names incrementally.

    @property
    def open_id(self) -> str:
        return self.id

    @property
    def name(self) -> str:
        return self.display_name

    @property
    def markdown_style(self) -> str | None:
        """Legacy ``User.markdown_style`` column is gone (DROP TABLE users).
        Per-user markdown style is stored in ``user_preferences`` by
        ``server.api.markdown_styles``; return None for legacy call sites
        that still expect the attribute on the user object."""
        return None


def _new_id() -> str:
    return uuid.uuid4().hex


def _decode_roles(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
        if isinstance(decoded, list):
            return _validate_roles([str(item) for item in decoded])
    return _validate_roles([raw])


def _encode_roles(roles: list[str]) -> str:
    return json.dumps(_validate_roles(roles), ensure_ascii=False)


def _validate_roles(roles: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for role in roles:
        value = str(role).strip()
        if not value:
            raise ValueError("role cannot be empty")
        if len(value) > 40:
            raise ValueError("role is too long")
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("role contains control characters")
        if value not in seen:
            cleaned.append(value)
            seen.add(value)
    if not cleaned:
        raise ValueError("user must have at least one role")
    return cleaned


def _primary_role(value: str) -> str:
    roles = _decode_roles(value)
    return roles[0] if roles else "member"


def _row_to_user(row: sqlite3.Row) -> PivotUser:
    raw_role = row["role"]
    roles = _decode_roles(raw_role)
    return PivotUser(
        id=row["id"],
        display_name=row["display_name"],
        pinyin=row["pinyin"],
        email=row["email"],
        avatar_url=row["avatar_url"] or "",
        github_username=row["github_username"],
        role=roles[0] if roles else "member",
        roles=roles,
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
                     _encode_roles(_decode_roles(role)), "active", now, now),
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

    def get_by_pinyin(self, pinyin: str) -> PivotUser | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user WHERE pinyin=? COLLATE NOCASE", (pinyin,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_any_id(self, value: str) -> PivotUser | None:
        """Compatibility lookup for migrated call sites.

        Accepts canonical pivot_user.id plus the user-facing identifiers
        that matter indexes may still carry: pinyin and email. Feishu open_id
        / union_id resolution lives in ExternalBindingRepo because those ids
        are no longer columns on the user table.
        """
        if not value:
            return None
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user"
                " WHERE id=? OR pinyin=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                (value, value, value),
            ).fetchone()
        return _row_to_user(row) if row else None

    def all(self) -> list[PivotUser]:
        """Return all active/non-deleted users for relevance scans.

        Mirrors the legacy UserRepo.all() shape while excluding deleted users
        that should no longer receive unread/relevance rows.
        """
        return self.list_for_admin(include_deleted=False)

    def list_all(self) -> list[PivotUser]:
        """Compatibility alias used by daily-report style enumerations."""
        return sorted(
            self.list_for_admin(include_deleted=False),
            key=lambda u: u.display_name.lower(),
        )

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

    def update_role(
        self, *, user_id: str, role: str | None = None, roles: list[str] | None = None
    ) -> PivotUser:
        if roles is None:
            if role is None:
                raise ValueError("role or roles is required")
            roles = [role]
        encoded = _encode_roles(roles)
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET role=?, updated_at=? WHERE id=?",
                (encoded, time(), user_id),
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
            rows = conn.execute(
                "SELECT role FROM pivot_user WHERE status='active'"
            ).fetchall()
        return sum(1 for row in rows if "admin" in _decode_roles(row["role"]))

    def list_roles(self) -> list[dict[str, object]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT role FROM pivot_user WHERE status='active'"
            ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            for role in _decode_roles(row["role"]):
                counts[role] = counts.get(role, 0) + 1
        return [
            {"role": role, "user_count": count}
            for role, count in sorted(counts.items(), key=lambda item: item[0].lower())
        ]

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

    def list_by_name_or_pinyin_exact(self, value: str) -> list[PivotUser]:
        """Exact-match lookup for @-mention resolution from MCP / publish path.

        Replaces the legacy ``ContactRepo.lookup_candidates`` exact-match
        branch (name / en_name / pinyin). pivot_user has no en_name column,
        so we match against display_name + pinyin only — both COLLATE NOCASE
        for forgiving "ZhangBo" vs "zhangbo" input. Returns a list because
        display_name is not unique by schema; callers MUST handle
        ambiguity rather than silently picking the first row.
        """
        if not value:
            return []
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pivot_user"
                " WHERE display_name = ? COLLATE NOCASE"
                "    OR pinyin = ? COLLATE NOCASE",
                (value, value),
            ).fetchall()
        return [_row_to_user(r) for r in rows]

    def search_mentionable(
        self,
        *,
        query: str | None,
        limit: int,
    ) -> list[tuple[PivotUser, str, str | None]]:
        """active 状态、且绑了飞书的 pivot_user 列表 —— 圈人候选数据源。

        返回 (PivotUser, feishu_open_id, feishu_union_id) 三元组。圈人本质
        是触发飞书 IM @-提醒，没飞书 binding 的邀请码用户没有 open_id 可发，
        不能进候选。每条记录唯一来自 external_binding(provider='feishu')。
        """
        like = f"%{query}%" if query else None
        sql = (
            "SELECT pu.*, eb.external_id AS feishu_open_id,"
            "       eb.external_union_id AS feishu_union_id"
            " FROM pivot_user pu"
            " JOIN external_binding eb"
            "   ON eb.pivot_user_id = pu.id AND eb.provider = 'feishu'"
            " WHERE pu.status = 'active'"
        )
        params: list[object] = []
        if like is not None:
            sql += (
                " AND (pu.display_name LIKE ?"
                " OR pu.email LIKE ?"
                " OR pu.pinyin LIKE ?)"
            )
            params.extend([like, like, like])
        sql += " ORDER BY pu.display_name ASC LIMIT ?"
        params.append(limit)
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            (_row_to_user(r), r["feishu_open_id"], r["feishu_union_id"])
            for r in rows
        ]
