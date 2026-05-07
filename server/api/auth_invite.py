"""Invite link load endpoint (public).

GET  /api/invite/{token}         → returns invite metadata (expires_at,
                                    provider) so the SPA landing page can
                                    show the IM-login button. 404 when the
                                    token is invalid, expired, or already
                                    used.
POST /api/invite/{token}/start   → returns the IM OAuth redirect URL
                                    (added in a follow-up commit).

Both endpoints are public — auth is the invite token itself.

Note on path prefix: the API lives under /api/* so a single reverse-proxy
rule (``handle /api/* { reverse_proxy backend }``) covers it. The
public-facing URL we put in invite messages is still ``/invite/<token>``
— that path is served by the SPA, which then fetches ``/api/invite/...``
for the JSON.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from server.invites import InviteRepo

SESSION_COOKIE = "sid"


def build_router(
    invites: InviteRepo,
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

    return router
