from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.feishu_oauth import TokenResult, UserInfo
from server.auth.routes import build_router
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.join_applications import JoinApplicationRepo
from server.notify import NoOpNotifier
from server.pivot_users import PivotUserRepo

SECRET = "test-secret-do-not-use-in-prod"

# FakeOAuth always returns open_id="ou_1", name="Ken".
class FakeOAuth:
    def __init__(self) -> None:
        self.exchange_calls: list[str] = []

    def authorize_url(self, state: str) -> str:
        return f"https://example.com/authorize?state={state}"

    def preauth_url(self, state: str) -> str:
        return f"https://example.com/preauth?state={state}"

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


def _make_app(db, *, secure_cookie: bool = False):
    """Build a TestClient with a pre-seeded PivotUser + feishu binding for ou_1."""
    oauth = FakeOAuth()
    sessions = SessionStore(db)
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    contacts = ContactRepo(db)
    notifier = NoOpNotifier()

    # Pre-seed: create pivot user and bind to feishu open_id ou_1
    user = pivot_users.create(
        display_name="Ken",
        pinyin=None,
        email=None,
        avatar_url="http://a/1.png",
    )
    bindings.bind(
        pivot_user_id=user.id,
        provider="feishu",
        external_id="ou_1",
        external_union_id="on_1",
        raw_profile_json=None,
    )

    app = FastAPI()
    app.include_router(
        build_router(
            oauth, sessions, pivot_users, bindings, applications, notifier,
            contacts, SECRET,
            secure_cookie=secure_cookie,
        )
    )
    return TestClient(app), oauth, contacts, pivot_users, bindings, applications, user


@pytest.fixture
def client_and_oauth(db):
    client, oauth, contacts, pivot_users, bindings, applications, user = _make_app(db)
    return client, oauth, contacts


def _login(client: TestClient) -> None:
    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)


def test_login_redirects_to_authorize(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://example.com/authorize?state=")


def test_callback_rejects_invalid_state(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.get("/auth/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code == 400


def test_callback_creates_session_and_sets_cookie(db):
    """Bound user (active) → 302 + sid cookie set."""
    client, oauth, contacts, pivot_users, bindings, applications, user = _make_app(db)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]

    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert "sid" in cb.cookies
    assert oauth.exchange_calls == ["abc"]
    # Verify pivot user still exists and is active
    pu = pivot_users.get(user.id)
    assert pu is not None and pu.display_name == "Ken"


def test_callback_redirects_to_next_path(db):
    client, _, _, _, _, _, _ = _make_app(db)
    login = client.get("/login?next=/t/%E4%BA%A7%E5%93%81/%E8%AE%A8%E8%AE%BA", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]

    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "/t/%E4%BA%A7%E5%93%81/%E8%AE%A8%E8%AE%BA"


def test_callback_uses_samesite_none_for_secure_cookie(db):
    client, _, _, _, _, _, _ = _make_app(db, secure_cookie=True)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    set_cookie = cb.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    assert "samesite=none" in set_cookie


def test_me_returns_401_without_session(client_and_oauth):
    client, _, _ = client_and_oauth
    assert client.get("/me").status_code == 401


def test_me_returns_user_with_needs_setup_flag(client_and_oauth):
    client, _, _ = client_and_oauth
    _login(client)
    body = client.get("/me").json()
    assert body["name"] == "Ken"
    assert body["needs_setup"] is True
    assert body["pinyin"] is None


def test_profile_update_sets_pinyin_and_clears_needs_setup(client_and_oauth):
    client, _, _ = client_and_oauth
    _login(client)
    r = client.post("/me/profile", json={"pinyin": "dengke", "github_username": "ken-d"})
    assert r.status_code == 200
    body = r.json()
    assert body["pinyin"] == "dengke"
    assert body["github_username"] == "ken-d"
    assert body["needs_setup"] is False


def test_profile_update_rejects_bad_pinyin(client_and_oauth):
    """Pinyin field rejects values that are too short (< 2 chars)."""
    client, _, _ = client_and_oauth
    _login(client)
    r = client.post("/me/profile", json={"pinyin": "x"})
    assert r.status_code == 422  # Pydantic min_length validation


def test_profile_update_requires_session(client_and_oauth):
    client, _, _ = client_and_oauth
    r = client.post("/me/profile", json={"pinyin": "dengke"})
    assert r.status_code == 401


def test_logout_clears_session(client_and_oauth):
    client, _, _ = client_and_oauth
    _login(client)
    assert client.get("/me").status_code == 200
    client.post("/logout")
    assert client.get("/me").status_code == 401


def test_callback_preserves_contact_en_name_on_activation(client_and_oauth):
    client, _, contacts = client_and_oauth
    contacts.upsert_many([
        {
            "open_id": "ou_1",
            "union_id": "on_1",
            "name": "Ken",
            "en_name": "Ken Deng",
            "avatar_url": "old.png",
        }
    ])

    _login(client)

    c = contacts.get("ou_1")
    assert c is not None
    assert c.en_name == "Ken Deng"
    assert c.avatar_url == "http://a/1.png"


def test_auth_entry_redirects_logged_in_user_to_target(client_and_oauth):
    client, _, _ = client_and_oauth
    _login(client)

    r = client.get("/auth/entry?next=/t/general/hello", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/t/general/hello"


def test_auth_entry_redirects_feishu_client_to_preauth(client_and_oauth):
    client, _, _ = client_and_oauth

    r = client.get(
        "/auth/entry?next=/t/general/hello",
        headers={"user-agent": "Mozilla/5.0 Lark/7.0"},
        follow_redirects=False,
    )
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://example.com/preauth?state=")


def test_auth_entry_redirects_browser_to_login(client_and_oauth):
    client, _, _ = client_and_oauth

    r = client.get("/auth/entry?next=/t/general/hello", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?next=%2Ft%2Fgeneral%2Fhello"


# ---------------------------------------------------------------------------
# Branch tests: callback dispatch by binding / application state
# ---------------------------------------------------------------------------

def test_callback_bound_user_suspended_redirects_with_reason(db):
    """Bound user with status=suspended → 302 to login?reason=suspended, no cookie."""
    client, _, _, pivot_users, _, _, user = _make_app(db)

    pivot_users.update_status(
        user_id=user.id, status="suspended", note="test", changed_by="admin"
    )

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    assert "reason=suspended" in cb.headers["location"]
    assert "sid" not in cb.cookies


def test_callback_bound_user_deleted_redirects_with_reason(db):
    """Bound user with status=deleted → 302 to login?reason=deleted, no cookie."""
    client, _, _, pivot_users, _, _, user = _make_app(db)

    pivot_users.update_status(
        user_id=user.id, status="deleted", note="test", changed_by="admin"
    )

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    assert "reason=deleted" in cb.headers["location"]
    assert "sid" not in cb.cookies


def _seed_existing_admin(pivot_users: PivotUserRepo) -> None:
    """Seed a pre-existing admin so callback's bootstrap branch is skipped."""
    pivot_users.create(
        display_name="Boot Admin",
        pinyin="boot",
        email="boot@example.com",
        avatar_url="",
        role="admin",
    )


def test_callback_no_binding_creates_application(db):
    """No binding and no prior application → creates join_application + 302 reason=submitted."""
    # Build app WITHOUT the default pre-seeded binding
    oauth = FakeOAuth()
    sessions = SessionStore(db)
    pivot_users = PivotUserRepo(db)
    bindings_repo = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    contacts = ContactRepo(db)
    notifier = NoOpNotifier()

    _seed_existing_admin(pivot_users)

    app = FastAPI()
    app.include_router(
        build_router(
            oauth, sessions, pivot_users, bindings_repo, applications, notifier,
            contacts, SECRET,
        )
    )
    client = TestClient(app)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    assert "reason=submitted" in cb.headers["location"]
    assert "sid" not in cb.cookies

    # Application should be created
    pending = applications.list_pending()
    assert len(pending) == 1
    assert pending[0].provider == "feishu"
    assert pending[0].external_id == "ou_1"
    assert pending[0].status == "pending"


def test_callback_no_binding_pending_application_blocks(db):
    """No binding but pending application exists → 302 reason=pending_approval, no new application."""
    oauth = FakeOAuth()
    sessions = SessionStore(db)
    pivot_users = PivotUserRepo(db)
    bindings_repo = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    contacts = ContactRepo(db)
    notifier = NoOpNotifier()

    _seed_existing_admin(pivot_users)

    # Pre-seed a pending application for ou_1
    applications.create(
        provider="feishu", external_id="ou_1",
        external_union_id="on_1",
        raw_profile={"name": "Ken", "avatar_url": None, "union_id": "on_1"},
        suggested_match_user_id=None,
    )

    app = FastAPI()
    app.include_router(
        build_router(
            oauth, sessions, pivot_users, bindings_repo, applications, notifier,
            contacts, SECRET,
        )
    )
    client = TestClient(app)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    assert "reason=pending_approval" in cb.headers["location"]
    assert "sid" not in cb.cookies

    # No new application should have been created
    assert len(applications.list_pending()) == 1


def test_callback_no_binding_rejected_application_blocks(db):
    """No binding but rejected application exists → 302 reason=rejected."""
    oauth = FakeOAuth()
    sessions = SessionStore(db)
    pivot_users = PivotUserRepo(db)
    bindings_repo = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    contacts = ContactRepo(db)
    notifier = NoOpNotifier()

    _seed_existing_admin(pivot_users)

    # Create then reject an application for ou_1
    app_obj = applications.create(
        provider="feishu", external_id="ou_1",
        external_union_id="on_1",
        raw_profile={"name": "Ken", "avatar_url": None, "union_id": "on_1"},
        suggested_match_user_id=None,
    )
    applications.reject(application_id=app_obj.id, reviewed_by="admin", reason="no slot")

    app = FastAPI()
    app.include_router(
        build_router(
            oauth, sessions, pivot_users, bindings_repo, applications, notifier,
            contacts, SECRET,
        )
    )
    client = TestClient(app)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    assert "reason=rejected" in cb.headers["location"]
    assert "sid" not in cb.cookies


def test_callback_bootstraps_first_feishu_user_as_admin(db):
    """Fresh deploy with zero admins: feishu first-login is promoted to admin
    instantly, skipping the join_application path."""
    oauth = FakeOAuth()
    sessions = SessionStore(db)
    pivot_users = PivotUserRepo(db)
    bindings_repo = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    contacts = ContactRepo(db)
    notifier = NoOpNotifier()

    # Sanity: no users / admins yet
    assert pivot_users.count_active_admins() == 0

    app = FastAPI()
    app.include_router(
        build_router(
            oauth, sessions, pivot_users, bindings_repo, applications, notifier,
            contacts, SECRET,
        )
    )
    client = TestClient(app)

    login = client.get("/login", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    cb = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)

    assert cb.status_code == 302
    # Goes to next_url (default "/"), NOT to login?reason=submitted
    assert "reason=" not in cb.headers["location"]
    assert "sid" in cb.cookies

    # User should have been created as admin + bound to ou_1, no application created
    binding = bindings_repo.lookup(provider="feishu", external_id="ou_1")
    assert binding is not None
    user = pivot_users.get(binding.pivot_user_id)
    assert user is not None
    assert user.role == "admin"
    assert user.status == "active"
    assert user.pinyin is None  # filled later by ProfileSetup
    assert applications.list_pending() == []
