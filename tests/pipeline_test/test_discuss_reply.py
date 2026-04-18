"""Pipeline test: discuss-reply full flow."""
from pathlib import Path

from tools import index as index_mod


def _seed_thread(runner, make_proposal_draft, category: str, thread: str):
    """Create a thread via discuss-new so reply has something to reply to."""
    draft_id = make_proposal_draft(
        title=thread, content="# Seed proposal\n\nInitial content.",
    )
    result = runner.run("discuss-new", {
        "draft_id": draft_id,
        "category": category,
        "mention_users": "",
        "mention_comments": "",
    })
    assert result.status == "completed", result.error


class TestDiscussReply:
    def test_appends_reply_to_existing_thread(self, runner, make_proposal_draft, make_reply_draft):
        _seed_thread(runner, make_proposal_draft, "test", "reply-target")

        reply_draft = make_reply_draft(
            thread="reply-target", content="# My Reply\n\nI agree.",
        )
        result = runner.run("discuss-reply", {
            "draft_id": reply_draft,
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "completed", result.error
        assert result.output["committed"] is True
        assert result.output["post_number"] == 2

        ws = Path(runner.data_space_dir)
        replies = list((ws / "discussions/test/reply-target").glob("002_*.md"))
        assert len(replies) == 1

    def test_fails_on_nonexistent_thread(self, runner, make_reply_draft):
        reply_draft = make_reply_draft(
            thread="no-such-thread", content="# Reply",
        )
        result = runner.run("discuss-reply", {
            "draft_id": reply_draft,
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "error"
