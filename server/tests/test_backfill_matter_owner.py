from __future__ import annotations

import yaml

from server.matter_index import create_matter_index, matter_index_path, read_matter_index
from server.scripts.backfill_matter_owner import backfill_matter_owner


def _initial(creator: str = "alice") -> dict:
    return {
        "file": "discussions/demo/001_alice_think_aaa.md",
        "creator": creator,
        "type": "think",
        "summary": "first thought",
    }


def test_backfill_sets_missing_owner_from_first_file_creator(tmp_path):
    path = matter_index_path(tmp_path, "demo")
    create_matter_index(
        path,
        matter_id="demo",
        title="Demo",
        initial_item=_initial("alice"),
        now_iso="2026-04-29T10:00:00+08:00",
    )
    data = read_matter_index(path)
    data["matter"].pop("owner", None)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    changed = backfill_matter_owner(tmp_path)

    assert changed == [path]
    data = read_matter_index(path)
    assert data["matter"]["owner"] == "alice"
    assert list(data["matter"]) == [
        "id",
        "title",
        "current_status",
        "owner",
        "created_at",
        "updated_at",
    ]


def test_backfill_is_idempotent_when_owner_exists(tmp_path):
    path = matter_index_path(tmp_path, "demo")
    create_matter_index(
        path,
        matter_id="demo",
        title="Demo",
        initial_item=_initial("alice"),
        now_iso="2026-04-29T10:00:00+08:00",
        matter_owner="bob",
    )
    before = path.read_text(encoding="utf-8")

    changed = backfill_matter_owner(tmp_path)

    assert changed == []
    assert path.read_text(encoding="utf-8") == before


def test_backfill_dry_run_does_not_write(tmp_path):
    path = matter_index_path(tmp_path, "demo")
    create_matter_index(
        path,
        matter_id="demo",
        title="Demo",
        initial_item=_initial("alice"),
        now_iso="2026-04-29T10:00:00+08:00",
    )
    data = read_matter_index(path)
    data["matter"].pop("owner", None)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    changed = backfill_matter_owner(tmp_path, dry_run=True)

    assert changed == [path]
    assert path.read_text(encoding="utf-8") == before


def test_backfill_skips_event_first_timeline_entry(tmp_path):
    path = matter_index_path(tmp_path, "demo")
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "matter": {
                    "id": "demo",
                    "title": "Demo",
                    "current_status": "planning",
                    "created_at": "2026-04-29T10:00:00+08:00",
                    "updated_at": "2026-04-29T10:00:00+08:00",
                },
                "timeline": [
                    {
                        "type": "owner_change",
                        "created_at": "2026-04-29T10:00:00+08:00",
                        "actor": "alice",
                        "from_owner": None,
                        "to_owner": "bob",
                        "reason": "handoff",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert backfill_matter_owner(tmp_path) == []
    assert "owner" not in read_matter_index(path)["matter"]
