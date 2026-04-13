"""Pipeline test: discuss-status (close/pending/reopen)."""
from pathlib import Path


def _seed_thread(runner, category: str, thread: str):
    result = runner.run("discuss-new", {
        "category": category,
        "title": thread,
        "content": "# Seed",
        "mention_users": "",
        "mention_comments": "",
    })
    assert result.status == "completed", result.error


class TestDiscussStatus:
    def test_close_thread(self, runner):
        _seed_thread(runner, "test", "close-me")
        result = runner.run("discuss-status", {
            "category": "test",
            "thread": "close-me",
            "action": "close",
            "reason": "",
        })
        assert result.status == "completed", result.error
        assert result.output["new_status"] == "closed"

    def test_pending_thread(self, runner):
        _seed_thread(runner, "test", "pend-me")
        result = runner.run("discuss-status", {
            "category": "test",
            "thread": "pend-me",
            "action": "pending",
            "reason": "",
        })
        assert result.status == "completed", result.error
        assert result.output["new_status"] == "pending"

    def test_reopen_requires_reason(self, runner):
        _seed_thread(runner, "test", "reopen-me")
        runner.run("discuss-status", {
            "category": "test",
            "thread": "reopen-me",
            "action": "close",
            "reason": "",
        })
        result = runner.run("discuss-status", {
            "category": "test",
            "thread": "reopen-me",
            "action": "reopen",
            "reason": "",
        })
        assert result.status == "error"

    def test_reopen_with_reason(self, runner):
        _seed_thread(runner, "test", "reopen2")
        runner.run("discuss-status", {
            "category": "test",
            "thread": "reopen2",
            "action": "close",
            "reason": "",
        })
        result = runner.run("discuss-status", {
            "category": "test",
            "thread": "reopen2",
            "action": "reopen",
            "reason": "new info",
        })
        assert result.status == "completed", result.error
        assert result.output["new_status"] == "open"
