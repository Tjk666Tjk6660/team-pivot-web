from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.drafts import build_router
from server.auth.session import SessionStore
from server.drafts import DraftRepo
from server.notify import NoOpNotifier


class _FakeWorkspace:
    """Drafts API only needs publish helpers in the publish path; for the
    CRUD tests below we never invoke /publish, so an unused stub is fine."""


@pytest.fixture
def client_and_sid(db, users):
    users.upsert_from_feishu(
        open_id="ou_1", union_id=None, name="Ken", avatar_url="",
    )
    users.update_profile("ou_1", pinyin="ken")

    sessions = SessionStore()
    sid = sessions.create("ou_1")
    drafts = DraftRepo(db)

    app = FastAPI()
    app.include_router(build_router(_FakeWorkspace(), sessions, users, drafts, NoOpNotifier()))
    client = TestClient(app)
    client.cookies.set("sid", sid)
    return client, sid, drafts


def test_requires_auth():
    from server.users import UserRepo
    from server.db import Database
    import tempfile, os
    tmp = tempfile.mkdtemp()
    try:
        d = Database(f"{tmp}/db.sqlite")
        sessions = SessionStore()
        app = FastAPI()
        app.include_router(build_router(_FakeWorkspace(), sessions, UserRepo(d), DraftRepo(d), NoOpNotifier()))
        client = TestClient(app)
        assert client.get("/api/drafts").status_code == 401
        assert client.post("/api/drafts", json={"type": "proposal"}).status_code == 401
    finally:
        import shutil; shutil.rmtree(tmp)


def test_create_get_update_delete_roundtrip(client_and_sid):
    client, _, _ = client_and_sid
    r = client.post(
        "/api/drafts",
        json={"type": "proposal", "title": "T", "category": "general", "body_md": "hi"},
    )
    assert r.status_code == 200
    draft_id = r.json()["id"]

    r = client.get(f"/api/drafts/{draft_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "T"

    r = client.patch(f"/api/drafts/{draft_id}", json={"body_md": "updated"})
    assert r.status_code == 200
    assert r.json()["body_md"] == "updated"

    r = client.get("/api/drafts")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    r = client.delete(f"/api/drafts/{draft_id}")
    assert r.status_code == 200
    assert client.get(f"/api/drafts/{draft_id}").status_code == 404


def test_cannot_access_other_users_draft(client_and_sid):
    client, _, drafts_repo = client_and_sid
    other = drafts_repo.create(
        user_open_id="ou_other", type_="proposal", body_md="private",
    )
    assert client.get(f"/api/drafts/{other.id}").status_code == 404
    assert client.patch(f"/api/drafts/{other.id}", json={"body_md": "hack"}).status_code == 404
    assert client.delete(f"/api/drafts/{other.id}").status_code == 404


def test_create_validates_category_pattern(client_and_sid):
    client, _, _ = client_and_sid
    r = client.post("/api/drafts", json={"type": "proposal", "category": "bad/cat"})
    assert r.status_code == 422


def test_publish_requires_fields(client_and_sid):
    client, _, _ = client_and_sid
    r = client.post(
        "/api/drafts",
        json={"type": "proposal", "title": "", "category": "general", "body_md": ""},
    )
    # empty title is allowed at draft stage; publish should refuse
    draft_id = r.json()["id"]
    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 400
