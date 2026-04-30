from __future__ import annotations

from server.db import Database
from server.permissions import PermissionService
from server.pivot_users import PivotUserRepo
from server.visibility_scopes import CategoryVisibilityScope, VisibilityScope
from server.visibility_store import write_category_visibility, write_matter_visibility
from server.acl_cache import rebuild_acl_cache


def _seed_user(repo: PivotUserRepo, user_id: str, roles: list[str]):
    return repo.create(
        id=user_id,
        display_name=user_id,
        pinyin=user_id,
        email=None,
        avatar_url="",
        role="member",
    ) if roles == ["member"] else repo.update_role(
        user_id=repo.create(
            id=user_id,
            display_name=user_id,
            pinyin=user_id,
            email=None,
            avatar_url="",
            role="member",
        ).id,
        roles=roles,
    )


def _write_index(index_dir, matter_id: str, category: str, creator="owner", owner="owner"):
    import yaml

    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{matter_id}.index.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "matter": {"id": matter_id, "title": matter_id, "current_status": "executing"},
                "timeline": [
                    {
                        "file": f"discussions/{category}/{matter_id}/001_a_think.md",
                        "creator": creator,
                        "owner": owner,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_restricted_matter_role_grants_read_when_any_role_matches(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    _seed_user(users, "u1", ["member", "技术部门"])
    _seed_user(users, "u2", ["member"])
    index_dir = tmp_path / "index"
    categories_dir = tmp_path / "categories"
    _write_index(index_dir, "m1", "Pivot")
    write_matter_visibility(
        index_dir,
        "m1",
        VisibilityScope(mode="restricted", roles=["技术部门"], user_ids=[]),
    )
    rebuild_acl_cache(db, index_dir=index_dir, categories_dir=categories_dir)

    service = PermissionService(db)

    assert service.can_read_matter("u1", "m1")
    assert not service.can_read_matter("u2", "m1")


def test_admin_does_not_get_global_business_read(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    _seed_user(users, "admin1", ["admin"])
    index_dir = tmp_path / "index"
    categories_dir = tmp_path / "categories"
    _write_index(index_dir, "m1", "Pivot")
    write_matter_visibility(
        index_dir,
        "m1",
        VisibilityScope(mode="restricted", roles=["技术部门"], user_ids=[]),
    )
    rebuild_acl_cache(db, index_dir=index_dir, categories_dir=categories_dir)

    assert not PermissionService(db).can_read_matter("admin1", "m1")


def test_category_scope_limits_matter_scope(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    _seed_user(users, "u1", ["member", "技术部门"])
    _seed_user(users, "u2", ["member", "行政部门"])
    index_dir = tmp_path / "index"
    categories_dir = tmp_path / "categories"
    _write_index(index_dir, "m1", "Pivot")
    write_category_visibility(
        categories_dir,
        "Pivot",
        CategoryVisibilityScope(mode="restricted", authorized_roles=["技术部门"]),
    )
    write_matter_visibility(
        index_dir,
        "m1",
        VisibilityScope(mode="public", roles=[], user_ids=[]),
    )
    rebuild_acl_cache(db, index_dir=index_dir, categories_dir=categories_dir)

    service = PermissionService(db)

    assert service.can_read_matter("u1", "m1")
    assert not service.can_read_matter("u2", "m1")
    assert not service.validate_matter_visibility_scope(
        "m1", VisibilityScope(mode="restricted", roles=["行政部门"], user_ids=[])
    ).ok


def test_creator_or_owner_can_update_visibility(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    _seed_user(users, "creator", ["member"])
    _seed_user(users, "owner", ["member"])
    _seed_user(users, "other", ["member"])
    index_dir = tmp_path / "index"
    categories_dir = tmp_path / "categories"
    _write_index(index_dir, "m1", "Pivot", creator="creator", owner="owner")
    rebuild_acl_cache(db, index_dir=index_dir, categories_dir=categories_dir)

    service = PermissionService(db)

    assert service.can_update_matter_visibility("creator", "m1")
    assert service.can_update_matter_visibility("owner", "m1")
    assert not service.can_update_matter_visibility("other", "m1")
