from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from server.auth.feishu_oauth import FeishuOAuth, FeishuOAuthError
from server.auth.session import SessionStore

SESSION_COOKIE = "sid"
STATE_MAX_AGE_SEC = 600


def build_router(
    oauth: FeishuOAuth,
    sessions: SessionStore,
    session_secret: str,
    post_login_redirect: str = "/",
) -> APIRouter:
    router = APIRouter()
    signer = URLSafeTimedSerializer(session_secret, salt="feishu-oauth-state")

    def _issue_state() -> str:
        return signer.dumps(secrets.token_urlsafe(16))

    def _verify_state(state: str) -> None:
        try:
            signer.loads(state, max_age=STATE_MAX_AGE_SEC)
        except BadSignature as e:
            raise HTTPException(status_code=400, detail="invalid state") from e

    @router.get("/login")
    def login() -> RedirectResponse:
        return RedirectResponse(oauth.authorize_url(_issue_state()))

    @router.get("/auth/callback")
    def callback(code: str, state: str) -> RedirectResponse:
        _verify_state(state)
        try:
            token = oauth.exchange_code(code)
            user = oauth.get_user_info(token.access_token)
        except FeishuOAuthError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        sid = sessions.create(
            user_open_id=user.open_id,
            name=user.name,
            avatar_url=user.avatar_url,
        )
        resp = RedirectResponse(post_login_redirect, status_code=302)
        resp.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
        return resp

    @router.get("/me")
    def me(sid: str | None = Cookie(default=None)) -> JSONResponse:
        s = sessions.get(sid)
        if s is None:
            raise HTTPException(status_code=401, detail="not logged in")
        return JSONResponse(
            {
                "open_id": s.user_open_id,
                "name": s.name,
                "avatar_url": s.avatar_url,
            }
        )

    @router.post("/logout")
    def logout(sid: str | None = Cookie(default=None)) -> JSONResponse:
        sessions.delete(sid)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    return router
