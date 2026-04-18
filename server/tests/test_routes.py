from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.feishu_oauth import TokenResult, UserInfo
from server.auth.routes import build_router
from server.auth.session import SessionStore

SECRET = "test-secret-do-not-use-in-prod"


class FakeOAuth:
    def __init__(self) -> None:
        self.exchange_calls: list[str] = []

    def authorize_url(self, state: str) -> str:
        return f"https://example.com/authorize?state={state}"

    def exchange_code(self, code: str) -> TokenResult:
        self.exchange_calls.append(code)
        return TokenResult(access_token="uat_" + code, refresh_token=None, expires_in=3600)

    def get_user_info(self, user_access_token: str) -> UserInfo:
        return UserInfo(
            open_id="ou_1",
            union_id="on_1",
            name="Ken",
            avatar_url="http://a/1.png",
            email=None,
        )


@pytest.fixture
def client_and_oauth(users) -> tuple[TestClient, FakeOAuth]:
    oauth = FakeOAuth()
    sessions = SessionStore()
    app = FastAPI()
    app.include_router(build_router(oauth, sessions, users, SECRET))
    return TestClient(app), oauth


def _login(client: TestClient) -> None:
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)


def test_login_redirects_to_authorize(client_and_oauth):
    client, _ = client_and_oauth
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://example.com/authorize?state=")


def test_callback_rejects_invalid_state(client_and_oauth):
    client, _ = client_and_oauth
    r = client.get("/auth/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code == 400


def test_callback_creates_user_and_sets_cookie(client_and_oauth, users):
    client, oauth = client_and_oauth
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]

    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert "sid" in cb.cookies
    assert oauth.exchange_calls == ["abc"]
    u = users.get("ou_1")
    assert u is not None and u.name == "Ken" and u.needs_setup is True


def test_me_returns_401_without_session(client_and_oauth):
    client, _ = client_and_oauth
    assert client.get("/me").status_code == 401


def test_me_returns_user_with_needs_setup_flag(client_and_oauth):
    client, _ = client_and_oauth
    _login(client)
    body = client.get("/me").json()
    assert body["open_id"] == "ou_1"
    assert body["needs_setup"] is True
    assert body["pinyin"] is None


def test_profile_update_sets_pinyin_and_clears_needs_setup(client_and_oauth):
    client, _ = client_and_oauth
    _login(client)
    r = client.post("/me/profile", json={"pinyin": "dengke", "github_username": "ken-d"})
    assert r.status_code == 200
    body = r.json()
    assert body["pinyin"] == "dengke"
    assert body["github_username"] == "ken-d"
    assert body["needs_setup"] is False


def test_profile_update_rejects_bad_pinyin(client_and_oauth):
    client, _ = client_and_oauth
    _login(client)
    r = client.post("/me/profile", json={"pinyin": "Bad!"})
    assert r.status_code == 400


def test_profile_update_requires_session(client_and_oauth):
    client, _ = client_and_oauth
    r = client.post("/me/profile", json={"pinyin": "dengke"})
    assert r.status_code == 401


def test_logout_clears_session(client_and_oauth):
    client, _ = client_and_oauth
    _login(client)
    assert client.get("/me").status_code == 200
    client.post("/logout")
    assert client.get("/me").status_code == 401
