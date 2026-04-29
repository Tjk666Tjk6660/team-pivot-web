from __future__ import annotations

import logging
import re
import subprocess
import time

log = logging.getLogger(__name__)


class GitError(Exception):
    def __init__(self, message: str, command: str, stderr: str) -> None:
        super().__init__(message)
        self.command = command
        self.stderr = stderr


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    start = time.monotonic()
    log.debug("git %s cwd=%s", " ".join(args[1:]) if len(args) > 1 else "", cwd or ".")
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        log.debug("git %s ok elapsed=%.0fms", args[1] if len(args) > 1 else "",
                  (time.monotonic() - start) * 1000)
        return proc
    except subprocess.CalledProcessError as e:
        log.warning("git failed cmd=%s stderr=%s",
                    " ".join(args), (e.stderr or "").strip()[:200])
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
    try:
        _run(args)
        return
    except GitError as e:
        if not branch or f"Remote branch {branch} not found" not in e.stderr:
            raise
        log.warning(
            "git clone branch missing branch=%s; retrying plain clone to support empty/default-branch repos",
            branch,
        )

    _run(["git", "clone", url, target])
    if branch:
        align_unborn_head(target, branch)


def align_unborn_head(repo_dir: str, branch: str) -> None:
    head_check = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if head_check.returncode == 0:
        return
    _run(["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=repo_dir)


def set_remote_url(repo_dir: str, remote: str, url: str) -> None:
    _run(["git", "remote", "set-url", remote, url], cwd=repo_dir)


def pull(repo_dir: str) -> None:
    try:
        _run(["git", "pull", "--rebase", "origin"], cwd=repo_dir)
    except GitError as e:
        if "no such ref was fetched" in e.stderr.lower():
            return
        if any(k in e.stderr.lower() for k in ("could not resolve", "network", "timeout")):
            return
        if "unstaged changes" in e.stderr.lower() or "cannot pull with rebase" in e.stderr.lower():
            log.warning("pull blocked by local dirty state; committing and retrying")
            _run(["git", "add", "-A"], cwd=repo_dir)
            _run(["git", "commit", "-m", "chore: auto-commit dirty state before pull",
                  "--author", "team-pivot-web <team-pivot-web@pivot.local>"], cwd=repo_dir)
            try:
                _run(["git", "push", "origin", "HEAD"], cwd=repo_dir)
            except GitError:
                log.warning("auto-commit push failed; proceeding with pull anyway")
            _run(["git", "pull", "--rebase", "origin"], cwd=repo_dir)
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
                log.warning("git push rejected, rebase+retry attempt=%d", attempt + 1)
                try:
                    pull(repo_dir)
                except GitError:
                    pass
                continue
            time.sleep(1 + attempt)
    assert last_error is not None
    raise last_error


def head_short(repo_dir: str) -> str | None:
    try:
        proc = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir)
    except GitError as e:
        if "Needed a single revision" in e.stderr:
            return None
        raise
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Read-only history queries (used by daily-report)
# ---------------------------------------------------------------------------

# Use ASCII unit/record separators as field/commit delimiters in the pretty
# format. They are non-printing control chars that no human types into a
# commit subject, so parsing stays robust against `|`, `,`, multiline body,
# etc. in user-authored content.
_LOG_FIELD_SEP = "\x1f"
_LOG_RECORD_SEP = "\x1e"
_LOG_PRETTY = (
    f"format:{_LOG_RECORD_SEP}%H{_LOG_FIELD_SEP}%ae"
    f"{_LOG_FIELD_SEP}%an{_LOG_FIELD_SEP}%aI{_LOG_FIELD_SEP}%s"
)
_SHORTSTAT_RE = re.compile(
    r"^\s*(\d+)\s+files?\s+changed"
    r"(?:,\s+(\d+)\s+insertions?\(\+\))?"
    r"(?:,\s+(\d+)\s+deletions?\(-\))?\s*$"
)


def log_commits(
    repo_dir: str,
    *,
    since: str,
    until: str,
    branches: str = "--all",
) -> list[dict]:
    """Run `git log` over a time window and return parsed commit records.

    Each record dict carries:
      sha             full hex sha
      author_email    %ae
      author_name     %an
      committed_at    ISO8601 with tz (%aI)
      subject         %s
      files_changed   from --shortstat (0 if absent / merge commit)
      insertions      from --shortstat
      deletions       from --shortstat

    `since` / `until` accept any value `git log --since/--until` understands
    (ISO 8601 with timezone recommended for unambiguous boundaries).

    `branches` is a single argv token: `--all` (default, scan all refs),
    `main`, or several refs space-separated.

    Empty repos return [] silently. Other git failures raise GitError.
    """
    args = [
        "git", "log", branches,
        f"--since={since}",
        f"--until={until}",
        f"--pretty={_LOG_PRETTY}",
        "--shortstat",
        "--date-order",
    ]
    try:
        proc = _run(args, cwd=repo_dir)
    except GitError as e:
        # Brand-new repo with no commits yet — caller doesn't care.
        if "does not have any commits yet" in e.stderr.lower():
            return []
        raise
    return _parse_log_output(proc.stdout)


def _parse_log_output(output: str) -> list[dict]:
    """Parse `git log --pretty=...record-sep... --shortstat` output.

    Each commit chunk starts with the record separator we embed in the
    pretty format, followed by 5 field-separated values on the first line,
    then optionally a blank line + shortstat line if files were changed.
    """
    commits: list[dict] = []
    chunks = output.split(_LOG_RECORD_SEP)
    # chunks[0] is empty (or whitespace) — content before the first marker.
    for chunk in chunks[1:]:
        first_nl = chunk.find("\n")
        if first_nl < 0:
            pretty_part = chunk
            rest = ""
        else:
            pretty_part = chunk[:first_nl]
            rest = chunk[first_nl + 1:]

        fields = pretty_part.split(_LOG_FIELD_SEP, 4)
        if len(fields) != 5:
            log.warning(
                "log_commits: malformed pretty line, skipping: %r",
                pretty_part[:120],
            )
            continue
        sha, email, name, iso, subject = fields

        files = ins = dels = 0
        for line in rest.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            m = _SHORTSTAT_RE.match(stripped)
            if m:
                files = int(m.group(1))
                ins = int(m.group(2) or 0)
                dels = int(m.group(3) or 0)
                break

        commits.append({
            "sha": sha,
            "author_email": email,
            "author_name": name,
            "committed_at": iso,
            "subject": subject,
            "files_changed": files,
            "insertions": ins,
            "deletions": dels,
        })
    return commits
