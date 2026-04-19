from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Cookie, HTTPException

log = logging.getLogger(__name__)
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from server.auth.feishu_oauth import FeishuOAuth, FeishuOAuthError
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.users import User, UserRepo

SESSION_COOKIE = "sid"
STATE_MAX_AGE_SEC = 600


class ProfileUpdate(BaseModel):
    pinyin: str | None = Field(default=None, min_length=2, max_length=40)
    github_username: str | None = Field(default=None, max_length=39)


def _user_dict(u: User) -> dict:
    return {
        "open_id": u.open_id,
        "name": u.name,
        "avatar_url": u.avatar_url,
        "pinyin": u.pinyin,
        "github_username": u.github_username,
        "needs_setup": u.needs_setup,
    }


def build_router(
    oauth: FeishuOAuth,
    sessions: SessionStore,
    users: UserRepo,
    contacts: ContactRepo,
    session_secret: str,
    post_login_redirect: str = "/",
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    signer = URLSafeTimedSerializer(session_secret, salt="feishu-oauth-state")
    cookie_samesite = "none" if secure_cookie else "lax"

    def _issue_state() -> str:
        return signer.dumps(secrets.token_urlsafe(16))

    def _verify_state(state: str) -> None:
        try:
            signer.loads(state, max_age=STATE_MAX_AGE_SEC)
        except BadSignature as e:
            raise HTTPException(status_code=400, detail="invalid state") from e

    def _current_user(sid: str | None) -> User:
        s = sessions.get(sid)
        if s is None:
            raise HTTPException(status_code=401, detail="not logged in")
        u = users.get(s.user_open_id)
        if u is None:
            sessions.delete(sid)
            raise HTTPException(status_code=401, detail="user not found")
        return u

    @router.get("/login")
    def login() -> RedirectResponse:
        log.info("login initiated")
        return RedirectResponse(oauth.authorize_url(_issue_state()))

    @router.get("/auth/callback")
    def callback(code: str, state: str) -> RedirectResponse:
        _verify_state(state)
        try:
            token = oauth.exchange_code(code)
            info = oauth.get_user_info(token.access_token)
        except FeishuOAuthError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        users.upsert_from_feishu(
            open_id=info.open_id,
            union_id=info.union_id,
            name=info.name,
            avatar_url=info.avatar_url,
        )
        contacts.upsert_many([{
            "open_id": info.open_id,
            "union_id": info.union_id,
            "name": info.name,
            "en_name": None,
            "avatar_url": info.avatar_url or "",
        }])
        sid = sessions.create(info.open_id, user_access_token=token.access_token)
        log.info("login success name=%s open_id=%s", info.name, info.open_id)
        resp = RedirectResponse(post_login_redirect, status_code=302)
        resp.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite=cookie_samesite,
            secure=secure_cookie,
            path="/",
        )
        return resp

    @router.get("/me")
    def me(sid: str | None = Cookie(default=None)) -> JSONResponse:
        return JSONResponse(_user_dict(_current_user(sid)))

    @router.post("/me/profile")
    def update_profile(
        body: ProfileUpdate, sid: str | None = Cookie(default=None)
    ) -> JSONResponse:
        user = _current_user(sid)
        try:
            updated = users.update_profile(
                user.open_id,
                pinyin=body.pinyin,
                github_username=body.github_username,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        assert updated is not None
        return JSONResponse(_user_dict(updated))

    @router.post("/logout")
    def logout(sid: str | None = Cookie(default=None)) -> JSONResponse:
        s = sessions.get(sid)
        if s is not None:
            log.info("logout user=%s", s.user_open_id)
        sessions.delete(sid)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    return router
