"""Tests for threads module (thread discovery and frontmatter parsing)."""
from pathlib import Path

import pytest

from tools import threads


class TestThreadDiscovery:
    def test_enumerate_threads_in_category(self, tmp_path: Path):
        (tmp_path / "discussions/enclaws/auth-redesign").mkdir(parents=True)
        (tmp_path / "discussions/enclaws/auth-redesign/001_ken_proposal.md").write_text(
            "---\ntype: proposal\n---\n# hello\n", encoding="utf-8"
        )
        (tmp_path / "discussions/enclaws/token-opt").mkdir()
        (tmp_path / "discussions/enclaws/token-opt/001_a.md").write_text(
            "---\ntype: proposal\n---\n# t\n", encoding="utf-8"
        )

        found = threads.list_threads(
            str(tmp_path / "discussions"), category="enclaws"
        )
        names = sorted(t["slug"] for t in found)
        assert names == ["auth-redesign", "token-opt"]

    def test_enumerate_all_categories(self, tmp_path: Path):
        (tmp_path / "discussions/enclaws/a").mkdir(parents=True)
        (tmp_path / "discussions/enclaws/a/001.md").write_text(
            "---\ntype: proposal\n---\n", encoding="utf-8"
        )
        (tmp_path / "discussions/marketing/b").mkdir(parents=True)
        (tmp_path / "discussions/marketing/b/001.md").write_text(
            "---\ntype: proposal\n---\n", encoding="utf-8"
        )

        found = threads.list_threads(str(tmp_path / "discussions"))
        assert len(found) == 2
        categories = {t["category"] for t in found}
        assert categories == {"enclaws", "marketing"}

    def test_list_posts_in_thread(self, tmp_path: Path):
        thread = tmp_path / "discussions/enclaws/t"
        thread.mkdir(parents=True)
        (thread / "001_ken_proposal.md").write_text(
            "---\ntype: proposal\nauthor: ken\n---\n# hi\n", encoding="utf-8"
        )
        (thread / "002_shengli_reply.md").write_text(
            "---\ntype: reply\nauthor: shengli\n---\n# yes\n", encoding="utf-8"
        )
        (thread / "RESULT_xxxx.md").write_text(
            "---\ntype: result\nauthor: ken\n---\n# done\n", encoding="utf-8"
        )

        posts = threads.list_posts(str(thread))
        assert len(posts) == 3
        assert posts[0]["filename"].startswith("001")
        assert posts[1]["filename"].startswith("002")

    def test_next_post_number_finds_max_plus_one(self, tmp_path: Path):
        thread = tmp_path / "discussions/enclaws/t"
        thread.mkdir(parents=True)
        (thread / "001_ken_proposal_f3a1b2.md").write_text(
            "---\ntype: proposal\n---\n", encoding="utf-8"
        )
        (thread / "002_shengli_reply_a2b3c4.md").write_text(
            "---\ntype: reply\n---\n", encoding="utf-8"
        )
        (thread / "RESULT_e5f6a7.md").write_text(
            "---\ntype: result\n---\n", encoding="utf-8"
        )
        assert threads.next_post_number(str(thread)) == 3

    def test_next_post_number_empty_thread_returns_1(self, tmp_path: Path):
        thread = tmp_path / "discussions/enclaws/empty"
        thread.mkdir(parents=True)
        assert threads.next_post_number(str(thread)) == 1


class TestShortHash:
    def test_generate_short_hash_returns_6_hex_chars(self):
        h = threads.generate_short_hash()
        assert len(h) == 6
        assert all(c in "0123456789abcdef" for c in h)

    def test_ensure_unique_hash_returns_non_colliding(self, tmp_path: Path):
        (tmp_path / "discussions/x/y").mkdir(parents=True)
        (tmp_path / "discussions/x/y/001_ken_proposal_aaaaaa.md").write_text(
            "---\n---\n", encoding="utf-8"
        )
        h = threads.ensure_unique_filename_hash(str(tmp_path))
        assert h != "aaaaaa"
        assert len(h) == 6

    def test_ensure_unique_hash_raises_when_exhausted(self, tmp_path: Path, monkeypatch):
        (tmp_path / "discussions/x/y").mkdir(parents=True)
        (tmp_path / "discussions/x/y/001_ken_proposal_aaaaaa.md").write_text(
            "---\n---\n", encoding="utf-8"
        )
        monkeypatch.setattr(threads, "generate_short_hash", lambda: "aaaaaa")
        with pytest.raises(RuntimeError, match="unique hash"):
            threads.ensure_unique_filename_hash(str(tmp_path), max_attempts=3)
