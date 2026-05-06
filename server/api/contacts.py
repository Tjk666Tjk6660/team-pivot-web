from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends

from server.pivot_users import PivotUser, PivotUserRepo

log = logging.getLogger(__name__)


def build_router(
    pivot_users: PivotUserRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/contacts")
    def list_contacts(
        q: str = "", limit: int = 20,
        _: PivotUser = Depends(current_user),
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
                    # 历史 contacts 表里有 en_name 字段；pivot_user 没有，
                    # 留 None，前端 fallback 到 name 显示。
                    "en_name": None,
                    "avatar_url": user.avatar_url or "",
                }
                for user, feishu_open_id, _union_id in rows
            ],
            # total 字段保留兼容前端，但意义改成"系统里能被 @ 的用户总数"。
            "total": len(rows),
        }

    return router
