"""Unified auth dependencies for /api/* routes (post-migration)."""
from __future__ import annotations

from typing import Callable

from fastapi import Cookie, Header, HTTPException

from server.api_tokens import ApiTokenRepo
from server.auth.session import SessionStore
from server.pivot_users import PivotUser, PivotUserRepo

BEARER_PREFIX = "Bearer "


class _BlockedUser(Exception):
    """Internal sentinel: the resolved user exists but is suspended /
    deleted. Carries the status for the dependency factory to surface
    as detail so the frontend can route to /login?reason=<status>."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _resolve_user(user_id: str, users: PivotUserRepo,
                  on_block_cleanup: Callable[[], None]) -> PivotUser | None:
    u = users.get(user_id)
    if u is None:
        on_block_cleanup()
        return None
    if getattr(u, "status", "active") != "active":
        on_block_cleanup()
        raise _BlockedUser(u.status)
    return u


def _user_from_session(
    sid: str | None, sessions: SessionStore, users: PivotUserRepo
) -> PivotUser | None:
    s = sessions.get(sid)
    if s is None:
        return None
    return _resolve_user(
        s.pivot_user_id, users,
        on_block_cleanup=lambda: sessions.delete(sid),
    )


def _user_from_bearer(
    authorization: str | None, tokens: ApiTokenRepo, users: PivotUserRepo,
) -> PivotUser | None:
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        return None
    token = authorization[len(BEARER_PREFIX):].strip()
    tok = tokens.lookup_by_plaintext(token)
    if tok is None:
        return None
    u = _resolve_user(tok.pivot_user_id, users, on_block_cleanup=lambda: None)
    if u is None:
        return None
    tokens.touch_last_used(tok.token_hash)
    return u


def make_current_user(
    sessions: SessionStore, users: PivotUserRepo, tokens: ApiTokenRepo,
) -> Callable:
    def current_user(
        sid: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> PivotUser:
        try:
            u = _user_from_session(sid, sessions, users)
            if u is None:
                u = _user_from_bearer(authorization, tokens, users)
        except _BlockedUser as blk:
            # 状态被改成 suspended / deleted —— session 已清，给前端
            # 一个能区分的 detail 以便跳 /login?reason=<status>。
            raise HTTPException(
                status_code=401, detail=blk.status,
            ) from None
        if u is None:
            raise HTTPException(status_code=401, detail="invalid_token")
        return u
    return current_user


def make_current_user_cookie_only(
    sessions: SessionStore, users: PivotUserRepo,
) -> Callable:
    def current_user_cookie(sid: str | None = Cookie(default=None)) -> PivotUser:
        try:
            u = _user_from_session(sid, sessions, users)
        except _BlockedUser as blk:
            raise HTTPException(
                status_code=401, detail=blk.status,
            ) from None
        if u is None:
            raise HTTPException(status_code=401, detail="not logged in")
        return u
    return current_user_cookie


def make_require_admin_user() -> Callable:
    """Returns a dependency that, given an already-resolved PivotUser
    (typically via Depends(current_user)), enforces the admin role.
    Status is already guaranteed active by current_user resolution."""
    def require(user: PivotUser) -> PivotUser:
        if "admin" not in user.roles:
            raise HTTPException(status_code=403, detail="admin_required")
        return user
    return require


def make_require_admin_user_cookie(
    sessions: SessionStore, users: PivotUserRepo,
) -> Callable:
    """Cookie-only auth + admin role check, returns the PivotUser.

    Replaces the legacy X-Admin-Password gate (server/auth/admin.py): instead
    of a hardcoded shared password, we now resolve the cookie session into a
    real PivotUser and enforce role='admin'. PATs are explicitly NOT honored
    here — admin-scoped endpoints stay browser-only.
    """
    def admin(sid: str | None = Cookie(default=None)) -> PivotUser:
        try:
            u = _user_from_session(sid, sessions, users)
        except _BlockedUser as blk:
            raise HTTPException(
                status_code=401, detail=blk.status,
            ) from None
        if u is None:
            raise HTTPException(status_code=401, detail="not logged in")
        if "admin" not in u.roles:
            raise HTTPException(status_code=403, detail="admin_required")
        return u
    return admin


def require_profile(user: PivotUser) -> PivotUser:
    if not user.pinyin:
        raise HTTPException(status_code=400, detail="profile setup required")
    return user
