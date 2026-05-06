from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from time import time

from server.db import Database
from server.pivot_users import PivotUserRepo

SYSTEM_ROLE_LABELS = {
    "admin": "管理员",
    "member": "成员",
}
SYSTEM_ROLES = set(SYSTEM_ROLE_LABELS)


@dataclass(frozen=True)
class PivotRole:
    name: str
    label: str | None
    kind: str
    description: str | None
    is_active: bool
    user_count: int
    created_at: float
    updated_at: float


def validate_role_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("role cannot be empty")
    if len(name) > 40:
        raise ValueError("role is too long")
    if any(ord(ch) < 32 for ch in name):
        raise ValueError("role contains control characters")
    return name


def _role_key_for_label(label: str, index: int = 0) -> str:
    digest = sha1(label.encode("utf-8")).hexdigest()[:10]
    return f"role_{digest}" if index == 0 else f"role_{digest}_{index}"


class PivotRoleRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def ensure_from_users(self) -> None:
        users = PivotUserRepo(self._db)
        now = time()
        with self._db.connect() as conn:
            for name in SYSTEM_ROLES:
                conn.execute(
                    "INSERT OR IGNORE INTO pivot_role"
                    " (name, label, kind, description, is_active, created_at, updated_at)"
                    " VALUES (?, ?, 'system', NULL, 1, ?, ?)",
                    (name, SYSTEM_ROLE_LABELS[name], now, now),
                )
                conn.execute(
                    "UPDATE pivot_role SET label=?, kind='system' WHERE name=?",
                    (SYSTEM_ROLE_LABELS[name], name),
                )
            for user in users.list_for_admin(include_deleted=False):
                for role in user.roles:
                    kind = "system" if role in SYSTEM_ROLES else "business"
                    conn.execute(
                        "INSERT OR IGNORE INTO pivot_role"
                        " (name, label, kind, description, is_active, created_at, updated_at)"
                        " VALUES (?, ?, ?, NULL, 1, ?, ?)",
                        (
                            role,
                            SYSTEM_ROLE_LABELS.get(role),
                            kind,
                            now,
                            now,
                        ),
                    )

    def list(self, include_inactive: bool = False) -> list[PivotRole]:
        self.ensure_from_users()
        users = PivotUserRepo(self._db).list_for_admin(include_deleted=False)
        counts: dict[str, int] = {}
        for user in users:
            if user.status != "active":
                continue
            for role in user.roles:
                counts[role] = counts.get(role, 0) + 1
        sql = "SELECT * FROM pivot_role"
        params: list[object] = []
        if not include_inactive:
            sql += " WHERE is_active=1"
        sql += " ORDER BY kind DESC, lower(name)"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            PivotRole(
                name=row["name"],
                label=row["label"],
                kind=row["kind"],
                description=row["description"],
                is_active=bool(row["is_active"]),
                user_count=counts.get(row["name"], 0),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get(self, name: str) -> PivotRole | None:
        target = validate_role_name(name)
        return next((role for role in self.list(include_inactive=True) if role.name == target), None)

    def create(
        self,
        *,
        name: str,
        description: str | None = None,
        kind: str = "business",
    ) -> PivotRole:
        label = validate_role_name(name)
        if kind not in {"system", "business"}:
            raise ValueError("invalid role kind")
        target = label if kind == "system" else _role_key_for_label(label)
        now = time()
        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM pivot_role WHERE name=? OR label=?",
                (label, label),
            ).fetchone()
            if existing is not None:
                raise ValueError("role already exists")
            index = 0
            while conn.execute(
                "SELECT 1 FROM pivot_role WHERE name=?", (target,)
            ).fetchone() is not None:
                index += 1
                target = _role_key_for_label(label, index)
            conn.execute(
                "INSERT INTO pivot_role"
                " (name, label, kind, description, is_active, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (target, label, kind, description, 1, now, now),
            )
        got = self.get(target)
        assert got is not None
        return got

    def set_active(self, name: str, active: bool) -> PivotRole:
        target = validate_role_name(name)
        if target in SYSTEM_ROLES and not active:
            raise ValueError("system_role_protected")
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM pivot_role WHERE name=?", (target,)
            ).fetchone()
            if row is None:
                raise KeyError(target)
            conn.execute(
                "UPDATE pivot_role SET is_active=?, updated_at=? WHERE name=?",
                (1 if active else 0, time(), target),
            )
        got = self.get(target)
        assert got is not None
        return got

    def set_members(self, name: str, user_ids: list[str]) -> PivotRole:
        target = validate_role_name(name)
        if self.get(target) is None:
            raise KeyError(target)
        users = PivotUserRepo(self._db)
        wanted = set(user_ids)
        all_users = users.list_for_admin(include_deleted=False)
        if target == "admin":
            active_admin_after = 0
            for user in all_users:
                roles = set(user.roles)
                if user.id in wanted:
                    roles.add("admin")
                else:
                    roles.discard("admin")
                if "admin" in roles and user.status == "active":
                    active_admin_after += 1
            if active_admin_after < 1:
                raise ValueError("last_active_admin_protected")
        for user in all_users:
            roles = list(user.roles)
            has_role = target in roles
            should_have = user.id in wanted
            if should_have and not has_role:
                roles.append(target)
            if has_role and not should_have:
                roles = [role for role in roles if role != target]
            if not roles:
                roles = ["member"]
            if roles != user.roles:
                users.update_role(user_id=user.id, roles=roles)
        got = self.get(target)
        assert got is not None
        return got
