from __future__ import annotations

import pytest

from server.db import Database
from server.pivot_users import PivotUser, PivotUserRepo


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    return PivotUserRepo(db)


def test_create_user_returns_pivot_user(repo):
    u = repo.create(
        display_name="Alice",
        pinyin="alice",
        email="alice@example.com",
        avatar_url="",
        role="admin",
    )
    assert isinstance(u, PivotUser)
    assert u.id  # ULID/uuid generated
    assert u.display_name == "Alice"
    assert u.pinyin == "alice"
    assert u.role == "admin"
    assert u.status == "active"


def test_get_returns_none_when_missing(repo):
    assert repo.get("nonexistent") is None


def test_get_after_create(repo):
    u = repo.create(display_name="Bob", pinyin="bob", email=None, avatar_url="", role="member")
    fetched = repo.get(u.id)
    assert fetched is not None
    assert fetched.display_name == "Bob"


def test_update_status_records_who_when(repo):
    u = repo.create(display_name="Carol", pinyin="carol", email=None, avatar_url="", role="member")
    admin = repo.create(display_name="Admin", pinyin="admin", email=None, avatar_url="", role="admin")
    updated = repo.update_status(
        user_id=u.id, status="suspended", note="休假", changed_by=admin.id
    )
    assert updated.status == "suspended"
    assert updated.status_note == "休假"
    assert updated.status_changed_by == admin.id
    assert updated.status_changed_at is not None


def test_count_active_admins(repo):
    repo.create(display_name="A1", pinyin="a1", email=None, avatar_url="", role="admin")
    repo.create(display_name="A2", pinyin="a2", email=None, avatar_url="", role="admin")
    repo.create(display_name="M1", pinyin="m1", email=None, avatar_url="", role="member")
    assert repo.count_active_admins() == 2


def test_count_active_admins_excludes_suspended(repo):
    a1 = repo.create(display_name="A1", pinyin="a1", email=None, avatar_url="", role="admin")
    repo.create(display_name="A2", pinyin="a2", email=None, avatar_url="", role="admin")
    repo.update_status(user_id=a1.id, status="suspended", note=None, changed_by=a1.id)
    assert repo.count_active_admins() == 1


def test_update_role(repo):
    u = repo.create(display_name="X", pinyin="x", email=None, avatar_url="", role="member")
    promoted = repo.update_role(user_id=u.id, role="admin")
    assert promoted.role == "admin"


def test_touch_last_login(repo):
    u = repo.create(display_name="X", pinyin="x", email=None, avatar_url="", role="member")
    assert u.last_login_at is None
    repo.touch_last_login(u.id)
    fetched = repo.get(u.id)
    assert fetched.last_login_at is not None


def test_email_unique(repo):
    repo.create(display_name="A", pinyin="a", email="dup@example.com", avatar_url="", role="member")
    with pytest.raises(ValueError):
        repo.create(display_name="B", pinyin="b", email="dup@example.com", avatar_url="", role="member")


def test_list_for_admin_lists_all_with_filter(repo):
    repo.create(display_name="A", pinyin="a", email=None, avatar_url="", role="admin")
    m = repo.create(display_name="M", pinyin="m", email=None, avatar_url="", role="member")
    repo.update_status(user_id=m.id, status="suspended", note=None, changed_by=m.id)
    all_active_or_suspended = repo.list_for_admin(include_deleted=False)
    assert len(all_active_or_suspended) == 2
    deleted = repo.create(display_name="D", pinyin="d", email=None, avatar_url="", role="member")
    repo.update_status(user_id=deleted.id, status="deleted", note=None, changed_by=deleted.id)
    without_deleted = repo.list_for_admin(include_deleted=False)
    with_deleted = repo.list_for_admin(include_deleted=True)
    assert len(without_deleted) == 2
    assert len(with_deleted) == 3
