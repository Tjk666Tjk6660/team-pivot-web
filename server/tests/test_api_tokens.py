from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.drafts import build_router as build_drafts_router
from server.api.tokens import build_router as build_tokens_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user, make_current_user_cookie_only
from server.auth.session import SessionStore
from server.drafts import DraftRepo
from server.external_bindings import ExternalBindingRepo
from server.notify import NoOpNotifier
from server.pivot_users import PivotUserRepo


class _FakeWorkspace:
    pass


@pytest.fixture
def app_and_sid(db):
    pivot_users = PivotUserRepo(db)
    user = pivot_users.create(
        display_name="Ken", pinyin="ken",
        email="ken@example.com", avatar_url="", role="member",
    )
    sessions = SessionStore(db)
    sid = sessions.create(pivot_user_id=user.id)
    tokens = ApiTokenRepo(db)
    cu = make_current_user(sessions, pivot_users, tokens)
    cu_cookie = make_current_user_cookie_only(sessions, pivot_users)

    app = FastAPI()
    app.include_router(build_tokens_router(tokens, cu_cookie))
    app.include_router(build_drafts_router(
        _FakeWorkspace(), DraftRepo(db), pivot_users, ExternalBindingRepo(db),
        NoOpNotifier(), cu,
    ))
    return app, sid, tokens, user


def test_create_list_use_revoke_lifecycle(app_and_sid):
    app, sid, _, _ = app_and_sid
    client = TestClient(app)
    client.cookies.set("sid", sid)

    # Create
    r = client.post("/api/tokens", json={"name": "MacBook Pro"})
    assert r.status_code == 200, r.text
    body = r.json()
    plaintext = body["token"]
    short_id = body["id"]
    assert plaintext.startswith("pvt_")
    assert len(short_id) == 8

    # List shows it (no plaintext)
    r = client.get("/api/tokens")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == short_id
    assert "token" not in items[0]

    # Use Bearer to call /api/drafts (clear cookies)
    bearer_client = TestClient(app)
    bearer_client.headers.update({"Authorization": f"Bearer {plaintext}"})
    r = bearer_client.get("/api/drafts")
    assert r.status_code == 200

    # Revoke
    r = client.delete(f"/api/tokens/{short_id}")
    assert r.status_code == 200

    # Bearer now rejected
    r = bearer_client.get("/api/drafts")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_token"


def test_expired_token_returns_invalid_token(app_and_sid, db):
    app, _, tokens, user = app_and_sid
    plaintext, tok = tokens.create(pivot_user_id=user.id, name="t1", ttl_days=1)
    # Force-expire
    with db.connect() as c:
        c.execute(
            "UPDATE api_tokens SET expires_at=? WHERE token_hash=?",
            (time.time() - 1, tok.token_hash),
        )

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {plaintext}"})
    r = client.get("/api/drafts")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_token"


def test_bearer_cannot_create_token(app_and_sid):
    app, sid, _, _ = app_and_sid
    cookie_client = TestClient(app)
    cookie_client.cookies.set("sid", sid)
    r = cookie_client.post("/api/tokens", json={"name": "first"})
    plaintext = r.json()["token"]

    bearer_client = TestClient(app)
    bearer_client.headers.update({"Authorization": f"Bearer {plaintext}"})
    r = bearer_client.post("/api/tokens", json={"name": "second"})
    # cookie-only dep on /api/tokens => 401 (no cookie session present)
    assert r.status_code == 401


def test_tokens_route_requires_cookie(app_and_sid):
    app, sid, _, _ = app_and_sid
    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.post("/api/tokens", json={"name": "n"})
    assert r.status_code == 200
    assert r.json()["name"] == "n"


def test_cookie_session_still_works(app_and_sid):
    app, sid, _, _ = app_and_sid
    client = TestClient(app)
    client.cookies.set("sid", sid)
    # /api/drafts via cookie should work without any Bearer header
    assert client.get("/api/drafts").status_code == 200


def test_bad_bearer_returns_invalid_token(app_and_sid):
    app, _, _, _ = app_and_sid
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer pvt_garbage"})
    r = client.get("/api/drafts")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_token"
