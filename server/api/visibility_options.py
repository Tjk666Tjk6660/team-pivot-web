from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends

from server.auth.deps import require_profile
from server.pivot_users import PivotUser, PivotUserRepo
from server.roles import PivotRoleRepo
from server.visibility_store import read_category_visibility


def build_router(
    users: PivotUserRepo,
    roles: PivotRoleRepo,
    *,
    categories_dir: Path,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/visibility-options")
    def visibility_options(
        category: str | None = None,
        user: PivotUser = Depends(current_user),
    ):
        require_profile(user)
        allowed_roles = _allowed_roles_for_category(categories_dir, category)
        active_users = [
            u for u in users.list_for_admin(include_deleted=False)
            if u.status == "active"
        ]
        role_members: dict[str, list[PivotUser]] = {
            item.name: []
            for item in roles.list(include_inactive=False)
            if item.name != "admin"
            and (allowed_roles is None or item.name in allowed_roles)
        }
        for candidate in active_users:
            for role in candidate.roles:
                if role == "admin":
                    continue
                if allowed_roles is not None and role not in allowed_roles:
                    continue
                role_members.setdefault(role, []).append(candidate)

        visible_users = [
            u for u in active_users
            if allowed_roles is None or set(u.roles).intersection(allowed_roles)
        ]
        return {
            "all": {"label": "全部用户", "value": "public"},
            "roles": [
                {
                    "role": role.name,
                    "name": role.label or role.name,
                    "label": role.label or role.name,
                    "users": [_user_option(u) for u in role_members[role.name]],
                }
                for role in sorted(
                    roles.list(include_inactive=False),
                    key=lambda item: (item.label or item.name).lower(),
                )
                if role.name in role_members
            ],
            "users": [_user_option(u) for u in visible_users],
        }

    return router


def _allowed_roles_for_category(
    categories_dir: Path, category: str | None
) -> set[str] | None:
    if not category:
        return None
    scope = read_category_visibility(categories_dir, category)
    if scope.mode == "public":
        return None
    return set(scope.authorized_roles)


def _user_option(user: PivotUser) -> dict[str, str | None]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "pinyin": user.pinyin,
        "avatar_url": user.avatar_url,
    }
