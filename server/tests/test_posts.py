from __future__ import annotations

from server.posts import read_post


def test_read_post_with_frontmatter(tmp_path):
    p = tmp_path / "001_hello_abc123.md"
    p.write_text(
        "---\n"
        "type: proposal\n"
        "author: dengke\n"
        "title: Hello world\n"
        "---\n"
        "body content here\n",
        encoding="utf-8",
    )
    post = read_post(p)
    assert post.filename == "001_hello_abc123.md"
    assert post.frontmatter["type"] == "proposal"
    assert post.frontmatter["author"] == "dengke"
    assert post.body.strip() == "body content here"


def test_read_post_without_frontmatter(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("just some text\n", encoding="utf-8")
    post = read_post(p)
    assert post.frontmatter == {}
    assert "just some text" in post.body


def test_read_post_with_malformed_frontmatter(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("---\n::: invalid :::\n---\nbody\n", encoding="utf-8")
    post = read_post(p)
    assert post.frontmatter == {}
