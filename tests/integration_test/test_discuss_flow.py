"""Integration test: discuss-new → reply → list → read full flow."""
from pathlib import Path

from tests.ec_simulator.runner import LocalPipelineRunner
from tests.ec_simulator.llm_backends.prerecorded import PrerecordedBackend

import pytest


@pytest.fixture
def runner(tmp_git_repo: Path) -> LocalPipelineRunner:
    app_dir = str(Path(__file__).parent.parent.parent)
    return LocalPipelineRunner(
        app_dir=app_dir,
        data_space_dir=str(tmp_git_repo),
        llm_backend=PrerecordedBackend.from_dict({
            "generate_summary": {
                "output": {"summary": "Integration test summary"}
            },
        }),
        user_id="ken",
    )


class TestFullDiscussFlow:
    def test_new_reply_list_read(self, runner, make_proposal_draft, make_reply_draft):
        # 1. Create new thread
        new_draft = make_proposal_draft(
            title="e2e-flow", content="# E2E Proposal\n\nFull lifecycle test.",
        )
        new_result = runner.run("discuss-new", {
            "draft_id": new_draft,
            "category": "test",
            "mention_users": "",
            "mention_comments": "",
        })
        assert new_result.status == "completed", new_result.error
        assert new_result.output["committed"] is True

        # 2. Reply
        runner.user_id = "shengli"
        reply_draft = make_reply_draft(
            thread="e2e-flow", content="# Reply\n\nI agree with the proposal.",
        )
        reply_result = runner.run("discuss-reply", {
            "draft_id": reply_draft,
            "mention_users": "ken",
            "mention_comments": "",
        })
        assert reply_result.status == "completed", reply_result.error
        assert reply_result.output["post_number"] == 2

        # 3. List
        list_result = runner.run("discuss-list", {"category": "test"})
        assert list_result.status == "completed"
        threads = list_result.output["threads"]
        assert len(threads) == 1
        assert threads[0]["slug"] == "e2e-flow"

        # 4. Read
        read_result = runner.run("discuss-read", {
            "category": "test",
            "thread": "e2e-flow",
        })
        assert read_result.status == "completed"
        posts = read_result.output["posts"]
        assert len(posts) == 2
        assert posts[0]["author"] == "ken"
        assert posts[1]["author"] == "shengli"
