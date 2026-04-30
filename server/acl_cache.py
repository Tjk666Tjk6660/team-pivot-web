from __future__ import annotations

from pathlib import Path
from time import time
from typing import Any

import yaml

from server.db import Database
from server.visibility_scopes import CategoryVisibilityScope, VisibilityScope


def rebuild_acl_cache(db: Database, *, index_dir: Path, categories_dir: Path) -> None:
    category_rows = _read_categories(categories_dir)
    matter_rows = _read_matters(index_dir)
    now = time()
    with db.connect() as conn:
        conn.execute("DELETE FROM category_visibility_role_cache")
        conn.execute("DELETE FROM category_visibility_cache")
        conn.execute("DELETE FROM matter_visibility_role_cache")
        conn.execute("DELETE FROM matter_visibility_user_cache")
        conn.execute("DELETE FROM matter_visibility_cache")
        for category_id, scope in category_rows:
            conn.execute(
                "INSERT INTO category_visibility_cache"
                " (category_id, mode, updated_at) VALUES (?, ?, ?)",
                (category_id, scope.mode, now),
            )
            for role in scope.authorized_roles:
                conn.execute(
                    "INSERT INTO category_visibility_role_cache (category_id, role)"
                    " VALUES (?, ?)",
                    (category_id, role),
                )
        for row in matter_rows:
            scope: VisibilityScope = row["scope"]
            conn.execute(
                "INSERT INTO matter_visibility_cache"
                " (matter_id, category_id, mode, creator_id, owner_id, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["matter_id"],
                    row["category_id"],
                    scope.mode,
                    row.get("creator_id"),
                    row.get("owner_id"),
                    now,
                ),
            )
            for role in scope.roles:
                conn.execute(
                    "INSERT INTO matter_visibility_role_cache (matter_id, role)"
                    " VALUES (?, ?)",
                    (row["matter_id"], role),
                )
            for user_id in scope.user_ids:
                conn.execute(
                    "INSERT INTO matter_visibility_user_cache (matter_id, pivot_user_id)"
                    " VALUES (?, ?)",
                    (row["matter_id"], user_id),
                )


def _read_categories(categories_dir: Path) -> list[tuple[str, CategoryVisibilityScope]]:
    path = Path(categories_dir)
    if not path.is_dir():
        return []
    out: list[tuple[str, CategoryVisibilityScope]] = []
    for file in sorted(path.glob("*.yaml")):
        data = _load(file)
        category = data.get("category") if isinstance(data.get("category"), dict) else {}
        category_id = str(category.get("name") or file.stem)
        out.append((category_id, CategoryVisibilityScope.from_dict(category.get("visibility"))))
    return out


def _read_matters(index_dir: Path) -> list[dict[str, Any]]:
    path = Path(index_dir)
    if not path.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for file in sorted(path.glob("*.index.yaml")):
        if file.name.endswith("-discuss.index.yaml"):
            continue
        data = _load(file)
        matter = data.get("matter") if isinstance(data.get("matter"), dict) else {}
        matter_id = str(matter.get("id") or file.name[: -len(".index.yaml")])
        first = _first_timeline_item(data)
        out.append(
            {
                "matter_id": matter_id,
                "category_id": _category_from_file(first.get("file")) or "",
                "creator_id": first.get("creator"),
                "owner_id": first.get("owner") or matter.get("owner") or first.get("creator"),
                "scope": VisibilityScope.from_dict(matter.get("visibility")),
            }
        )
    return out


def _load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _first_timeline_item(data: dict[str, Any]) -> dict[str, Any]:
    timeline = data.get("timeline")
    if isinstance(timeline, list) and timeline and isinstance(timeline[0], dict):
        return timeline[0]
    return {}


def _category_from_file(value: object) -> str | None:
    if not value:
        return None
    parts = str(value).replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "discussions":
        return parts[1]
    return None
