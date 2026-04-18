from __future__ import annotations

import pytest

from server.inbox import compute_inbox, latest_post_filename
from server.read_state import ReadStateRepo


def _write_post(root, category, slug, filename, type_="proposal", author="x", title=""):
    p = root / category / slug / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = f"type: {type_}\nauthor: {author}\nindex_state: indexed\n"
    if title:
        fm += f"title: {title}\n"
    p.write_text(f"---\n{fm}---\nbody\n", encoding="utf-8")


def _write_index(index_dir, slug, last_updated="2026-04-19T10:00:00+08:00"):
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / f"{slug}-discuss.index.yaml").write_text(
        f"last_updated: '{last_updated}'\n"
        "discussions:\n- path: p\n  status: open\n",
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "discussions"
    idx = tmp_path / "index"
    _write_post(root, "c", "t1", "001_a_proposal_aa.md", title="T1")
    _write_post(root, "c", "t1", "002_a_reply_bb.md", type_="reply")
    _write_post(root, "c", "t1", "003_a_reply_cc.md", type_="reply")
    _write_post(root, "c", "t2", "001_b_proposal_dd.md", title="T2")
    _write_index(idx, "t1", last_updated="2026-04-19T12:00")
    _write_index(idx, "t2", last_updated="2026-04-19T08:00")
    return root, idx


@pytest.fixture
def read_states(db):
    return ReadStateRepo(db)


def test_inbox_new_user_sees_all_threads(repo, read_states):
    root, idx = repo
    items = compute_inbox(root, idx, "ou_new", read_states)
    by_slug = {it.meta.slug: it for it in items}
    assert by_slug["t1"].unread_count == 3
    assert by_slug["t2"].unread_count == 1


def test_inbox_after_read_is_empty(repo, read_states):
    root, idx = repo
    read_states.set("ou_1", "c/t1", "003_a_reply_cc.md")
    read_states.set("ou_1", "c/t2", "001_b_proposal_dd.md")
    items = compute_inbox(root, idx, "ou_1", read_states)
    assert items == []


def test_inbox_partial_read(repo, read_states):
    root, idx = repo
    read_states.set("ou_1", "c/t1", "001_a_proposal_aa.md")
    items = compute_inbox(root, idx, "ou_1", read_states)
    by_slug = {it.meta.slug: it for it in items}
    assert by_slug["t1"].unread_count == 2
    assert by_slug["t2"].unread_count == 1


def test_inbox_reports_last_post_author(repo, read_states):
    root, idx = repo
    items = compute_inbox(root, idx, "ou_new", read_states)
    t1 = next(it for it in items if it.meta.slug == "t1")
    assert t1.last_post_filename == "003_a_reply_cc.md"
    assert t1.last_post_author == "x"


def test_latest_post_filename(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "001_a.md").write_text("---\nindex_state: indexed\n---\nx\n")
    (d / "002_b.md").write_text("---\nindex_state: indexed\n---\nx\n")
    assert latest_post_filename(d) == "002_b.md"
    assert latest_post_filename(tmp_path / "nope") is None


def test_latest_skips_un_indexed(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "001_a.md").write_text("---\nindex_state: indexed\n---\nx\n")
    (d / "002_b.md").write_text("---\nindex_state: un-indexed\n---\nx\n")
    assert latest_post_filename(d) == "001_a.md"
