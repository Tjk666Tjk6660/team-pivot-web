"""Pipeline test: discuss-list."""
from pathlib import Path


class TestDiscussList:
    def test_empty_data_space_returns_empty(self, runner):
        result = runner.run("discuss-list", {"category": ""})
        assert result.status == "completed"
        assert result.output["threads"] == []

    def test_lists_threads_after_creation(self, runner, make_proposal_draft):
        d1 = make_proposal_draft(title="alpha", content="# Alpha")
        runner.run("discuss-new", {
            "draft_id": d1,
            "category": "dev",
            "mention_users": "",
            "mention_comments": "",
        })
        d2 = make_proposal_draft(title="beta", content="# Beta")
        runner.run("discuss-new", {
            "draft_id": d2,
            "category": "dev",
            "mention_users": "",
            "mention_comments": "",
        })

        result = runner.run("discuss-list", {"category": "dev"})
        assert result.status == "completed"
        slugs = sorted(t["slug"] for t in result.output["threads"])
        assert slugs == ["alpha", "beta"]
