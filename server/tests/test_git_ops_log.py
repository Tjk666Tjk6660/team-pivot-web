"""Tests for `server.git_ops.log_commits` — the daily-report read-only
history query helper."""
from __future__ import annotations

import subprocess
from pathlib import Path

from server.git_ops import log_commits, _parse_log_output


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in `repo` and return stdout. Force UTF-8 decoding —
    Windows defaults to GBK which mojibakes Chinese commit data."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
        env={**__import__("os").environ, **(env or {})},
    )
    return proc.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--initial-branch=main", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(
    repo: Path, *, file: str, content: str, msg: str,
    author_name: str = "Test", author_email: str = "test@example.com",
    when: str | None = None,
) -> str:
    """Create file + add + commit. Returns commit sha."""
    (repo / file).write_text(content, encoding="utf-8")
    _git(repo, "add", file)
    env: dict[str, str] = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    _git(repo, "commit", "-m", msg, env=env)
    return _git(repo, "rev-parse", "HEAD").strip()


# --------------------------------------------------------------------------- #
# log_commits — happy path on a real repo                                     #
# --------------------------------------------------------------------------- #


def test_log_commits_empty_window(tmp_path):
    """No commits in window → []."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="a.txt", content="hi\n", msg="init",
            when="2026-04-20T10:00:00+08:00")

    out = log_commits(
        str(repo),
        since="2026-04-25T00:00:00+08:00",
        until="2026-04-26T00:00:00+08:00",
    )
    assert out == []


def test_log_commits_basic_parsing(tmp_path):
    """Single commit with one file change parses with correct fields and stats."""
    repo = tmp_path / "r"
    _init_repo(repo)
    sha = _commit(
        repo, file="src.py", content="x = 1\n", msg="feat: initial impl",
        author_name="邓柯", author_email="dengke@pivot.local",
        when="2026-04-26T10:30:00+08:00",
    )

    out = log_commits(
        str(repo),
        since="2026-04-26T09:30:00+08:00",
        until="2026-04-27T09:30:00+08:00",
    )
    assert len(out) == 1
    c = out[0]
    assert c["sha"] == sha
    assert c["author_name"] == "邓柯"
    assert c["author_email"] == "dengke@pivot.local"
    assert c["subject"] == "feat: initial impl"
    assert c["committed_at"].startswith("2026-04-26T10:30:00")
    assert c["files_changed"] == 1
    assert c["insertions"] == 1
    assert c["deletions"] == 0


def test_log_commits_subject_with_special_chars_does_not_break_parsing(tmp_path):
    """Subjects containing `|`, `,`, quotes — our \\x1e/\\x1f delimiters
    are non-printing ASCII so they don't collide."""
    repo = tmp_path / "r"
    _init_repo(repo)
    weird = "fix: handle a|b, \"quoted\" + 中文 chars"
    _commit(repo, file="x.txt", content="ok\n", msg=weird,
            when="2026-04-26T11:00:00+08:00")

    out = log_commits(
        str(repo),
        since="2026-04-26T09:30:00+08:00",
        until="2026-04-27T09:30:00+08:00",
    )
    assert len(out) == 1
    assert out[0]["subject"] == weird


def test_log_commits_multiple_authors_across_branches(tmp_path):
    """--all crosses branches; commits from feature branch surface too."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="main1.py", content="m\n", msg="main: first",
            author_name="alice", author_email="alice@x.com",
            when="2026-04-26T10:00:00+08:00")

    # Create a feature branch with its own commit.
    _git(repo, "checkout", "-b", "feature/x", "-q")
    _commit(repo, file="feat1.py", content="f\n", msg="feat: branch work",
            author_name="bob", author_email="bob@y.com",
            when="2026-04-26T11:00:00+08:00")
    # Switch back so HEAD is main but feature/x ref still exists.
    _git(repo, "checkout", "main", "-q")
    _commit(repo, file="main2.py", content="m2\n", msg="main: second",
            author_name="alice", author_email="alice@x.com",
            when="2026-04-26T12:00:00+08:00")

    out = log_commits(
        str(repo),
        since="2026-04-26T09:30:00+08:00",
        until="2026-04-27T09:30:00+08:00",
    )
    # Should see all 3 commits, including the one only on feature/x.
    subjects = sorted(c["subject"] for c in out)
    assert subjects == ["feat: branch work", "main: first", "main: second"]


def test_log_commits_window_filters_correctly(tmp_path):
    """Commits outside [since, until) are excluded."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="a.txt", content="a\n", msg="too early",
            when="2026-04-25T08:00:00+08:00")
    _commit(repo, file="b.txt", content="b\n", msg="in window",
            when="2026-04-26T15:00:00+08:00")
    _commit(repo, file="c.txt", content="c\n", msg="too late",
            when="2026-04-28T09:00:00+08:00")

    out = log_commits(
        str(repo),
        since="2026-04-26T09:30:00+08:00",
        until="2026-04-27T09:30:00+08:00",
    )
    subjects = [c["subject"] for c in out]
    assert subjects == ["in window"]


def test_log_commits_branch_arg_can_narrow_scope(tmp_path):
    """If caller passes a specific ref instead of --all, only that ref shows."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, file="m.txt", content="m\n", msg="main only",
            when="2026-04-26T10:00:00+08:00")
    _git(repo, "checkout", "-b", "side", "-q")
    _commit(repo, file="s.txt", content="s\n", msg="side only",
            when="2026-04-26T11:00:00+08:00")

    out = log_commits(
        str(repo),
        since="2026-04-26T09:30:00+08:00",
        until="2026-04-27T09:30:00+08:00",
        branches="main",
    )
    subjects = [c["subject"] for c in out]
    assert subjects == ["main only"]


# --------------------------------------------------------------------------- #
# _parse_log_output — fast unit tests on synthetic git log output             #
# --------------------------------------------------------------------------- #


def _synth(*records: tuple[str, str]) -> str:
    """Build synthetic git log output. Each record is (pretty_line, shortstat).
    pretty_line is just the field-separator-joined string (no leading marker;
    we add it). Pass shortstat="" for commits without file changes."""
    SEP = "\x1e"
    parts = []
    for pretty, stat in records:
        parts.append(SEP + pretty)
        if stat:
            parts.append("\n\n " + stat)
        parts.append("\n")
    return "".join(parts)


def test_parse_handles_commit_without_shortstat():
    """Merge commits or empty commits have no shortstat line; should default
    files/ins/dels to 0."""
    SEP = "\x1f"
    pretty = SEP.join(
        ["abc1234", "x@x.com", "x", "2026-04-26T10:00:00+08:00", "merge: nothing changed"]
    )
    out = _parse_log_output(_synth((pretty, "")))
    assert len(out) == 1
    assert out[0]["files_changed"] == 0
    assert out[0]["insertions"] == 0
    assert out[0]["deletions"] == 0


def test_parse_shortstat_only_insertions():
    """Pure-add commit: shortstat omits the deletions clause."""
    SEP = "\x1f"
    pretty = SEP.join(
        ["abc1234", "x@x.com", "x", "2026-04-26T10:00:00+08:00", "add file"]
    )
    out = _parse_log_output(_synth((pretty, "1 file changed, 5 insertions(+)")))
    assert out[0]["files_changed"] == 1
    assert out[0]["insertions"] == 5
    assert out[0]["deletions"] == 0


def test_parse_shortstat_only_deletions():
    """Pure-delete commit: shortstat omits the insertions clause."""
    SEP = "\x1f"
    pretty = SEP.join(
        ["abc1234", "x@x.com", "x", "2026-04-26T10:00:00+08:00", "remove file"]
    )
    out = _parse_log_output(_synth((pretty, "1 file changed, 3 deletions(-)")))
    assert out[0]["files_changed"] == 1
    assert out[0]["insertions"] == 0
    assert out[0]["deletions"] == 3


def test_parse_shortstat_pluralization():
    """N files / insertions / deletions vs 1 file — both forms accepted."""
    SEP = "\x1f"
    pretty = SEP.join(
        ["abc1234", "x@x.com", "x", "2026-04-26T10:00:00+08:00", "many"]
    )
    out = _parse_log_output(
        _synth((pretty, "5 files changed, 120 insertions(+), 30 deletions(-)"))
    )
    assert out[0]["files_changed"] == 5
    assert out[0]["insertions"] == 120
    assert out[0]["deletions"] == 30


def test_parse_skips_malformed_pretty_line(caplog):
    """A chunk with too few field separators is logged + skipped, doesn't crash."""
    SEP = "\x1f"
    good = SEP.join(
        ["abc1234", "x@x.com", "x", "2026-04-26T10:00:00+08:00", "good"]
    )
    bad = "missing-fields"   # only 1 field, no separators
    out = _parse_log_output(_synth((bad, ""), (good, "1 file changed, 1 insertion(+)")))
    # bad chunk skipped, good one parsed
    assert len(out) == 1
    assert out[0]["sha"] == "abc1234"


def test_parse_empty_output():
    """No records in input → empty list."""
    assert _parse_log_output("") == []
