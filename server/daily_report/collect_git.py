"""Collect git commits from the team-pivot-web code mirror workspace.

Thin adapter over `server.git_ops.log_commits` that:
  - parses the raw dict records into typed `CommitRecord`
  - converts `committed_at` ISO strings into tz-aware datetimes
  - swallows GitError into an empty list (caller already standardized
    on "fetch / collect failures degrade, don't kill the report")"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from server.daily_report.types import CommitRecord, TimeWindow
from server.git_ops import GitError, log_commits

log = logging.getLogger("server.daily_report.collect_git")


def collect_commits(
    code_repo_dir: Path,
    window: TimeWindow,
    *,
    branches: str = "--all",
) -> list[CommitRecord]:
    """Return commits in the half-open window [since, until) from the local
    code mirror at `code_repo_dir`. Defensive against missing/uninitialized
    mirror, git failures, and unparseable timestamps."""
    if not code_repo_dir.is_dir() or not (code_repo_dir / ".git").exists():
        log.warning(
            "code_repo_dir is missing or not a git repo: %s — has the "
            "mirror been cloned? (see daily-report README §setup)",
            code_repo_dir,
        )
        return []

    try:
        raw = log_commits(
            str(code_repo_dir),
            since=window.since.isoformat(),
            until=window.until.isoformat(),
            branches=branches,
        )
    except GitError as e:
        log.warning("git log failed in %s: %s",
                    code_repo_dir, e.stderr.strip()[:200])
        return []

    out: list[CommitRecord] = []
    for c in raw:
        dt = _parse_iso(c.get("committed_at"))
        if dt is None:
            log.warning(
                "commit %s has unparseable committed_at=%r; skipping",
                c.get("sha"), c.get("committed_at"),
            )
            continue
        out.append(CommitRecord(
            sha=str(c.get("sha") or ""),
            author_name=str(c.get("author_name") or ""),
            author_email=str(c.get("author_email") or ""),
            committed_at=dt,
            subject=str(c.get("subject") or ""),
            files_changed=int(c.get("files_changed") or 0),
            insertions=int(c.get("insertions") or 0),
            deletions=int(c.get("deletions") or 0),
        ))
    return out


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
