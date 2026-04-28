from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth.admin import require_admin
from server.markdown_styles import (
    DEFAULT_MARKDOWN_STYLE,
    KEY_MARKDOWN_DEFAULT_STYLE,
    all_markdown_style_dicts,
    effective_markdown_style,
    is_markdown_style_id,
    system_default_style,
)
from server.settings import SettingsRepo
from server.users import User, UserRepo


class UserMarkdownStyleIn(BaseModel):
    style: str = Field(min_length=1, max_length=40)


class AdminMarkdownSettingsIn(BaseModel):
    system_default_style: str = Field(min_length=1, max_length=40)


def build_router(
    settings: SettingsRepo,
    users: UserRepo,
    current_user_dep,
    current_user_cookie_only,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/markdown/styles")
    def get_markdown_styles(user: User = Depends(current_user_dep)):
        system_style = system_default_style(settings)
        user_style = user.markdown_style if is_markdown_style_id(user.markdown_style) else None
        return {
            "styles": all_markdown_style_dicts(),
            "system_default_style": system_style,
            "user_style": user_style,
            "effective_style": effective_markdown_style(user=user, settings=settings),
            "builtin_default_style": DEFAULT_MARKDOWN_STYLE,
        }

    @router.put("/api/me/markdown-style")
    def update_user_markdown_style(
        body: UserMarkdownStyleIn,
        user: User = Depends(current_user_dep),
    ):
        if not is_markdown_style_id(body.style):
            raise HTTPException(status_code=400, detail="invalid_markdown_style")
        updated = users.update_markdown_style(user.open_id, body.style)
        assert updated is not None
        return {
            "user_style": updated.markdown_style,
            "effective_style": effective_markdown_style(user=updated, settings=settings),
        }

    @router.get(
        "/api/admin/markdown-settings",
        dependencies=[Depends(require_admin)],
    )
    def get_admin_markdown_settings(_: User = Depends(current_user_cookie_only)):
        system_style = system_default_style(settings)
        return {
            "styles": all_markdown_style_dicts(),
            "system_default_style": system_style,
            "effective_system_default_style": system_style or DEFAULT_MARKDOWN_STYLE,
        }

    @router.put(
        "/api/admin/markdown-settings",
        dependencies=[Depends(require_admin)],
    )
    def update_admin_markdown_settings(
        body: AdminMarkdownSettingsIn,
        _: User = Depends(current_user_cookie_only),
    ):
        if not is_markdown_style_id(body.system_default_style):
            raise HTTPException(status_code=400, detail="invalid_markdown_style")
        settings.set(KEY_MARKDOWN_DEFAULT_STYLE, body.system_default_style)
        return {"ok": True}

    return router
