from __future__ import annotations

import time

import pytest

from server.db import Database
from server.pivot_users import PivotUserRepo
from server.scoring.resolve import PinyinResolver


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def users(db):
    return PivotUserRepo(db)


@pytest.fixture
def resolver(db):
    return PinyinResolver(db)


def test_resolve_returns_none_for_empty(resolver):
    assert resolver.resolve(None) is None
    assert resolver.resolve("") is None
    assert resolver.resolve_id(None) is None


def test_resolve_returns_none_when_no_match(resolver, users):
    users.create(display_name="Alice", pinyin="alice", email=None, avatar_url="")
    assert resolver.resolve("nobody") is None
    assert resolver.resolve_id("nobody") is None


def test_resolve_basic_match(resolver, users):
    u = users.create(display_name="Alice", pinyin="alice", email=None, avatar_url="")
    got = resolver.resolve("alice")
    assert got is not None
    assert got.id == u.id
    assert got.pinyin == "alice"
    assert got.display_name == "Alice"
    assert got.status == "active"


def test_resolve_id_shortcut(resolver, users):
    u = users.create(display_name="Bob", pinyin="bob", email=None, avatar_url="")
    assert resolver.resolve_id("bob") == u.id


def test_resolve_uses_cache(resolver, users):
    """Second lookup should not need to hit the DB. We test by deleting the
    user via raw SQL after the first call and verifying the second still
    returns the cached entry."""
    users.create(display_name="Carol", pinyin="carol", email=None, avatar_url="")
    first = resolver.resolve("carol")
    assert first is not None

    with resolver._db.connect() as conn:
        conn.execute("DELETE FROM pivot_user WHERE pinyin=?", ("carol",))

    second = resolver.resolve("carol")
    assert second is not None
    assert second.id == first.id


def test_resolve_prefers_active_over_deleted(resolver, users):
    """When two users share a pinyin, active should win over deleted."""
    deleted = users.create(
        display_name="Dave Old", pinyin="dave", email=None, avatar_url="",
    )
    users.update_status(
        user_id=deleted.id, status="deleted", note=None, changed_by=deleted.id,
    )
    # Wait so created_at differs deterministically.
    time.sleep(0.01)
    active = users.create(
        display_name="Dave New", pinyin="dave", email=None, avatar_url="",
    )

    got = resolver.resolve("dave")
    assert got is not None
    assert got.id == active.id
    assert got.status == "active"


def test_resolve_prefers_active_over_suspended(resolver, users):
    suspended = users.create(
        display_name="Eve A", pinyin="eve", email=None, avatar_url="",
    )
    users.update_status(
        user_id=suspended.id, status="suspended", note=None, changed_by=suspended.id,
    )
    time.sleep(0.01)
    active = users.create(
        display_name="Eve B", pinyin="eve", email=None, avatar_url="",
    )

    got = resolver.resolve("eve")
    assert got is not None
    assert got.id == active.id


def test_resolve_falls_back_to_deleted_if_no_active(resolver, users):
    """If only a deleted user has the pinyin, still return them — historical
    timeline evidence should still be attributable to former employees."""
    u = users.create(display_name="Frank", pinyin="frank", email=None, avatar_url="")
    users.update_status(
        user_id=u.id, status="deleted", note="离职", changed_by=u.id,
    )

    got = resolver.resolve("frank")
    assert got is not None
    assert got.id == u.id
    assert got.status == "deleted"


def test_resolve_orders_by_created_at_when_same_status(resolver, users):
    """Two active users with same pinyin — earlier created wins (deterministic)."""
    first = users.create(
        display_name="Gina A", pinyin="gina", email=None, avatar_url="",
    )
    time.sleep(0.01)
    users.create(
        display_name="Gina B", pinyin="gina", email=None, avatar_url="",
    )
    got = resolver.resolve("gina")
    assert got is not None
    assert got.id == first.id


def test_get_by_id(resolver, users):
    u = users.create(display_name="Henry", pinyin="henry", email=None, avatar_url="")
    got = resolver.get_by_id(u.id)
    assert got is not None
    assert got.pinyin == "henry"


def test_get_by_id_missing(resolver):
    assert resolver.get_by_id(None) is None
    assert resolver.get_by_id("") is None
    assert resolver.get_by_id("does-not-exist") is None
