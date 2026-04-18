from __future__ import annotations

import time

from server.auth.session import SessionStore


def test_create_and_get_roundtrip():
    store = SessionStore()
    sid = store.create("ou_1")
    s = store.get(sid)
    assert s is not None
    assert s.user_open_id == "ou_1"


def test_get_unknown_returns_none():
    store = SessionStore()
    assert store.get("nope") is None
    assert store.get(None) is None


def test_expired_session_is_purged():
    store = SessionStore(ttl_sec=0)
    sid = store.create("ou_1")
    time.sleep(0.01)
    assert store.get(sid) is None


def test_delete_removes_session():
    store = SessionStore()
    sid = store.create("ou_1")
    store.delete(sid)
    assert store.get(sid) is None


def test_sids_are_unique():
    store = SessionStore()
    sids = {store.create(f"ou_{i}") for i in range(100)}
    assert len(sids) == 100
