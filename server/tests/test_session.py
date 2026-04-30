from __future__ import annotations

import sqlite3
import time

import pytest

from server.db import Database
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


def test_database_refuses_legacy_sessions_user_open_id(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_open_id TEXT NOT NULL,
                pivot_user_id TEXT,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
    with pytest.raises(RuntimeError, match="legacy user_open_id"):
        Database(db_path)


def test_database_refuses_legacy_sessions_user_open_id_with_feishu_binding(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                user_open_id TEXT NOT NULL,
                pivot_user_id TEXT,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
    with pytest.raises(RuntimeError, match="legacy user_open_id"):
        Database(db_path)


def test_sweep_expired_removes_old(db):
    store = SessionStore(db, ttl_sec=0)
    store.create("ou_1")
    store.create("ou_2")
    time.sleep(0.01)
    n = store.sweep_expired()
    assert n == 2
