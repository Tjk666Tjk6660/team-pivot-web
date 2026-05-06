from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.visibility_options import build_router
from server.db import Database
from server.pivot_users import PivotUser, PivotUserRepo
from server.roles import PivotRoleRepo
from server.visibility_scopes import CategoryVisibilityScope
from server.visibility_store import write_category_visibility


def _client(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    current = users.create(
        display_name="Current",
        pinyin="current",
        email="current@example.com",
        avatar_url="",
        role="member",
    )
    app = FastAPI()
    app.include_router(
        build_router(
            users,
            PivotRoleRepo(db),
            categories_dir=tmp_path / "categories",
            current_user=lambda: current,
        )
    )
    return TestClient(app), users, tmp_path / "categories"


def _make_user(
    users: PivotUserRepo,
    *,
    name: str,
    roles: list[str],
) -> PivotUser:
    user = users.create(
        display_name=name,
        pinyin=name.lower(),
        email=f"{name.lower()}@example.com",
        avatar_url="",
        role="member",
    )
    return users.update_role(user_id=user.id, roles=roles)


def test_visibility_options_excludes_admin_role_but_keeps_admin_users_selectable(tmp_path):
    client, users, _categories_dir = _client(tmp_path)
    _make_user(users, name="Tech", roles=["member", "tech"])
    _make_user(users, name="Admin", roles=["admin", "tech"])

    r = client.get("/api/visibility-options")

    assert r.status_code == 200
    body = r.json()
    assert {item["role"] for item in body["roles"]} == {"member", "tech"}
    assert {item["display_name"] for item in body["users"]} == {"Current", "Tech", "Admin"}
    tech_role = next(item for item in body["roles"] if item["role"] == "tech")
    assert [item["display_name"] for item in tech_role["users"]] == ["Tech", "Admin"]


def test_visibility_options_are_limited_by_restricted_category(tmp_path):
    client, users, categories_dir = _client(tmp_path)
    _make_user(users, name="Tech", roles=["member", "tech"])
    _make_user(users, name="Ops", roles=["member", "ops"])
    write_category_visibility(
        categories_dir,
        "Pivot",
        CategoryVisibilityScope(mode="restricted", authorized_roles=["tech"]),
    )

    r = client.get("/api/visibility-options?category=Pivot")

    assert r.status_code == 200
    body = r.json()
    assert [item["role"] for item in body["roles"]] == ["tech"]
    assert [item["display_name"] for item in body["users"]] == ["Tech"]
