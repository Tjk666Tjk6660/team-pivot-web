from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.discussions import build_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.favorites import FavoriteRepo
from server.mentions import DisplayResolver
from server.notify import NoOpNotifier
from server.pivot_users import PivotUserRepo
from server.read_state import ReadStateRepo

from .test_discussions_api import _WorkspaceStub, _write_post


def _write_index(index_dir, slug: str, last_updated: str) -> None:
    # 用显式引号防止 PyYAML 把 ISO8601 字符串隐式转成 datetime 对象
    # （生产代码路径用 yaml.safe_dump，默认会给这种字符串加引号）
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{slug}-discuss.index.yaml").write_text(
        f"origin_path: discussions/x/{slug}/\n"
        f"created: \"{last_updated}\"\n"
        f"last_updated: \"{last_updated}\"\n"
        f"discussions:\n"
        f"  - path: discussions/x/{slug}/\n"
        f"    status: open\n"
        f"    files: []\n",
        encoding="utf-8",
    )


def _build_app(db, users, contacts, discussions, index_dir):
    current_user = make_current_user(SessionStore(db), users, ApiTokenRepo(db))
    resolver = DisplayResolver(PivotUserRepo(db), ExternalBindingRepo(db), contacts)
    app = FastAPI()
    app.include_router(
        build_router(
            _WorkspaceStub(discussions, index_dir),
            users,
            contacts,
            NoOpNotifier(),
            ReadStateRepo(db),
            FavoriteRepo(db),
            resolver,
            current_user,
        )
    )
    return app


def test_categories_ok_with_cookie_session(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_ken_proposal_aaaaaa.md",
        type_="proposal", author="ou_1", title="Hello",
    )
    _write_post(
        discussions / "general" / "hello" / "002_ken_reply_bbbbbb.md",
        type_="reply", author="ou_1",
    )
    _write_post(
        discussions / "engineering" / "refactor" / "001_ken_proposal_cccccc.md",
        type_="proposal", author="ou_1", title="Refactor",
    )

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    body = r.json()
    names = {it["name"] for it in body["items"]}
    assert names == {"general", "engineering"}
    general = next(it for it in body["items"] if it["name"] == "general")
    assert general["post_count"] == 2
    engineering = next(it for it in body["items"] if it["name"] == "engineering")
    assert engineering["post_count"] == 1


def test_categories_ok_with_bearer_pat(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_ken_proposal_aaaaaa.md",
        type_="proposal", author="ou_1", title="Hello",
    )

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    token_repo = ApiTokenRepo(db)
    plaintext, _ = token_repo.create(user_open_id="ou_1", name="test", ttl_days=30)

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)

    r = client.get(
        "/api/categories",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [it["name"] for it in body["items"]] == ["general"]


def test_categories_empty_workspace(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    discussions.mkdir(parents=True, exist_ok=True)
    index_dir = tmp_path / "index"

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}


def test_categories_missing_discussions_dir_returns_empty(db, users, tmp_path):
    # 根目录不存在时 list_threads 返回 []，同样应返回 200 + 空列表
    discussions = tmp_path / "discussions"  # not created
    index_dir = tmp_path / "index"

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}


def test_categories_invalid_pat_returns_401(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    discussions.mkdir(parents=True, exist_ok=True)
    index_dir = tmp_path / "index"
    contacts = ContactRepo(db)

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)

    r = client.get(
        "/api/categories",
        headers={"Authorization": "Bearer pvt_definitely_not_a_real_token"},
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_token"}


def test_categories_post_count_aggregates_across_threads(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    # category A: 2 个 thread，各 3 / 5 个 post
    for i in range(3):
        _write_post(
            discussions / "A" / "t1" / f"{i+1:03d}_ken_{'proposal' if i==0 else 'reply'}_{i:06x}.md",
            type_="proposal" if i == 0 else "reply", author="ou_1",
            title="T1" if i == 0 else "",
        )
    for i in range(5):
        _write_post(
            discussions / "A" / "t2" / f"{i+1:03d}_ken_{'proposal' if i==0 else 'reply'}_{i+10:06x}.md",
            type_="proposal" if i == 0 else "reply", author="ou_1",
            title="T2" if i == 0 else "",
        )
    # category B: 1 个 thread，2 个 post
    for i in range(2):
        _write_post(
            discussions / "B" / "t3" / f"{i+1:03d}_ken_{'proposal' if i==0 else 'reply'}_{i+20:06x}.md",
            type_="proposal" if i == 0 else "reply", author="ou_1",
            title="T3" if i == 0 else "",
        )

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    items = {it["name"]: it for it in r.json()["items"]}
    assert items["A"]["post_count"] == 8
    assert items["B"]["post_count"] == 2


def test_categories_last_updated_is_max_of_threads(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "A" / "older" / "001_ken_proposal_aaaaaa.md",
        type_="proposal", author="ou_1", title="Older",
    )
    _write_post(
        discussions / "A" / "newer" / "001_ken_proposal_bbbbbb.md",
        type_="proposal", author="ou_1", title="Newer",
    )
    _write_index(index_dir, "older", "2026-01-01T00:00:00+00:00")
    _write_index(index_dir, "newer", "2026-04-20T12:00:00+00:00")

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    a = next(it for it in r.json()["items"] if it["name"] == "A")
    assert a["last_updated"] == "2026-04-20T12:00:00+00:00"


def test_categories_sorted_by_last_updated_desc(db, users, tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "cat_old" / "slug_old" / "001_ken_proposal_aaaaaa.md",
        type_="proposal", author="ou_1", title="Old",
    )
    _write_post(
        discussions / "cat_mid" / "slug_mid" / "001_ken_proposal_bbbbbb.md",
        type_="proposal", author="ou_1", title="Mid",
    )
    _write_post(
        discussions / "cat_new" / "slug_new" / "001_ken_proposal_cccccc.md",
        type_="proposal", author="ou_1", title="New",
    )
    _write_index(index_dir, "slug_old", "2026-01-01T00:00:00+00:00")
    _write_index(index_dir, "slug_mid", "2026-02-01T00:00:00+00:00")
    _write_index(index_dir, "slug_new", "2026-04-20T00:00:00+00:00")

    contacts = ContactRepo(db)
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="Ken", avatar_url="")
    sessions = SessionStore(db)
    sid = sessions.create("ou_1")

    app = _build_app(db, users, contacts, discussions, index_dir)
    client = TestClient(app)
    client.cookies.set("sid", sid)

    r = client.get("/api/categories")
    assert r.status_code == 200, r.text
    names = [it["name"] for it in r.json()["items"]]
    assert names == ["cat_new", "cat_mid", "cat_old"]
