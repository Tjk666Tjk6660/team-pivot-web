from __future__ import annotations

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.matters import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.db import Database
from server.events import TOPIC_MATTER_VISIBILITY_CHANGED, clear_subscribers, subscribe
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo
from server.external_bindings import ExternalBindingRepo
from server.mentions import DisplayResolver
from server.notify import NoOpNotifier
from server.pivot_users import PivotUserRepo
from server.read_state import ReadStateRepo
from server.relevance_events import RelevanceEventsRepo


class _WorkspaceStub:
    def __init__(self, root):
        self.path = root
        self.discussions_dir = root / "discussions"
        self.index_dir = root / "index"

    def write_session(self, **_):
        from contextlib import contextmanager

        @contextmanager
        def cm():
            self.discussions_dir.mkdir(parents=True, exist_ok=True)
            self.index_dir.mkdir(parents=True, exist_ok=True)
            yield

        return cm()


def _client(tmp_path):
    db = Database(tmp_path / "test.db")
    # Auth/session is keyed by pivot_user.id post-migration; legacy users table is unused here.
    pivot_users = PivotUserRepo(db)
    pivot_user = pivot_users.create(
        display_name="dengke",
        pinyin="dengke",
        email="dengke@example.com",
        avatar_url="",
        role="member",
    )
    pivot_users.update_role(user_id=pivot_user.id, roles=["member", "tech", "ops"])
    sessions = SessionStore(db)
    sid = sessions.create(pivot_user.id)
    current_user = make_current_user(sessions, pivot_users, ApiTokenRepo(db))
    workspace = _WorkspaceStub(tmp_path / "workspace")
    bindings = ExternalBindingRepo(db)
    app = FastAPI()
    app.include_router(
        build_router(
            workspace,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            FavoriteRepo(db),
            FileReadRepo(db),
            RelevanceEventsRepo(db),
            DisplayResolver(pivot_users, bindings),
            current_user,
            db,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)
    return client, workspace, pivot_users, sessions, db


def _as_user(client, sessions, pivot_users, *, pinyin: str, roles: list[str] | None = None):
    pu = pivot_users.create(
        display_name=pinyin,
        pinyin=pinyin,
        email=f"{pinyin}@example.com",
        avatar_url="",
        role="member",
    )
    if roles is not None:
        pivot_users.update_role(user_id=pu.id, roles=roles)
    sid = sessions.create(pu.id)
    client.cookies.set("sid", sid)


def test_create_matter_writes_visibility_yaml(tmp_path):
    client, workspace, _users, _sessions, _db = _client(tmp_path)

    r = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Auth Redesign",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["技术部门"],
            },
            "visibility": {
                "mode": "restricted",
                "roles": ["技术部门"],
                "user_ids": [],
            },
            "initial_file": {
                "type": "think",
                "summary": "初步思考",
                "body": "# Summary\n\n初步思考\n",
            },
        },
    )

    assert r.status_code == 200
    matter_id = r.json()["matter_id"]
    matter_yaml = yaml.safe_load(
        (workspace.index_dir / f"{matter_id}.index.yaml").read_text(encoding="utf-8")
    )
    category_yaml = yaml.safe_load(
        (workspace.path / "categories" / "Pivot.yaml").read_text(encoding="utf-8")
    )
    assert matter_yaml["matter"]["visibility"] == {
        "mode": "restricted",
        "roles": ["技术部门"],
        "user_ids": [],
    }
    assert category_yaml["category"]["visibility"] == {
        "mode": "restricted",
        "authorized_roles": ["技术部门"],
    }


def test_create_matter_rejects_visibility_exceeding_new_category(tmp_path):
    client, _workspace, _users, _sessions, _db = _client(tmp_path)

    r = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Auth Redesign",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["技术部门"],
            },
            "visibility": {
                "mode": "restricted",
                "roles": ["行政部门"],
                "user_ids": [],
            },
            "initial_file": {
                "type": "think",
                "summary": "初步思考",
                "body": "# Summary\n\n初步思考\n",
            },
        },
    )

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "visibility_scope_exceeds_category"


def test_get_matter_visibility_returns_persisted_scope(tmp_path):
    client, _workspace, _users, _sessions, _db = _client(tmp_path)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Visibility Read",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["tech"],
            },
            "visibility": {
                "mode": "restricted",
                "roles": ["tech"],
                "user_ids": ["ou_2"],
            },
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200

    r = client.get(f"/api/matters/{created.json()['matter_id']}/visibility")

    assert r.status_code == 200
    assert r.json()["visibility"] == {
        "mode": "restricted",
        "roles": ["tech"],
        "user_ids": ["ou_2"],
    }


def test_creator_can_update_matter_visibility(tmp_path):
    client, workspace, _users, _sessions, db = _client(tmp_path)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Visibility Update",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["tech", "ops"],
            },
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200
    matter_id = created.json()["matter_id"]

    r = client.put(
        f"/api/matters/{matter_id}/visibility",
        json={"mode": "restricted", "roles": ["ops"], "user_ids": []},
    )

    assert r.status_code == 200
    assert r.json()["visibility"] == {
        "mode": "restricted",
        "roles": ["ops"],
        "user_ids": [],
    }
    matter_yaml = yaml.safe_load(
        (workspace.index_dir / f"{matter_id}.index.yaml").read_text(encoding="utf-8")
    )
    assert matter_yaml["matter"]["visibility"]["roles"] == ["ops"]
    with db.connect() as conn:
        cached_role = conn.execute(
            "SELECT role FROM matter_visibility_role_cache WHERE matter_id=?",
            (matter_id,),
        ).fetchone()
    assert cached_role["role"] == "ops"


def test_update_matter_visibility_rejects_non_creator_or_owner(tmp_path):
    client, _workspace, pivot_users, sessions, _db = _client(tmp_path)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Visibility Forbidden",
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200
    _as_user(client, sessions, pivot_users, pinyin="other")

    r = client.put(
        f"/api/matters/{created.json()['matter_id']}/visibility",
        json={"mode": "restricted", "roles": ["tech"], "user_ids": []},
    )

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "matter_visibility_forbidden"


def test_update_matter_visibility_rejects_scope_exceeding_category(tmp_path):
    client, _workspace, _users, _sessions, _db = _client(tmp_path)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Visibility Category Limit",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["tech"],
            },
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200

    r = client.put(
        f"/api/matters/{created.json()['matter_id']}/visibility",
        json={"mode": "restricted", "roles": ["ops"], "user_ids": []},
    )

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "visibility_scope_exceeds_category"


def test_create_restricted_matter_requires_new_category_visibility(tmp_path):
    client, _workspace, _users, _sessions, _db = _client(tmp_path)

    r = client.post(
        "/api/matters",
        json={
            "category": "NewCat",
            "title": "Missing Category Visibility",
            "visibility": {
                "mode": "restricted",
                "roles": ["tech"],
                "user_ids": [],
            },
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "missing_category_visibility"


def test_update_matter_visibility_emits_event(tmp_path):
    client, _workspace, _users, _sessions, _db = _client(tmp_path)
    clear_subscribers()
    seen = []
    unsubscribe = subscribe(seen.append)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Visibility Event",
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200

    try:
        r = client.put(
            f"/api/matters/{created.json()['matter_id']}/visibility",
            json={"mode": "restricted", "roles": ["tech"], "user_ids": []},
        )
    finally:
        unsubscribe()
        clear_subscribers()

    assert r.status_code == 200
    assert seen[-1].topic == TOPIC_MATTER_VISIBILITY_CHANGED


def test_restricted_matter_is_hidden_from_unauthorized_user(tmp_path):
    client, _workspace, pivot_users, sessions, _db = _client(tmp_path)
    created = client.post(
        "/api/matters",
        json={
            "category": "Pivot",
            "title": "Hidden Matter",
            "new_category_visibility": {
                "mode": "restricted",
                "authorized_roles": ["tech"],
            },
            "visibility": {
                "mode": "restricted",
                "roles": ["tech"],
                "user_ids": [],
            },
            "initial_file": {
                "type": "think",
                "summary": "init",
                "body": "# Summary\n\ninit\n",
            },
        },
    )
    assert created.status_code == 200
    matter_id = created.json()["matter_id"]
    _as_user(client, sessions, pivot_users, pinyin="other", roles=["member"])

    listing = client.get("/api/matters")
    detail = client.get(f"/api/matters/{matter_id}")
    append = client.post(
        f"/api/matters/{matter_id}/files",
        json={"type": "act", "summary": "next", "body": "next"},
    )
    comment = client.post(
        f"/api/matters/{matter_id}/comments",
        json={"target_file": "001_missing.md", "body": "comment"},
    )

    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert detail.status_code == 404
    assert detail.json()["detail"]["code"] == "matter_not_found"
    assert append.status_code == 404
    assert append.json()["detail"]["code"] == "matter_not_found"
    assert comment.status_code == 404
    assert comment.json()["detail"]["code"] == "matter_not_found"
