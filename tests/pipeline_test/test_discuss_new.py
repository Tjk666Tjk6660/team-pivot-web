"""Pipeline test: discuss-new full flow."""
from pathlib import Path

from tools import index as index_mod


class TestDiscussNew:
    def test_creates_thread_and_index(self, runner, make_proposal_draft):
        draft_id = make_proposal_draft(
            title="new-thread", content="# Proposal\n\nBody text.",
        )
        result = runner.run("discuss-new", {
            "draft_id": draft_id,
            "category": "test",
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "completed", result.error
        assert result.output["committed"] is True

        ws = Path(runner.data_space_dir)
        canonical = list((ws / "discussions/test/new-thread").glob("001_*.md"))
        assert len(canonical) == 1
        idx = ws / "index/new-thread-discuss.index.yaml"
        assert idx.exists()

        loaded = index_mod.load(str(idx))
        assert len(loaded.discussions) == 1
        assert loaded.discussions[0].status == "open"
        assert len(loaded.timeline) == 1

    def test_llm_generates_summary(self, runner, make_proposal_draft):
        draft_id = make_proposal_draft(
            title="summary-thread", content="# Long proposal\n\nWith details...",
        )
        result = runner.run("discuss-new", {
            "draft_id": draft_id,
            "category": "test",
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "completed", result.error
        assert "generate_summary" in result.step_outputs
        summary = result.step_outputs["generate_summary"]["output"]["summary"]
        assert len(summary) > 0

    def test_fails_without_draft_id(self, runner, user_workspace):
        result = runner.run("discuss-new", {
            "category": "test",
        })
        assert result.status == "error"

    def test_fails_on_missing_draft(self, runner, user_workspace):
        result = runner.run("discuss-new", {
            "draft_id": "draft-does-not-exist",
            "category": "test",
        })
        assert result.status == "error"
