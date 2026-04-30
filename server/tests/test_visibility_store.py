from __future__ import annotations

import yaml

from server.acl_cache import rebuild_acl_cache
from server.db import Database
from server.visibility_scopes import CategoryVisibilityScope, VisibilityScope
from server.visibility_store import (
    read_category_visibility,
    read_matter_visibility,
    write_category_visibility,
    write_matter_visibility,
)


def test_write_matter_visibility_preserves_existing_index_fields(tmp_path):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    path = index_dir / "m1.index.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "matter": {
                    "id": "m1",
                    "title": "Demo",
                    "current_status": "executing",
                },
                "timeline": [
                    {"file": "discussions/Pivot/m1/001_a_think.md", "creator": "u1"}
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    write_matter_visibility(
        index_dir,
        "m1",
        VisibilityScope(mode="restricted", roles=["技术部门"], user_ids=["u2"]),
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["matter"]["current_status"] == "executing"
    assert data["matter"]["visibility"] == {
        "mode": "restricted",
        "roles": ["技术部门"],
        "user_ids": ["u2"],
    }
    assert read_matter_visibility(index_dir, "m1").roles == ["技术部门"]


def test_write_category_visibility(tmp_path):
    categories_dir = tmp_path / "categories"

    write_category_visibility(
        categories_dir,
        "Pivot",
        CategoryVisibilityScope(mode="restricted", authorized_roles=["技术部门"]),
    )

    data = yaml.safe_load((categories_dir / "Pivot.yaml").read_text(encoding="utf-8"))
    assert data["category"]["visibility"] == {
        "mode": "restricted",
        "authorized_roles": ["技术部门"],
    }
    assert read_category_visibility(categories_dir, "Pivot").authorized_roles == ["技术部门"]


def test_rebuild_acl_cache_from_yaml(tmp_path):
    db = Database(tmp_path / "test.db")
    index_dir = tmp_path / "index"
    categories_dir = tmp_path / "categories"
    index_dir.mkdir()
    (index_dir / "m1.index.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "matter": {
                    "id": "m1",
                    "title": "Demo",
                    "current_status": "executing",
                    "visibility": {
                        "mode": "restricted",
                        "roles": ["技术部门"],
                        "user_ids": ["u2"],
                    },
                },
                "timeline": [
                    {"file": "discussions/Pivot/m1/001_a_think.md", "creator": "u1"}
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_category_visibility(
        categories_dir,
        "Pivot",
        CategoryVisibilityScope(mode="restricted", authorized_roles=["技术部门"]),
    )

    rebuild_acl_cache(db, index_dir=index_dir, categories_dir=categories_dir)

    with db.connect() as conn:
        matter = conn.execute(
            "SELECT * FROM matter_visibility_cache WHERE matter_id='m1'"
        ).fetchone()
        roles = conn.execute(
            "SELECT role FROM matter_visibility_role_cache WHERE matter_id='m1'"
        ).fetchall()
        users = conn.execute(
            "SELECT pivot_user_id FROM matter_visibility_user_cache WHERE matter_id='m1'"
        ).fetchall()
    assert matter["category_id"] == "Pivot"
    assert matter["mode"] == "restricted"
    assert [row["role"] for row in roles] == ["技术部门"]
    assert [row["pivot_user_id"] for row in users] == ["u2"]
