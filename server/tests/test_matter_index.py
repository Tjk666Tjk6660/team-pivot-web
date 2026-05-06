from __future__ import annotations

import pytest
import yaml

from server.matter_index import (
    ValidationError,
    append_comment,
    append_file_item,
    apply_owner_change,
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


# ---------- mentions (writer always emits the new shape) ----------


def test_append_mention_on_existing_file_writes_new_shape(tmp_path):
    """Writer accepts a comment dict that uses the legacy inner key
    ``mentions`` and persists it as the new ``targets`` shape under the
    new outer ``mentions`` field."""
    path = _bootstrap(tmp_path)
    target = "discussions/auth-redesign/001_dengke_think_aaa.md"
    append_comment(
        path,
        target_file=target,
        comment={"body": "同意", "mentions": ["liuyu"]},
        now_iso="2026-04-23T10:05:00+08:00",
    )
    data = read_matter_index(path)
    mentions = data["timeline"][0]["mentions"]
    assert len(mentions) == 1
    assert mentions[0]["body"] == "同意"
    assert mentions[0]["targets"] == ["liuyu"]
    assert mentions[0]["created_at"] == "2026-04-23T10:05:00+08:00"
    # matter.updated_at unchanged — mentions don't bump progress
    assert data["matter"]["updated_at"] == "2026-04-23T10:00:00+08:00"
    # On disk should be the new key, not the legacy `comments`.
    raw = path.read_text(encoding="utf-8")
    assert "comments:" not in raw
    assert "mentions:" in raw
    assert "targets:" in raw


def test_append_mention_accepts_new_shape_input(tmp_path):
    """Writer also accepts a comment dict already in the new shape
    ({body, targets}) — no double rename."""
    path = _bootstrap(tmp_path)
    target = "discussions/auth-redesign/001_dengke_think_aaa.md"
    append_comment(
        path,
        target_file=target,
        comment={"body": "ok", "targets": ["liuyu"]},
        now_iso="2026-04-23T10:05:00+08:00",
    )
    data = read_matter_index(path)
    mentions = data["timeline"][0]["mentions"]
    assert mentions[0]["targets"] == ["liuyu"]


def test_append_mention_target_not_found(tmp_path):
    path = _bootstrap(tmp_path)
    with pytest.raises(ValueError):
        append_comment(
            path,
            target_file="does/not/exist.md",
            comment={"body": "x"},
            now_iso="2026-04-23T10:05:00+08:00",
        )


# ---------- reader compatibility: legacy YAML normalisation ----------


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_reader_normalises_legacy_comments_to_mentions(tmp_path):
    """A YAML file written before the rename contains
    ``timeline[i].comments[j].{body, mentions}``. The reader must
    surface it as ``timeline[i].mentions[j].{body, targets}`` so that
    every downstream consumer only ever sees the new shape."""
    path = matter_index_path(tmp_path / "index", "legacy")
    _write_yaml(path, {
        "version": 1,
        "matter": {
            "id": "legacy",
            "title": "L",
            "current_status": "planning",
            "created_at": "2026-04-23T10:00:00+08:00",
            "updated_at": "2026-04-23T10:00:00+08:00",
        },
        "timeline": [{
            "file": "discussions/legacy/001_a_think_x.md",
            "creator": "alice",
            "owner": "alice",
            "type": "think",
            "summary": "x",
            "comments": [
                {"created_at": "2026-04-23T10:05:00+08:00",
                 "body": "@you",
                 "mentions": ["bob"]},
                {"created_at": "2026-04-23T10:06:00+08:00",
                 "body": "+1",
                 "mentions": []},
            ],
        }],
    })
    data = read_matter_index(path)
    item = data["timeline"][0]
    assert "comments" not in item
    assert len(item["mentions"]) == 2
    first, second = item["mentions"]
    assert first["body"] == "@you"
    assert "mentions" not in first  # inner key renamed
    assert first["targets"] == ["bob"]
    assert second["targets"] == []


def test_reader_passes_through_new_shape_unchanged(tmp_path):
    """A YAML already written in the new shape goes through the reader
    untouched."""
    path = matter_index_path(tmp_path / "index", "modern")
    _write_yaml(path, {
        "version": 1,
        "matter": {
            "id": "modern",
            "title": "M",
            "current_status": "planning",
            "created_at": "2026-04-23T10:00:00+08:00",
            "updated_at": "2026-04-23T10:00:00+08:00",
        },
        "timeline": [{
            "file": "discussions/modern/001_a_think_x.md",
            "creator": "alice",
            "owner": "alice",
            "type": "think",
            "summary": "x",
            "mentions": [
                {"created_at": "2026-04-23T10:05:00+08:00",
                 "body": "ok",
                 "targets": ["bob"]},
            ],
        }],
    })
    data = read_matter_index(path)
    item = data["timeline"][0]
    assert item["mentions"][0]["targets"] == ["bob"]
    assert "comments" not in item


def test_reader_does_not_overwrite_existing_mentions(tmp_path):
    """If both the legacy and new keys are present (shouldn't happen but
    defensive), the new one wins — the normaliser must not clobber it."""
    path = matter_index_path(tmp_path / "index", "both")
    _write_yaml(path, {
        "version": 1,
        "matter": {
            "id": "both",
            "title": "B",
            "current_status": "planning",
            "created_at": "2026-04-23T10:00:00+08:00",
            "updated_at": "2026-04-23T10:00:00+08:00",
        },
        "timeline": [{
            "file": "discussions/both/001_a_think_x.md",
            "creator": "alice",
            "owner": "alice",
            "type": "think",
            "summary": "x",
            "comments": [{"body": "old"}],
            "mentions": [{"body": "new", "targets": ["bob"]}],
        }],
    })
    data = read_matter_index(path)
    assert data["timeline"][0]["mentions"][0]["body"] == "new"


def test_reader_then_write_upgrades_legacy_yaml_in_place(tmp_path):
    """Read a legacy file, append something via the public API, and the
    file on disk is now in the new shape — including the formerly-legacy
    pre-existing item."""
    path = matter_index_path(tmp_path / "index", "upgrade")
    _write_yaml(path, {
        "version": 1,
        "matter": {
            "id": "upgrade",
            "title": "U",
            "current_status": "planning",
            "created_at": "2026-04-23T10:00:00+08:00",
            "updated_at": "2026-04-23T10:00:00+08:00",
        },
        "timeline": [{
            "file": "discussions/upgrade/001_a_think_x.md",
            "creator": "alice",
            "owner": "alice",
            "type": "think",
            "summary": "x",
            "comments": [{"body": "legacy", "mentions": ["bob"]}],
        }],
    })
    append_comment(
        path,
        target_file="discussions/upgrade/001_a_think_x.md",
        comment={"body": "new", "mentions": ["carol"]},
        now_iso="2026-04-23T11:00:00+08:00",
    )
    raw = path.read_text(encoding="utf-8")
    assert "comments:" not in raw
    assert raw.count("mentions:") >= 1
    data = read_matter_index(path)
    bodies = [m["body"] for m in data["timeline"][0]["mentions"]]
    assert bodies == ["legacy", "new"]
    assert data["timeline"][0]["mentions"][1]["targets"] == ["carol"]


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
    # First add an act so the verify has a valid target in the same matter.
    act_path = "discussions/auth-redesign/002_u_act_a.md"
    append_file_item(path, item={
        "file": act_path,
        "creator": "u", "type": "act", "summary": "act1",
    }, now_iso="2026-04-23T10:30:00+08:00")
    # Caller presents fields in arbitrary order
    append_file_item(path, item={
        "summary": "s",
        "type": "verify",
        "creator": "u",
        "verifications": [{"target": act_path, "judgement": "passed", "comment": "ok"}],
        "file": "discussions/auth-redesign/003_u_verify.md",
        "quote": act_path,
    }, now_iso="2026-04-23T11:00:00+08:00")
    raw = path.read_text(encoding="utf-8")
    # The verify item should have file first, then created_at, creator, owner, type, summary, quote, verifications
    verify_block = raw.split("- file: discussions/auth-redesign/003_u_verify.md", 1)[1]
    # Assert the first six keys appear in the canonical order
    idx_created = verify_block.find("created_at:")
    idx_creator = verify_block.find("creator:")
    idx_owner = verify_block.find("owner:")
    idx_type = verify_block.find("type:")
    idx_summary = verify_block.find("summary:")
    idx_quote = verify_block.find("quote:")
    idx_verif = verify_block.find("verifications:")
    assert 0 < idx_created < idx_creator < idx_owner < idx_type < idx_summary < idx_quote < idx_verif


# ---------- P4.7 verifications_received reverse-write ----------


def _bootstrap_with_act(tmp_path, *, act_file: str, act_creator: str = "u",
                        act_owner: str | None = None,
                        now_iso_init: str = "2026-04-23T10:00:00+08:00",
                        now_iso_act: str = "2026-04-23T10:30:00+08:00"):
    """Create a planning matter with one think + one act ready to be verified."""
    path = matter_index_path(tmp_path / "index", "auth-redesign")
    create_matter_index(
        path,
        matter_id="auth-redesign",
        title="Auth Redesign",
        initial_item=_initial_think(creator=act_creator),
        now_iso=now_iso_init,
    )
    item: dict = {
        "file": act_file,
        "creator": act_creator,
        "type": "act",
        "summary": "do something",
    }
    if act_owner is not None:
        item["owner"] = act_owner
    append_file_item(path, item=item, now_iso=now_iso_act)
    return path


def test_reverse_write_single_verify_single_target(tmp_path):
    """Single verify covering a single act lands one entry on the act."""
    act = "discussions/auth-redesign/002_u_act_a.md"
    path = _bootstrap_with_act(tmp_path, act_file=act)

    verify_file = "discussions/auth-redesign/003_u_verify_a.md"
    append_file_item(path, item={
        "file": verify_file,
        "creator": "u",
        "type": "verify",
        "summary": "ok",
        "verifications": [{"target": act, "judgement": "passed", "comment": "good"}],
    }, now_iso="2026-04-23T11:00:00+08:00")

    data = read_matter_index(path)
    act_item = next(it for it in data["timeline"] if it["file"] == act)
    received = act_item["verifications_received"]
    assert len(received) == 1
    entry = received[0]
    assert entry == {
        "verify_file": verify_file,
        "verified_at": "2026-04-23T11:00:00+08:00",
        "verified_by": "u",
        "judgement": "passed",
        "comment": "good",
    }


def test_reverse_write_single_verify_multiple_targets(tmp_path):
    """One verify covering two acts mirrors one entry onto each act."""
    act_a = "discussions/auth-redesign/002_u_act_a.md"
    act_b = "discussions/auth-redesign/003_u_act_b.md"
    path = _bootstrap_with_act(tmp_path, act_file=act_a)
    append_file_item(path, item={
        "file": act_b, "creator": "u", "type": "act", "summary": "act b",
    }, now_iso="2026-04-23T10:45:00+08:00")

    verify_file = "discussions/auth-redesign/004_u_verify.md"
    append_file_item(path, item={
        "file": verify_file,
        "creator": "u", "owner": "u",
        "type": "verify",
        "summary": "汇总",
        "verifications": [
            {"target": act_a, "judgement": "passed", "comment": "A 通过"},
            {"target": act_b, "judgement": "failed", "comment": "B 边界遗漏"},
        ],
    }, now_iso="2026-04-23T11:30:00+08:00")

    data = read_matter_index(path)
    a = next(it for it in data["timeline"] if it["file"] == act_a)
    b = next(it for it in data["timeline"] if it["file"] == act_b)
    assert len(a["verifications_received"]) == 1
    assert a["verifications_received"][0]["judgement"] == "passed"
    assert a["verifications_received"][0]["comment"] == "A 通过"
    assert len(b["verifications_received"]) == 1
    assert b["verifications_received"][0]["judgement"] == "failed"
    assert b["verifications_received"][0]["comment"] == "B 边界遗漏"


def test_reverse_write_multiple_verifies_accumulate_in_order(tmp_path):
    """Two verifies targeting the same act accumulate two entries in
    chronological order (I6: append-only by verify write time)."""
    act = "discussions/auth-redesign/002_u_act_a.md"
    path = _bootstrap_with_act(tmp_path, act_file=act)

    verify1 = "discussions/auth-redesign/003_u_verify1.md"
    verify2 = "discussions/auth-redesign/004_u_verify2.md"
    append_file_item(path, item={
        "file": verify1, "creator": "u", "type": "verify", "summary": "v1",
        "verifications": [{"target": act, "judgement": "failed", "comment": "first round failed"}],
    }, now_iso="2026-04-23T11:00:00+08:00")
    append_file_item(path, item={
        "file": verify2, "creator": "u", "type": "verify", "summary": "v2",
        "verifications": [{"target": act, "judgement": "passed", "comment": "second round passed"}],
    }, now_iso="2026-04-23T13:00:00+08:00")

    data = read_matter_index(path)
    act_item = next(it for it in data["timeline"] if it["file"] == act)
    received = act_item["verifications_received"]
    assert len(received) == 2
    assert received[0]["verify_file"] == verify1
    assert received[0]["judgement"] == "failed"
    assert received[1]["verify_file"] == verify2
    assert received[1]["judgement"] == "passed"
    # Chronological order matches verify created_at
    assert received[0]["verified_at"] == "2026-04-23T11:00:00+08:00"
    assert received[1]["verified_at"] == "2026-04-23T13:00:00+08:00"


def test_reverse_write_skipped_for_cross_matter_target(tmp_path):
    """Cross-matter verify (target lives in another matter, only listed in
    refer[]) leaves the local matter untouched (I7)."""
    act_local = "discussions/auth-redesign/002_u_act_a.md"
    path = _bootstrap_with_act(tmp_path, act_file=act_local)

    external_act = "discussions/other-matter/001_u_act_x.md"
    append_file_item(path, item={
        "file": "discussions/auth-redesign/003_u_verify.md",
        "creator": "u", "type": "verify", "summary": "cross-matter",
        "refer": [external_act],
        "verifications": [
            {"target": external_act, "judgement": "passed", "comment": "ok"},
        ],
    }, now_iso="2026-04-23T11:00:00+08:00")

    data = read_matter_index(path)
    # Local act untouched — no verifications_received attached.
    a = next(it for it in data["timeline"] if it["file"] == act_local)
    assert "verifications_received" not in a


def test_reverse_write_verified_by_uses_owner_field(tmp_path):
    """verified_by 取 verify 的 owner（spec §九.2 判断责任人）。

    备注：`_normalize_item` 在 creator 存在时自动 `owner = creator`，因此通过
    `append_file_item` 写入时 owner 必非空，`_reverse_write_verifications` 里
    `owner or creator` 的右半 fallback 实际走不到——它作为防御性兜底保留，
    应对未来可能直接调内部函数的调用路径。
    """
    act = "discussions/auth-redesign/002_u_act_a.md"
    path = _bootstrap_with_act(tmp_path, act_file=act)
    append_file_item(path, item={
        "file": "discussions/auth-redesign/003_u_verify.md",
        "creator": "alice", "owner": "bob",
        "type": "verify", "summary": "v",
        "verifications": [{"target": act, "judgement": "passed", "comment": ""}],
    }, now_iso="2026-04-23T11:00:00+08:00")

    data = read_matter_index(path)
    a = next(it for it in data["timeline"] if it["file"] == act)
    assert a["verifications_received"][0]["verified_by"] == "bob"


def test_reverse_write_verified_by_falls_back_to_creator(tmp_path):
    """直接调 _reverse_write_verifications 验证 owner 缺失时回退到 creator。

    这条用例 bypass `_normalize_item`，否则 owner 总会被默认填成 creator，
    fallback 分支无法被覆盖。
    """
    from server.matter_index import _reverse_write_verifications

    act = "discussions/auth-redesign/002_u_act_a.md"
    index = {
        "matter": {"current_status": "executing"},
        "timeline": [
            {"file": act, "type": "act", "summary": "a"},
        ],
    }
    verify_no_owner = {
        "file": "discussions/auth-redesign/003_u_verify.md",
        "created_at": "2026-04-23T11:00:00+08:00",
        "creator": "alice",
        # 故意不传 owner
        "type": "verify",
        "summary": "v",
        "verifications": [
            {"target": act, "judgement": "passed", "comment": ""},
        ],
    }
    _reverse_write_verifications(index, verify_no_owner)

    a = index["timeline"][0]
    assert a["verifications_received"][0]["verified_by"] == "alice"


def test_reverse_write_does_not_appear_on_non_act_items(tmp_path):
    """think / verify / result / insight items must never carry
    verifications_received (I2)."""
    path = _bootstrap(tmp_path)
    # Add an act so we can have a legal verify target.
    act = "discussions/auth-redesign/002_u_act_a.md"
    append_file_item(path, item={
        "file": act, "creator": "u", "type": "act", "summary": "go",
        "status_change": {"from": "planning", "to": "executing"},
    }, now_iso="2026-04-23T10:30:00+08:00")
    # Verify covers act
    append_file_item(path, item={
        "file": "discussions/auth-redesign/003_u_verify.md",
        "creator": "u", "type": "verify", "summary": "v",
        "verifications": [{"target": act, "judgement": "passed", "comment": ""}],
    }, now_iso="2026-04-23T11:00:00+08:00")
    # Result terminates the matter
    append_file_item(path, item={
        "file": "discussions/auth-redesign/004_u_result.md",
        "creator": "u", "type": "result", "summary": "done",
        "outcome": "finished",
        "status_change": {"from": "executing", "to": "finished"},
    }, now_iso="2026-04-23T12:00:00+08:00")
    # Insight in finished
    append_file_item(path, item={
        "file": "discussions/auth-redesign/005_u_insight.md",
        "creator": "u", "type": "insight", "summary": "lesson",
    }, now_iso="2026-04-23T13:00:00+08:00")

    data = read_matter_index(path)
    for it in data["timeline"]:
        if it.get("type") != "act":
            assert "verifications_received" not in it, (
                f"non-act item {it.get('file')} (type={it.get('type')}) "
                f"unexpectedly has verifications_received"
            )


def test_reverse_write_atomic_with_verify_in_same_yaml(tmp_path):
    """I5: verify item and the matching verifications_received entry must
    materialize together in one atomic yaml write. Read the file once and
    confirm both sides are mutually consistent."""
    act_a = "discussions/auth-redesign/002_u_act_a.md"
    act_b = "discussions/auth-redesign/003_u_act_b.md"
    path = _bootstrap_with_act(tmp_path, act_file=act_a)
    append_file_item(path, item={
        "file": act_b, "creator": "u", "type": "act", "summary": "b",
    }, now_iso="2026-04-23T10:45:00+08:00")
    verify_file = "discussions/auth-redesign/004_u_verify.md"
    append_file_item(path, item={
        "file": verify_file,
        "creator": "u", "owner": "u",
        "type": "verify", "summary": "汇总",
        "verifications": [
            {"target": act_a, "judgement": "passed", "comment": "A"},
            {"target": act_b, "judgement": "failed", "comment": "B"},
        ],
    }, now_iso="2026-04-23T11:30:00+08:00")

    data = read_matter_index(path)
    verify_item = next(it for it in data["timeline"] if it["file"] == verify_file)
    assert len(verify_item["verifications"]) == 2

    for j_target, expected_judgement, expected_comment in [
        (act_a, "passed", "A"),
        (act_b, "failed", "B"),
    ]:
        target = next(it for it in data["timeline"] if it["file"] == j_target)
        rec = target["verifications_received"]
        assert len(rec) == 1
        assert rec[0]["verify_file"] == verify_file
        assert rec[0]["judgement"] == expected_judgement
        assert rec[0]["comment"] == expected_comment
        # Mirror is consistent with the source verify entry
        src = next(v for v in verify_item["verifications"] if v["target"] == j_target)
        assert rec[0]["judgement"] == src["judgement"]
        assert rec[0]["comment"] == src["comment"]


def test_reverse_write_field_appears_in_canonical_position(tmp_path):
    """`verifications_received` must sit between `verifications` (absent on act)
    and `outcome`/`comments`/`status_change` per _ITEM_KEY_ORDER."""
    act = "discussions/auth-redesign/002_u_act_a.md"
    path = _bootstrap_with_act(tmp_path, act_file=act)
    append_file_item(path, item={
        "file": "discussions/auth-redesign/003_u_verify.md",
        "creator": "u", "type": "verify", "summary": "v",
        "verifications": [{"target": act, "judgement": "passed", "comment": ""}],
    }, now_iso="2026-04-23T11:00:00+08:00")

    raw = path.read_text(encoding="utf-8")
    # Slice the act item block out of the yaml; act has no comments/status_change
    # by default in this fixture, just headers + verifications_received.
    act_block = raw.split(f"- file: {act}", 1)[1].split("- file:", 1)[0]
    idx_summary = act_block.find("summary:")
    idx_received = act_block.find("verifications_received:")
    assert 0 < idx_summary < idx_received, (
        f"verifications_received should appear after summary in act item, got "
        f"summary@{idx_summary} received@{idx_received}"
    )


# ---------- matter-level owner + owner_change ----------


def test_create_matter_index_with_matter_owner_writes_field(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    data = read_matter_index(path)
    assert data["matter"]["owner"] == "alice"


def test_create_matter_index_without_matter_owner_omits_field(tmp_path):
    path = _bootstrap(tmp_path)
    data = read_matter_index(path)
    assert "owner" not in data["matter"]


def test_create_matter_index_matter_owner_key_order(tmp_path):
    """matter.owner sits between current_status and created_at."""
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    raw = path.read_text(encoding="utf-8")
    matter_block = raw.split("matter:", 1)[1].split("timeline:", 1)[0]
    idx_status = matter_block.find("current_status:")
    idx_owner = matter_block.find("owner:")
    idx_created = matter_block.find("created_at:")
    assert 0 < idx_status < idx_owner < idx_created


def test_apply_owner_change_appends_event_and_updates_matter_owner(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    apply_owner_change(
        path,
        item={
            "type": "owner_change",
            "actor": "alice",
            "from_owner": "alice",
            "to_owner": "bob",
            "reason": "lead change",
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    data = read_matter_index(path)
    assert data["matter"]["owner"] == "bob"
    assert data["matter"]["updated_at"] == "2026-04-23T11:00:00+08:00"
    assert data["matter"]["current_status"] == "planning"  # unchanged
    last = data["timeline"][-1]
    assert last["type"] == "owner_change"
    assert last["actor"] == "alice"
    assert last["from_owner"] == "alice"
    assert last["to_owner"] == "bob"
    assert last["reason"] == "lead change"


def test_apply_owner_change_with_status_change_updates_both(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    apply_owner_change(
        path,
        item={
            "type": "owner_change",
            "actor": "alice",
            "from_owner": "alice",
            "to_owner": "bob",
            "reason": "kick off execution",
            "status_change": {"from": "planning", "to": "executing"},
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    data = read_matter_index(path)
    assert data["matter"]["owner"] == "bob"
    assert data["matter"]["current_status"] == "executing"
    last = data["timeline"][-1]
    assert last["status_change"] == {"from": "planning", "to": "executing"}


def test_apply_owner_change_when_matter_owner_missing(tmp_path):
    """Legacy matters without an explicit matter.owner field can still be
    transferred. The validator (per `eb8c60f`) treats missing matter.owner
    as "effective owner = first non-event timeline item's owner/creator",
    so callers transfer them by passing that fallback as from_owner."""
    path = _bootstrap(tmp_path)  # no matter_owner → owner field absent
    # _bootstrap's first item is creator='dengke' (owner defaults from creator).
    apply_owner_change(
        path,
        item={
            "type": "owner_change",
            "actor": "dengke",
            "from_owner": "dengke",
            "to_owner": "bob",
            "reason": "claim ownership",
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    data = read_matter_index(path)
    assert data["matter"]["owner"] == "bob"
    last = data["timeline"][-1]
    assert last["from_owner"] == "dengke"
    assert last["to_owner"] == "bob"


def test_apply_owner_change_invalid_raises_validation_error(tmp_path):
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    # from_owner mismatch → owner_stale
    with pytest.raises(ValidationError) as exc:
        apply_owner_change(
            path,
            item={
                "type": "owner_change",
                "actor": "alice",
                "from_owner": "ghost",
                "to_owner": "bob",
                "reason": "x",
            },
            now_iso="2026-04-23T11:00:00+08:00",
        )
    assert exc.value.result.code == "owner_stale"


def test_apply_owner_change_unknown_matter_raises(tmp_path):
    path = matter_index_path(tmp_path / "index", "ghost")
    with pytest.raises(FileNotFoundError):
        apply_owner_change(
            path,
            item={
                "type": "owner_change",
                "actor": "a",
                "from_owner": None,
                "to_owner": "b",
                "reason": "x",
            },
            now_iso="2026-04-23T11:00:00+08:00",
        )


def test_apply_owner_change_yaml_key_order(tmp_path):
    """owner_change entry serializes with type → created_at → actor → ..."""
    path = matter_index_path(tmp_path / "index", "m")
    create_matter_index(
        path,
        matter_id="m",
        title="m",
        initial_item=_initial_think(),
        now_iso="2026-04-23T10:00:00+08:00",
        matter_owner="alice",
    )
    apply_owner_change(
        path,
        item={
            # Pass keys in deliberately wrong order to confirm reorder works
            "reason": "x",
            "to_owner": "bob",
            "from_owner": "alice",
            "actor": "alice",
            "type": "owner_change",
            "status_change": {"from": "planning", "to": "executing"},
        },
        now_iso="2026-04-23T11:00:00+08:00",
    )
    raw = path.read_text(encoding="utf-8")
    # Locate the owner_change entry block (last one in timeline)
    oc_block = raw.split("- type: owner_change", 1)[1]
    # Each field must appear in canonical order before the next
    expected_order = ["created_at:", "actor:", "from_owner:", "to_owner:", "reason:", "status_change:"]
    last_idx = -1
    for marker in expected_order:
        idx = oc_block.find(marker)
        assert idx > last_idx, f"{marker} out of order"
        last_idx = idx
