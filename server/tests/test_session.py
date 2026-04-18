from __future__ import annotations

import time

from server.auth.session import SessionStore


def test_create_and_get_roundtrip():
    store = SessionStore()
    sid = store.create(user_open_id="ou_1", name="Ken", avatar_url="http://a/1.png")
    s = store.get(sid)
    assert s is not None
    assert s.user_open_id == "ou_1"
    assert s.name == "Ken"


def test_get_unknown_returns_none():
    store = SessionStore()
    assert store.get("nope") is None
    assert store.get(None) is None


def test_expired_session_is_purged():
    store = SessionStore(ttl_sec=0)
    sid = store.create(user_open_id="ou_1", name="x", avatar_url="")
    time.sleep(0.01)
    assert store.get(sid) is None


def test_delete_removes_session():
    store = SessionStore()
    sid = store.create(user_open_id="ou_1", name="x", avatar_url="")
    store.delete(sid)
    assert store.get(sid) is None


def test_sids_are_unique():
    store = SessionStore()
    sids = {store.create(user_open_id=f"ou_{i}", name="x", avatar_url="") for i in range(100)}
    assert len(sids) == 100
