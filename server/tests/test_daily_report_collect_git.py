"""Tests for `server.daily_report.collect_git`. Reuses real git via subprocess
similarly to test_git_ops_log."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from server.daily_report.collect_git import collect_commits
from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# helpers (kept in-file for clarity; mirrors test_git_ops_log style)          #
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, **(env or {})},
    )
    return proc.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--initial-branch=main", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(
    repo: Path, *, file: str, msg: str,
    author_name: str = "Test", author_email: str = "test@example.com",
    when: str = "2026-04-26T10:00:00+08:00",
) -> None:
    (repo / file).write_text("x\n", encoding="utf-8")
    _git(repo, "add", file)
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    _git(repo, "commit", "-m", msg, env=env)


def _window(since: str, until: str) -> TimeWindow:
    return TimeWindow(
        since=datetime.fromisoformat(since),
        until=datetime.fromisoformat(until),
    )


# --------------------------------------------------------------------------- #
# happy paths                                                                 #
# --------------------------------------------------------------------------- #


def test_collect_commits_empty_returns_empty_list(tmp_path):
    """Empty repo → []."""
    repo = tmp_path / "r"
    _init_repo(repo)
    out = collect_commits(
        repo,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_commits_basic(tmp_path):
    """Single commit → CommitRecord with parsed fields."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(
        repo, file="src.py", msg="feat: implement",
        author_name="dengke", author_email="dengke@stacs.cn",
        when="2026-04-26T15:00:00+08:00",
    )
    out = collect_commits(
        repo,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert len(out) == 1
    c = out[0]
    assert c.author_name == "dengke"
    assert c.author_email == "dengke@stacs.cn"
    assert c.subject == "feat: implement"
    assert c.committed_at.tzinfo is not None
    assert c.files_changed == 1
    assert c.insertions == 1
    assert c.deletions == 0
    assert c.matched_pinyin is None    # attribution layer hasn't run


def test_collect_commits_window_filters(tmp_path):
    """Out-of-window commits dropped by git's --since/--until."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="a.txt", msg="early", when="2026-04-25T08:00:00+08:00")
    _commit(repo, file="b.txt", msg="in window", when="2026-04-26T15:00:00+08:00")
    _commit(repo, file="c.txt", msg="late", when="2026-04-28T10:00:00+08:00")

    out = collect_commits(
        repo,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    subjects = [c.subject for c in out]
    assert subjects == ["in window"]


# --------------------------------------------------------------------------- #
# defensive paths                                                             #
# --------------------------------------------------------------------------- #


def test_collect_commits_returns_empty_when_dir_missing(tmp_path):
    """Mirror dir doesn't exist → [] + warning, not exception."""
    out = collect_commits(
        tmp_path / "nope",
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_commits_returns_empty_when_not_a_git_repo(tmp_path):
    """Path exists but no .git → []."""
    plain = tmp_path / "plain"
    plain.mkdir()
    out = collect_commits(
        plain,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
    )
    assert out == []


def test_collect_commits_branch_arg_narrows_scope(tmp_path):
    """Caller can pass branches='main' instead of --all when desired."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="m.txt", msg="main only",
            when="2026-04-26T10:00:00+08:00")
    _git(repo, "checkout", "-b", "side", "-q")
    _commit(repo, file="s.txt", msg="side only",
            when="2026-04-26T11:00:00+08:00")

    out = collect_commits(
        repo,
        _window("2026-04-26T09:30:00+08:00", "2026-04-27T09:30:00+08:00"),
        branches="main",
    )
    assert [c.subject for c in out] == ["main only"]
