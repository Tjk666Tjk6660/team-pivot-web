from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.admin_applications import build_router as build_admin_apps_router
from server.external_bindings import ExternalBindingRepo
from server.join_applications import JoinApplicationRepo
from server.notify import NoOpNotifier
from server.pivot_users import PivotUser, PivotUserRepo


class _RecordingNotifier(NoOpNotifier):
    def __init__(self) -> None:
        self.approved_calls: list[dict[str, Any]] = []
        self.rejected_calls: list[dict[str, Any]] = []

    def notify_application_approved(
        self, *, applicant_open_id: str, merged: bool,
    ) -> None:
        self.approved_calls.append(
            {"applicant_open_id": applicant_open_id, "merged": merged}
        )

    def notify_application_rejected(self, *, applicant_open_id: str) -> None:
        self.rejected_calls.append({"applicant_open_id": applicant_open_id})


def _make_admin(pivot_users: PivotUserRepo) -> PivotUser:
    return pivot_users.create(
        display_name="Admin",
        pinyin="admin",
        email="admin@example.com",
        avatar_url="",
        role="admin",
    )


def _build_app(db) -> tuple[
    TestClient, PivotUserRepo, ExternalBindingRepo, JoinApplicationRepo,
    _RecordingNotifier, PivotUser,
]:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    notifier = _RecordingNotifier()
    admin = _make_admin(pivot_users)

    def admin_user_dep() -> PivotUser:
        return admin

    app = FastAPI()
    app.include_router(
        build_admin_apps_router(
            applications, pivot_users, bindings, notifier, admin_user_dep,
        )
    )
    return (
        TestClient(app), pivot_users, bindings, applications, notifier, admin,
    )


def test_list_pending_applications(db):
    client, _, _, applications, _, _ = _build_app(db)
    a1 = applications.create(
        provider="feishu", external_id="ou_a", external_union_id=None,
        raw_profile={"name": "Alice"}, suggested_match_user_id=None,
    )
    a2 = applications.create(
        provider="feishu", external_id="ou_b", external_union_id=None,
        raw_profile={"name": "Bob"}, suggested_match_user_id=None,
    )
    applications.reject(application_id=a2.id, reviewed_by="admin", reason=None)

    r = client.get("/api/admin/applications")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == a1.id
    assert items[0]["status"] == "pending"


def test_list_with_status_filter(db):
    client, _, _, applications, _, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_x", external_union_id=None,
        raw_profile={"name": "Bob"}, suggested_match_user_id=None,
    )
    applications.reject(application_id=a.id, reviewed_by="admin", reason="dup")

    r = client.get("/api/admin/applications", params={"status": "rejected"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "rejected"
    assert items[0]["reject_reason"] == "dup"


def test_match_candidates_returns_email_match(db):
    client, pivot_users, _, applications, _, _ = _build_app(db)
    pivot_users.create(
        display_name="Carol", pinyin="carol",
        email="carol@example.com", avatar_url="", role="member",
    )
    a = applications.create(
        provider="feishu", external_id="ou_c", external_union_id=None,
        raw_profile={"name": "C", "email": "carol@example.com"},
        suggested_match_user_id=None,
    )
    r = client.get(f"/api/admin/applications/{a.id}/match-candidates")
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert len(cands) == 1
    assert cands[0]["display_name"] == "Carol"
    assert cands[0]["reason"] == "email_exact"


def test_match_candidates_404_when_missing(db):
    client, *_ = _build_app(db)
    r = client.get("/api/admin/applications/missing/match-candidates")
    assert r.status_code == 404


def test_approve_creates_new_user_and_binding(db):
    client, pivot_users, bindings, applications, notifier, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_new", external_union_id="on_new",
        raw_profile={
            "name": "Dave", "email": "dave@example.com",
            "avatar_url": "https://x/avatar.png",
        },
        suggested_match_user_id=None,
    )
    r = client.post(f"/api/admin/applications/{a.id}/approve", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] is True
    assert body["merged"] is False
    new_user = pivot_users.get(body["user_id"])
    assert new_user is not None
    assert new_user.display_name == "Dave"
    assert new_user.email == "dave@example.com"
    assert new_user.role == "member"

    binding = bindings.lookup(provider="feishu", external_id="ou_new")
    assert binding is not None
    assert binding.pivot_user_id == new_user.id
    assert binding.external_union_id == "on_new"

    assert applications.get(a.id).status == "approved"
    assert notifier.approved_calls == [
        {"applicant_open_id": "ou_new", "merged": False}
    ]


def test_approve_merges_into_existing_user(db):
    client, pivot_users, bindings, applications, notifier, _ = _build_app(db)
    existing = pivot_users.create(
        display_name="Eve", pinyin="eve",
        email="eve@example.com", avatar_url="", role="member",
    )
    a = applications.create(
        provider="feishu", external_id="ou_eve", external_union_id=None,
        raw_profile={"name": "Eve", "email": "eve@example.com"},
        suggested_match_user_id=existing.id,
    )
    r = client.post(
        f"/api/admin/applications/{a.id}/approve",
        json={"target_pivot_user_id": existing.id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged"] is True
    assert body["user_id"] == existing.id

    binding = bindings.lookup(provider="feishu", external_id="ou_eve")
    assert binding is not None
    assert binding.pivot_user_id == existing.id
    assert notifier.approved_calls == [
        {"applicant_open_id": "ou_eve", "merged": True}
    ]


def test_approve_rejects_when_target_inactive(db):
    client, pivot_users, _, applications, _, _ = _build_app(db)
    target = pivot_users.create(
        display_name="X", pinyin="x", email=None, avatar_url="", role="member",
    )
    pivot_users.update_status(
        user_id=target.id, status="suspended", note=None, changed_by="admin",
    )
    a = applications.create(
        provider="feishu", external_id="ou_x", external_union_id=None,
        raw_profile={"name": "X"}, suggested_match_user_id=None,
    )
    r = client.post(
        f"/api/admin/applications/{a.id}/approve",
        json={"target_pivot_user_id": target.id},
    )
    assert r.status_code == 400


def test_approve_404_when_application_not_pending(db):
    client, _, _, applications, _, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_z", external_union_id=None,
        raw_profile={"name": "Z"}, suggested_match_user_id=None,
    )
    applications.reject(application_id=a.id, reviewed_by="admin", reason=None)
    r = client.post(f"/api/admin/applications/{a.id}/approve", json={})
    assert r.status_code == 404


def test_reject_marks_application_and_dms_applicant(db):
    client, _, _, applications, notifier, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_rej", external_union_id=None,
        raw_profile={"name": "Reject"}, suggested_match_user_id=None,
    )
    r = client.post(
        f"/api/admin/applications/{a.id}/reject",
        json={"reason": "duplicate"},
    )
    assert r.status_code == 200
    assert r.json() == {"rejected": True}
    refreshed = applications.get(a.id)
    assert refreshed.status == "rejected"
    assert refreshed.reject_reason == "duplicate"
    assert notifier.rejected_calls == [{"applicant_open_id": "ou_rej"}]


def test_reject_404_when_already_resolved(db):
    client, _, _, applications, _, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_dup", external_union_id=None,
        raw_profile={"name": "X"}, suggested_match_user_id=None,
    )
    applications.reject(application_id=a.id, reviewed_by="admin", reason=None)
    r = client.post(
        f"/api/admin/applications/{a.id}/reject", json={},
    )
    assert r.status_code == 404


def test_unblock_clears_rejected_application(db):
    client, _, _, applications, _, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_u", external_union_id=None,
        raw_profile={"name": "U"}, suggested_match_user_id=None,
    )
    applications.reject(application_id=a.id, reviewed_by="admin", reason=None)
    r = client.post(f"/api/admin/applications/{a.id}/unblock")
    assert r.status_code == 200
    assert applications.get(a.id) is None  # physically deleted


def test_unblock_refuses_pending_application(db):
    client, _, _, applications, _, _ = _build_app(db)
    a = applications.create(
        provider="feishu", external_id="ou_p", external_union_id=None,
        raw_profile={"name": "P"}, suggested_match_user_id=None,
    )
    r = client.post(f"/api/admin/applications/{a.id}/unblock")
    assert r.status_code == 422
    assert applications.get(a.id).status == "pending"


def test_unblock_404_when_missing(db):
    client, *_ = _build_app(db)
    r = client.post("/api/admin/applications/missing/unblock")
    assert r.status_code == 404
