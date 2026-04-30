from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException

from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.feishu_contacts import FeishuContactSyncer
from server.pivot_users import PivotUser
from server.users import User

log = logging.getLogger(__name__)


def build_router(
    sessions: SessionStore,
    contacts: ContactRepo,
    bindings: ExternalBindingRepo,
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
        user: PivotUser = Depends(admin_user_cookie_only),
    ):
        # 同步走 tenant_access_token（飞书 app 自己的凭据，服务器级），
        # 但仍要求当前 admin 自己绑了飞书 —— 这是产品语义判断：联系人
        # 同步是"飞书企业管理"动作，没绑飞书的邀请 admin 不应触发。
        # 前端会按 me.providers 隐藏菜单条目；这里是服务器端兜底守卫，
        # 防止直接 POST 绕过 UI。
        my_bindings = bindings.list_for_user(user.id)
        if not any(b.provider == "feishu" for b in my_bindings):
            raise HTTPException(
                status_code=403,
                detail="需要飞书账号绑定才能同步通讯录",
            )
        log.info("manual contact sync triggered by user=%s", user.id)
        try:
            n = syncer.sync()
        except Exception as e:
            log.warning("manual contact sync failed", exc_info=True)
            raise HTTPException(status_code=502, detail=f"同步失败：{e}") from e
        return {"ok": True, "synced": n, "total": contacts.count()}

    return router
