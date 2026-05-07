"""Invite link load + accept endpoints (public).

GET  /api/invite/{token}         → returns invite metadata (email,
                                    display_name, expires_at) so the
                                    frontend can show the accept form.
                                    404 when the token is invalid,
                                    expired, or already used.
POST /api/invite/{token}/accept  → consumes the invite, creates the pivot
                                    user + invite-provider binding (bcrypt
                                    password), opens a session, and sets
                                    the sid cookie.

Both endpoints are public — auth is the invite token itself.

Note on path prefix: the API lives under /api/* so a single reverse-proxy
rule (``handle /api/* { reverse_proxy backend }``) covers it. The
public-facing URL we put in invite emails is still ``/invite/<token>``
— that path is served by the SPA, which then fetches ``/api/invite/...``
for the JSON.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.invites import InviteRepo
from server.passwords import hash_password
from server.pivot_users import PINYIN_RE_PATTERN, PivotUserRepo

SESSION_COOKIE = "sid"


class InviteAcceptBody(BaseModel):
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    pinyin: str = Field(min_length=2, max_length=40, pattern=PINYIN_RE_PATTERN)


def build_router(
    invites: InviteRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.get("/api/invite/{token}")
    def load(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        return JSONResponse(
            {
                "expires_at": invite.expires_at,
            }
        )

    @router.post("/api/invite/{token}/accept")
    def accept(token: str, body: InviteAcceptBody) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        try:
            user = pivot_users.create(
                display_name=body.display_name,
                pinyin=body.pinyin,
                email=invite.email,
                avatar_url="",
                role="member",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        bindings.bind(
            pivot_user_id=user.id,
            provider="invite",
            external_id=invite.email,
            external_union_id=None,
            raw_profile_json=None,
            password_hash=hash_password(body.password),
        )
        invites.mark_used(invite_id=invite.id, used_by_user_id=user.id)
        sid = sessions.create(pivot_user_id=user.id)
        resp = JSONResponse(
            {
                "user": {
                    "id": user.id,
                    "display_name": user.display_name,
                    "role": user.role,
                    "roles": user.roles,
                    "status": user.status,
                },
            }
        )
        resp.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite=samesite,
            secure=secure_cookie,
            path="/",
        )
        return resp

    return router
