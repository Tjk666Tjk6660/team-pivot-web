from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.auth_invite import build_router as build_invite_router
from server.auth.feishu_oauth import FeishuOAuth
from server.invites import InviteRepo
from server.pivot_users import PivotUserRepo

_TEST_SECRET = "test-state-secret"


def _make_client(db) -> tuple[TestClient, InviteRepo, PivotUserRepo]:
    invites = InviteRepo(db)
    pivot_users = PivotUserRepo(db)
    oauth = MagicMock(spec=FeishuOAuth)
    oauth.authorize_url.side_effect = lambda state: (
        f"https://open.feishu.cn/open-apis/authen/v1/authorize?state={state}"
    )
    app = FastAPI()
    app.include_router(build_invite_router(
        invites, feishu_oauth=oauth, state_secret=_TEST_SECRET,
    ))
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


def test_invite_start_returns_redirect_url(db):
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, _ = invites.create(created_by=admin_id)

    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["redirect_url"].startswith("https://open.feishu.cn/")
    assert "state=" in body["redirect_url"]


def test_invite_start_rejects_used(db):
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, record = invites.create(created_by=admin_id)
    invites.mark_used(invite_id=record.id, used_by_user_id="someone")

    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 410


def test_invite_start_rejects_expired(db):
    client, invites, pivot_users = _make_client(db)
    admin_id = _seed_admin(pivot_users)
    token, record = invites.create(created_by=admin_id)
    invites.revoke(invite_id=record.id)

    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 410


def test_invite_start_rejects_unknown_token(db):
    client, _, _ = _make_client(db)
    r = client.post("/api/invite/never-existed/start")
    assert r.status_code == 404
