from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from server.acl_cache import rebuild_acl_cache
from server.db import Database


@dataclass(frozen=True)
class MigrationReport:
    categories_changed: int
    matters_changed: int
    backup_dir: Path | None


def migrate_visibility(
    workspace: Path,
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    backup: bool = True,
) -> MigrationReport:
    root = Path(workspace)
    categories_dir = root / "categories"
    index_dir = root / "index"
    category_paths = sorted(categories_dir.glob("*.yaml")) if categories_dir.is_dir() else []
    matter_paths = [
        p for p in sorted(index_dir.glob("*.index.yaml"))
        if not p.name.endswith("-discuss.index.yaml")
    ] if index_dir.is_dir() else []

    categories_to_write = [_with_category_visibility(p) for p in category_paths]
    matters_to_write = [_with_matter_visibility(p) for p in matter_paths]
    categories_changed = sum(1 for item in categories_to_write if item is not None)
    matters_changed = sum(1 for item in matters_to_write if item is not None)

    backup_dir: Path | None = None
    if not dry_run and backup and (categories_changed or matters_changed):
        backup_dir = root / ".visibility-migration-backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        for folder_name in ("categories", "index"):
            src = root / folder_name
            if src.exists():
                shutil.copytree(src, backup_dir / folder_name)

    if not dry_run:
        for item in categories_to_write:
            if item is not None:
                _write_yaml(item[0], item[1])
        for item in matters_to_write:
            if item is not None:
                _write_yaml(item[0], item[1])
        if db_path is not None:
            rebuild_acl_cache(
                Database(db_path),
                index_dir=index_dir,
                categories_dir=categories_dir,
            )

    return MigrationReport(categories_changed, matters_changed, backup_dir)


def _with_category_visibility(path: Path) -> tuple[Path, dict] | None:
    data = _read_yaml(path)
    category = data.setdefault("category", {})
    if isinstance(category.get("visibility"), dict):
        return None
    category.setdefault("name", path.stem)
    category["visibility"] = {"mode": "public", "authorized_roles": []}
    return path, data


def _with_matter_visibility(path: Path) -> tuple[Path, dict] | None:
    data = _read_yaml(path)
    matter = data.setdefault("matter", {})
    if isinstance(matter.get("visibility"), dict):
        return None
    matter.setdefault("id", path.name.removesuffix(".index.yaml"))
    matter["visibility"] = {"mode": "public", "roles": [], "user_ids": []}
    return path, data


def _read_yaml(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    report = migrate_visibility(
        args.workspace,
        db_path=args.db,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )
    print(
        f"categories={report.categories_changed} matters={report.matters_changed} "
        f"dry_run={args.dry_run} backup={report.backup_dir or ''}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
