"""Invite link load + OAuth start endpoints (public).

GET  /api/invite/{token}         → invite metadata (expires_at, provider)
                                    so the SPA landing page can render the
                                    IM-login button. 404 when invalid /
                                    expired / used.
POST /api/invite/{token}/start   → returns {redirect_url} pointing at the
                                    IM OAuth authorize page. The state
                                    parameter carries an HMAC-signed
                                    envelope with the invite_token so the
                                    callback can credit the application.

Both endpoints are public — auth is the invite token itself.

Note on path prefix: the API lives under /api/* so a single reverse-proxy
rule (``handle /api/* { reverse_proxy backend }``) covers it. The
public-facing URL we put in invite messages is still ``/invite/<token>``
— that path is served by the SPA, which then fetches ``/api/invite/...``
for the JSON.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from server.auth.invite_state import encode_invite_state
from server.invites import InviteRepo

if TYPE_CHECKING:
    from server.auth.feishu_oauth import FeishuOAuth

SESSION_COOKIE = "sid"


def build_router(
    invites: InviteRepo,
    feishu_oauth: "FeishuOAuth | None" = None,
    state_secret: str = "",
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/invite/{token}")
    def load(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        return JSONResponse(
            {
                "expires_at": invite.expires_at,
                "provider": "feishu",
            }
        )

    @router.post("/api/invite/{token}/start")
    def start(token: str) -> JSONResponse:
        if feishu_oauth is None or not state_secret:
            raise HTTPException(status_code=500, detail="oauth_not_configured")
        invite = invites.resolve_token(token)
        if invite is None:
            # resolve_token returns None for unknown AND expired/used. Drill
            # into the underlying record to tell apart 404 (never existed)
            # from 410 (existed but no longer usable) per spec.
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            with invites._db.connect() as conn:  # noqa: SLF001
                row = conn.execute(
                    "SELECT used_at, expires_at FROM invite WHERE token_hash=?",
                    (token_hash,),
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="not_found")
            raise HTTPException(status_code=410, detail="invite_unusable")
        state = encode_invite_state(invite_token=token, secret=state_secret)
        return JSONResponse({
            "redirect_url": feishu_oauth.authorize_url(state=state),
        })

    return router
