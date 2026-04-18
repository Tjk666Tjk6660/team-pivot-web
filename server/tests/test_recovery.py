from __future__ import annotations

import yaml

from server.index_files import create_thread_index, read_thread_index
from server.posts import mark_indexed, read_post, scan_un_indexed, write_post_pending
from server.recovery import repair_partial_writes


def _write_pending_post(discussions_root, category, slug, filename, ptype, author):
    p = discussions_root / category / slug / filename
    write_post_pending(
        p,
        frontmatter={
            "type": ptype,
            "author": author,
            "created_at": "2026-04-19T10:00:00+08:00",
        },
        body="# Hi\n\nbody\n",
    )
    return p


def test_scan_un_indexed_yields_pending_files(tmp_path):
    d = tmp_path / "discussions"
    _write_pending_post(d, "c", "t", "001_a_proposal_abc.md", "proposal", "a")
    (d / "c" / "t" / "ignored.md").write_text(
        "---\nindex_state: indexed\n---\nbody\n", encoding="utf-8"
    )
    names = sorted(p.name for p in scan_un_indexed(d))
    assert names == ["001_a_proposal_abc.md"]


def test_mark_indexed_flips_flag(tmp_path):
    d = tmp_path / "discussions"
    p = _write_pending_post(d, "c", "t", "001_a_proposal_abc.md", "proposal", "a")
    assert read_post(p).frontmatter["index_state"] == "un-indexed"
    mark_indexed(p)
    assert read_post(p).frontmatter["index_state"] == "indexed"


def test_recover_creates_missing_index_for_proposal(tmp_path):
    d = tmp_path / "discussions"
    idx = tmp_path / "index"
    p = _write_pending_post(d, "c", "t", "001_ken_proposal_aaa.md", "proposal", "ken")

    fixed = repair_partial_writes(d, idx)
    assert fixed == 1
    assert read_post(p).frontmatter["index_state"] == "indexed"
    ti = read_thread_index(idx, "t")
    assert ti is not None and ti.status == "open"


def test_recover_appends_reply_when_index_exists_no_entry(tmp_path):
    d = tmp_path / "discussions"
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_ken_proposal_aaa.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    _write_pending_post(d, "c", "t", "002_ken_reply_bbb.md", "reply", "ken")

    fixed = repair_partial_writes(d, idx)
    assert fixed == 1
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    paths = [f["path"] for f in data["discussions"][0]["files"]]
    assert paths == ["001_ken_proposal_aaa.md", "002_ken_reply_bbb.md"]


def test_recover_idempotent_when_index_has_entry_just_flag_stale(tmp_path):
    d = tmp_path / "discussions"
    idx = tmp_path / "index"
    create_thread_index(
        idx, category="c", slug="t", filename="001_ken_proposal_aaa.md",
        author_id="ken", now_iso="2026-04-19T10:00:00+08:00",
    )
    p = _write_pending_post(d, "c", "t", "001_ken_proposal_aaa.md", "proposal", "ken")

    fixed = repair_partial_writes(d, idx)
    assert fixed == 1
    assert read_post(p).frontmatter["index_state"] == "indexed"
    data = yaml.safe_load((idx / "t-discuss.index.yaml").read_text())
    assert len(data["discussions"][0]["files"]) == 1


def test_recover_no_op_when_nothing_un_indexed(tmp_path):
    d = tmp_path / "discussions"
    (d / "c" / "t").mkdir(parents=True)
    (d / "c" / "t" / "001_x.md").write_text(
        "---\nindex_state: indexed\ntype: proposal\n---\nbody\n",
        encoding="utf-8",
    )
    assert repair_partial_writes(d, tmp_path / "index") == 0
