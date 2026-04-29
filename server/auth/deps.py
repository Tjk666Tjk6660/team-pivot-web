"""Unified auth dependencies for /api/* routes.

Two dependency factories:
- make_current_user: accepts cookie session OR Bearer token (PAT). Used everywhere.
- make_current_user_cookie_only: accepts cookie session only. Used by routes
  that PATs are not allowed to call (e.g. /api/tokens).
"""
from __future__ import annotations

from typing import Callable

from fastapi import Cookie, Header, HTTPException

from server.api_tokens import ApiTokenRepo
from server.auth.session import SessionStore
from server.users import User, UserRepo

BEARER_PREFIX = "Bearer "


def _user_from_session(sid: str | None, sessions: SessionStore, users: UserRepo) -> User | None:
    s = sessions.get(sid)
    if s is None:
        return None
    u = users.get(s.user_open_id)
    if u is None:
        sessions.delete(sid)
        return None
    return u


def _user_from_bearer(
    authorization: str | None,
    tokens: ApiTokenRepo,
    users: UserRepo,
) -> User | None:
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        return None
    token = authorization[len(BEARER_PREFIX):].strip()
    tok = tokens.lookup_by_plaintext(token)
    if tok is None:
        return None
    u = users.get(tok.pivot_user_id)
    if u is None:
        return None
    tokens.touch_last_used(tok.token_hash)
    return u


def make_current_user(
    sessions: SessionStore,
    users: UserRepo,
    tokens: ApiTokenRepo,
) -> Callable:
    """Returns a FastAPI dependency that resolves to a User via cookie OR Bearer."""
    def current_user(
        sid: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> User:
        u = _user_from_session(sid, sessions, users)
        if u is None:
            u = _user_from_bearer(authorization, tokens, users)
        if u is None:
            # Distinct error code so the VS Code extension can pattern-match
            raise HTTPException(status_code=401, detail="invalid_token")
        return u

    return current_user


def make_current_user_cookie_only(
    sessions: SessionStore,
    users: UserRepo,
) -> Callable:
    """Returns a dependency that ONLY accepts cookie session. Bearer is rejected."""
    def current_user_cookie(
        sid: str | None = Cookie(default=None),
    ) -> User:
        u = _user_from_session(sid, sessions, users)
        if u is None:
            raise HTTPException(status_code=401, detail="not logged in")
        return u

    return current_user_cookie


def require_profile(user: User) -> User:
    """Raise 400 if the user has not completed first-run profile setup.
    Use this inline at routes that need pinyin (publishing, etc)."""
    if not user.pinyin:
        raise HTTPException(status_code=400, detail="profile setup required")
    return user
