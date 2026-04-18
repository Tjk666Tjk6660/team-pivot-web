from __future__ import annotations

from server.index_files import read_thread_index


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


def test_read_thread_index_uses_first_discussion(tmp_path):
    idx = tmp_path / "index"
    _write_index(idx, "t",
        "discussions:\n"
        "- path: p1\n  status: concluded\n"
        "- path: p2\n  status: open\n"
    )
    res = read_thread_index(idx, "t")
    assert res is not None and res.status == "concluded"
