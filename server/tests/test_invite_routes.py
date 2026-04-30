from __future__ import annotations

from time import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.auth_invite import build_router as build_invite_router
from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.invites import InviteRepo
from server.passwords import verify_password
from server.pivot_users import PivotUserRepo


def _make_client(db) -> tuple[TestClient, InviteRepo, PivotUserRepo, ExternalBindingRepo]:
    invites = InviteRepo(db)
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    sessions = SessionStore(db)
    app = FastAPI()
    app.include_router(build_invite_router(invites, pivot_users, bindings, sessions))
    return TestClient(app), invites, pivot_users, bindings


def _seed_admin(pivot_users: PivotUserRepo) -> str:
    """Create an admin to be invite.created_by; returns user id."""
    admin = pivot_users.create(
        display_name="Admin",
        pinyin="admin",
        email="admin@example.com",
        avatar_url="",
        role="admin",
    )
    return admin.id


def test_invite_load_valid_returns_metadata(db):
    client, invites, pivot_users, _ = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, invite = invites.create(
        email="newbie@example.com",
        display_name="Newbie",
        created_by=admin_id,
    )

    r = client.get(f"/api/invite/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "newbie@example.com"
    assert body["display_name"] == "Newbie"
    assert body["expires_at"] == invite.expires_at


def test_invite_load_expired_returns_404(db):
    client, invites, pivot_users, _ = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, invite = invites.create(
        email="newbie@example.com",
        display_name=None,
        created_by=admin_id,
    )
    invites.revoke(invite_id=invite.id)  # sets expires_at to the past

    r = client.get(f"/api/invite/{token}")
    assert r.status_code == 404


def test_invite_load_unknown_token_returns_404(db):
    client, _, _, _ = _make_client(db)
    r = client.get("/api/invite/totally-bogus-token")
    assert r.status_code == 404


def test_invite_accept_creates_member_and_session(db):
    client, invites, pivot_users, bindings = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, invite = invites.create(
        email="newbie@example.com",
        display_name="Newbie",
        created_by=admin_id,
    )

    r = client.post(
        f"/api/invite/{token}/accept",
        json={
            "password": "hunter2",
            "display_name": "Newbie Choi",
            "pinyin": "newbie",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "member"
    assert body["user"]["status"] == "active"
    assert body["user"]["display_name"] == "Newbie Choi"
    assert "sid" in r.cookies

    # Bcrypt hash persisted, not plaintext
    binding = bindings.lookup(provider="invite", external_id="newbie@example.com")
    assert binding is not None
    assert binding.password_hash is not None
    assert binding.password_hash != "hunter2"
    assert verify_password("hunter2", binding.password_hash)

    # Invite is now marked used → resolve_token returns None
    assert invites.resolve_token(token) is None


def test_invite_accept_reuse_rejected(db):
    client, invites, pivot_users, _ = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, _invite = invites.create(
        email="newbie@example.com",
        display_name=None,
        created_by=admin_id,
    )

    body = {
        "password": "hunter2",
        "display_name": "Newbie",
        "pinyin": "newbie",
    }
    first = client.post(f"/api/invite/{token}/accept", json=body)
    assert first.status_code == 200

    # Second accept on the same token must fail (resolve_token returns None
    # for already-used invites)
    second = client.post(
        f"/api/invite/{token}/accept",
        json={
            "password": "hunter2",
            "display_name": "Imposter",
            "pinyin": "imposter",
        },
    )
    assert second.status_code == 404


def test_invite_accept_unknown_token_returns_404(db):
    client, _, _, _ = _make_client(db)
    r = client.post(
        "/api/invite/no-such-token/accept",
        json={
            "password": "hunter2",
            "display_name": "Ghost",
            "pinyin": "ghost",
        },
    )
    assert r.status_code == 404


def test_invite_accept_rejects_short_password(db):
    client, invites, pivot_users, _ = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, _ = invites.create(
        email="x@example.com", display_name=None, created_by=admin_id,
    )

    r = client.post(
        f"/api/invite/{token}/accept",
        json={"password": "abc", "display_name": "x", "pinyin": "xname"},
    )
    assert r.status_code == 422


def test_invite_accept_rejects_bad_pinyin(db):
    client, invites, pivot_users, _ = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, _ = invites.create(
        email="x@example.com", display_name=None, created_by=admin_id,
    )

    r = client.post(
        f"/api/invite/{token}/accept",
        json={"password": "hunter2", "display_name": "x", "pinyin": "X-Bad"},
    )
    assert r.status_code == 422
