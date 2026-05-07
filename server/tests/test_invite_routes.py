from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.auth_invite import build_router as build_invite_router
from server.invites import InviteRepo
from server.pivot_users import PivotUserRepo


def _make_client(db) -> tuple[TestClient, InviteRepo, PivotUserRepo]:
    invites = InviteRepo(db)
    pivot_users = PivotUserRepo(db)
    app = FastAPI()
    app.include_router(build_invite_router(invites))
    return TestClient(app), invites, pivot_users


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
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, invite = invites.create(created_by=admin_id)

    r = client.get(f"/api/invite/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_at"] == invite.expires_at
    assert body["provider"] == "feishu"


def test_invite_load_expired_returns_404(db):
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, invite = invites.create(created_by=admin_id)
    invites.revoke(invite_id=invite.id)  # sets expires_at to the past

    r = client.get(f"/api/invite/{token}")
    assert r.status_code == 404


def test_invite_load_unknown_token_returns_404(db):
    client, _, _ = _make_client(db)
    r = client.get("/api/invite/totally-bogus-token")
    assert r.status_code == 404


def test_invite_accept_endpoint_is_gone(db):
    """The email/password accept flow is removed in favor of the Feishu
    OAuth path (POST /start). Hitting the old endpoint should 404."""
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, _ = invites.create(created_by=admin_id)

    r = client.post(
        f"/api/invite/{token}/accept",
        json={"password": "p" * 8, "display_name": "X", "pinyin": "x"},
    )
    assert r.status_code == 404
