from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user,
)
from server.auth.session import SessionStore
from server.db import Database
from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    sessions = SessionStore(db)
    api_tokens = ApiTokenRepo(db)
    bindings = ExternalBindingRepo(db)
    user = users.create(display_name="Alice", pinyin="alice",
                        email=None, avatar_url="", role="member")
    return users, sessions, api_tokens, bindings, user


def test_active_user_passes_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    result = dep(sid=sid, authorization=None)
    assert result.id == user.id


def test_suspended_user_blocked_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="suspended", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException) as exc:
        dep(sid=sid, authorization=None)
    assert exc.value.status_code == 401


def test_deleted_user_blocked_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="deleted", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException):
        dep(sid=sid, authorization=None)


def test_session_deleted_after_status_block(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="suspended", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException):
        dep(sid=sid, authorization=None)
    assert sessions.get(sid) is None  # forced logout


def test_admin_user_passes_admin_dep(stack):
    users, sessions, api_tokens, _, user = stack
    users.update_role(user_id=user.id, role="admin")
    sid = sessions.create(pivot_user_id=user.id)
    user_dep = make_current_user(sessions, users, api_tokens)
    admin_dep = make_require_admin_user()
    fetched = user_dep(sid=sid, authorization=None)
    result = admin_dep(user=fetched)
    assert result.id == user.id


def test_member_blocked_by_admin_dep(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    user_dep = make_current_user(sessions, users, api_tokens)
    admin_dep = make_require_admin_user()
    fetched = user_dep(sid=sid, authorization=None)
    with pytest.raises(HTTPException) as exc:
        admin_dep(user=fetched)
    assert exc.value.status_code == 403
