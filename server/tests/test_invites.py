from __future__ import annotations

import time as time_mod

import pytest

from server.db import Database
from server.invites import Invite, InviteRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    invites = InviteRepo(db)
    admin = users.create(display_name="Admin", pinyin="admin",
                         email=None, avatar_url="", role="admin")
    return users, invites, admin


def test_invite_create_returns_minimal_record(tmp_path):
    invites = InviteRepo(Database(tmp_path / "t.db"))
    token, record = invites.create(created_by="admin", ttl_sec=3600)
    assert record.id
    assert record.token_hash
    assert record.created_by == "admin"
    assert not hasattr(record, "email")
    assert not hasattr(record, "display_name")


def test_create_returns_token_plus_record(deps):
    _, invites, admin = deps
    token, record = invites.create(
        created_by=admin.id, ttl_sec=86400 * 7,
    )
    assert token  # plaintext returned ONCE
    assert isinstance(record, Invite)
    assert record.used_at is None


def test_resolve_token_finds_active_invite(deps):
    _, invites, admin = deps
    token, _ = invites.create(created_by=admin.id, ttl_sec=3600)
    found = invites.resolve_token(token)
    assert found is not None


def test_resolve_invalid_token_returns_none(deps):
    _, invites, _ = deps
    assert invites.resolve_token("not-a-real-token") is None


def test_expired_invite_not_resolved(deps, monkeypatch):
    _, invites, admin = deps
    token, _ = invites.create(created_by=admin.id, ttl_sec=1)
    # Force time to be after expiry
    real_time = time_mod.time
    monkeypatch.setattr("server.invites.time", lambda: real_time() + 10)
    assert invites.resolve_token(token) is None


def test_used_invite_not_resolved(deps):
    _, invites, admin = deps
    token, record = invites.create(created_by=admin.id, ttl_sec=3600)
    invites.mark_used(invite_id=record.id, used_by_user_id="u-new")
    assert invites.resolve_token(token) is None


def test_revoke_invalidates_invite(deps):
    _, invites, admin = deps
    token, record = invites.create(created_by=admin.id, ttl_sec=3600)
    invites.revoke(invite_id=record.id)
    assert invites.resolve_token(token) is None


def test_list_active_for_admin(deps):
    _, invites, admin = deps
    token1, r1 = invites.create(created_by=admin.id, ttl_sec=3600)
    token2, r2 = invites.create(created_by=admin.id, ttl_sec=3600)
    invites.mark_used(invite_id=r1.id, used_by_user_id="someone")
    listed = invites.list_for_admin(include_used=False)
    assert len(listed) == 1
    assert listed[0].id == r2.id
