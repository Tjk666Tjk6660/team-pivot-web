from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai.client import DEFAULT_BASE_URL, DEFAULT_MODEL
from server.ai_conversations import AIConversationRepo
from server.api.ai import build_router as build_ai_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user_cookie,
)
from server.auth.session import SessionStore
from server.pivot_users import PivotUserRepo
from server.settings import SettingsRepo
from server.users import UserRepo
from server.workspace import Workspace


def _build_app(tmp_path, db):
    # Legacy mirror — kept while non-admin endpoints still consult it.
    users = UserRepo(db)
    users.upsert_from_feishu(open_id="ou_admin", union_id=None,
                             name="Admin", avatar_url="")
    users.update_profile("ou_admin", pinyin="admin")

    pivot_users = PivotUserRepo(db)
    admin = pivot_users.create(
        display_name="Admin", pinyin="admin",
        email="admin@example.com", avatar_url="", role="admin",
    )

    sessions = SessionStore(db)
    sid = sessions.create(pivot_user_id=admin.id)
    tokens = ApiTokenRepo(db)
    settings = SettingsRepo(db)
    conversations = AIConversationRepo(db)
    workspace = Workspace(
        path=tmp_path / "git",
        repo_url="https://github.com/acme/test-team-pivot.git",
    )

    cu = make_current_user(sessions, pivot_users, tokens)
    cu_cookie = make_current_user_cookie_only(sessions, pivot_users)
    admin_cookie = make_require_admin_user_cookie(sessions, pivot_users)

    app = FastAPI()
    app.include_router(build_ai_router(
        workspace, settings, conversations, cu, cu_cookie, admin_cookie,
    ))
    return app, sid, settings


def test_ai_settings_defaults(db, tmp_path):
    app, sid, _ = _build_app(tmp_path, db)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/ai/settings")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "has_key": False,
        "max_context_tokens": 5000,
        "min_rounds": 3,
        "max_rounds": 20,
    }


def test_ai_settings_update_roundtrip(db, tmp_path):
    app, sid, settings = _build_app(tmp_path, db)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.put(
        "/api/ai/settings",
        json={
            "base_url": "https://coding.dashscope.aliyuncs.com/v1/",
            "api_key": "sk-test",
            "model": "qwen-plus",
            "max_context_tokens": 12000,
            "min_rounds": 4,
            "max_rounds": 18,
        },
    )
    assert r.status_code == 200, r.text

    assert settings.get("ai.base_url") == "https://coding.dashscope.aliyuncs.com/v1"
    assert settings.get("ai.openrouter_api_key") == "sk-test"

    fetched = client.get("/api/ai/settings")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == {
        "base_url": "https://coding.dashscope.aliyuncs.com/v1",
        "model": "qwen-plus",
        "has_key": True,
        "max_context_tokens": 12000,
        "min_rounds": 4,
        "max_rounds": 18,
    }


def test_ai_settings_rejects_non_admin_cookie(db, tmp_path):
    """Non-admin user with a valid cookie session must get 403, not 200."""
    pivot_users = PivotUserRepo(db)
    member = pivot_users.create(
        display_name="Member", pinyin="member",
        email="member@example.com", avatar_url="", role="member",
    )
    sessions = SessionStore(db)
    member_sid = sessions.create(pivot_user_id=member.id)
    tokens = ApiTokenRepo(db)
    settings = SettingsRepo(db)
    conversations = AIConversationRepo(db)
    workspace = Workspace(
        path=tmp_path / "git",
        repo_url="https://github.com/acme/test-team-pivot.git",
    )
    cu = make_current_user(sessions, pivot_users, tokens)
    cu_cookie = make_current_user_cookie_only(sessions, pivot_users)
    admin_cookie = make_require_admin_user_cookie(sessions, pivot_users)
    app = FastAPI()
    app.include_router(build_ai_router(
        workspace, settings, conversations, cu, cu_cookie, admin_cookie,
    ))

    client = TestClient(app)
    client.cookies.set("sid", member_sid)
    r = client.get("/api/ai/settings")
    assert r.status_code == 403
    assert r.json()["detail"] == "admin_required"


def test_ai_settings_rejects_no_session(db, tmp_path):
    app, _, _ = _build_app(tmp_path, db)
    client = TestClient(app)  # no cookie
    r = client.get("/api/ai/settings")
    assert r.status_code == 401
