"""Pipeline test: discuss-list."""
from pathlib import Path


class TestDiscussList:
    def test_empty_data_space_returns_empty(self, runner):
        result = runner.run("discuss-list", {"category": ""})
        assert result.status == "completed"
        assert result.output["threads"] == []

    def test_lists_threads_after_creation(self, runner):
        runner.run("discuss-new", {
            "category": "dev",
            "title": "alpha",
            "content": "# Alpha",
            "mention_users": "",
            "mention_comments": "",
        })
        runner.run("discuss-new", {
            "category": "dev",
            "title": "beta",
            "content": "# Beta",
            "mention_users": "",
            "mention_comments": "",
        })

        result = runner.run("discuss-list", {"category": "dev"})
        assert result.status == "completed"
        slugs = sorted(t["slug"] for t in result.output["threads"])
        assert slugs == ["alpha", "beta"]
