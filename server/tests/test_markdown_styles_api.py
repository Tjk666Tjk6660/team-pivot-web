from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.api.markdown_styles import build_router
from server.auth.admin import ADMIN_PASSWORD
from server.settings import SettingsRepo
from server.users import User, UserRepo


def _user(open_id: str = "ou_1") -> User:
    return User(
        open_id=open_id,
        union_id=None,
        name="Ken",
        avatar_url="",
        pinyin="ken",
        github_username=None,
        markdown_style=None,
        created_at=1.0,
    )


def _build_client(db, users: UserRepo) -> tuple[TestClient, SettingsRepo]:
    settings = SettingsRepo(db)
    current = _user()

    def current_user() -> User:
        got = users.get(current.open_id)
        if got is None:
            raise HTTPException(status_code=401, detail="not logged in")
        return got

    app = FastAPI()
    app.include_router(build_router(settings, users, current_user, current_user))
    return TestClient(app), settings


def test_markdown_styles_falls_back_to_builtin_default(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, _ = _build_client(db, users)

    r = client.get("/api/markdown/styles")

    assert r.status_code == 200
    body = r.json()
    assert body["user_style"] is None
    assert body["system_default_style"] is None
    assert body["effective_style"] == "code-light"
    assert {s["id"] for s in body["styles"]} >= {"code-light", "neon-dark"}


def test_markdown_styles_uses_system_default_when_user_has_no_preference(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, settings = _build_client(db, users)
    settings.set("markdown.default_style", "page-brown")

    body = client.get("/api/markdown/styles").json()

    assert body["system_default_style"] == "page-brown"
    assert body["user_style"] is None
    assert body["effective_style"] == "page-brown"


def test_user_markdown_style_overrides_system_default(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, settings = _build_client(db, users)
    settings.set("markdown.default_style", "page-brown")

    r = client.put("/api/me/markdown-style", json={"style": "neon-dark"})

    assert r.status_code == 200
    assert r.json() == {
        "user_style": "neon-dark",
        "effective_style": "neon-dark",
    }
    assert client.get("/api/markdown/styles").json()["effective_style"] == "neon-dark"


def test_user_markdown_style_rejects_unknown_style(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, _ = _build_client(db, users)

    r = client.put("/api/me/markdown-style", json={"style": "unknown"})

    assert r.status_code == 400


def test_admin_markdown_default_roundtrip_and_validation(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, _ = _build_client(db, users)
    headers = {"X-Admin-Password": ADMIN_PASSWORD}

    ok = client.put(
        "/api/admin/markdown-settings",
        json={"system_default_style": "nord-dark"},
        headers=headers,
    )

    assert ok.status_code == 200
    body = client.get("/api/admin/markdown-settings", headers=headers).json()
    assert body["system_default_style"] == "nord-dark"
    assert body["effective_system_default_style"] == "nord-dark"

    bad = client.put(
        "/api/admin/markdown-settings",
        json={"system_default_style": "unknown"},
        headers=headers,
    )
    assert bad.status_code == 400


def test_admin_markdown_settings_requires_admin_password(db, users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    client, _ = _build_client(db, users)

    r = client.get("/api/admin/markdown-settings")

    assert r.status_code == 401
