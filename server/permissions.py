from __future__ import annotations

from dataclasses import dataclass

from server.db import Database
from server.pivot_users import PivotUserRepo
from server.visibility_scopes import VisibilityScope


@dataclass(frozen=True)
class VisibilityValidationResult:
    ok: bool
    code: str | None = None
    message: str | None = None


class PermissionService:
    def __init__(self, db: Database):
        self.db = db

    def can_read_category(self, user_id: str, category_id: str) -> bool:
        roles = self._user_roles(user_id)
        if not roles:
            return False
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT mode FROM category_visibility_cache WHERE category_id=?",
                (category_id,),
            ).fetchone()
        if row is None or row["mode"] == "public":
            return True
        return self._matches_roles(
            "category_visibility_role_cache", "category_id", category_id, roles
        )

    def can_read_matter(self, user_id: str, matter_id: str) -> bool:
        roles = self._user_roles(user_id)
        if not roles:
            return False
        with self.db.connect() as conn:
            matter = conn.execute(
                "SELECT category_id, mode FROM matter_visibility_cache WHERE matter_id=?",
                (matter_id,),
            ).fetchone()
            if matter is None:
                return False
            direct = conn.execute(
                "SELECT 1 FROM matter_visibility_user_cache"
                " WHERE matter_id=? AND pivot_user_id=?",
                (matter_id, user_id),
            ).fetchone()
        if not self.can_read_category(user_id, matter["category_id"]):
            return False
        if matter["mode"] == "public":
            return True
        if direct is not None:
            return True
        return self._matches_roles(
            "matter_visibility_role_cache", "matter_id", matter_id, roles
        )

    def can_write_matter(self, user_id: str, matter_id: str) -> bool:
        return self.can_read_matter(user_id, matter_id)

    def can_update_matter_visibility(self, user_id: str, matter_id: str) -> bool:
        if not self.can_read_matter(user_id, matter_id):
            return False
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT creator_id, owner_id FROM matter_visibility_cache WHERE matter_id=?",
                (matter_id,),
            ).fetchone()
        if row is None:
            return False
        return user_id in {row["creator_id"], row["owner_id"]}

    def validate_matter_visibility_scope(
        self, matter_id: str, scope: VisibilityScope
    ) -> VisibilityValidationResult:
        with self.db.connect() as conn:
            matter = conn.execute(
                "SELECT category_id FROM matter_visibility_cache WHERE matter_id=?",
                (matter_id,),
            ).fetchone()
        if matter is None:
            return VisibilityValidationResult(False, "matter_not_found")
        category_id = matter["category_id"]
        category_mode, category_roles = self._category_scope(category_id)
        if category_mode == "public":
            return VisibilityValidationResult(True)
        if scope.mode == "public":
            return VisibilityValidationResult(True)
        extra = set(scope.roles) - set(category_roles)
        if extra:
            return VisibilityValidationResult(
                False,
                "visibility_scope_exceeds_category",
                "matter visibility roles must be within category visibility",
            )
        return VisibilityValidationResult(True)

    def filter_visible_matters(self, user_id: str, matters: list[dict]) -> list[dict]:
        return [
            item for item in matters
            if self.can_read_matter(user_id, str(item.get("id") or ""))
        ]

    def list_mentionable_users(self, user_id: str, matter_id: str):
        if not self.can_read_matter(user_id, matter_id):
            return []
        users = PivotUserRepo(self.db).list_for_admin(include_deleted=False)
        return [u for u in users if self.can_read_matter(u.id, matter_id)]

    def _user_roles(self, user_id: str) -> list[str]:
        user = PivotUserRepo(self.db).get(user_id)
        if user is None or user.status != "active":
            return []
        return user.roles

    def _matches_roles(
        self, table: str, key_col: str, key: str, roles: list[str]
    ) -> bool:
        if not roles:
            return False
        placeholders = ",".join("?" for _ in roles)
        with self.db.connect() as conn:
            return conn.execute(
                f"SELECT 1 FROM {table} WHERE {key_col}=? AND role IN ({placeholders})",
                (key, *roles),
            ).fetchone() is not None

    def _category_scope(self, category_id: str) -> tuple[str, list[str]]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT mode FROM category_visibility_cache WHERE category_id=?",
                (category_id,),
            ).fetchone()
            roles = conn.execute(
                "SELECT role FROM category_visibility_role_cache WHERE category_id=?",
                (category_id,),
            ).fetchall()
        return (row["mode"] if row else "public", [r["role"] for r in roles])
