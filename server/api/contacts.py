from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Cookie, Depends, HTTPException

from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.feishu_contacts import FeishuContactSyncer
from server.pivot_users import PivotUser, PivotUserRepo
from server.users import User

log = logging.getLogger(__name__)


def build_router(
    sessions: SessionStore,
    contacts: ContactRepo,
    pivot_users: PivotUserRepo,
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
        """圈人候选源：返回 active 且绑了飞书的 pivot_user。

        没绑飞书的邀请码用户不能被 @（飞书 IM 没法 ping 到他们），所以
        从候选中过滤掉。前端 MentionField 期望的字段格式（open_id /
        name / en_name / avatar_url）保留，open_id 填飞书 binding 的
        external_id，name 填 pivot_user.display_name —— 写入路径下游
        语义不变。
        """
        limit = max(1, min(100, limit))
        rows = pivot_users.search_mentionable(query=q or None, limit=limit)
        return {
            "items": [
                {
                    "open_id": feishu_open_id,
                    "name": user.display_name,
                    # pivot_user 没 en_name 字段（contacts 表才有）；这里
                    # 留 None，前端 fallback 到 name 显示。
                    "en_name": None,
                    "avatar_url": user.avatar_url or "",
                }
                for user, feishu_open_id, _union_id in rows
            ],
            # total 字段保留兼容前端，但意义改成"系统里能被 @ 的用户总数"
            # 而不是"飞书联系人总数"。
            "total": len(rows),
        }

    # /contacts/sync endpoint 暂时注释掉（圈人候选切到 pivot_user JOIN
    # external_binding(feishu) 后，admin 触发的全量飞书通讯录同步失去
    # 主要使用场景，前端菜单也下线了）。contacts 表的填充改由
    # /auth/callback 飞书登录时 contacts.upsert_from_login 单条更新维护，
    # 足够 DisplayResolver 兼容渲染老 frontmatter 用。
    # 如未来重启此功能，去掉下面注释即可，syncer / bindings 参数都
    # 仍然在 build_router 签名里 ready。
    #
    # @router.post("/contacts/sync")
    # def sync_contacts(
    #     user: PivotUser = Depends(admin_user_cookie_only),
    # ):
    #     # 同步走 tenant_access_token（飞书 app 自己的凭据，服务器级），
    #     # 但仍要求当前 admin 自己绑了飞书 —— 联系人同步是"飞书企业
    #     # 管理"动作，没绑飞书的邀请 admin 不应触发。
    #     my_bindings = bindings.list_for_user(user.id)
    #     if not any(b.provider == "feishu" for b in my_bindings):
    #         raise HTTPException(
    #             status_code=403,
    #             detail="需要飞书账号绑定才能同步通讯录",
    #         )
    #     log.info("manual contact sync triggered by user=%s", user.id)
    #     try:
    #         n = syncer.sync()
    #     except Exception as e:
    #         log.warning("manual contact sync failed", exc_info=True)
    #         raise HTTPException(status_code=502, detail=f"同步失败：{e}") from e
    #     return {"ok": True, "synced": n, "total": contacts.count()}

    return router
