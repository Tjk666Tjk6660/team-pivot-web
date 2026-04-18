from __future__ import annotations

import subprocess
import time


class GitError(Exception):
    def __init__(self, message: str, command: str, stderr: str) -> None:
        super().__init__(message)
        self.command = command
        self.stderr = stderr


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitError(
            f"git command failed: {' '.join(args)}",
            command=" ".join(args),
            stderr=e.stderr or "",
        ) from e


def clone(url: str, target: str, branch: str | None = None) -> None:
    args = ["git", "clone"]
    if branch:
        args += ["--branch", branch]
    args += [url, target]
    _run(args)


def pull(repo_dir: str) -> None:
    try:
        _run(["git", "pull", "--rebase", "origin"], cwd=repo_dir)
    except GitError as e:
        if any(k in e.stderr.lower() for k in ("could not resolve", "network", "timeout")):
            return
        raise


def commit(
    repo_dir: str,
    *,
    message: str,
    paths: list[str],
    author: str | None = None,
    committer_name: str | None = None,
    committer_email: str | None = None,
) -> bool:
    if paths:
        _run(["git", "add", *paths], cwd=repo_dir)
    else:
        _run(["git", "add", "-A"], cwd=repo_dir)
    check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir)
    if check.returncode == 0:
        return False
    args = ["git"]
    if committer_name:
        args += ["-c", f"user.name={committer_name}"]
    if committer_email:
        args += ["-c", f"user.email={committer_email}"]
    args += ["commit", "-m", message]
    if author:
        args += ["--author", author]
    _run(args, cwd=repo_dir)
    return True


def push(repo_dir: str, *, remote: str = "origin", branch: str = "HEAD", max_retries: int = 3) -> None:
    last_error: GitError | None = None
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


def head_short(repo_dir: str) -> str:
    proc = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir)
    return proc.stdout.strip()
