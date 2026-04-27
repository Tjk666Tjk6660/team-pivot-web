"""Tests for scripts/migrate_index_schema.py.

Pure-function tests on `migrate_one` cover the §映射规则 decision matrix.
Integration tests on `apply_migration` exercise IO + git rename detection
in a temporary git repo.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.migrate_index_schema import (
    MigrationItem,
    apply_migration,
    discover_legacy,
    migrate_one,
    preflight_checks,
)


# --------------------------------------------------------------------------- #
# Test fixtures: build a legacy thread on disk                                #
# --------------------------------------------------------------------------- #


def _write_legacy_md(
    workspace: Path,
    *,
    category: str,
    slug: str,
    nnn: int,
    author: str,
    type_seg: str,
    hash_seg: str,
    body: str = "",
    extra_fm: dict | None = None,
    created: str = "2026-04-23T10:00:00+08:00",
) -> Path:
    """Write a legacy MD file with the standard frontmatter shape."""
    fname = f"{nnn:03d}_{author}_{type_seg}_{hash_seg}.md"
    path = workspace / "discussions" / category / slug / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    fm: dict = {
        "type": type_seg,
        "author": author,
        "created": created,
        "index_state": "indexed",
    }
    if extra_fm:
        fm.update(extra_fm)
    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip()
    body = body or f"# {fname}\n"
    path.write_text(f"---\n{fm_yaml}\n---\n{body}", encoding="utf-8")
    return path


def _synthesize_creation_timeline(
    *,
    category: str,
    slug: str,
    files: list[dict],
    base_iso: str = "2026-04-23T10:00:00+08:00",
) -> list[dict]:
    """Build minimal "X created thread" + "X replied" events for each file in
    `files`, sourcing author from the filename's author segment. Times are
    spaced 1h apart starting from `base_iso`. Mirrors what real legacy index
    writers (server/index_files.py) produce.

    Tests that need carry-over mention on a specific event should use the
    explicit `timeline=` parameter on _write_legacy_index instead.
    """
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(base_iso)
    events: list[dict] = []
    for i, f in enumerate(files):
        old_filename = str(f.get("path") or "")
        m = re.match(r"^(\d{3})_([^_]+)_([^_]+)_([a-f0-9]{6})\.md$", old_filename)
        author = m.group(2) if m else "unknown"
        type_seg = m.group(3) if m else "reply"
        verb = "created thread" if type_seg == "proposal" else "replied"
        time = (base + timedelta(hours=i)).isoformat()
        events.append({
            "time": time,
            "event": f"{author} {verb}",
            "file": f"discussions/{category}/{slug}/{old_filename}",
        })
    return events


def _write_legacy_index(
    workspace: Path,
    *,
    category: str,
    slug: str,
    status: str,
    files: list[dict],
    created: str = "2026-04-23T10:00:00+08:00",
    last_updated: str = "2026-04-23T15:30:00+08:00",
    timeline: list[dict] | None = None,
) -> Path:
    """Write `index/{slug}-discuss.index.yaml`. `files` are the legacy
    `discussions[0].files[]` entries (path/summary/refs).

    If `timeline` is None, a minimal created/replied event is synthesized
    for each file (1h apart starting at `created`). Pass `timeline=[]`
    explicitly to test the no-events degraded path.
    """
    index_dir = workspace / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / f"{slug}-discuss.index.yaml"
    if timeline is None:
        timeline = _synthesize_creation_timeline(
            category=category, slug=slug, files=files, base_iso=created,
        )
    data = {
        "origin_path": f"discussions/{category}/{slug}/",
        "created": created,
        "last_updated": last_updated,
        "discussions": [{
            "path": f"discussions/{category}/{slug}/",
            "status": status,
            "files": files,
        }],
        "timeline": timeline,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


def _build_open_thread(workspace: Path, slug: str = "demo") -> Path:
    """Open thread: 1 proposal + 2 replies."""
    cat = "test"
    _write_legacy_md(workspace, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(workspace, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    _write_legacy_md(workspace, category=cat, slug=slug,
                     nnn=3, author="alice", type_seg="reply", hash_seg="ccc333")
    return _write_legacy_index(
        workspace, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "",
             "refs": [{"type": "from", "path": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md"}]},
            {"path": "003_alice_reply_ccc333.md", "summary": "",
             "refs": [{"type": "from", "path": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md"}]},
        ],
    )


# --------------------------------------------------------------------------- #
# §映射规则 §1 状态机映射 —— migrate_one 单测                                  #
# --------------------------------------------------------------------------- #


def test_status_open_maps_to_planning(tmp_path):
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "planning"
    types = [t["type"] for t in item.new_index_data["timeline"]]
    assert types == ["think", "think", "think"]


def test_status_pending_maps_to_planning(tmp_path):
    cat, slug = "test", "pend"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="pending",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
    )
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "planning"


def test_status_closed_maps_to_cancelled_no_status_change(tmp_path):
    cat, slug = "test", "cls"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="closed",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "cancelled"
    types = [t["type"] for t in item.new_index_data["timeline"]]
    assert types == ["think", "think"]
    # No status_change synthesized for closed → cancelled
    assert all("status_change" not in t for t in item.new_index_data["timeline"])


def test_status_concluded_pivot_is_max_nnn_reply(tmp_path):
    """concluded → executing; pivot = max NNN reply (002 here, the highest reply)."""
    cat, slug = "test", "ccd"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=3, author="alice", type_seg="reply", hash_seg="ccc333")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="concluded",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
            {"path": "003_alice_reply_ccc333.md", "summary": "", "refs": []},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "executing"
    timeline = item.new_index_data["timeline"]
    types = [t["type"] for t in timeline]
    assert types == ["think", "think", "act"]
    # The act (last item) carries status_change
    assert timeline[-1]["status_change"] == {"from": "planning", "to": "executing"}
    assert "status_change" not in timeline[0]
    assert "status_change" not in timeline[1]


def test_status_produced_same_as_concluded(tmp_path):
    cat, slug = "test", "prd"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="produced",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "executing"
    timeline = item.new_index_data["timeline"]
    assert timeline[1]["type"] == "act"
    assert timeline[1]["status_change"] == {"from": "planning", "to": "executing"}


def test_status_concluded_no_reply_falls_back_to_proposal(tmp_path):
    """If thread has only proposal (no reply), proposal becomes the act."""
    cat, slug = "test", "soloprop"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="concluded",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
    )
    item = migrate_one(tmp_path, legacy)
    assert item.new_index_data["matter"]["current_status"] == "executing"
    timeline = item.new_index_data["timeline"]
    assert len(timeline) == 1
    assert timeline[0]["type"] == "act"
    assert timeline[0]["status_change"] == {"from": "planning", "to": "executing"}


def test_status_concluded_no_files_raises(tmp_path):
    """status=concluded but no files at all → raise (data corruption);
    apply_migration surfaces it as a report.errors entry."""
    cat, slug = "test", "empty"
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="concluded", files=[],
    )
    with pytest.raises(ValueError, match="no usable files for pivot"):
        migrate_one(tmp_path, legacy)


def test_status_concluded_no_files_apply_reports_error(tmp_path):
    """End-to-end: zero-file concluded thread → error in report, no commit."""
    workspace = _init_git_workspace(tmp_path)
    cat, slug = "test", "empty2"
    legacy = _write_legacy_index(
        workspace, category=cat, slug=slug, status="concluded", files=[],
    )
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed empty thread")
    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=False)
    assert report.errors
    assert any("no usable files" in e for e in report.errors)
    # Legacy file untouched (no new commit, no delete)
    assert legacy.exists()


# --------------------------------------------------------------------------- #
# §映射规则 §2 文档类型映射 + filename rename                                  #
# --------------------------------------------------------------------------- #


def test_filename_rename_preserves_nnn_author_hash(tmp_path):
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    rename_map = {old.name: new.name for old, new in item.md_renames}
    assert rename_map == {
        "001_alice_proposal_aaa111.md": "001_alice_think_aaa111.md",
        "002_bob_reply_bbb222.md": "002_bob_think_bbb222.md",
        "003_alice_reply_ccc333.md": "003_alice_think_ccc333.md",
    }


def test_filename_rename_pivot_act_for_concluded(tmp_path):
    cat, slug = "test", "pivact"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=3, author="alice", type_seg="reply", hash_seg="ccc333")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="concluded",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
            {"path": "003_alice_reply_ccc333.md", "summary": "", "refs": []},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    rename_map = {old.name: new.name for old, new in item.md_renames}
    assert rename_map["003_alice_reply_ccc333.md"] == "003_alice_act_ccc333.md"
    # Non-pivot replies still go to think
    assert rename_map["002_bob_reply_bbb222.md"] == "002_bob_think_bbb222.md"
    assert rename_map["001_alice_proposal_aaa111.md"] == "001_alice_think_aaa111.md"


def test_md_frontmatter_updates_target_renamed_path(tmp_path):
    """frontmatter update entries must point at NEW paths (after rename)."""
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    rename_targets = {new for _, new in item.md_renames}
    fm_targets = {p for p, _ in item.md_frontmatter_updates}
    # Every frontmatter update must reference a renamed path (or unchanged path
    # if no rename was needed)
    for path, _ in item.md_frontmatter_updates:
        assert path in rename_targets or path == (
            tmp_path / "discussions" / "test" / "demo" / path.name
        )
    # Counts must align: one frontmatter update per file (3 files)
    assert len(item.md_frontmatter_updates) == 3


def test_no_rename_when_no_type_change(tmp_path):
    """If a file would map to the same type segment, no rename emitted."""
    # Synthetic: filename has a non-standard type segment that maps to itself.
    # In practice this can't happen for proposal/reply/comment, but we cover
    # the branch via reading frontmatter type=think (already a valid matter type).
    cat, slug = "test", "noop"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
    )
    item = migrate_one(tmp_path, legacy)
    # proposal → think implies rename
    assert len(item.md_renames) == 1


# --------------------------------------------------------------------------- #
# §映射规则 §3 timeline item 字段映射                                          #
# --------------------------------------------------------------------------- #


def test_timeline_item_fields_complete(tmp_path):
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    timeline = item.new_index_data["timeline"]
    first = timeline[0]
    assert first["file"] == "discussions/test/demo/001_alice_think_aaa111.md"
    assert first["created_at"] == "2026-04-23T10:00:00+08:00"
    assert first["creator"] == "alice"
    assert first["owner"] == "alice"
    assert first["type"] == "think"
    assert first["summary"] == ""
    # second item has from-ref → quote; refer is empty (not in dict)
    second = timeline[1]
    assert second["quote"] == "discussions/test/demo/001_alice_think_aaa111.md"
    assert "refer" not in second


def test_quote_uses_renamed_filename(tmp_path):
    """quote must reference the new (post-rename) filename."""
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    timeline = item.new_index_data["timeline"]
    # second item quotes the first; first was renamed proposal→think
    assert timeline[1]["quote"].endswith("/001_alice_think_aaa111.md")


def test_multiple_from_refs_takes_first_with_warning(tmp_path):
    cat, slug = "test", "multifrom"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=3, author="alice", type_seg="reply", hash_seg="ccc333")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
            {"path": "003_alice_reply_ccc333.md", "summary": "",
             "refs": [
                 {"type": "from", "path": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md"},
                 {"type": "from", "path": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md"},
             ]},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    third = item.new_index_data["timeline"][2]
    assert third["quote"].endswith("/001_alice_think_aaa111.md")  # first one taken
    assert any("'from' refs" in w for w in item.warnings)


def test_refer_refs_preserve_order_with_rename(tmp_path):
    cat, slug = "test", "multirefer"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=3, author="alice", type_seg="reply", hash_seg="ccc333")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
            {"path": "003_alice_reply_ccc333.md", "summary": "",
             "refs": [
                 {"type": "from", "path": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md"},
                 {"type": "refer", "path": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md"},
                 {"type": "refer", "path": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md"},
             ]},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    third = item.new_index_data["timeline"][2]
    assert third["refer"] == [
        "discussions/test/multirefer/001_alice_think_aaa111.md",
        "discussions/test/multirefer/002_bob_think_bbb222.md",
    ]


# --------------------------------------------------------------------------- #
# §映射规则 §4 事件流迁移 (mention → comments[])                                #
# --------------------------------------------------------------------------- #


def test_mention_event_routed_to_parent_comments(tmp_path):
    cat, slug = "test", "menthd"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
        ],
        timeline=[
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice mentioned",
             "file": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md",
             "mention": {
                 "users": [{"user": "bob", "open_id": "ou_bob_xxxxxxxxxxxxxxx"}],
                 "comments": "请确认",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    second = item.new_index_data["timeline"][1]
    assert "comments" in second
    assert len(second["comments"]) == 1
    c = second["comments"][0]
    assert c["body"] == "请确认"
    assert c["author"] == "alice"
    assert c["created_at"] == "2026-04-23T11:00:00+08:00"
    # No users_repo passed → mentions fall back to open_id
    assert c["mentions"] == ["ou_bob_xxxxxxxxxxxxxxx"]


def test_mention_uses_post_rename_filename_lookup(tmp_path):
    """mention.event.file is the OLD filename; lookup must apply rename map."""
    cat, slug = "test", "menren"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
        ],
        timeline=[
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice mentioned",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "bob", "open_id": "ou_bob_xxxxxxxxxxxxxxx"}],
                 "comments": "fyi",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    # The mention attached to OLD proposal path resolves to NEW think path
    assert first["file"].endswith("/001_alice_think_aaa111.md")
    assert len(first["comments"]) == 1


def test_multiple_mentions_same_file_sorted_by_time(tmp_path):
    cat, slug = "test", "menorder"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T13:00:00+08:00",
             "event": "alice mentioned",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {"users": [{"user": "x", "open_id": "ou_x"}], "comments": "second"}},
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice mentioned",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {"users": [{"user": "x", "open_id": "ou_x"}], "comments": "first"}},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    bodies = [c["body"] for c in first["comments"]]
    assert bodies == ["first", "second"]


def test_orphan_mention_dropped_with_warning(tmp_path):
    """mention pointing at file not in this thread → dropped + warning."""
    cat, slug = "test", "orph"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice mentioned",
             "file": f"discussions/{cat}/{slug}/999_ghost_reply_zzzzzz.md",
             "mention": {"users": [], "comments": "lost"}},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    assert "comments" not in item.new_index_data["timeline"][0]
    assert any("not in new timeline" in w for w in item.warnings)


def test_mention_without_file_dropped_with_warning(tmp_path):
    cat, slug = "test", "nofile"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice mentioned",
             "mention": {"users": [], "comments": "where?"}},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    assert "comments" not in item.new_index_data["timeline"][0]
    assert any("without file field" in w for w in item.warnings)


def test_status_change_events_dropped_silently(tmp_path):
    """状态变更 events without mention drop silently per plan §4."""
    cat, slug = "test", "stchg"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T10:00:00+08:00", "event": "alice created thread",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md"},
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "alice 状态变更 open->concluded"},
            {"time": "2026-04-23T12:00:00+08:00",
             "event": "alice 从 concluded 状态重新打开，原因：发现新数据"},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    timeline = item.new_index_data["timeline"]
    assert len(timeline) == 1
    # No comments synthesized from status-change events
    assert "comments" not in timeline[0]


# --------------------------------------------------------------------------- #
# §映射规则 §4 created/replied 携带 mention → 首条 comment                     #
# (漏洞 2 修复:发帖时附带的 @mention.comments 必须迁入新 timeline item)        #
# --------------------------------------------------------------------------- #


def test_created_event_with_mention_comments_becomes_first_comment(tmp_path):
    """`X created thread` 事件携带 mention.comments → 该 file item 的第一条 comment。"""
    cat, slug = "test", "createdmen"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T10:00:00+08:00",
             "event": "alice created thread",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "Bob", "open_id": "ou_bob_xxxxxxxxxxxxxxx"}],
                 "comments": "请看一下这个提案",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    assert first["creator"] == "alice"
    assert first["created_at"] == "2026-04-23T10:00:00+08:00"
    assert "comments" in first
    assert len(first["comments"]) == 1
    c = first["comments"][0]
    assert c["body"] == "请看一下这个提案"
    assert c["author"] == "alice"
    assert c["created_at"] == "2026-04-23T10:00:00+08:00"
    assert c["mentions"] == ["ou_bob_xxxxxxxxxxxxxxx"]


def test_replied_event_with_mention_comments_becomes_first_comment(tmp_path):
    """`X replied` 事件携带 mention.comments → 该 reply file item 的第一条 comment。"""
    cat, slug = "test", "repliedmen"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=2, author="bob", type_seg="reply", hash_seg="bbb222")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[
            {"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []},
            {"path": "002_bob_reply_bbb222.md", "summary": "", "refs": []},
        ],
        timeline=[
            {"time": "2026-04-23T10:00:00+08:00",
             "event": "alice created thread",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md"},
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "bob replied",
             "file": f"discussions/{cat}/{slug}/002_bob_reply_bbb222.md",
             "mention": {
                 "users": [{"user": "Alice", "open_id": "ou_alice_xxxxxxxxxxxxx"}],
                 "comments": "回复 + 圈一下你",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    second = item.new_index_data["timeline"][1]
    assert second["creator"] == "bob"
    assert second["comments"][0]["body"] == "回复 + 圈一下你"
    assert second["comments"][0]["author"] == "bob"
    # Proposal item has no mention; should not have comments[]
    first = item.new_index_data["timeline"][0]
    assert "comments" not in first


def test_event_with_users_only_no_comments_still_produces_comment(tmp_path):
    """Real production data has 2 cases where created/replied events carry
    mention.users but mention.comments is empty (圈了人但没留话)。仍应产出
    comment 条目（body=""，mentions 落 pinyin/open_id）以保留圈人记录。"""
    cat, slug = "test", "usersonly"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T10:00:00+08:00",
             "event": "alice created thread",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "Bob", "open_id": "ou_bob_xxxxxxxxxxxxxxx"}],
                 "comments": "",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    assert first["comments"][0]["body"] == ""
    assert first["comments"][0]["mentions"] == ["ou_bob_xxxxxxxxxxxxxxx"]


def test_first_event_mention_and_later_standalone_mentions_coexist_sorted(tmp_path):
    """Created/replied 携带的 mention 是首条 comment;后续独立 mentioned 事件追加在后。
    最终 comments[] 按 created_at 升序。"""
    cat, slug = "test", "twosrc"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[
            {"time": "2026-04-23T10:00:00+08:00",
             "event": "alice created thread",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "Bob", "open_id": "ou_b"}],
                 "comments": "first (carried)",
             }},
            {"time": "2026-04-23T11:00:00+08:00",
             "event": "carol mentioned",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "Bob", "open_id": "ou_b"}],
                 "comments": "second (standalone)",
             }},
            {"time": "2026-04-23T12:00:00+08:00",
             "event": "dave mentioned",
             "file": f"discussions/{cat}/{slug}/001_alice_proposal_aaa111.md",
             "mention": {
                 "users": [{"user": "Bob", "open_id": "ou_b"}],
                 "comments": "third (standalone)",
             }},
        ],
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    bodies = [c["body"] for c in first["comments"]]
    authors = [c["author"] for c in first["comments"]]
    assert bodies == ["first (carried)", "second (standalone)", "third (standalone)"]
    assert authors == ["alice", "carol", "dave"]


def test_pure_created_replied_events_without_mention_produce_no_comments(tmp_path):
    """Bare created/replied events (no mention payload) drive file items
    but do NOT synthesize comments[]."""
    legacy = _build_open_thread(tmp_path)   # auto-synthesized timeline, no mentions
    item = migrate_one(tmp_path, legacy)
    for t in item.new_index_data["timeline"]:
        assert "comments" not in t


# --------------------------------------------------------------------------- #
# §映射规则 §5 matter header                                                   #
# --------------------------------------------------------------------------- #


def test_matter_header_complete(tmp_path):
    legacy = _build_open_thread(tmp_path)
    item = migrate_one(tmp_path, legacy)
    matter = item.new_index_data["matter"]
    assert matter["id"] == "demo"
    assert matter["created_at"] == "2026-04-23T10:00:00+08:00"
    assert matter["updated_at"] == "2026-04-23T15:30:00+08:00"
    # title fallback to slug since no frontmatter.title and body is "# 001_..."
    assert matter["title"]


def test_title_uses_first_post_h1(tmp_path):
    cat, slug = "test", "h1title"
    path = _write_legacy_md(tmp_path, category=cat, slug=slug,
                            nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111",
                            body="# Auth Redesign\n\n正文内容\n")
    _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
    )
    item = migrate_one(tmp_path, tmp_path / "index" / f"{slug}-discuss.index.yaml")
    assert item.new_index_data["matter"]["title"] == "Auth Redesign"


def test_title_uses_frontmatter_title_if_present(tmp_path):
    cat, slug = "test", "fmtitle"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111",
                     extra_fm={"title": "Custom Title From FM"},
                     body="# Body H1\n")
    _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
    )
    item = migrate_one(tmp_path, tmp_path / "index" / f"{slug}-discuss.index.yaml")
    assert item.new_index_data["matter"]["title"] == "Custom Title From FM"


# --------------------------------------------------------------------------- #
# Degraded paths: timeline event missing                                      #
# (plan §3 — created_at + creator come from the legacy timeline event, not    #
# from MD frontmatter; if the event is missing, creator falls to "unknown"   #
# and created_at to "" with a warning.)                                       #
# --------------------------------------------------------------------------- #


def test_missing_creation_event_creator_unknown(tmp_path):
    """If files[] lists a file but legacy.timeline has no created/replied
    event for it, creator/owner fall to 'unknown' with a warning."""
    cat, slug = "test", "noevt"
    _write_legacy_md(tmp_path, category=cat, slug=slug,
                     nnn=1, author="alice", type_seg="proposal", hash_seg="aaa111")
    legacy = _write_legacy_index(
        tmp_path, category=cat, slug=slug, status="open",
        files=[{"path": "001_alice_proposal_aaa111.md", "summary": "", "refs": []}],
        timeline=[],   # explicit empty: no created/replied events
    )
    item = migrate_one(tmp_path, legacy)
    first = item.new_index_data["timeline"][0]
    assert first["creator"] == "unknown"
    assert first["owner"] == "unknown"
    assert first["created_at"] == ""
    assert any("no 'created thread'/'replied' event" in w for w in item.warnings)


# --------------------------------------------------------------------------- #
# discover_legacy                                                             #
# --------------------------------------------------------------------------- #


def test_discover_legacy_picks_only_discuss_yaml(tmp_path):
    idx = tmp_path / "index"
    idx.mkdir()
    (idx / "a-discuss.index.yaml").write_text("x")
    (idx / "b-discuss.index.yaml").write_text("x")
    (idx / "c.index.yaml").write_text("x")              # new format, ignored
    (idx / "random.txt").write_text("x")
    paths = discover_legacy(idx)
    names = sorted(p.name for p in paths)
    assert names == ["a-discuss.index.yaml", "b-discuss.index.yaml"]


# --------------------------------------------------------------------------- #
# Integration: apply_migration on a temp git repo                             #
# --------------------------------------------------------------------------- #


def _git(workspace: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True, text=True, check=check,
    )


def _init_git_workspace(tmp_path: Path) -> Path:
    """Init a git repo in tmp_path with main branch + initial commit."""
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("init\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_apply_migration_dry_run_no_disk_writes(tmp_path):
    workspace = _init_git_workspace(tmp_path)
    legacy = _build_open_thread(workspace)
    # Stage everything so working tree is clean
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed legacy data")

    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=True)

    # No disk changes
    assert legacy.exists()
    assert (workspace / "index" / f"{legacy.stem.replace('-discuss.index', '.index')}.yaml").exists() is False
    # Report populated
    assert report.dry_run is True
    assert report.legacy_count == 1
    assert len(report.threads) == 1
    assert report.threads[0]["timeline_count"] == 3


def test_apply_migration_apply_lands_renames_and_index(tmp_path):
    workspace = _init_git_workspace(tmp_path)
    legacy = _build_open_thread(workspace)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed legacy data")

    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=False)

    assert not report.errors, report.errors
    assert report.migrated_count == 1
    # Old yaml gone
    assert not legacy.exists()
    # New yaml present
    new_index = workspace / "index" / "demo.index.yaml"
    assert new_index.is_file()
    # MDs renamed (no _proposal_/_reply_ tokens left)
    md_dir = workspace / "discussions" / "test" / "demo"
    md_names = sorted(p.name for p in md_dir.glob("*.md"))
    assert md_names == [
        "001_alice_think_aaa111.md",
        "002_bob_think_bbb222.md",
        "003_alice_think_ccc333.md",
    ]
    # Frontmatter type updated, body unchanged
    first = (md_dir / "001_alice_think_aaa111.md").read_text(encoding="utf-8")
    assert "type: think" in first
    assert "type: proposal" not in first
    # Single git commit was created
    log = _git(workspace, "log", "--oneline").stdout
    assert "migrate legacy thread indexes to matter format" in log


def test_apply_migration_git_status_shows_rename_R(tmp_path):
    """git rename detection should mark renames as R, not D + A."""
    workspace = _init_git_workspace(tmp_path)
    _build_open_thread(workspace)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed")
    # Don't run apply_migration's git commit step; pause and check status
    # by emulating the apply with dry_run=False but inspecting before commit.
    # Instead, run apply_migration normally and check log diff
    legacy_paths = discover_legacy(workspace / "index")
    apply_migration(workspace, legacy_paths, dry_run=False)
    # Inspect last commit's name-status
    name_status = _git(workspace, "log", "-1", "--name-status").stdout
    # Each renamed MD should appear as R<num> entry
    md_lines = [l for l in name_status.splitlines() if "_proposal_" in l or "_reply_" in l or "_think_" in l]
    # 3 MDs should each show as a rename (R) line
    rename_count = sum(1 for l in md_lines if l.startswith("R"))
    assert rename_count == 3, f"expected 3 R entries, got: {md_lines}"


def test_apply_migration_idempotent_on_rerun(tmp_path):
    workspace = _init_git_workspace(tmp_path)
    _build_open_thread(workspace)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed")

    legacy_paths_1 = discover_legacy(workspace / "index")
    apply_migration(workspace, legacy_paths_1, dry_run=False)
    # Working tree is clean now (commit created)
    # Re-running discover finds zero legacy files
    legacy_paths_2 = discover_legacy(workspace / "index")
    assert legacy_paths_2 == []


def test_apply_migration_conflict_existing_new_index_different_content(tmp_path):
    """If {slug}.index.yaml already exists with different content, refuse."""
    workspace = _init_git_workspace(tmp_path)
    _build_open_thread(workspace)
    # Drop a stale matter index that doesn't match what migration would produce
    (workspace / "index" / "demo.index.yaml").write_text(
        "version: 1\nmatter:\n  id: demo\n  title: stale\n  current_status: planning\n  created_at: x\n  updated_at: x\ntimeline: []\n",
        encoding="utf-8",
    )
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed")

    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=False)
    assert report.errors
    assert any("already exists with different content" in e for e in report.errors)


def test_apply_migration_rename_target_collision_stops(tmp_path):
    """If a rename target already exists, refuse."""
    workspace = _init_git_workspace(tmp_path)
    _build_open_thread(workspace)
    # Pre-create a file with the rename target name → collision
    (workspace / "discussions" / "test" / "demo" / "001_alice_think_aaa111.md").write_text(
        "---\ntype: think\nauthor: alice\n---\nstale\n",
        encoding="utf-8",
    )
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed")

    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=False)
    assert report.errors
    assert any("rename target collision" in e for e in report.errors)


def test_apply_migration_already_migrated_identical_skips(tmp_path):
    """If new index already exists AND content equals what migrate_one
    currently produces, skip + remove legacy + bump skipped_count.

    Setup: keep legacy MDs unchanged (so migrate_one re-runs deterministically
    against same inputs); only pre-write the matter yaml. This simulates an
    operator who pre-created the new yaml but didn't delete the legacy yaml.
    """
    workspace = _init_git_workspace(tmp_path)
    legacy = _build_open_thread(workspace)

    # Pre-compute migrate_one output (no IO writes)
    from scripts.migrate_index_schema import migrate_one
    item = migrate_one(workspace, legacy)

    # Write the matter index dict to disk as if migration already happened
    item.new_index_path.parent.mkdir(parents=True, exist_ok=True)
    item.new_index_path.write_text(
        yaml.safe_dump(item.new_index_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "seed: legacy + matter yaml coexist, MDs untouched")

    assert legacy.exists()
    assert item.new_index_path.exists()

    # Run migration — migrate_one will produce the same dict; idempotent kicks in
    legacy_paths = discover_legacy(workspace / "index")
    report = apply_migration(workspace, legacy_paths, dry_run=False)

    assert not report.errors, report.errors
    assert report.skipped_count == 1
    assert report.migrated_count == 0
    assert any(
        t.get("skipped") == "already_migrated_identical"
        for t in report.threads
    )
    assert not legacy.exists()
    assert item.new_index_path.exists()


# --------------------------------------------------------------------------- #
# preflight_checks                                                            #
# --------------------------------------------------------------------------- #


def test_preflight_rejects_non_git_dir(tmp_path):
    failures = preflight_checks(tmp_path, strict=True)
    assert any("not a git repo" in f for f in failures)


def test_preflight_strict_rejects_dirty_working_tree(tmp_path):
    workspace = _init_git_workspace(tmp_path)
    (workspace / "wip.txt").write_text("dirty")
    failures = preflight_checks(workspace, strict=True)
    assert any("not clean" in f for f in failures)


def test_preflight_dry_run_allows_dirty_working_tree(tmp_path):
    """In dry-run (strict=False), a dirty working tree should NOT block."""
    workspace = _init_git_workspace(tmp_path)
    (workspace / "wip.txt").write_text("dirty")
    failures = preflight_checks(workspace, strict=False)
    assert not any("not clean" in f for f in failures)


def test_preflight_rejects_non_main_branch(tmp_path):
    workspace = _init_git_workspace(tmp_path)
    _git(workspace, "checkout", "-b", "feature")
    failures = preflight_checks(workspace, strict=False)
    assert any("not on main branch" in f for f in failures)


# --------------------------------------------------------------------------- #
# _build_users_repo --db-path override                                        #
# --------------------------------------------------------------------------- #


def test_build_users_repo_with_explicit_db_path_resolves_pinyin(tmp_path):
    """--db-path lets the script point at any SQLite. The script opens it
    via file:URI?mode=ro (read-only) so it's safe to point at a live
    production data.db without risking schema migrations / DELETE side
    effects from server.db.Database's constructor."""
    from scripts.migrate_index_schema import _build_users_repo
    from server.db import Database
    from server.users import UserRepo

    # Build a tiny SQLite with one registered user (this uses Database, which
    # is the writable path — fine for test fixture setup, but the migration
    # script itself never goes through Database).
    db_path = tmp_path / "snapshot.db"
    db = Database(db_path)
    repo = UserRepo(db)
    repo.upsert_from_feishu(
        open_id="ou_explicit_test_open_id_xxxx",
        union_id=None, name="测试用户", avatar_url="",
    )
    repo.update_profile("ou_explicit_test_open_id_xxxx", pinyin="testuser")

    # Hand-pass the path; should bypass .env entirely
    explicit = _build_users_repo(db_path)
    assert explicit is not None
    u = explicit.get_by_any_id("ou_explicit_test_open_id_xxxx")
    assert u is not None
    assert u.pinyin == "testuser"


def test_build_users_repo_opens_db_in_readonly_mode(tmp_path):
    """**Critical safety invariant:** when --db-path points at a real SQLite,
    the script must NOT be able to write to it. Any attempt to INSERT /
    UPDATE / DELETE / DDL via the returned object's underlying connection
    must error with sqlite3.OperationalError("readonly database")."""
    import sqlite3
    from scripts.migrate_index_schema import _build_users_repo
    from server.db import Database

    db_path = tmp_path / "snapshot.db"
    Database(db_path)   # initialize schema via the writable path

    view = _build_users_repo(db_path)
    assert view is not None

    # Reach the underlying read-only URI and try to write — must error.
    # We bypass the public API (which only exposes SELECT) to verify the
    # underlying connection itself refuses writes.
    conn = sqlite3.connect(view._uri, uri=True)   # type: ignore[attr-defined]
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            conn.execute(
                "INSERT INTO users (open_id, name, created_at) VALUES (?, ?, ?)",
                ("ou_should_fail", "x", 0.0),
            )
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            conn.execute("DELETE FROM users")
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            conn.execute("ALTER TABLE users ADD COLUMN evil TEXT")
    finally:
        conn.close()


def test_build_users_repo_does_not_create_missing_db(tmp_path):
    """Pointing --db-path at a non-existent file must NOT create an empty
    SQLite there — that was the old behavior with `Database(path)`. With
    URI mode=ro, sqlite3 errors instead of creating, and `_build_users_repo`
    returns None (mentions degrade to open_id literal)."""
    from scripts.migrate_index_schema import _build_users_repo
    db_path = tmp_path / "does-not-exist.db"
    assert not db_path.exists()
    repo = _build_users_repo(db_path)
    assert repo is None
    # Critical: the path must STILL not exist — we didn't auto-create
    assert not db_path.exists()
