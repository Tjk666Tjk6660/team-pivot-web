from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends

from server.auth.deps import require_profile
from server.pivot_users import PivotUser, PivotUserRepo


def build_router(
    users: PivotUserRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/users/search")
    def search_users(
        q: str = "",
        limit: int = 20,
        user: PivotUser = Depends(current_user),
    ):
        require_profile(user)
        limit = max(1, min(100, limit))
        rows = users.list_for_admin(
            include_deleted=False,
            search=q.strip() or None,
        )
        active = [u for u in rows if u.status == "active" and u.pinyin]
        return {
            "items": [
                {
                    "id": u.id,
                    "display_name": u.display_name,
                    "pinyin": u.pinyin,
                    "avatar_url": u.avatar_url,
                }
                for u in active[:limit]
            ],
        }

    return router
