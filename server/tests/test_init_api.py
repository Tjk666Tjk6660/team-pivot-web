from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.init import build_router as build_init_router
from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import verify_password
from server.pivot_users import PivotUserRepo


def _make_client(db, *, seed_admin: bool = False) -> TestClient:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    sessions = SessionStore(db)
    if seed_admin:
        admin = pivot_users.create(
            display_name="Existing Admin",
            pinyin="exadmin",
            email="exadmin@example.com",
            avatar_url="",
            role="admin",
        )
        bindings.bind(
            pivot_user_id=admin.id,
            provider="invite",
            external_id=admin.email,
            external_union_id=None,
            raw_profile_json=None,
            password_hash="bcrypt$placeholder",
        )
    app = FastAPI()
    app.include_router(build_init_router(pivot_users, bindings, sessions))
    return TestClient(app)


def test_init_status_when_no_admin(db):
    client = _make_client(db)
    r = client.get("/init/status")
    assert r.status_code == 200
    assert r.json() == {"needs_init": True}


def test_init_status_when_admin_exists(db):
    client = _make_client(db, seed_admin=True)
    r = client.get("/init/status")
    assert r.status_code == 200
    assert r.json() == {"needs_init": False}


def test_init_complete_email_password_creates_admin_and_session(db):
    client = _make_client(db)
    payload = {
        "method": "email_password",
        "email": "first@example.com",
        "password": "hunter2",
        "display_name": "First Admin",
        "pinyin": "first",
    }
    r = client.post("/init/complete", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["status"] == "active"
    assert body["user"]["display_name"] == "First Admin"
    # session cookie set
    assert "sid" in r.cookies

    # Subsequent /init/status now reports already-initialized
    r2 = client.get("/init/status")
    assert r2.json() == {"needs_init": False}

    # Binding was persisted with hashed password (not plaintext)
    bindings = ExternalBindingRepo(db)
    binding = bindings.lookup(provider="invite", external_id="first@example.com")
    assert binding is not None
    assert binding.password_hash is not None
    assert binding.password_hash != "hunter2"
    assert verify_password("hunter2", binding.password_hash)


def test_init_complete_blocked_when_admin_exists(db):
    client = _make_client(db, seed_admin=True)
    payload = {
        "method": "email_password",
        "email": "second@example.com",
        "password": "hunter2",
        "display_name": "Late",
        "pinyin": "late",
    }
    r = client.post("/init/complete", json=payload)
    assert r.status_code == 409


def test_init_complete_rejects_unsupported_method(db):
    client = _make_client(db)
    payload = {
        "method": "magic_link",
        "email": "x@example.com",
        "password": "hunter2",
        "display_name": "x",
        "pinyin": "xname",
    }
    r = client.post("/init/complete", json=payload)
    assert r.status_code == 400


def test_init_complete_rejects_short_password(db):
    client = _make_client(db)
    payload = {
        "method": "email_password",
        "email": "x@example.com",
        "password": "abc",
        "display_name": "x",
        "pinyin": "xname",
    }
    r = client.post("/init/complete", json=payload)
    assert r.status_code == 422  # pydantic min_length


def test_init_complete_rejects_bad_pinyin(db):
    client = _make_client(db)
    payload = {
        "method": "email_password",
        "email": "x@example.com",
        "password": "hunter2",
        "display_name": "x",
        "pinyin": "X-Bad",  # uppercase not allowed
    }
    r = client.post("/init/complete", json=payload)
    assert r.status_code == 422
