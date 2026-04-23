from __future__ import annotations

import pytest
import yaml

from server.matter_index import (
    ValidationError,
    append_comment,
    append_file_item,
    create_matter_index,
    matter_index_path,
    read_matter_index,
    snapshot,
    view,
)


def _initial_think(creator: str = "dengke", file_: str = "001_dengke_think_aaa.md") -> dict:
    return {
        "file": f"discussions/auth-redesign/{file_}",
        "creator": creator,
        "type": "think",
        "summary": "初步思考登录链路",
    }


def _bootstrap(tmp_path):
    path = matter_index_path(tmp_path / "index", "auth-redesign")
    create_matter_index(
        path,
        matter_id="auth-redesign",
        title="Auth Redesign",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
    )
    return path


# ---------- create ----------


def test_create_matter_index_writes_expected_header(tmp_path):
    path = _bootstrap(tmp_path)
    data = read_matter_index(path)
    assert data["version"] == 1
    assert data["matter"] == {
        "id": "auth-redesign",
        "title": "Auth Redesign",
        "current_status": "planning",
        "created_at": "2026-04-23T10:00:00+08:00",
        "updated_at": "2026-04-23T10:00:00+08:00",
    }
    assert len(data["timeline"]) == 1
    first = data["timeline"][0]
    assert first["type"] == "think"
    assert first["creator"] == "dengke"
    assert first["owner"] == "dengke"  # defaulted from creator


def test_create_matter_index_existing_file_raises(tmp_path):
    path = _bootstrap(tmp_path)
    with pytest.raises(FileExistsError):
        create_matter_index(
            path,
            matter_id="auth-redesign",
            title="x",
            initial_item=_initial_think(),
            now_iso="2026-04-23T11:00:00+08:00",
        )


def test_create_rejects_type_not_allowed_in_planning(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    bad = {
        "file": "discussions/m/001_u_result_a.md",
        "creator": "u",
        "type": "result",
        "outcome": "finished",
        "summary": "x",
        "status_change": {"from": "planning", "to": "finished"},
    }
    with pytest.raises(ValidationError) as exc:
        create_matter_index(
            path, matter_id="m", title="m", initial_item=bad,
            now_iso="2026-04-23T10:00:00+08:00",
        )
    assert exc.value.result.code == "type_not_allowed"


def test_create_first_file_can_trigger_planning_to_executing(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    item = {
        "file": "discussions/m/001_u_act_a.md",
        "creator": "u",
        "type": "act",
        "summary": "直接开始做",
        "status_change": {"from": "planning", "to": "executing"},
    }
    create_matter_index(
        path, matter_id="m", title="m", initial_item=item,
        now_iso="2026-04-23T10:00:00+08:00",
    )
    data = read_matter_index(path)
    assert data["matter"]["current_status"] == "executing"


# ---------- append ----------


def test_append_file_item_updates_timeline_and_updated_at(tmp_path):
    path = _bootstrap(tmp_path)
    append_file_item(
        path,
        item={
            "file": "discussions/auth-redesign/002_liuyu_think_bbb.md",
            "creator": "liuyu",
            "type": "think",
            "summary": "接着想",
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    data = read_matter_index(path)
    assert len(data["timeline"]) == 2
    assert data["matter"]["updated_at"] == "2026-04-23T11:00:00+08:00"
    assert data["matter"]["created_at"] == "2026-04-23T10:00:00+08:00"


def test_append_triggers_status_change(tmp_path):
    path = _bootstrap(tmp_path)
    append_file_item(
        path,
        item={
            "file": "discussions/auth-redesign/002_liuyu_act_bbb.md",
            "creator": "liuyu",
            "type": "act",
            "summary": "开始行动",
            "status_change": {"from": "planning", "to": "executing"},
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    data = read_matter_index(path)
    assert data["matter"]["current_status"] == "executing"


def test_append_validator_blocks_invalid(tmp_path):
    path = _bootstrap(tmp_path)
    with pytest.raises(ValidationError) as exc:
        append_file_item(
            path,
            item={
                "file": "x.md",
                "creator": "u",
                "type": "insight",  # not allowed in planning
                "summary": "",
            },
            now_iso="2026-04-23T11:00:00+08:00",
        )
    assert exc.value.result.code == "type_not_allowed"


def test_append_missing_index_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        append_file_item(
            tmp_path / "nope.yaml",
            item=_initial_think(),
            now_iso="t",
        )


def test_full_lifecycle(tmp_path):
    path = _bootstrap(tmp_path)
    # planning -> executing via act
    append_file_item(path, item={
        "file": "discussions/auth-redesign/002_u_act_a.md",
        "creator": "u", "type": "act", "summary": "act1",
        "status_change": {"from": "planning", "to": "executing"},
    }, now_iso="2026-04-23T11:00:00+08:00")
    # executing -> finished via result
    append_file_item(path, item={
        "file": "discussions/auth-redesign/003_u_result_a.md",
        "creator": "u", "type": "result", "summary": "done",
        "outcome": "finished",
        "status_change": {"from": "executing", "to": "finished"},
    }, now_iso="2026-04-23T12:00:00+08:00")
    # finished -> reviewed via insight
    append_file_item(path, item={
        "file": "discussions/auth-redesign/004_u_insight_a.md",
        "creator": "u", "type": "insight", "summary": "lesson",
        "status_change": {"from": "finished", "to": "reviewed"},
    }, now_iso="2026-04-23T13:00:00+08:00")
    data = read_matter_index(path)
    assert data["matter"]["current_status"] == "reviewed"
    assert len(data["timeline"]) == 4


def test_reviewed_rejects_any_new_file(tmp_path):
    path = _bootstrap(tmp_path)
    # force into reviewed quickly for the test
    append_file_item(path, item={
        "file": "discussions/x/002_u_act.md", "creator": "u", "type": "act",
        "summary": "", "status_change": {"from": "planning", "to": "executing"},
    }, now_iso="2026-04-23T11:00:00+08:00")
    append_file_item(path, item={
        "file": "discussions/x/003_u_result.md", "creator": "u", "type": "result",
        "summary": "", "outcome": "finished",
        "status_change": {"from": "executing", "to": "finished"},
    }, now_iso="2026-04-23T12:00:00+08:00")
    append_file_item(path, item={
        "file": "discussions/x/004_u_insight.md", "creator": "u", "type": "insight",
        "summary": "",
        "status_change": {"from": "finished", "to": "reviewed"},
    }, now_iso="2026-04-23T13:00:00+08:00")
    # strict deny on reviewed
    with pytest.raises(ValidationError) as exc:
        append_file_item(path, item={
            "file": "discussions/x/005_u_insight.md", "creator": "u",
            "type": "insight", "summary": "another",
        }, now_iso="2026-04-23T14:00:00+08:00")
    assert exc.value.result.code == "type_not_allowed"


# ---------- comments ----------


def test_append_comment_on_existing_file(tmp_path):
    path = _bootstrap(tmp_path)
    target = "discussions/auth-redesign/001_dengke_think_aaa.md"
    append_comment(
        path,
        target_file=target,
        comment={"body": "同意", "mentions": ["liuyu"]},
        now_iso="2026-04-23T10:05:00+08:00",
    )
    data = read_matter_index(path)
    comments = data["timeline"][0]["comments"]
    assert len(comments) == 1
    assert comments[0]["body"] == "同意"
    assert comments[0]["mentions"] == ["liuyu"]
    assert comments[0]["created_at"] == "2026-04-23T10:05:00+08:00"
    # matter.updated_at unchanged — comments don't bump progress
    assert data["matter"]["updated_at"] == "2026-04-23T10:00:00+08:00"


def test_append_comment_target_not_found(tmp_path):
    path = _bootstrap(tmp_path)
    with pytest.raises(ValueError):
        append_comment(
            path,
            target_file="does/not/exist.md",
            comment={"body": "x"},
            now_iso="2026-04-23T10:05:00+08:00",
        )


# ---------- atomic write + roundtrip ----------


def test_write_is_atomic_no_tmp_left_on_success(tmp_path):
    path = _bootstrap(tmp_path)
    # No .tmp file should remain
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert path.is_file()


def test_roundtrip_byte_identical(tmp_path):
    path = _bootstrap(tmp_path)
    append_file_item(path, item={
        "file": "discussions/x/002_u_act.md",
        "creator": "u", "type": "act", "summary": "",
    }, now_iso="2026-04-23T11:00:00+08:00")
    original = path.read_bytes()
    # Read + re-write the exact same data should produce the same bytes
    data = read_matter_index(path)
    # simulate a no-op re-dump: load -> write back
    import os as _os
    tmp = path.with_suffix(path.suffix + ".tmp2")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    _os.replace(tmp, path)
    assert path.read_bytes() == original


def test_read_missing_file_returns_none(tmp_path):
    assert read_matter_index(tmp_path / "nope.yaml") is None


def test_read_malformed_yaml_returns_none(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(":::\n:\n--", encoding="utf-8")
    assert read_matter_index(p) is None


def test_snapshot_is_deep_copy(tmp_path):
    path = _bootstrap(tmp_path)
    snap = snapshot(path)
    snap["matter"]["current_status"] = "tampered"
    # Re-read: on-disk should be untouched
    data = read_matter_index(path)
    assert data["matter"]["current_status"] == "planning"


def test_view_returns_structured_matter(tmp_path):
    path = _bootstrap(tmp_path)
    v = view(path)
    assert v is not None
    assert v.matter.id == "auth-redesign"
    assert v.matter.current_status == "planning"
    assert len(v.timeline) == 1


def test_view_missing_returns_none(tmp_path):
    assert view(tmp_path / "nope.yaml") is None


# ---------- key order canonicalization ----------


def test_timeline_item_key_order_matches_example(tmp_path):
    path = _bootstrap(tmp_path)
    # Caller presents fields in arbitrary order
    append_file_item(path, item={
        "summary": "s",
        "type": "verify",
        "creator": "u",
        "verifications": [{"target": "001_dengke_think_aaa.md", "judgement": "passed", "comment": "ok"}],
        "file": "discussions/auth-redesign/002_u_verify.md",
        "quote": "discussions/auth-redesign/001_dengke_think_aaa.md",
    }, now_iso="2026-04-23T11:00:00+08:00")
    raw = path.read_text(encoding="utf-8")
    # The verify item should have file first, then created_at, creator, owner, type, summary, quote, verifications
    verify_block = raw.split("- file: discussions/auth-redesign/002_u_verify.md", 1)[1]
    # Assert the first six keys appear in the canonical order
    idx_created = verify_block.find("created_at:")
    idx_creator = verify_block.find("creator:")
    idx_owner = verify_block.find("owner:")
    idx_type = verify_block.find("type:")
    idx_summary = verify_block.find("summary:")
    idx_quote = verify_block.find("quote:")
    idx_verif = verify_block.find("verifications:")
    assert 0 < idx_created < idx_creator < idx_owner < idx_type < idx_summary < idx_quote < idx_verif
