"""Tests for git_ops module."""
import subprocess
from pathlib import Path

import pytest

from tools import git_ops


class TestGitOps:
    def test_pull_succeeds_on_clean_repo(self, tmp_git_repo: Path):
        git_ops.pull(str(tmp_git_repo))

    def test_commit_creates_commit_when_changes_exist(self, tmp_git_repo: Path):
        (tmp_git_repo / "NEW.md").write_text("new content\n")
        result = git_ops.commit(
            str(tmp_git_repo),
            message="add NEW.md",
            paths=["NEW.md"],
        )
        assert result is True
        log = subprocess.check_output(
            ["git", "-C", str(tmp_git_repo), "log", "--oneline"]
        ).decode()
        assert "add NEW.md" in log

    def test_commit_returns_false_when_no_changes(self, tmp_git_repo: Path):
        result = git_ops.commit(
            str(tmp_git_repo),
            message="no-op",
            paths=[],
        )
        assert result is False

    def test_push_succeeds(self, tmp_git_repo: Path):
        (tmp_git_repo / "NEW.md").write_text("new content\n")
        git_ops.commit(str(tmp_git_repo), message="add NEW.md", paths=["NEW.md"])
        git_ops.push(str(tmp_git_repo))
        remote_log = subprocess.check_output(
            ["git", "-C", str(tmp_git_repo), "log", "origin/main", "--oneline"]
        ).decode()
        assert "add NEW.md" in remote_log

    def test_get_author_and_date(self, tmp_git_repo: Path):
        (tmp_git_repo / "A.md").write_text("a\n")
        git_ops.commit(str(tmp_git_repo), message="add A", paths=["A.md"])
        info = git_ops.get_file_author_date(str(tmp_git_repo), "A.md")
        assert info["author"] == "t"
        assert info["date"].startswith("2")
