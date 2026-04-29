from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException

from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.feishu_contacts import FeishuContactSyncer
from server.pivot_users import PivotUser
from server.users import User

log = logging.getLogger(__name__)


def build_router(
    sessions: SessionStore,
    contacts: ContactRepo,
    syncer: FeishuContactSyncer,
    current_user: Callable,
    current_user_cookie_only: Callable,
    admin_user_cookie_only: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/contacts")
    def list_contacts(
        q: str = "", limit: int = 20,
        _: User = Depends(current_user),
    ):
        limit = max(1, min(100, limit))
        items = contacts.search(q, limit=limit)
        return {
            "items": [
                {
                    "open_id": c.open_id,
                    "name": c.name,
                    "en_name": c.en_name,
                    "avatar_url": c.avatar_url,
                }
                for c in items
            ],
            "total": contacts.count(),
        }

    @router.post("/contacts/sync")
    def sync_contacts(
        sid: str | None = Cookie(default=None),
        user: PivotUser = Depends(admin_user_cookie_only),
    ):
        # Cookie-only because we need the Feishu user_access_token attached
        # to the browser session — PATs don't carry one.
        s = sessions.get(sid)
        token = s.user_access_token if s else None
        if not token:
            raise HTTPException(
                status_code=400,
                detail="当前会话没有飞书 user_access_token，请重新登录后再试",
            )
        log.info("manual contact sync triggered by user=%s", user.id)
        try:
            n = syncer.sync(token)
        except Exception as e:
            log.warning("manual contact sync failed", exc_info=True)
            raise HTTPException(status_code=502, detail=f"同步失败：{e}") from e
        return {"ok": True, "synced": n, "total": contacts.count()}

    return router
