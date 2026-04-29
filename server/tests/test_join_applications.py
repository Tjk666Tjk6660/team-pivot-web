from __future__ import annotations

import json

import pytest

from server.db import Database
from server.join_applications import (
    JoinApplication,
    JoinApplicationRepo,
    MatchCandidate,
    compute_match_candidates,
)
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    apps = JoinApplicationRepo(db)
    return users, apps


def test_create_application(deps):
    _, apps = deps
    a = apps.create(
        provider="feishu",
        external_id="ou_xxx",
        external_union_id="on_xxx",
        raw_profile={"name": "李伟", "email": "li@example.com"},
        suggested_match_user_id=None,
    )
    assert isinstance(a, JoinApplication)
    assert a.status == "pending"
    assert a.raw_profile["name"] == "李伟"


def test_lookup_blocking_finds_pending_then_rejected(deps):
    _, apps = deps
    apps.create(provider="feishu", external_id="ou_a",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    blocker = apps.lookup_blocking("feishu", "ou_a")
    assert blocker is not None
    assert blocker.status == "pending"
    assert apps.lookup_blocking("feishu", "ou_nope") is None


def test_unique_pending_per_external_id(deps):
    _, apps = deps
    apps.create(provider="feishu", external_id="ou_a",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    with pytest.raises(ValueError):
        apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)


def test_approve_marks_status(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.approve(application_id=a.id, reviewed_by="admin1")
    fetched = apps.get(a.id)
    assert fetched.status == "approved"
    assert fetched.reviewed_by == "admin1"


def test_reject_with_reason(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin1", reason="not part of org")
    fetched = apps.get(a.id)
    assert fetched.status == "rejected"
    assert fetched.reject_reason == "not part of org"


def test_unblock_deletes_rejected(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin1", reason=None)
    apps.unblock(application_id=a.id)
    assert apps.lookup_blocking("feishu", "ou_a") is None


def test_list_pending(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.create(provider="feishu", external_id="ou_b",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin", reason=None)
    pending = apps.list_pending()
    assert len(pending) == 1
    assert pending[0].external_id == "ou_b"


def test_match_candidates_email_exact(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email="li@example.com", avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": "li@example.com"}
    )
    assert any(c.user_id == u.id and c.reason == "email_exact" for c in cands)


def test_match_candidates_display_name_exact(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email=None, avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": None}
    )
    assert any(c.user_id == u.id and c.reason == "name_exact" for c in cands)


def test_match_candidates_skip_non_active(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email=None, avatar_url="", role="member")
    users.update_status(user_id=u.id, status="suspended", note=None, changed_by=u.id)
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": None}
    )
    assert all(c.user_id != u.id for c in cands)


def test_match_candidates_truncated_to_5(deps):
    users, _ = deps
    for i in range(10):
        users.create(display_name=f"User{i}", pinyin="dup", email=None, avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "Whatever", "email": None}
    )
    # 10 全拼匹配候选 → 截断到 5
    assert len(cands) <= 5
