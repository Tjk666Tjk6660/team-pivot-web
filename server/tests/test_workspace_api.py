from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.tokens import build_router as build_tokens_router
from server.api.workspace import build_router as build_workspace_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user_cookie,
)
from server.auth.session import SessionStore
from server.pivot_users import PivotUserRepo
from server.settings import SettingsRepo
from server.workspace_config import save_workspace_config
from server.workspace_runtime import WorkspaceRuntime


def _stub_workspace(monkeypatch):
    monkeypatch.setattr("server.workspace_runtime.Workspace.ensure_cloned", lambda self: None)
    monkeypatch.setattr("server.workspace_runtime.Workspace.recover", lambda self: 0)
    monkeypatch.setattr("server.workspace_runtime.Workspace.is_cloned", lambda self: True)
    monkeypatch.setattr("server.workspace_runtime.Workspace.head", lambda self: "abc1234")
    monkeypatch.setattr("server.workspace_runtime.Workspace.refresh", lambda self: None)


def _build_app(db, tmp_path, monkeypatch):
    _stub_workspace(monkeypatch)
    pivot_users = PivotUserRepo(db)
    admin = pivot_users.create(
        display_name="Admin", pinyin="admin",
        email="admin@example.com", avatar_url="", role="admin",
    )
    sessions = SessionStore(db)
    sid = sessions.create(pivot_user_id=admin.id)
    tokens = ApiTokenRepo(db)
    settings = SettingsRepo(db)
    runtime = WorkspaceRuntime(base_dir=tmp_path / "git", settings=settings)

    cu = make_current_user(sessions, pivot_users, tokens)
    cu_cookie = make_current_user_cookie_only(sessions, pivot_users)
    admin_cookie = make_require_admin_user_cookie(sessions, pivot_users)

    app = FastAPI()
    app.include_router(build_tokens_router(tokens, cu_cookie))
    app.include_router(build_workspace_router(
        runtime, settings, cu, cu_cookie, admin_cookie,
    ))
    return app, sid, tokens, settings, runtime


def test_bearer_can_call_workspace_mirror(db, tmp_path, monkeypatch):
    app, sid, tokens, settings, runtime = _build_app(db, tmp_path, monkeypatch)
    save_workspace_config(
        settings,
        repo_url="https://github.com/acme/test-team-pivot.git",
        visibility="private",
        write_token="write-secret",
        readonly_token="read-secret",
    )
    runtime.reload()

    cookie_client = TestClient(app)
    cookie_client.cookies.set("sid", sid)
    created = cookie_client.post("/api/tokens", json={"name": "vscode"})
    plaintext = created.json()["token"]

    bearer_client = TestClient(app)
    bearer_client.headers.update({"Authorization": f"Bearer {plaintext}"})
    r = bearer_client.get("/api/workspace/mirror")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_url"] == "https://github.com/acme/test-team-pivot.git"
    assert body["visibility"] == "private"
    assert body["branch"] == "main"
    assert body["git_username"] == "x-access-token"
    assert body["git_token"] == "read-secret"
    assert body["head"] == "abc1234"


def test_invalid_pat_returns_invalid_token(db, tmp_path, monkeypatch):
    app, _, _, _, _ = _build_app(db, tmp_path, monkeypatch)
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer pvt_nope"})
    r = client.get("/api/workspace/mirror")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_token"


def test_public_repo_returns_null_credentials(db, tmp_path, monkeypatch):
    app, sid, _, settings, runtime = _build_app(db, tmp_path, monkeypatch)
    save_workspace_config(
        settings,
        repo_url="https://github.com/acme/public-repo.git",
        visibility="public",
        write_token="write-secret",
        readonly_token="",
    )
    runtime.reload()

    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.get("/api/workspace/mirror")
    assert r.status_code == 200
    body = r.json()
    assert body["git_username"] is None
    assert body["git_token"] is None


def test_private_repo_returns_configured_credentials(db, tmp_path, monkeypatch):
    app, sid, _, _, _ = _build_app(db, tmp_path, monkeypatch)
    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.put(
        "/api/admin/workspace-config",
        json={
            "repo_url": "https://github.com/acme/private-repo.git",
            "visibility": "private",
            "write_token": "write-secret",
            "readonly_token": "read-secret",
        },
    )
    assert r.status_code == 200, r.text

    mirror = client.get("/api/workspace/mirror")
    body = mirror.json()
    assert body["git_username"] == "x-access-token"
    assert body["git_token"] == "read-secret"


def test_admin_workspace_config_validation(db, tmp_path, monkeypatch):
    app, sid, _, _, _ = _build_app(db, tmp_path, monkeypatch)
    client = TestClient(app)
    client.cookies.set("sid", sid)
    r = client.put(
        "/api/admin/workspace-config",
        json={
            "repo_url": "https://github.com/acme/private-repo.git",
            "visibility": "private",
            "write_token": "write-secret",
            "readonly_token": "",
        },
    )
    assert r.status_code == 400
    assert "readonly_token" in r.json()["detail"]


def test_admin_workspace_config_rejects_non_admin(db, tmp_path, monkeypatch):
    """Member-role users cannot read or write the workspace config."""
    _stub_workspace(monkeypatch)
    pivot_users = PivotUserRepo(db)
    member = pivot_users.create(
        display_name="Member", pinyin="member",
        email="member@example.com", avatar_url="", role="member",
    )
    sessions = SessionStore(db)
    member_sid = sessions.create(pivot_user_id=member.id)
    tokens = ApiTokenRepo(db)
    settings = SettingsRepo(db)
    runtime = WorkspaceRuntime(base_dir=tmp_path / "git", settings=settings)
    cu = make_current_user(sessions, pivot_users, tokens)
    cu_cookie = make_current_user_cookie_only(sessions, pivot_users)
    admin_cookie = make_require_admin_user_cookie(sessions, pivot_users)
    app = FastAPI()
    app.include_router(build_workspace_router(
        runtime, settings, cu, cu_cookie, admin_cookie,
    ))

    client = TestClient(app)
    client.cookies.set("sid", member_sid)
    r = client.get("/api/admin/workspace-config")
    assert r.status_code == 403
