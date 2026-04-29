from __future__ import annotations

import time

import pytest

from server.auth.session import SessionStore


@pytest.fixture
def store(db):
    return SessionStore(db)


def test_create_and_get_roundtrip(store):
    sid = store.create("ou_1")
    s = store.get(sid)
    assert s is not None
    assert s.pivot_user_id == "ou_1"


def test_get_unknown_returns_none(store):
    assert store.get("nope") is None
    assert store.get(None) is None


def test_expired_session_is_purged(db):
    store = SessionStore(db, ttl_sec=0)
    sid = store.create("ou_1")
    time.sleep(0.01)
    assert store.get(sid) is None


def test_delete_removes_session(store):
    sid = store.create("ou_1")
    store.delete(sid)
    assert store.get(sid) is None


def test_sids_are_unique(store):
    sids = {store.create(f"ou_{i}") for i in range(100)}
    assert len(sids) == 100


def test_session_persists_across_store_instances(db):
    s1 = SessionStore(db)
    sid = s1.create("ou_1")
    s2 = SessionStore(db)
    assert s2.get(sid) is not None


def test_sweep_expired_removes_old(db):
    store = SessionStore(db, ttl_sec=0)
    store.create("ou_1")
    store.create("ou_2")
    time.sleep(0.01)
    n = store.sweep_expired()
    assert n == 2
