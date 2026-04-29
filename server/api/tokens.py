from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.api_tokens import ApiToken, ApiTokenRepo, MAX_TTL_DAYS, MIN_TTL_DAYS, DEFAULT_TTL_DAYS
from server.pivot_users import PivotUser


class CreateTokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=MIN_TTL_DAYS, le=MAX_TTL_DAYS)


def build_router(
    tokens: ApiTokenRepo,
    current_user_cookie_only: Callable,
) -> APIRouter:
    """Token management routes. Cookie-session only (no admin password required).

    Every logged-in user needs to create their own PAT to use the VS Code client.
    """
    router = APIRouter(prefix="/api/tokens")

    @router.post("")
    def create_token(
        body: CreateTokenBody,
        user: PivotUser = Depends(current_user_cookie_only),
    ):
        plaintext, tok = tokens.create(
            pivot_user_id=user.id,
            name=body.name.strip(),
            ttl_days=body.ttl_days,
        )
        return {
            "id": tok.short_id,
            "name": tok.name,
            "token": plaintext,
            "created_at": tok.created_at,
            "expires_at": tok.expires_at,
        }

    @router.get("")
    def list_tokens(user: PivotUser = Depends(current_user_cookie_only)):
        items = [_to_dict(t) for t in tokens.list_for_user(user.id)]
        return {"items": items}

    @router.delete("/{short_id}")
    def delete_token(
        short_id: str,
        user: PivotUser = Depends(current_user_cookie_only),
    ):
        ok = tokens.delete_by_short_id(user.id, short_id)
        if not ok:
            raise HTTPException(status_code=404, detail="token not found")
        return {"ok": True}

    return router


def _to_dict(t: ApiToken) -> dict:
    return {
        "id": t.short_id,
        "name": t.name,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "expires_at": t.expires_at,
    }
