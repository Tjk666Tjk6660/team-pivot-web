"""Git operations wrapper. Ported from appv2/tools/git_ops.py.

Assumes system git is available and git credentials are configured externally
(SSH key or embedded token). Raises GitError on command failures.
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional


class GitError(Exception):
    def __init__(self, message: str, command: str, stderr: str):
        super().__init__(message)
        self.command = command
        self.stderr = stderr


def _run(args: list[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitError(
            f"git command failed: {' '.join(args)}",
            command=" ".join(args),
            stderr=e.stderr or "",
        ) from e


def pull(repo_dir: str) -> None:
    """Pull with rebase. Warn (not fail) on transient network errors."""
    try:
        _run(["git", "pull", "--rebase", "origin"], cwd=repo_dir)
    except GitError as e:
        if any(k in e.stderr.lower() for k in ("could not resolve", "network", "timeout")):
            return
        raise


def commit(repo_dir: str, *, message: str, paths: list[str]) -> bool:
    """Stage `paths` and create a commit if anything changed. Returns True if committed."""
    if paths:
        _run(["git", "add", *paths], cwd=repo_dir)
    else:
        _run(["git", "add", "-A"], cwd=repo_dir)
    check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_dir,
    )
    if check.returncode == 0:
        return False
    _run(["git", "commit", "-m", message], cwd=repo_dir)
    return True


def push(repo_dir: str, *, remote: str = "origin", branch: str = "HEAD", max_retries: int = 3) -> None:
    last_error: Optional[GitError] = None
    for attempt in range(max_retries):
        try:
            _run(["git", "push", remote, branch], cwd=repo_dir)
            return
        except GitError as e:
            last_error = e
            if any(k in e.stderr.lower() for k in ("rejected", "non-fast-forward", "conflict")):
                try:
                    pull(repo_dir)
                except GitError:
                    pass
                continue
            time.sleep(1 + attempt)
    assert last_error is not None
    raise last_error


def clone(url: str, target: str) -> None:
    _run(["git", "clone", url, target])


def get_file_author_date(repo_dir: str, file_path: str) -> dict[str, str]:
    """Get the last author and ISO date for a file."""
    proc = _run(
        ["git", "log", "-1", "--format=%an%x09%aI", "--", file_path],
        cwd=repo_dir,
    )
    line = proc.stdout.strip()
    if not line:
        return {"author": "unknown", "date": ""}
    author, date = line.split("\t", 1)
    return {"author": author, "date": date}
