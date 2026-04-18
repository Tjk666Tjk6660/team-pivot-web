from __future__ import annotations

import pytest

from server.threads import (
    generate_unique_hash,
    get_thread,
    list_threads,
    next_post_number,
    sanitize_slug,
)


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


def test_list_threads_populates_status_and_last_updated(tmp_path):
    root = tmp_path / "discussions"
    idx = tmp_path / "index"
    _write_post(
        root / "c" / "hello" / "001_hi_abc.md",
        type_="proposal", author="x", title="Hi",
    )
    idx.mkdir(parents=True)
    (idx / "hello-discuss.index.yaml").write_text(
        "last_updated: '2026-04-19T12:00:00+08:00'\n"
        "discussions:\n- path: discussions/c/hello/\n  status: concluded\n",
        encoding="utf-8",
    )
    threads = list_threads(root, idx)
    assert len(threads) == 1
    assert threads[0].status == "concluded"
    assert threads[0].last_updated == "2026-04-19T12:00:00+08:00"


def test_list_threads_sorts_by_last_updated_desc(tmp_path):
    root = tmp_path / "discussions"
    idx = tmp_path / "index"
    idx.mkdir(parents=True)
    for slug, when in [("old", "2026-01-01"), ("new", "2026-04-19"), ("mid", "2026-03-01")]:
        _write_post(
            root / "c" / slug / f"001_p_{slug}.md",
            type_="proposal", author="x", title=slug,
        )
        (idx / f"{slug}-discuss.index.yaml").write_text(
            f"last_updated: '{when}'\ndiscussions:\n- path: p\n  status: open\n",
            encoding="utf-8",
        )
    threads = list_threads(root, idx)
    assert [t.slug for t in threads] == ["new", "mid", "old"]


def test_list_threads_without_index_has_none_status(tmp_path):
    root = tmp_path / "discussions"
    _write_post(
        root / "c" / "t" / "001_p_abc.md", type_="proposal", author="x", title="T",
    )
    threads = list_threads(root)
    assert threads[0].status is None
    assert threads[0].last_updated is None


def test_sanitize_slug_replaces_unsafe_chars():
    assert sanitize_slug("a/b:c*d?") == "a_b_c_d_"
    assert sanitize_slug("  spaces  ") == "spaces"
    assert sanitize_slug("中文 title：多行") == "中文 title：多行"
    assert sanitize_slug("") == "untitled"
    assert sanitize_slug("///") == "_"


def test_next_post_number(tmp_path):
    assert next_post_number(tmp_path / "nope") == 1
    (tmp_path / "t").mkdir()
    assert next_post_number(tmp_path / "t") == 1
    for name in ("001_a.md", "002_b.md", "RESULT_z.md", "not_a_post.txt"):
        (tmp_path / "t" / name).write_text("")
    assert next_post_number(tmp_path / "t") == 3


def test_generate_unique_hash_avoids_collision(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "001_x_proposal_abc123.md").write_text("")
    for _ in range(50):
        h = generate_unique_hash(d)
        assert h != "abc123"
        assert len(h) == 6


def test_generate_unique_hash_works_on_missing_dir(tmp_path):
    h = generate_unique_hash(tmp_path / "nope")
    assert len(h) == 6


def test_title_prefers_frontmatter_then_h1_then_filename(tmp_path):
    root = tmp_path / "discussions"
    (root / "cat" / "t1").mkdir(parents=True)
    (root / "cat" / "t1" / "001_slug_aaa.md").write_text(
        "---\ntype: proposal\nauthor: x\ntitle: Frontmatter Wins\n---\n"
        "# Body heading\nbody\n", encoding="utf-8",
    )
    (root / "cat" / "t2").mkdir(parents=True)
    (root / "cat" / "t2" / "001_slug_bbb.md").write_text(
        "---\ntype: proposal\nauthor: x\n---\n# H1 Wins\nbody\n",
        encoding="utf-8",
    )
    (root / "cat" / "t3").mkdir(parents=True)
    (root / "cat" / "t3" / "001_fallback-title_ccc.md").write_text(
        "---\ntype: proposal\nauthor: x\n---\nno heading here\n",
        encoding="utf-8",
    )

    by_slug = {t.slug: t for t in list_threads(root)}
    assert by_slug["t1"].title == "Frontmatter Wins"
    assert by_slug["t2"].title == "H1 Wins"
    assert by_slug["t3"].title == "fallback title"


def test_get_thread_returns_posts_sorted(discussions):
    detail = get_thread(discussions, None, "engineering", "auth-rewrite")
    assert detail is not None
    assert [p.filename for p in detail.posts] == [
        "001_auth_abc123.md",
        "002_reply_def456.md",
    ]


def test_get_thread_missing_returns_none(discussions):
    assert get_thread(discussions, None, "engineering", "nope") is None


def test_get_thread_skips_result_and_summary(tmp_path):
    root = tmp_path / "discussions"
    _write_post(
        root / "eng" / "t" / "001_a_h1.md", type_="proposal", author="x", title="T",
    )
    _write_post(root / "eng" / "t" / "RESULT_h2.md", type_="result", author="x")
    _write_post(root / "eng" / "t" / "SUMMARY_h3.md", type_="summary", author="x")
    detail = get_thread(root, None, "eng", "t")
    assert detail is not None
    assert [p.filename for p in detail.posts] == ["001_a_h1.md"]
