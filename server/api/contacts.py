from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException

from server.auth.admin import require_admin
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.feishu_contacts import FeishuContactSyncer
from server.users import User

log = logging.getLogger(__name__)


def build_router(
    sessions: SessionStore,
    contacts: ContactRepo,
    syncer: FeishuContactSyncer,
    current_user: Callable,
    current_user_cookie_only: Callable,
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

    @router.get("/contacts/by-ids")
    def lookup_contacts_by_ids(
        ids: str = "",
        _: User = Depends(current_user),
    ):
        """批量按 open_id 解析联系人。`ids` 是逗号分隔的 open_id 列表。
        返回 items: list[Contact]。未匹配的 id 不出现在结果里(调用方按需兜底)。
        给前端 OpenIdMultiPick 等组件用 — 编辑已有 receiver_ids 时把 open_id
        转成可读姓名。"""
        raw = [x.strip() for x in ids.split(",") if x.strip()]
        # 上限保护:一次最多 200 条避免 SQL 参数过载
        ids_list = raw[:200]
        if not ids_list:
            return {"items": []}
        result = contacts.get_many(ids_list)
        return {
            "items": [
                {
                    "open_id": c.open_id,
                    "name": c.name,
                    "en_name": c.en_name,
                    "avatar_url": c.avatar_url,
                }
                for c in result.values()
            ],
        }

    @router.post("/contacts/sync", dependencies=[Depends(require_admin)])
    def sync_contacts(
        sid: str | None = Cookie(default=None),
        user: User = Depends(current_user_cookie_only),
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
        log.info("manual contact sync triggered by user=%s", user.open_id)
        try:
            n = syncer.sync(token)
        except Exception as e:
            log.warning("manual contact sync failed", exc_info=True)
            raise HTTPException(status_code=502, detail=f"同步失败：{e}") from e
        return {"ok": True, "synced": n, "total": contacts.count()}

    return router
