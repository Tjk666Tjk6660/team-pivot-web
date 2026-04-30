from __future__ import annotations

import yaml

from scripts.migrate_visibility import migrate_visibility
from server.db import Database


def test_migrate_visibility_dry_run_does_not_write(tmp_path):
    workspace = tmp_path / "workspace"
    index = workspace / "index"
    index.mkdir(parents=True)
    path = index / "m1.index.yaml"
    path.write_text("matter:\n  id: m1\n", encoding="utf-8")

    report = migrate_visibility(workspace, dry_run=True)

    assert report.matters_changed == 1
    assert "visibility" not in path.read_text(encoding="utf-8")


def test_migrate_visibility_writes_public_defaults_and_is_idempotent(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "categories").mkdir(parents=True)
    (workspace / "index").mkdir(parents=True)
    (workspace / "categories" / "Pivot.yaml").write_text(
        "category:\n  name: Pivot\n",
        encoding="utf-8",
    )
    (workspace / "index" / "m1.index.yaml").write_text(
        "matter:\n  id: m1\n  current_status: planning\n",
        encoding="utf-8",
    )

    first = migrate_visibility(workspace)
    second = migrate_visibility(workspace)

    assert first.categories_changed == 1
    assert first.matters_changed == 1
    assert first.backup_dir is not None
    assert second.categories_changed == 0
    assert second.matters_changed == 0
    category = yaml.safe_load((workspace / "categories" / "Pivot.yaml").read_text(encoding="utf-8"))
    matter = yaml.safe_load((workspace / "index" / "m1.index.yaml").read_text(encoding="utf-8"))
    assert category["category"]["visibility"] == {
        "mode": "public",
        "authorized_roles": [],
    }
    assert matter["matter"]["visibility"] == {
        "mode": "public",
        "roles": [],
        "user_ids": [],
    }


def test_migrate_visibility_preserves_restricted_and_rebuilds_cache(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "categories").mkdir(parents=True)
    (workspace / "index").mkdir(parents=True)
    (workspace / "categories" / "Pivot.yaml").write_text(
        "category:\n"
        "  name: Pivot\n"
        "  visibility:\n"
        "    mode: restricted\n"
        "    authorized_roles:\n"
        "      - tech\n",
        encoding="utf-8",
    )
    (workspace / "index" / "m1.index.yaml").write_text(
        "matter:\n"
        "  id: m1\n"
        "  visibility:\n"
        "    mode: restricted\n"
        "    roles:\n"
        "      - tech\n"
        "    user_ids: []\n"
        "timeline:\n"
        "  - file: discussions/Pivot/m1/001.md\n"
        "    creator: alice\n"
        "    owner: alice\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "test.db"
    Database(db_path)

    report = migrate_visibility(workspace, db_path=db_path)

    assert report.categories_changed == 0
    assert report.matters_changed == 0
    with Database(db_path).connect() as conn:
        role = conn.execute(
            "SELECT role FROM matter_visibility_role_cache WHERE matter_id='m1'"
        ).fetchone()
    assert role["role"] == "tech"
