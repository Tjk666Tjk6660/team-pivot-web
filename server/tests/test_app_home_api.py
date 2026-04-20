from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.app_home import build_router as build_app_home_router
from server.api.app_home import load_app_version, load_home_markdown, load_recent_releases
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore


def _build_app(db, users, tmp_path, monkeypatch):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    tokens = ApiTokenRepo(db)

    class DummyWorkspace:
        def head(self) -> str:
            return "abc1234"

    runtime = DummyWorkspace()

    cu = make_current_user(sessions, users, tokens)

    app = FastAPI()
    app.include_router(build_app_home_router(runtime, cu))
    return app, sid


def test_home_api_returns_markdown_and_version(db, users, tmp_path, monkeypatch):
    home = tmp_path / "HOME.md"
    home.write_text("# 欢迎\n\n这里是首页。", encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## 0.2.0 - 2026-04-20\n"
        "### Title\n"
        "欢迎首页上线\n\n"
        "### Added\n"
        "- 首页欢迎页\n",
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")

    monkeypatch.setattr("server.api.app_home.HOME_PATH", home)
    monkeypatch.setattr("server.api.app_home.CHANGELOG_PATH", changelog)
    monkeypatch.setattr("server.api.app_home.PYPROJECT_PATH", pyproject)

    app, sid = _build_app(db, users, tmp_path, monkeypatch)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/app/home")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app"]["version"] == "0.2.0"
    assert body["app"]["head"] == "abc1234"
    assert "这里是首页" in body["welcome"]["body_md"]
    assert body["latest_release"]["title"] == "欢迎首页上线"
    assert body["latest_release"]["version"] == "0.2.0"


def test_home_helpers_fallbacks(tmp_path):
    assert load_app_version(tmp_path / "missing.toml") == "0.0.0"
    assert "欢迎使用 Pivot" in load_home_markdown(tmp_path / "missing.md")
    assert load_recent_releases(tmp_path / "missing.md") == []
