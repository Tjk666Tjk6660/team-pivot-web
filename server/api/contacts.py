from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, HTTPException

from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.feishu_contacts import FeishuContactSyncer
from server.users import User, UserRepo

log = logging.getLogger(__name__)


def build_router(
    sessions: SessionStore,
    users: UserRepo,
    contacts: ContactRepo,
    syncer: FeishuContactSyncer,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _require_auth(sid: str | None) -> User:
        s = sessions.get(sid)
        if s is None:
            raise HTTPException(status_code=401, detail="not logged in")
        u = users.get(s.user_open_id)
        if u is None:
            sessions.delete(sid)
            raise HTTPException(status_code=401, detail="user not found")
        return u

    @router.get("/contacts")
    def list_contacts(
        q: str = "", limit: int = 20, sid: str | None = Cookie(default=None),
    ):
        _require_auth(sid)
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
    def sync_contacts(sid: str | None = Cookie(default=None)):
        user = _require_auth(sid)
        log.info("manual contact sync triggered by user=%s", user.open_id)
        try:
            n = syncer.sync()
        except Exception as e:
            log.warning("manual contact sync failed", exc_info=True)
            raise HTTPException(status_code=502, detail=f"同步失败：{e}") from e
        return {"ok": True, "synced": n, "total": contacts.count()}

    return router
