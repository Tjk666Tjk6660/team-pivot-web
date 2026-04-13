"""Pipeline test: discuss-reply full flow."""
from pathlib import Path

from tools import index as index_mod


def _seed_thread(runner, category: str, thread: str):
    """Create a thread via discuss-new so reply has something to reply to."""
    result = runner.run("discuss-new", {
        "category": category,
        "title": thread,
        "content": "# Seed proposal\n\nInitial content.",
        "mention_users": "",
        "mention_comments": "",
    })
    assert result.status == "completed", result.error


class TestDiscussReply:
    def test_appends_reply_to_existing_thread(self, runner):
        _seed_thread(runner, "test", "reply-target")

        result = runner.run("discuss-reply", {
            "category": "test",
            "thread": "reply-target",
            "content": "# My Reply\n\nI agree.",
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "completed", result.error
        assert result.output["committed"] is True
        assert result.output["post_number"] == 2

        ws = Path(runner.workspace_dir)
        replies = list((ws / "discussions/test/reply-target").glob("002_*.md"))
        assert len(replies) == 1

    def test_fails_on_nonexistent_thread(self, runner):
        result = runner.run("discuss-reply", {
            "category": "test",
            "thread": "no-such-thread",
            "content": "# Reply",
            "mention_users": "",
            "mention_comments": "",
        })
        assert result.status == "error"
