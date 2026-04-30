from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.admin_users import build_router as build_admin_users_router
from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password, verify_password
from server.pivot_users import PivotUser, PivotUserRepo


def _build_app(db) -> tuple[
    TestClient, PivotUserRepo, ExternalBindingRepo, PivotUser,
]:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
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
    app.include_router(
        build_admin_users_router(pivot_users, bindings, admin_user_dep)
    )
    return TestClient(app), pivot_users, bindings, admin


def _make_member(
    pivot_users: PivotUserRepo,
    *,
    name: str = "Member",
    email: str | None = None,
    pinyin: str = "member",
) -> PivotUser:
    return pivot_users.create(
        display_name=name,
        pinyin=pinyin,
        email=email,
        avatar_url="",
        role="member",
    )


def test_list_users_excludes_deleted_by_default(db):
    client, pivot_users, _, _ = _build_app(db)
    keep = _make_member(pivot_users, name="Keep", pinyin="keep")
    drop = _make_member(pivot_users, name="Drop", pinyin="drop")
    pivot_users.update_status(
        user_id=drop.id, status="deleted", note=None, changed_by="admin",
    )
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    items = r.json()["items"]
    ids = [u["id"] for u in items]
    assert keep.id in ids
    assert drop.id not in ids


def test_list_users_with_include_deleted(db):
    client, pivot_users, _, _ = _build_app(db)
    keep = _make_member(pivot_users, name="Keep", pinyin="keep")
    drop = _make_member(pivot_users, name="Drop", pinyin="drop")
    pivot_users.update_status(
        user_id=drop.id, status="deleted", note=None, changed_by="admin",
    )
    r = client.get("/api/admin/users", params={"include_deleted": True})
    items = r.json()["items"]
    ids = [u["id"] for u in items]
    assert keep.id in ids
    assert drop.id in ids


def test_suspend_member(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users)
    r = client.post(
        f"/api/admin/users/{member.id}/suspend",
        json={"note": "vacation"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "suspended"
    assert body["status_note"] == "vacation"


def test_resume_suspended_member(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users)
    pivot_users.update_status(
        user_id=member.id, status="suspended", note=None, changed_by="admin",
    )
    r = client.post(f"/api/admin/users/{member.id}/resume", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_suspend_self_refused(db):
    client, _, _, admin = _build_app(db)
    r = client.post(f"/api/admin/users/{admin.id}/suspend", json={})
    assert r.status_code == 422
    assert r.json()["detail"] == "cannot_modify_self_state_or_role"


def test_suspend_last_active_admin_refused(db):
    """Suspending the only remaining active admin (non-self) must be blocked."""
    client, pivot_users, _, admin = _build_app(db)
    peer = pivot_users.create(
        display_name="Peer", pinyin="peer", email=None, avatar_url="",
        role="admin",
    )
    # Demote the dep admin so `peer` becomes the only active admin.
    pivot_users.update_role(user_id=admin.id, role="member")
    r = client.post(f"/api/admin/users/{peer.id}/suspend", json={})
    assert r.status_code == 422
    assert r.json()["detail"] == "last_active_admin_protected"


def test_mark_deleted_requires_display_name_confirm(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users, name="Carol", pinyin="carol")
    r = client.post(
        f"/api/admin/users/{member.id}/mark-deleted",
        json={"confirm_display_name": "Wrong"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "display_name_mismatch"


def test_mark_deleted_with_correct_confirm(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users, name="Carol", pinyin="carol")
    r = client.post(
        f"/api/admin/users/{member.id}/mark-deleted",
        json={"confirm_display_name": "Carol"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"


def test_restore_deleted_user(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users, name="Carol", pinyin="carol")
    pivot_users.update_status(
        user_id=member.id, status="deleted", note=None, changed_by="admin",
    )
    r = client.post(
        f"/api/admin/users/{member.id}/restore",
        json={"confirm_display_name": "Carol"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"


def test_change_role_promote_to_admin(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users)
    r = client.post(
        f"/api/admin/users/{member.id}/role", json={"role": "admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


def test_change_role_demote_self_refused(db):
    client, _, _, admin = _build_app(db)
    r = client.post(
        f"/api/admin/users/{admin.id}/role", json={"role": "member"},
    )
    assert r.status_code == 422


def test_change_role_demote_last_admin_refused(db):
    """Demoting the only active admin to member must be blocked."""
    client, pivot_users, _, admin = _build_app(db)
    peer = pivot_users.create(
        display_name="Peer", pinyin="peer", email=None, avatar_url="",
        role="admin",
    )
    # Demote dep so peer is the only active admin
    pivot_users.update_role(user_id=admin.id, role="member")
    r = client.post(
        f"/api/admin/users/{peer.id}/role", json={"role": "member"},
    )
    assert r.status_code == 422


def test_change_role_invalid_role(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users)
    r = client.post(
        f"/api/admin/users/{member.id}/role", json={"role": "guest"},
    )
    assert r.status_code == 400


def test_reset_password_updates_invite_binding(db):
    client, pivot_users, bindings, _ = _build_app(db)
    member = _make_member(pivot_users, email="alice@example.com")
    bindings.bind(
        pivot_user_id=member.id, provider="invite",
        external_id="alice@example.com",
        external_union_id=None, raw_profile_json=None,
        password_hash=hash_password("oldpass"),
    )
    r = client.post(
        f"/api/admin/users/{member.id}/reset-password",
        json={"new_password": "newpass1"},
    )
    assert r.status_code == 200
    new_binding = bindings.lookup(provider="invite", external_id="alice@example.com")
    assert verify_password("newpass1", new_binding.password_hash)
    assert not verify_password("oldpass", new_binding.password_hash)


def test_reset_password_user_without_invite_binding(db):
    client, pivot_users, _, _ = _build_app(db)
    member = _make_member(pivot_users)  # no invite binding seeded
    r = client.post(
        f"/api/admin/users/{member.id}/reset-password",
        json={"new_password": "anything1"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "no_invite_binding"


def test_reset_password_user_not_found(db):
    client, *_ = _build_app(db)
    r = client.post(
        "/api/admin/users/nonexistent/reset-password",
        json={"new_password": "anything1"},
    )
    assert r.status_code == 404


def test_user_dict_includes_provider_list(db):
    client, pivot_users, bindings, _ = _build_app(db)
    member = _make_member(pivot_users, email="bob@example.com")
    bindings.bind(
        pivot_user_id=member.id, provider="feishu",
        external_id="ou_bob",
        external_union_id=None, raw_profile_json=None,
    )
    bindings.bind(
        pivot_user_id=member.id, provider="invite",
        external_id="bob@example.com",
        external_union_id=None, raw_profile_json=None,
        password_hash=hash_password("p"),
    )
    r = client.get("/api/admin/users")
    items = r.json()["items"]
    target = [u for u in items if u["id"] == member.id][0]
    assert set(target["providers"]) == {"feishu", "invite"}
