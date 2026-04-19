from __future__ import annotations

from server.index_files import (
    append_reply_to_index,
    append_standalone_mention,
    change_thread_status,
    create_thread_index,
    read_thread_index,
)


def _write_index(index_dir, slug, content):
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{slug}-discuss.index.yaml").write_text(content, encoding="utf-8")


def test_read_thread_index_parses_status_and_last_updated(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "my-thread",
        "origin_path: discussions/cat/my-thread/\n"
        "created: '2026-04-18T21:20:13+08:00'\n"
        "last_updated: '2026-04-19T09:00:00+08:00'\n"
        "discussions:\n"
        "- path: discussions/cat/my-thread/\n"
        "  status: open\n"
        "timeline: []\n"
    )
    res = read_thread_index(idx, "my-thread")
    assert res is not None
    assert res.status == "open"
    assert res.last_updated == "2026-04-19T09:00:00+08:00"


def test_read_thread_index_missing_file_returns_none(tmp_path):
    assert read_thread_index(tmp_path / "index", "nope") is None


def test_read_thread_index_missing_discussions_returns_none_status(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "t", "last_updated: '2026-01-01'\n")
    res = read_thread_index(idx, "t")
    assert res is not None
    assert res.status is None
    assert res.last_updated == "2026-01-01"


def test_read_thread_index_malformed_yaml_returns_none(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "t", "::: broken ::\n:\n--\n")
    assert read_thread_index(idx, "t") is None


def test_create_thread_index_roundtrip(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx,
        category="general",
        slug="hello",
        filename="001_dengke_proposal_abc123.md",
        author_id="dengke",
        now_iso="2026-04-19T10:00:00+08:00",
    )
    res = read_thread_index(idx, "hello")
    assert res is not None and res.status == "open"
    assert res.last_updated == "2026-04-19T10:00:00+08:00"


def test_append_reply_updates_last_updated_and_timeline(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_a.md",
        author_id="dengke", now_iso="2026-04-19T10:00:00+08:00",
    )
    append_reply_to_index(
        idx, category="c", slug="t", filename="002_r.md",
        author_id="ken", now_iso="2026-04-19T11:00:00+08:00",
    )
    import yaml
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    assert data["last_updated"] == "2026-04-19T11:00:00+08:00"
    assert len(data["timeline"]) == 2
    assert data["timeline"][1]["event"] == "ken replied"
    assert len(data["discussions"][0]["files"]) == 2


def test_append_standalone_mention(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_a.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    append_standalone_mention(
        idx, category="c", slug="t",
        target_filename="001_a.md",
        author_id="dengke",
        mention={"users": [{"user": "Ken", "open_id": "ou_1"}], "comments": "看一下"},
        now_iso="2026-04-19T12:00:00+08:00",
    )
    import yaml
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    # mention 不更新 last_updated，排序顺序不受影响
    assert data["last_updated"] == "2026-04-19T10:00:00+08:00"
    last = data["timeline"][-1]
    assert last["event"] == "dengke mentioned"
    assert last["file"].endswith("001_a.md")
    assert last["mention"]["comments"] == "看一下"


def test_change_status_updates_and_appends_timeline(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_a.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    change_thread_status(
        idx, category="c", slug="t",
        from_state="open", to_state="concluded",
        author_id="ken", reason=None,
        now_iso="2026-04-19T12:00:00+08:00",
    )
    import yaml
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    assert data["discussions"][0]["status"] == "concluded"
    assert data["last_updated"] == "2026-04-19T12:00:00+08:00"
    assert data["timeline"][-1]["event"] == "ken 状态变更 open -> concluded"


def test_change_status_reopen_records_reason(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_a.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    (idx / "t-discuss.index.yaml").write_text(
        (idx / "t-discuss.index.yaml").read_text().replace(
            "status: open", "status: concluded"
        ),
        encoding="utf-8",
    )
    change_thread_status(
        idx, category="c", slug="t",
        from_state="concluded", to_state="open",
        author_id="dengke", reason="发现新数据",
        now_iso="2026-04-19T13:00:00+08:00",
    )
    import yaml
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    assert data["discussions"][0]["status"] == "open"
    last = data["timeline"][-1]
    assert "从 concluded 状态重新打开" in last["event"]
    assert "发现新数据" in last["event"]


def test_change_status_rejects_stale_from_state(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_a.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    import pytest
    with pytest.raises(ValueError):
        change_thread_status(
            idx, category="c", slug="t",
            from_state="closed", to_state="open",
            author_id="ken", reason="x",
            now_iso="2026-04-19T11:00:00+08:00",
        )


def test_append_reply_adds_from_ref_to_proposal(tmp_path):
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="eng", slug="auth", filename="001_ken_proposal_aa.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    append_reply_to_index(
        idx, category="eng", slug="auth", filename="002_dengke_reply_bb.md",
        author_id="dengke", now_iso="2026-04-19T11:00:00+08:00",
    )
    import yaml
    data = yaml.safe_load((idx / "auth-discuss.index.yaml").read_text())
    reply = data["discussions"][0]["files"][1]
    assert reply["refs"] == [
        {"type": "from", "path": "discussions/eng/auth/001_ken_proposal_aa.md"}
    ]


def test_append_reply_missing_index_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        append_reply_to_index(
            tmp_path / "index", category="c", slug="nope", filename="x.md",
            author_id="a", now_iso="t",
        )


def test_read_thread_index_uses_first_discussion(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "t",
        "discussions:\n"
        "- path: p1\n  status: concluded\n"
        "- path: p2\n  status: open\n"
    )
    res = read_thread_index(idx, "t")
    assert res is not None and res.status == "concluded"
