"""Self-tests for the local pipeline runner."""
import json
from pathlib import Path

import pytest

from tests.ec_simulator.runner import LocalPipelineRunner
from tests.ec_simulator.llm_backends.prerecorded import PrerecordedBackend


@pytest.fixture
def runner(tmp_git_repo: Path) -> LocalPipelineRunner:
    app_dir = str(Path(__file__).parent.parent.parent)  # team-pivot/
    return LocalPipelineRunner(
        app_dir=app_dir,
        data_space_dir=str(tmp_git_repo),
        llm_backend=PrerecordedBackend.from_dict({
            "generate_summary": {
                "output": {"summary": "Test summary from prerecorded backend"}
            },
        }),
    )


class TestRunnerCodeStep:
    def test_runs_discuss_list_on_empty_data_space(self, runner):
        result = runner.run("discuss-list", {"category": ""})
        assert result.status == "completed"
        assert result.output["threads"] == []

    def test_runs_discuss_new_creates_files(self, runner, make_proposal_draft):
        draft_id = make_proposal_draft(
            title="runner-test", content="# Hello\n\nRunner test content.",
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
        canonical = list((ws / "discussions/test/runner-test").glob("001_*.md"))
        assert len(canonical) == 1
        idx = ws / "index/runner-test-discuss.index.yaml"
        assert idx.exists()

    def test_error_on_missing_params(self, runner, user_workspace):
        result = runner.run("discuss-new", {
            "category": "",
        })
        assert result.status == "error"
        assert "draft_id" in result.error.lower()


class TestRunnerLLMStep:
    def test_llm_step_uses_prerecorded_backend(self, runner, make_proposal_draft):
        draft_id = make_proposal_draft(
            title="llm-test", content="# Proposal that needs LLM summary",
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
        assert "Test summary from prerecorded backend" in summary


class TestRunnerSkipIf:
    def test_nonexistent_pipeline_returns_error(self, runner):
        result = runner.run("nonexistent-pipeline", {})
        assert result.status == "error"
        assert "not found" in result.error.lower()
