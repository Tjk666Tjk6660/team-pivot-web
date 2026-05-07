"""Tests for `server.daily_report.collect_matter`."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from server.daily_report.collect_matter import collect_matter_events
from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ


def _window(since_iso: str, until_iso: str) -> TimeWindow:
    return TimeWindow(
        since=datetime.fromisoformat(since_iso),
        until=datetime.fromisoformat(until_iso),
    )


def _write_index(
    index_dir: Path, matter_id: str, *, status: str = "executing",
    timeline: list[dict] | None = None,
) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    p = index_dir / f"{matter_id}.index.yaml"
    p.write_text(yaml.safe_dump({
        "version": 1,
        "matter": {
            "id": matter_id,
            "title": f"matter {matter_id}",
            "current_status": status,
            "created_at": "2026-04-26T08:00:00+08:00",
            "updated_at": "2026-04-27T08:00:00+08:00",
        },
        "timeline": timeline or [],
    }, allow_unicode=True), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# basic filtering                                                             #
# --------------------------------------------------------------------------- #


def test_collect_returns_empty_when_index_dir_missing(tmp_path):
    """No index dir → [] (warning logged), not exception."""
    out = collect_matter_events(
        tmp_path / "nonexistent",
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_returns_empty_when_no_index_files(tmp_path):
    (tmp_path / "index").mkdir()
    out = collect_matter_events(
        tmp_path / "index",
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_picks_up_in_window_file(tmp_path):
    """Item with created_at inside [since, until) is emitted."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_alice_think_aaa111.md",
            "type": "think",
            "created_at": "2026-04-26T15:00:00+08:00",   # in window
            "creator": "alice",
            "owner": "alice",
            "summary": "first think",
        },
    ])
    w = _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00")
    out = collect_matter_events(idx, w)
    assert len(out) == 1
    ev = out[0]
    assert ev.matter_id == "demo"
    assert ev.file_type == "think"
    assert ev.creator == "alice"
    assert ev.file_in_window is True
    assert ev.created_at == datetime(2026, 4, 26, 15, 0, tzinfo=CHINA_TZ)


def test_collect_excludes_out_of_window_file_without_comments(tmp_path):
    """Item before window with no comments → skipped."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_alice_think_aaa111.md",
            "type": "think",
            "created_at": "2026-04-20T15:00:00+08:00",   # too early
            "creator": "alice",
            "owner": "alice",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_excludes_after_window(tmp_path):
    """Item after `until` → skipped (half-open)."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_alice_think_aaa111.md",
            "type": "think",
            "created_at": "2026-04-27T10:00:00+08:00",   # past until
            "creator": "alice",
            "owner": "alice",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_half_open_boundaries(tmp_path):
    """[since, until):  9:30:00 inclusive (since), 9:30:00 next day exclusive."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_a_think_aaa.md",
            "type": "think",
            "created_at": "2026-04-26T09:30:00+08:00",   # exactly since (inclusive)
            "creator": "a",
            "owner": "a",
        },
        {
            "file": "discussions/test/demo/002_b_think_bbb.md",
            "type": "think",
            "created_at": "2026-04-27T09:30:00+08:00",   # exactly until (exclusive)
            "creator": "b",
            "owner": "b",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    files = [e.file for e in out]
    assert "discussions/test/demo/001_a_think_aaa.md" in files
    assert "discussions/test/demo/002_b_think_bbb.md" not in files


# --------------------------------------------------------------------------- #
# comments out-of-band on old file                                            #
# --------------------------------------------------------------------------- #


def test_collect_emits_old_file_when_in_window_comment_lands(tmp_path):
    """File created earlier (out of window), but a comment landed today —
    emit the file with file_in_window=False + the in-window comments."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_a_think_aaa.md",
            "type": "think",
            "created_at": "2026-04-20T10:00:00+08:00",   # 6 days ago
            "creator": "a",
            "owner": "a",
            "comments": [
                {
                    "created_at": "2026-04-26T11:00:00+08:00",  # today
                    "author": "b",
                    "body": "想法不错",
                    "mentions": ["a"],
                },
                {
                    "created_at": "2026-04-21T10:00:00+08:00",  # too early
                    "author": "c",
                    "body": "yesterday's view",
                },
            ],
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1
    ev = out[0]
    assert ev.file_in_window is False    # 文件本身在窗口外
    assert len(ev.comments_in_window) == 1
    assert ev.comments_in_window[0].author == "b"
    assert ev.comments_in_window[0].mentions == ("a",)


def test_collect_filters_per_comment(tmp_path):
    """File in window + multiple comments — each comment independently filtered."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_a_think_aaa.md",
            "type": "think",
            "created_at": "2026-04-26T10:00:00+08:00",
            "creator": "a",
            "owner": "a",
            "comments": [
                {"created_at": "2026-04-26T11:00:00+08:00", "author": "b", "body": "in"},
                {"created_at": "2026-04-25T11:00:00+08:00", "author": "c", "body": "out"},
                {"created_at": "2026-04-26T20:00:00+08:00", "author": "d", "body": "in2"},
            ],
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1
    authors = [c.author for c in out[0].comments_in_window]
    assert authors == ["b", "d"]


# --------------------------------------------------------------------------- #
# edge cases / defenses                                                       #
# --------------------------------------------------------------------------- #


def test_collect_skips_item_with_missing_file(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "type": "think",
            "created_at": "2026-04-26T15:00:00+08:00",
            "creator": "a",
            # no `file` key → skip
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_handles_naive_iso_as_china_tz(tmp_path):
    """Legacy migrated data may store created_at without tz; assume Asia/Shanghai."""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_a_think_aaa.md",
            "type": "think",
            "created_at": "2026-04-26T15:00:00",   # NAIVE
            "creator": "a",
            "owner": "a",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1
    assert out[0].created_at.tzinfo is not None
    assert out[0].created_at.utcoffset().total_seconds() == 8 * 3600


def test_collect_carries_status_change_and_verifications(tmp_path):
    """Verify file with verifications + status_change → both fields preserved."""
    idx = tmp_path / "index"
    _write_index(idx, "auth", status="finished", timeline=[
        {
            "file": "discussions/eng/auth/006_dengke_verify_f6.md",
            "type": "verify",
            "created_at": "2026-04-26T15:00:00+08:00",
            "creator": "dengke",
            "owner": "dengke",
            "verifications": [
                {"target": "discussions/eng/auth/003_a.md", "judgement": "passed", "comment": "ok"},
            ],
            "status_change": {"from": "executing", "to": "finished"},
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1
    assert out[0].status_change == {"from": "executing", "to": "finished"}
    assert len(out[0].verifications) == 1
    assert out[0].verifications[0]["judgement"] == "passed"


def test_collect_drops_invalidated_files(tmp_path):
    """已失效文件(invalidated: true)在数据层被剔除,不进入日报事件流。

    Why: 日报场景下"失效内容彻底不进叙事"是产品决策(路径 2,见 act 007
    后续讨论)。通过数据层过滤而不是 prompt 软约束,避免 LLM 把已失效的
    summary 当今日成果叙述。"""
    idx = tmp_path / "index"
    _write_index(idx, "demo", timeline=[
        {
            "file": "discussions/test/demo/001_a_act_aaa.md",
            "type": "act",
            "created_at": "2026-04-26T15:00:00+08:00",
            "creator": "a",
            "owner": "a",
            "summary": "valid act content",
        },
        {
            "file": "discussions/test/demo/002_a_act_bbb.md",
            "type": "act",
            "created_at": "2026-04-26T16:00:00+08:00",
            "creator": "a",
            "owner": "a",
            "summary": "this content has been invalidated and must NOT leak",
            "invalidated": True,
            "invalidated_at": "2026-04-26T16:30:00+08:00",
            "invalidated_reason": "misposted",
            "invalidated_by": "a",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1, "invalidated file must be dropped from event stream"
    assert out[0].file.endswith("001_a_act_aaa.md")
    assert "invalidated" not in out[0].summary


def test_renderer_drops_invalidated_files_and_invalidation_events(tmp_path):
    """matter_timeline_renderer 同样剔除失效文件 + 失效/恢复事件项。

    LLM 看到的 timeline_yaml 就是清洁版,不含任何 invalidated:true 的
    file 项,也不含 reason ∈ {misposted, inaccurate, restored} 的事件项。"""
    from server.daily_report.matter_timeline_renderer import render_matter_timeline_yaml

    matter_index = {
        "matter": {
            "id": "demo",
            "title": "demo",
            "current_status": "executing",
            "owner": "a",
        },
        "timeline": [
            {
                "file": "discussions/test/demo/001_a_act_aaa.md",
                "type": "act",
                "created_at": "2026-04-26T15:00:00+08:00",
                "creator": "a",
                "owner": "a",
                "summary": "valid act content",
            },
            {
                "file": "discussions/test/demo/002_a_act_bbb.md",
                "type": "act",
                "created_at": "2026-04-26T16:00:00+08:00",
                "creator": "a",
                "owner": "a",
                "summary": "INVALIDATED_CONTENT_MUST_NOT_LEAK",
                "invalidated": True,
                "invalidated_reason": "misposted",
            },
            {
                "creator": "a",
                "created_at": "2026-04-26T16:30:00+08:00",
                "quote": "discussions/test/demo/002_a_act_bbb.md",
                "reason": "misposted",
                "summary": "INVALIDATION_EVENT_MUST_NOT_LEAK",
            },
        ],
    }
    rendered = render_matter_timeline_yaml(
        matter_index,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert "001_a_act_aaa.md" in rendered, "valid act must be present"
    assert "INVALIDATED_CONTENT_MUST_NOT_LEAK" not in rendered
    assert "INVALIDATION_EVENT_MUST_NOT_LEAK" not in rendered
    assert "002_a_act_bbb.md" not in rendered, (
        "invalidated file path itself must be filtered too"
    )


def test_collect_continues_when_one_yaml_corrupt(tmp_path):
    """A malformed yaml shouldn't kill the whole report."""
    idx = tmp_path / "index"
    idx.mkdir()
    (idx / "bad.index.yaml").write_text("not: valid: yaml: ::: [", encoding="utf-8")
    _write_index(idx, "good", timeline=[
        {
            "file": "discussions/test/good/001_a_think_aaa.md",
            "type": "think",
            "created_at": "2026-04-26T15:00:00+08:00",
            "creator": "a",
            "owner": "a",
        },
    ])
    out = collect_matter_events(
        idx,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    # bad.yaml skipped, good.yaml's event still picked up
    assert len(out) == 1
    assert out[0].matter_id == "good"
