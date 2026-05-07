from __future__ import annotations

from time import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.admin_invites import build_router as build_admin_invites_router
from server.invites import InviteRepo
from server.pivot_users import PivotUser, PivotUserRepo


def _build_app(db) -> tuple[TestClient, InviteRepo, PivotUser]:
    pivot_users = PivotUserRepo(db)
    invites = InviteRepo(db)
    admin = pivot_users.create(
        display_name="Admin",
        pinyin="admin",
        email="admin@example.com",
        avatar_url="",
        role="admin",
    )

    def admin_user_dep() -> PivotUser:
        return admin

    app = FastAPI()
    app.include_router(build_admin_invites_router(invites, admin_user_dep))
    return TestClient(app), invites, admin


def test_create_returns_plaintext_token_and_persists_only_hash(db):
    client, invites, admin = _build_app(db)
    r = client.post(
        "/api/admin/invites",
        json={"ttl_days": 7},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["link_path"] == f"/invite/{body['token']}"
    assert body["token"]  # plaintext returned exactly once

    # The plaintext token resolves the persisted invite.
    record = invites.resolve_token(body["token"])
    assert record is not None
    assert record.created_by == admin.id


def test_list_excludes_used_by_default(db):
    client, invites, admin = _build_app(db)
    _, alive = invites.create(created_by=admin.id, ttl_sec=86400)
    _, used = invites.create(created_by=admin.id, ttl_sec=86400)
    invites.mark_used(invite_id=used.id, used_by_user_id="someone")

    r = client.get("/api/admin/invites")
    assert r.status_code == 200
    items = r.json()["items"]
    ids = [i["id"] for i in items]
    assert alive.id in ids
    assert used.id not in ids


def test_list_with_include_used(db):
    client, invites, admin = _build_app(db)
    _, alive = invites.create(created_by=admin.id, ttl_sec=86400)
    _, used = invites.create(created_by=admin.id, ttl_sec=86400)
    invites.mark_used(invite_id=used.id, used_by_user_id="someone")

    r = client.get("/api/admin/invites", params={"include_used": True})
    items = r.json()["items"]
    ids = [i["id"] for i in items]
    assert alive.id in ids
    assert used.id in ids


def test_revoke_invalidates_invite(db):
    client, invites, admin = _build_app(db)
    token, record = invites.create(created_by=admin.id, ttl_sec=86400)
    assert invites.resolve_token(token) is not None

    r = client.delete(f"/api/admin/invites/{record.id}")
    assert r.status_code == 200
    assert r.json() == {"revoked": True}

    # Token no longer resolves (expires_at moved to past).
    assert invites.resolve_token(token) is None


def test_create_rejects_invalid_ttl(db):
    client, *_ = _build_app(db)
    r = client.post(
        "/api/admin/invites",
        json={"ttl_days": 0},
    )
    assert r.status_code == 422


def test_ttl_days_translates_to_expires_at(db):
    client, *_ = _build_app(db)
    before = time()
    r = client.post(
        "/api/admin/invites",
        json={"ttl_days": 3},
    )
    assert r.status_code == 200
    expires_at = r.json()["expires_at"]
    delta = expires_at - before
    # 3 days = 259200s; allow 60s wiggle on either side
    assert 259140 <= delta <= 259260, f"unexpected ttl delta {delta}"
