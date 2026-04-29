from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.auth_email_password import build_router as build_login_router
from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PivotUserRepo


def _make_client(db) -> tuple[TestClient, PivotUserRepo, ExternalBindingRepo]:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    sessions = SessionStore(db)
    app = FastAPI()
    app.include_router(build_login_router(pivot_users, bindings, sessions))
    return TestClient(app), pivot_users, bindings


def _seed_invite_user(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    *,
    email: str = "alice@example.com",
    password: str = "hunter2",
    status: str = "active",
):
    user = pivot_users.create(
        display_name="Alice",
        pinyin="alice",
        email=email,
        avatar_url="",
        role="member",
    )
    if status != "active":
        pivot_users.update_status(
            user_id=user.id, status=status, note=None, changed_by="admin"
        )
    bindings.bind(
        pivot_user_id=user.id,
        provider="invite",
        external_id=email,
        external_union_id=None,
        raw_profile_json=None,
        password_hash=hash_password(password),
    )
    return user


def test_email_password_login_success(db):
    client, pivot_users, bindings = _make_client(db)
    user = _seed_invite_user(pivot_users, bindings)

    r = client.post(
        "/auth/login_email_password",
        json={"email": "alice@example.com", "password": "hunter2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == user.id
    assert body["user"]["status"] == "active"
    assert body["user"]["display_name"] == "Alice"
    assert "sid" in r.cookies


def test_email_password_login_wrong_password(db):
    client, pivot_users, bindings = _make_client(db)
    _seed_invite_user(pivot_users, bindings)

    r = client.post(
        "/auth/login_email_password",
        json={"email": "alice@example.com", "password": "WRONG"},
    )
    assert r.status_code == 401
    assert "sid" not in r.cookies


def test_email_password_login_suspended_user(db):
    client, pivot_users, bindings = _make_client(db)
    _seed_invite_user(pivot_users, bindings, status="suspended")

    r = client.post(
        "/auth/login_email_password",
        json={"email": "alice@example.com", "password": "hunter2"},
    )
    assert r.status_code == 401
    assert "sid" not in r.cookies


def test_email_password_login_no_such_email(db):
    client, _, _ = _make_client(db)

    r = client.post(
        "/auth/login_email_password",
        json={"email": "ghost@example.com", "password": "anything"},
    )
    assert r.status_code == 401
    assert "sid" not in r.cookies


def test_email_password_login_deleted_user(db):
    """Soft-deleted user must not be able to log in."""
    client, pivot_users, bindings = _make_client(db)
    _seed_invite_user(pivot_users, bindings, status="deleted")

    r = client.post(
        "/auth/login_email_password",
        json={"email": "alice@example.com", "password": "hunter2"},
    )
    assert r.status_code == 401
    assert "sid" not in r.cookies
