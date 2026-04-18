from __future__ import annotations

import pytest

from server.threads import get_thread, list_threads


def _write_post(path, *, type_: str, author: str, title: str = "", body: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = f"type: {type_}\nauthor: {author}\n"
    if title:
        fm += f"title: {title}\n"
    path.write_text(f"---\n{fm}---\n{body}\n", encoding="utf-8")


@pytest.fixture
def discussions(tmp_path):
    root = tmp_path / "discussions"
    _write_post(
        root / "engineering" / "auth-rewrite" / "001_auth_abc123.md",
        type_="proposal", author="dengke", title="Auth rewrite",
    )
    _write_post(
        root / "engineering" / "auth-rewrite" / "002_reply_def456.md",
        type_="reply", author="ken",
    )
    _write_post(
        root / "product" / "new-feature" / "001_new_xyz789.md",
        type_="proposal", author="ken", title="New feature",
    )
    (root / "engineering" / "no-proposal" / "001_stray_zzz000.md").parent.mkdir(parents=True)
    _write_post(
        root / "engineering" / "no-proposal" / "001_stray_zzz000.md",
        type_="reply", author="x",
    )
    return root


def test_list_threads_finds_all_with_proposal(discussions):
    threads = list_threads(discussions)
    slugs = sorted(t.slug for t in threads)
    assert slugs == ["auth-rewrite", "new-feature"]


def test_list_threads_skips_dirs_without_proposal(discussions):
    threads = list_threads(discussions)
    assert all(t.slug != "no-proposal" for t in threads)


def test_list_threads_filter_by_category(discussions):
    items = list_threads(discussions, category="product")
    assert [t.slug for t in items] == ["new-feature"]


def test_list_threads_meta_fields(discussions):
    t = next(t for t in list_threads(discussions) if t.slug == "auth-rewrite")
    assert t.category == "engineering"
    assert t.title == "Auth rewrite"
    assert t.author == "dengke"
    assert t.post_count == 2
    assert t.status is None


def test_list_threads_empty_root(tmp_path):
    assert list_threads(tmp_path / "nope") == []


def test_get_thread_returns_posts_sorted(discussions):
    detail = get_thread(discussions, "engineering", "auth-rewrite")
    assert detail is not None
    assert [p.filename for p in detail.posts] == [
        "001_auth_abc123.md",
        "002_reply_def456.md",
    ]


def test_get_thread_missing_returns_none(discussions):
    assert get_thread(discussions, "engineering", "nope") is None


def test_get_thread_skips_result_and_summary(tmp_path):
    root = tmp_path / "discussions"
    _write_post(
        root / "eng" / "t" / "001_a_h1.md", type_="proposal", author="x", title="T",
    )
    _write_post(root / "eng" / "t" / "RESULT_h2.md", type_="result", author="x")
    _write_post(root / "eng" / "t" / "SUMMARY_h3.md", type_="summary", author="x")
    detail = get_thread(root, "eng", "t")
    assert detail is not None
    assert [p.filename for p in detail.posts] == ["001_a_h1.md"]
