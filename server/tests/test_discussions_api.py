from __future__ import annotations

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.discussions import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.favorites import FavoriteRepo
from server.mentions import DisplayResolver
from server.notify import NoOpNotifier
from server.pivot_users import PivotUserRepo
from server.read_state import ReadStateRepo


def _resolver(db) -> DisplayResolver:
    return DisplayResolver(PivotUserRepo(db), ExternalBindingRepo(db))


class _WorkspaceStub:
    def __init__(self, discussions_dir, index_dir) -> None:
        self.discussions_dir = discussions_dir
        self.index_dir = index_dir

    @contextmanager
    def write_session(self, **_: object):
        self.discussions_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        yield


def _write_post(path, *, type_: str, author: str, title: str = "", body: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = f"type: {type_}\nauthor: {author}\nindex_state: indexed\n"
    if title:
        fm += f"title: {title}\n"
    path.write_text(f"---\n{fm}---\n{body}\n", encoding="utf-8")


def test_threads_route_resolves_author_display_via_pivot_user(db, users, tmp_path):
    """Author open_id in frontmatter is resolved to display_name via the
    pivot_user + external_binding(feishu) chain. Replaces the old contacts
    fallback path."""
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_contact_proposal_abc123.md",
        type_="proposal",
        author="ou_contact000000000000",
        title="Hello",
    )

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    pu = pivot_users.create(
        display_name="联系人A", pinyin="lianxirena",
        email=None, avatar_url="",
    )
    bindings.bind(
        pivot_user_id=pu.id, provider="feishu",
        external_id="ou_contact000000000000",
        external_union_id=None, raw_profile_json=None,
    )

    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            FavoriteRepo(db),
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/threads")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"][0]["author_display"] == "联系人A"


def test_create_thread_accepts_chinese_category(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)

    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    users.update_profile("ou_1", pinyin="ken")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            FavoriteRepo(db),
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.post(
        "/api/threads",
        json={"category": "技术讨论", "title": "中文分类测试", "body": "正文"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "技术讨论"
    assert (discussions / "技术讨论").is_dir()


def test_threads_route_marks_favorites_for_current_user(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_contact_proposal_abc123.md",
        type_="proposal",
        author="ou_1",
        title="Hello",
    )

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    favorites = FavoriteRepo(db)
    favorites.set("ou_1", "general/hello")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            favorites,
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/threads")
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["favorite"] is True


def test_toggle_thread_favorite(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_contact_proposal_abc123.md",
        type_="proposal",
        author="ou_1",
        title="Hello",
    )

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    favorites = FavoriteRepo(db)
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            favorites,
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    on = client.post("/api/threads/general/hello/favorite", json={"favorite": True})
    assert on.status_code == 200, on.text
    assert on.json()["favorite"] is True
    assert favorites.has("ou_1", "general/hello") is True

    off = client.post("/api/threads/general/hello/favorite", json={"favorite": False})
    assert off.status_code == 200, off.text
    assert off.json()["favorite"] is False
    assert favorites.has("ou_1", "general/hello") is False


def test_thread_detail_includes_favorite_flag(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_contact_proposal_abc123.md",
        type_="proposal",
        author="ou_1",
        title="Hello",
    )

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    favorites = FavoriteRepo(db)
    favorites.set("ou_1", "general/hello")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            favorites,
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/threads/general/hello")
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["favorite"] is True


def test_thread_detail_includes_author_avatar_url(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_contact_proposal_abc123.md",
        type_="proposal",
        author="ou_1",
        title="Hello",
    )

    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    users.upsert_from_feishu(
        open_id="ou_1",
        union_id=None,
        name="Ken",
        avatar_url="http://a/1.png",
    )
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")
    current_user = make_current_user(sessions, users, ApiTokenRepo(db))

    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            pivot_users,
            bindings,
            NoOpNotifier(),
            ReadStateRepo(db),
            FavoriteRepo(db),
            _resolver(db),
            current_user,
        )
    )
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/threads/general/hello")
    assert r.status_code == 200, r.text
    assert r.json()["posts"][0]["author_avatar_url"] == "http://a/1.png"
