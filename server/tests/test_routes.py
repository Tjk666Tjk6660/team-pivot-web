from __future__ import annotations

from dataclasses import dataclass

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
def client_and_oauth() -> tuple[TestClient, FakeOAuth, SessionStore]:
    oauth = FakeOAuth()
    sessions = SessionStore()
    app = FastAPI()
    app.include_router(build_router(oauth, sessions, SECRET))
    return TestClient(app), oauth, sessions


def test_login_redirects_to_authorize(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://example.com/authorize?state=")


def test_callback_rejects_invalid_state(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.get("/auth/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code == 400


def test_callback_happy_path_sets_session_cookie(client_and_oauth):
    client, oauth, sessions = client_and_oauth
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]

    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "/"
    assert "sid" in cb.cookies
    assert oauth.exchange_calls == ["abc"]


def test_me_returns_401_without_session(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.get("/me")
    assert r.status_code == 401


def test_me_returns_user_after_login(client_and_oauth):
    client, _, _ = client_and_oauth
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    r = client.get("/me")
    assert r.status_code == 200
    body = r.json()
    assert body["open_id"] == "ou_1"
    assert body["name"] == "Ken"


def test_logout_clears_session(client_and_oauth):
    client, _, _ = client_and_oauth
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert client.get("/me").status_code == 200
    client.post("/logout")
    assert client.get("/me").status_code == 401
