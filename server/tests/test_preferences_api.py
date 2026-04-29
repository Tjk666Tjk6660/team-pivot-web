"""Tests for /api/me/preferences endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.preferences import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.user_preferences import UserPreferenceRepo


@pytest.fixture
def client(db, users):
    users.upsert_from_feishu(
        open_id="ou_alice", union_id=None, name="Alice", avatar_url="",
    )
    users.update_profile("ou_alice", pinyin="alice")

    sessions = SessionStore(db)
    sid = sessions.create("ou_alice")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    prefs = UserPreferenceRepo(db)
    app = FastAPI()
    app.include_router(build_router(prefs, current_user))

    c = TestClient(app)
    c.cookies.set("sid", sid)
    return c


def test_list_preferences_empty_returns_empty_dict(client):
    r = client.get("/api/me/preferences")
    assert r.status_code == 200
    assert r.json() == {}


def test_set_preference_then_list_returns_value(client):
    r = client.put(
        "/api/me/preferences/matter_list_filter",
        json={"value": "mine"},
    )
    assert r.status_code == 200
    assert r.json() == {"key": "matter_list_filter", "value": "mine"}

    r = client.get("/api/me/preferences")
    assert r.status_code == 200
    assert r.json() == {"matter_list_filter": "mine"}


def test_set_preference_overwrites(client):
    client.put("/api/me/preferences/matter_list_filter", json={"value": "mine"})
    client.put("/api/me/preferences/matter_list_filter", json={"value": "all"})
    r = client.get("/api/me/preferences")
    assert r.json() == {"matter_list_filter": "all"}


def test_set_preference_unknown_key_returns_400(client):
    r = client.put(
        "/api/me/preferences/some_random_key",
        json={"value": "anything"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unknown_preference_key"


def test_set_preference_value_too_long_rejected(client):
    """Value > 200 chars → pydantic 422."""
    r = client.put(
        "/api/me/preferences/matter_list_filter",
        json={"value": "x" * 201},
    )
    assert r.status_code == 422


def test_preferences_isolated_per_user(db, users):
    """Two users have independent preference bags."""
    sessions = SessionStore(db)
    users.upsert_from_feishu(
        open_id="ou_a", union_id=None, name="A", avatar_url="",
    )
    users.update_profile("ou_a", pinyin="aaa")
    users.upsert_from_feishu(
        open_id="ou_b", union_id=None, name="B", avatar_url="",
    )
    users.update_profile("ou_b", pinyin="bbb")

    sid_a = sessions.create("ou_a")
    sid_b = sessions.create("ou_b")

    current_user = make_current_user(sessions, users, ApiTokenRepo(db))
    app = FastAPI()
    app.include_router(build_router(UserPreferenceRepo(db), current_user))
    c_a = TestClient(app)
    c_a.cookies.set("sid", sid_a)
    c_b = TestClient(app)
    c_b.cookies.set("sid", sid_b)

    c_a.put("/api/me/preferences/matter_list_filter", json={"value": "mine"})
    c_b.put("/api/me/preferences/matter_list_filter", json={"value": "all"})

    assert c_a.get("/api/me/preferences").json() == {"matter_list_filter": "mine"}
    assert c_b.get("/api/me/preferences").json() == {"matter_list_filter": "all"}
