from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from server.matter_index import matter_index_path
from server.visibility_scopes import CategoryVisibilityScope, VisibilityScope


def category_visibility_path(categories_dir: Path, category_id: str) -> Path:
    return Path(categories_dir) / f"{category_id}.yaml"


def read_category_visibility(
    categories_dir: Path, category_id: str
) -> CategoryVisibilityScope:
    path = category_visibility_path(categories_dir, category_id)
    if not path.is_file():
        return CategoryVisibilityScope()
    data = _read_yaml(path)
    category = data.get("category") if isinstance(data.get("category"), dict) else {}
    return CategoryVisibilityScope.from_dict(category.get("visibility"))


def write_category_visibility(
    categories_dir: Path, category_id: str, scope: CategoryVisibilityScope
) -> None:
    path = category_visibility_path(categories_dir, category_id)
    data = _read_yaml(path) if path.exists() else {}
    category = data.setdefault("category", {})
    category.setdefault("name", category_id)
    category["visibility"] = scope.to_dict()
    _write_yaml(path, data)


def read_matter_visibility(index_dir: Path, matter_id: str) -> VisibilityScope:
    path = matter_index_path(index_dir, matter_id)
    if not path.is_file():
        return VisibilityScope()
    data = _read_yaml(path)
    matter = data.get("matter") if isinstance(data.get("matter"), dict) else {}
    return VisibilityScope.from_dict(matter.get("visibility"))


def write_matter_visibility(
    index_dir: Path, matter_id: str, scope: VisibilityScope
) -> None:
    path = matter_index_path(index_dir, matter_id)
    data = _read_yaml(path)
    matter = data.setdefault("matter", {})
    matter.setdefault("id", matter_id)
    matter["visibility"] = scope.to_dict()
    _write_yaml(path, data)


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
