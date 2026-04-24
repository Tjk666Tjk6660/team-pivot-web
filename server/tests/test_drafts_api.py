from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.drafts import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
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

    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    drafts = DraftRepo(db)

    app = FastAPI()
    from server.contacts import ContactRepo
    cu = make_current_user(sessions, users, ApiTokenRepo(db))
    app.include_router(build_router(
        _FakeWorkspace(), drafts, ContactRepo(db), NoOpNotifier(), cu,
    ))
    client = TestClient(app)
    client.cookies.set("sid", sid)
    return client, sid, drafts


def test_requires_auth():
    from server.users import UserRepo
    from server.db import Database
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        d = Database(f"{tmp}/db.sqlite")
        sessions = SessionStore(d)
        ur = UserRepo(d)
        app = FastAPI()
        from server.contacts import ContactRepo
        cu = make_current_user(sessions, ur, ApiTokenRepo(d))
        app.include_router(build_router(
            _FakeWorkspace(), DraftRepo(d), ContactRepo(d), NoOpNotifier(), cu,
        ))
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


def test_create_accepts_chinese_category(client_and_sid):
    client, _, _ = client_and_sid
    r = client.post("/api/drafts", json={"type": "proposal", "category": "技术讨论"})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "技术讨论"


def test_create_rejects_category_too_long(client_and_sid):
    client, _, _ = client_and_sid
    r = client.post("/api/drafts", json={"type": "proposal", "category": "这是一二三四五六七八九十一二三四五六七八九十"})
    assert r.status_code == 422


def test_publish_without_matter_payload_rejected(client_and_sid):
    """P4.6: matter 迁移后，publish_draft 不再回落到老 publish_proposal / publish_reply。
    历史草稿或缺 matter_payload 的草稿必须先补全再发布。"""
    client, _, _ = client_and_sid
    r = client.post(
        "/api/drafts",
        json={"type": "proposal", "title": "Legacy", "category": "general", "body_md": "hi"},
    )
    draft_id = r.json()["id"]
    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "matter_payload_required"


# ---------- P4.6: matter drafts via matter_payload ----------


from contextlib import contextmanager
from pathlib import Path


class _RealWorkspaceStub:
    """Drafts API publish path needs a workspace that responds to discussions_dir,
    index_dir, path, and write_session. This stub provides them backed by a real
    tmp directory so publish_matter_* can actually write files and YAML."""

    def __init__(self, root: Path) -> None:
        self.path = root
        self.discussions_dir = root / "discussions"
        self.index_dir = root / "index"

    @contextmanager
    def write_session(self, **_: object):
        self.discussions_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        yield


@pytest.fixture
def matter_client(db, users, tmp_path):
    users.upsert_from_feishu(
        open_id="ou_1", union_id=None, name="邓柯", avatar_url="",
    )
    users.update_profile("ou_1", pinyin="dengke")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    drafts = DraftRepo(db)

    from server.contacts import ContactRepo
    ws = _RealWorkspaceStub(tmp_path)
    cu = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(build_router(
        ws, drafts, ContactRepo(db), NoOpNotifier(), cu,
    ))
    client = TestClient(app)
    client.cookies.set("sid", sid)
    return client, ws, drafts


def test_matter_draft_crud_roundtrip(client_and_sid):
    """POST + PATCH + GET must preserve matter_payload verbatim."""
    client, _, _ = client_and_sid
    payload = {
        "doc_type": "think",
        "summary": "初步想法",
        "owner": "dengke",
    }
    r = client.post(
        "/api/drafts",
        json={
            "type": "proposal",
            "title": "Matter-Draft-T",
            "category": "P4t",
            "body_md": "# Summary\n\n想法\n",
            "matter_payload": payload,
        },
    )
    assert r.status_code == 200, r.text
    draft_id = r.json()["id"]
    assert r.json()["matter_payload"] == payload

    r = client.get(f"/api/drafts/{draft_id}")
    assert r.json()["matter_payload"] == payload

    updated = {**payload, "summary": "更新后的想法"}
    r = client.patch(
        f"/api/drafts/{draft_id}",
        json={"matter_payload": updated},
    )
    assert r.status_code == 200
    assert r.json()["matter_payload"]["summary"] == "更新后的想法"


def test_matter_draft_publish_creates_matter(matter_client):
    """type=proposal + matter_payload → publish_matter_create."""
    client, ws, _ = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "Matter-From-Draft",
        "category": "P4t",
        "body_md": "# Summary\n\nvia draft\n",
        "matter_payload": {"doc_type": "think", "summary": "via draft"},
    })
    assert r.status_code == 200, r.text
    draft_id = r.json()["id"]

    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 200, r.text
    published = r.json()["published"]
    assert "matter_id" in published
    # Real matter index was written
    matter_id = published["matter_id"]
    idx = ws.index_dir / f"{matter_id}.index.yaml"
    assert idx.is_file()
    import yaml as _yaml
    data = _yaml.safe_load(idx.read_text(encoding="utf-8"))
    assert data["matter"]["current_status"] == "planning"
    assert data["timeline"][0]["type"] == "think"
    # Draft removed after publish
    assert client.get(f"/api/drafts/{draft_id}").status_code == 404


def test_matter_draft_publish_appends_file(matter_client):
    """type=reply + matter_payload + thread_key → publish_matter_append."""
    client, ws, _ = matter_client
    # First seed a matter to append into
    seed = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "Matter-Seed",
        "category": "P4t",
        "body_md": "seed\n",
        "matter_payload": {"doc_type": "think", "summary": "seed"},
    })
    matter_id = client.post(
        f"/api/drafts/{seed.json()['id']}/publish"
    ).json()["published"]["matter_id"]

    # Now append via a reply draft
    r = client.post("/api/drafts", json={
        "type": "reply",
        "thread_key": matter_id,
        "body_md": "# Do\n\nstart work\n",
        "matter_payload": {
            "doc_type": "act",
            "summary": "开始行动",
            "status_change": {"from": "planning", "to": "executing"},
        },
    })
    draft_id = r.json()["id"]
    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 200, r.text

    idx = ws.index_dir / f"{matter_id}.index.yaml"
    import yaml as _yaml
    data = _yaml.safe_load(idx.read_text(encoding="utf-8"))
    assert len(data["timeline"]) == 2
    assert data["timeline"][1]["type"] == "act"
    assert data["matter"]["current_status"] == "executing"
    assert client.get(f"/api/drafts/{draft_id}").status_code == 404


def test_matter_draft_publish_requires_doc_type(matter_client):
    client, _, _ = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "No-DocType",
        "category": "P4t",
        "body_md": "x\n",
        "matter_payload": {"summary": "missing doc_type"},
    })
    r = client.post(f"/api/drafts/{r.json()['id']}/publish")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "matter_doc_type_required"


def test_matter_draft_publish_requires_summary(matter_client):
    client, _, _ = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "No-Summary",
        "category": "P4t",
        "body_md": "x\n",
        "matter_payload": {"doc_type": "think"},
    })
    r = client.post(f"/api/drafts/{r.json()['id']}/publish")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "matter_summary_required"


def test_matter_draft_publish_validator_rejects_bad_type(matter_client):
    """result as matter-first-file must be rejected with 422 (type_not_allowed in planning)."""
    client, _, _ = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "Bad-First",
        "category": "P4t",
        "body_md": "x\n",
        "matter_payload": {
            "doc_type": "result",
            "summary": "x",
            "outcome": "finished",
            "status_change": {"from": "planning", "to": "finished"},
        },
    })
    r = client.post(f"/api/drafts/{r.json()['id']}/publish")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "type_not_allowed"


def test_legacy_draft_rejected_without_matter_payload(matter_client):
    """P4.6: 历史 proposal 草稿（无 matter_payload）发布时应被拒绝；草稿保留，
    便于用户 PATCH 补全后重试。"""
    client, ws, drafts_repo = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "Legacy-T",
        "category": "P4t",
        "body_md": "legacy content\n",
    })
    draft_id = r.json()["id"]
    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "matter_payload_required"
    # 草稿仍然在库里，没被误删
    assert drafts_repo.get(draft_id) is not None
    # 没有任何老式 thread index 被写入
    assert not any(ws.index_dir.glob("*-discuss.index.yaml")) if ws.index_dir.exists() else True


def test_legacy_draft_upgradable_via_patch(matter_client):
    """补全后应能正常发布为 matter。"""
    client, ws, _ = matter_client
    r = client.post("/api/drafts", json={
        "type": "proposal",
        "title": "Upgrade-Me",
        "category": "P4t",
        "body_md": "old body\n",
    })
    draft_id = r.json()["id"]
    # 初次发布失败
    assert client.post(f"/api/drafts/{draft_id}/publish").status_code == 400
    # PATCH 补全 matter_payload
    assert client.patch(f"/api/drafts/{draft_id}", json={
        "matter_payload": {"doc_type": "think", "summary": "upgraded"},
    }).status_code == 200
    # 再发布成功
    r = client.post(f"/api/drafts/{draft_id}/publish")
    assert r.status_code == 200, r.text
    assert "matter_id" in r.json()["published"]
