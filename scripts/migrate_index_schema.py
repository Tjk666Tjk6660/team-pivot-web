#!/usr/bin/env python3
"""One-time migration: legacy thread index → matter index.

Design: AI-docs/coding-test-plan/index-migration-plan.md

Usage:
    uv run python scripts/migrate_index_schema.py --workspace <path> [--apply]
                                                  [--slug SLUG] [--report FILE]
                                                  [--db-path PATH]

Default mode is dry-run (no disk writes, no commit). Pass --apply to actually
land the migration; the script does NOT push — operator pushes after verifying.

`migrate_one` is a pure function (reads only). `apply_migration` orchestrates
the writes: rename MDs → write new index yaml → rewrite MD frontmatter type
→ delete legacy yaml → single git commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.posts import read_post, write_post  # noqa: E402
from server.publish import _resolve_mentions_for_index  # noqa: E402


# --------------------------------------------------------------------------- #
# Mapping rules (mirrors plan §映射规则)                                        #
# --------------------------------------------------------------------------- #

# legacy thread.status → matter.current_status
STATUS_MAP: dict[str, str] = {
    "open": "planning",
    "pending": "planning",
    "concluded": "executing",   # via pivot act
    "produced": "executing",    # via pivot act
    "closed": "cancelled",
}

# Statuses that synthesize a planning→executing status_change on a pivot file.
EXECUTING_FROM_STATUSES: frozenset[str] = frozenset({"concluded", "produced"})

LEGACY_INDEX_GLOB = "*-discuss.index.yaml"
LEGACY_INDEX_SUFFIX = "-discuss.index.yaml"

# Filename: NNN_<author>_<type>_<hash>.md — author/type can't contain "_"
# (pinyin per server/users.py:PINYIN_RE has no underscore; type tokens are
# atomic words). Anything else is logged as a warning and left untouched.
FILENAME_RE = re.compile(r"^(\d{3})_([^_]+)_([^_]+)_([a-f0-9]{6})\.md$")

COMMIT_MESSAGE = "chore: migrate legacy thread indexes to matter format"


# --------------------------------------------------------------------------- #
# Data structures                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class MigrationItem:
    """Per-thread migration plan returned by migrate_one().

    Paths are absolute; new_index_data is the dict to write to new_index_path.
    md_renames is [(old_abs, new_abs)]; md_frontmatter_updates is
    [(new_abs, new_type)] — applied AFTER renames so the path resolves.
    """
    legacy_index_path: Path
    new_index_path: Path
    new_index_data: dict
    md_renames: list[tuple[Path, Path]] = field(default_factory=list)
    md_frontmatter_updates: list[tuple[Path, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    """Aggregate report for a migration run."""
    workspace: str
    dry_run: bool
    legacy_count: int = 0
    migrated_count: int = 0
    skipped_count: int = 0
    threads: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pre-flight checks                                                           #
# --------------------------------------------------------------------------- #


def preflight_checks(workspace: Path, *, strict: bool) -> list[str]:
    """Return list of failure messages (empty = pass).

    `strict=True` is enforced for --apply: rejects dirty working tree, wrong
    branch, or being behind origin/main. `strict=False` (dry-run) skips the
    "clean working tree" hard rule so users can preview in WIP state.
    """
    failures: list[str] = []

    if not (workspace / ".git").is_dir():
        failures.append(f"workspace is not a git repo: {workspace}")
        return failures

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True, text=True, check=False,
        )

    if strict:
        st = _git("status", "--porcelain")
        if st.stdout.strip():
            failures.append(
                "working tree not clean (refusing to mix migration with WIP):\n"
                + st.stdout
            )

    br = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = br.stdout.strip()
    if branch != "main":
        failures.append(f"not on main branch (current: {branch!r})")

    if strict:
        # 必须有 origin/main ref;否则同步检查会假阳性放过
        verify = _git("rev-parse", "--verify", "--quiet", "origin/main")
        if verify.returncode != 0:
            failures.append(
                "origin/main ref not found locally; ensure remote is "
                "configured and `git fetch origin main` succeeds"
            )
            return failures

        _git("fetch", "origin", "main")
        ahead_behind = _git(
            "rev-list", "--left-right", "--count", "main...origin/main"
        )
        parts = ahead_behind.stdout.strip().split()
        if len(parts) == 2:
            _ahead, behind = int(parts[0]), int(parts[1])
            if behind > 0:
                failures.append(
                    f"local main is behind origin/main by {behind} commit(s); "
                    "pull/rebase first"
                )

    return failures


# --------------------------------------------------------------------------- #
# Discover legacy indexes                                                     #
# --------------------------------------------------------------------------- #


def discover_legacy(index_dir: Path) -> list[Path]:
    """Return all legacy *-discuss.index.yaml paths, sorted for determinism."""
    if not index_dir.is_dir():
        return []
    return sorted(index_dir.glob(LEGACY_INDEX_GLOB))


def slug_from_legacy_path(legacy_index_path: Path) -> str:
    """`{slug}-discuss.index.yaml` → `{slug}`."""
    name = legacy_index_path.name
    if not name.endswith(LEGACY_INDEX_SUFFIX):
        raise ValueError(f"not a legacy index file: {legacy_index_path}")
    return name[: -len(LEGACY_INDEX_SUFFIX)]


# --------------------------------------------------------------------------- #
# Pure migration logic (migrate_one)                                          #
# --------------------------------------------------------------------------- #


def migrate_one(
    workspace: Path,
    legacy_index_path: Path,
    *,
    users_repo=None,
) -> MigrationItem:
    """Pure function: read legacy yaml → return MigrationItem.

    Only IO reads (no writes). `users_repo` is an optional UserRepo used for
    open_id → pinyin resolution in mention.comments[].mentions; if None, all
    mentions fall through to open_id literal (acceptable for unit tests).

    Algorithm (per plan §3 / §4): timeline-driven + files-supplemented merge.

      1. Index legacy.timeline by file: which "X created thread"/"X replied"
         event birthed each file. Event.time → created_at; event prefix →
         creator/owner. Event.mention (if any) → first comment.
      2. For each entry in legacy.discussions[0].files[i], build a timeline
         item using metadata from step 1, plus summary/refs from the entry.
      3. Apply pivot logic for concluded/produced statuses.
      4. Walk timeline a second time for standalone "X mentioned" events,
         routing each to the matching item's comments[].
      5. Sort each item's comments[] by created_at (so the first-from-event
         mention naturally lands at index 0).
    """
    discussions_dir = workspace / "discussions"
    index_dir = workspace / "index"

    with open(legacy_index_path, encoding="utf-8") as f:
        legacy = yaml.safe_load(f) or {}

    discussions = legacy.get("discussions") or []
    if not discussions:
        raise ValueError(f"legacy index has no discussions[]: {legacy_index_path}")

    discussion = discussions[0]
    legacy_status = str(discussion.get("status") or "open")
    legacy_files = discussion.get("files") or []
    legacy_timeline = legacy.get("timeline") or []
    origin_path = str(discussion.get("path") or "").rstrip("/")
    # origin_path = "discussions/<category>/<slug>"
    parts = origin_path.split("/")
    if len(parts) != 3 or parts[0] != "discussions":
        raise ValueError(f"unexpected discussion path: {origin_path!r}")
    category, slug = parts[1], parts[2]

    # Sanity: filename slug ↔ path slug
    file_slug = slug_from_legacy_path(legacy_index_path)
    if file_slug != slug:
        raise ValueError(
            f"slug mismatch: filename slug={file_slug!r} but path slug={slug!r}"
        )

    new_status = STATUS_MAP.get(legacy_status, "planning")
    warnings: list[str] = []

    # ---- Index timeline events by old filename ----
    # creation_event_by_file: old_filename → the "X created thread"/"X replied"
    # event that birthed this file (used to source created_at + creator + first
    # comment from carried mention).
    creation_event_by_file: dict[str, dict] = _index_creation_events(
        legacy_timeline
    )

    # ---- Determine pivot (the file that becomes act for executing migration) ----
    pivot_filename: str | None = None
    if legacy_status in EXECUTING_FROM_STATUSES:
        pivot_filename = _select_pivot(legacy_files, warnings)
        if pivot_filename is None:
            # plan §1 边界覆盖了"有 proposal 无 reply" → proposal 当 pivot;但
            # 这里走到 None 说明 legacy_files 完全为空或全部 unparseable,属于
            # 数据损坏。不静默降级——抛错让运维肉眼看到,经手工核查后再决定
            # 是修数据还是 plan 补口径。
            raise ValueError(
                f"status={legacy_status} but no usable files for pivot "
                f"(empty or all unparseable filenames); refusing to migrate"
            )

    # ---- Build rename_map: old_filename → new_filename ----
    rename_map: dict[str, str] = {}
    # processed in order of legacy_files (== NNN-monotonic == natural timeline order)
    processed: list[dict] = []
    for f_entry in legacy_files:
        old_filename = str(f_entry.get("path") or "")
        if not old_filename:
            warnings.append("skipping files[] entry with empty path")
            continue
        new_type = "act" if old_filename == pivot_filename else "think"
        m = FILENAME_RE.match(old_filename)
        if not m:
            warnings.append(
                f"unparseable legacy filename {old_filename!r}; "
                "skipping rename + treating as think"
            )
            new_filename = old_filename  # leave name as-is, still map type
            new_type = "act" if old_filename == pivot_filename else "think"
        else:
            nnn, author_seg, _old_type_seg, hash_seg = m.groups()
            new_filename = f"{nnn}_{author_seg}_{new_type}_{hash_seg}.md"
        rename_map[old_filename] = new_filename
        processed.append({
            "old_filename": old_filename,
            "new_filename": new_filename,
            "new_type": new_type,
            "summary": str(f_entry.get("summary") or ""),
            "refs": list(f_entry.get("refs") or []),
        })

    # ---- Build new timeline (file items, driven by legacy_files order) ----
    new_timeline: list[dict] = []
    for fp in processed:
        item = _build_item_from_event(
            fp,
            origin_path=origin_path,
            rename_map=rename_map,
            creation_event=creation_event_by_file.get(fp["old_filename"]),
            users_repo=users_repo,
            warnings=warnings,
        )
        # Pivot gets status_change planning→executing
        if pivot_filename is not None and fp["old_filename"] == pivot_filename:
            item["status_change"] = {"from": "planning", "to": "executing"}
        new_timeline.append(item)

    # ---- Process standalone "X mentioned" events → comments[] ----
    _apply_standalone_mentions_to_timeline(
        legacy_timeline,
        new_timeline,
        rename_map=rename_map,
        users_repo=users_repo,
        warnings=warnings,
    )

    # ---- Sort comments by created_at within each item (defensive) ----
    for item in new_timeline:
        if "comments" in item:
            item["comments"].sort(key=lambda c: c.get("created_at") or "")

    # ---- Build matter header (title still needs MD read for fallback) ----
    matter_title = _derive_title(
        legacy_files, discussions_dir / category / slug, slug
    )
    matter_created_at = str(legacy.get("created") or "")
    matter_updated_at = str(legacy.get("last_updated") or matter_created_at)

    # ---- Compose new matter index dict ----
    new_index_data: dict = {
        "version": 1,
        "matter": {
            "id": slug,
            "title": matter_title,
            "current_status": new_status,
            "created_at": matter_created_at,
            "updated_at": matter_updated_at,
        },
        "timeline": new_timeline,
    }

    # ---- Compute md_renames + md_frontmatter_updates ----
    md_renames: list[tuple[Path, Path]] = []
    md_frontmatter_updates: list[tuple[Path, str]] = []
    for fp in processed:
        old_path = discussions_dir / category / slug / fp["old_filename"]
        new_path = discussions_dir / category / slug / fp["new_filename"]
        if old_path != new_path:
            md_renames.append((old_path, new_path))
        md_frontmatter_updates.append((new_path, fp["new_type"]))

    new_index_path = index_dir / f"{slug}.index.yaml"
    return MigrationItem(
        legacy_index_path=legacy_index_path,
        new_index_path=new_index_path,
        new_index_data=new_index_data,
        md_renames=md_renames,
        md_frontmatter_updates=md_frontmatter_updates,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Helpers (pure)                                                              #
# --------------------------------------------------------------------------- #


def _select_pivot(legacy_files: list[dict], warnings: list[str]) -> str | None:
    """Pick the pivot per plan §2 Rule:
    - max NNN reply (frontmatter type=reply via filename segment)
    - if no reply, fall back to proposal
    - if no files at all, return None (caller degrades)
    """
    replies: list[tuple[int, str]] = []
    proposals: list[tuple[int, str]] = []
    for f in legacy_files:
        name = str(f.get("path") or "")
        m = FILENAME_RE.match(name)
        if not m:
            continue
        nnn = int(m.group(1))
        type_seg = m.group(3)
        if type_seg == "reply":
            replies.append((nnn, name))
        elif type_seg == "proposal":
            proposals.append((nnn, name))
    if replies:
        replies.sort(key=lambda t: t[0])
        return replies[-1][1]
    if proposals:
        proposals.sort(key=lambda t: t[0])
        return proposals[-1][1]
    return None


def _derive_title(
    legacy_files: list[dict], thread_dir: Path, slug_fallback: str
) -> str:
    """Three-level fallback per plan §5: first-file frontmatter.title →
    first-file body H1 → slug. Mirrors server/threads.py::_thread_meta."""
    if not legacy_files:
        return slug_fallback
    first_name = str(legacy_files[0].get("path") or "")
    first_path = thread_dir / first_name
    try:
        post = read_post(first_path)
    except Exception:
        return slug_fallback
    fm_title = post.frontmatter.get("title")
    if fm_title:
        return str(fm_title).strip() or slug_fallback
    for line in post.body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip() or slug_fallback
        if line:
            break
    return slug_fallback


def _index_creation_events(legacy_timeline: list[dict]) -> dict[str, dict]:
    """Index the legacy timeline by file: which "X created thread"/"X replied"
    event birthed each file. Returns {old_filename: event_dict}.

    Per plan §3, each file's authoritative created_at and creator come from
    these events (not MD frontmatter). The event's `mention` field, if any,
    is also harvested here (deferred to _build_item_from_event).
    """
    by_file: dict[str, dict] = {}
    for ev in legacy_timeline:
        e = str(ev.get("event") or "")
        if "created thread" not in e and "replied" not in e:
            continue
        file_path = str(ev.get("file") or "")
        if not file_path:
            continue
        old_filename = file_path.rsplit("/", 1)[-1]
        # Last write wins if duplicates exist (shouldn't happen in well-formed
        # legacy data, but cheap to be defensive).
        by_file[old_filename] = ev
    return by_file


def _build_item_from_event(
    fp: dict,
    *,
    origin_path: str,
    rename_map: dict[str, str],
    creation_event: dict | None,
    users_repo,
    warnings: list[str],
) -> dict:
    """Build one matter timeline item, sourcing time/creator from the legacy
    timeline event that birthed the file (per plan §3) and metadata from the
    files[] entry. If the event carries a mention, attach as the first comment.
    """
    new_filename = fp["new_filename"]
    file_path = f"{origin_path}/{new_filename}"

    # ---- Source created_at + creator from the timeline event (plan §3) ----
    created_at = ""
    creator = "unknown"
    first_comment: dict | None = None
    if creation_event is None:
        warnings.append(
            f"file {fp['old_filename']} has no 'created thread'/'replied' "
            "event in legacy timeline; created_at/creator unknown"
        )
    else:
        created_at = str(creation_event.get("time") or "")
        event_str = str(creation_event.get("event") or "")
        if event_str:
            creator = event_str.split(" ", 1)[0]
        # Carry mention as the file's first comment (plan §4).
        mention = creation_event.get("mention") or {}
        if mention.get("users") or mention.get("comments"):
            first_comment = _mention_to_comment(
                mention,
                time=created_at,
                author=creator,
                users_repo=users_repo,
            )

    # ---- quote / refer from refs[] (apply rename_map to in-thread paths) ----
    quote: str | None = None
    refer: list[str] = []
    from_refs = [r for r in fp["refs"] if r.get("type") == "from"]
    refer_refs = [r for r in fp["refs"] if r.get("type") == "refer"]
    if len(from_refs) > 1:
        warnings.append(
            f"file {fp['old_filename']} has {len(from_refs)} 'from' refs; "
            "took the first one as quote"
        )
    if from_refs:
        quote = _rewrite_ref_path(from_refs[0].get("path"), rename_map)
    for r in refer_refs:
        new = _rewrite_ref_path(r.get("path"), rename_map)
        if new is not None:
            refer.append(new)

    item: dict = {
        "file": file_path,
        "created_at": created_at,
        "creator": creator,
        "owner": creator,                       # legacy has no owner concept
        "type": fp["new_type"],
        "summary": fp["summary"],
    }
    if quote is not None:
        item["quote"] = quote
    if refer:
        item["refer"] = refer
    if first_comment is not None:
        item["comments"] = [first_comment]
    return item


def _rewrite_ref_path(
    ref_path: str | None, rename_map: dict[str, str]
) -> str | None:
    """If `ref_path` ends with a filename in our rename_map, swap it out;
    otherwise return as-is. Cross-thread refs (different slug) pass through."""
    if not ref_path:
        return None
    last_slash = ref_path.rfind("/")
    if last_slash < 0:
        return ref_path
    prefix, fname = ref_path[: last_slash + 1], ref_path[last_slash + 1 :]
    if fname in rename_map:
        return prefix + rename_map[fname]
    return ref_path


def _apply_standalone_mentions_to_timeline(
    legacy_events: list[dict],
    new_timeline: list[dict],
    *,
    rename_map: dict[str, str],
    users_repo,
    warnings: list[str],
) -> None:
    """Walk legacy event log, route standalone 'X mentioned' events into the
    matching timeline item's comments[]. Created/replied events were already
    consumed by _build_item_from_event (their carried mention became the first
    comment); status-change events are dropped per plan §4."""
    by_file: dict[str, dict] = {it["file"]: it for it in new_timeline}

    for ev in legacy_events:
        event = str(ev.get("event") or "")
        # "mentioned" but not the substring "created thread"/"replied" — those
        # were absorbed at item-build time.
        if "mentioned" not in event:
            continue
        if "created thread" in event or "replied" in event:
            # defensive — shouldn't normally co-occur in a single event string
            continue
        old_file_path = str(ev.get("file") or "")
        if not old_file_path:
            warnings.append(
                f"mention event without file field; dropping: event={event!r}"
            )
            continue
        new_file_path = _rewrite_event_file(old_file_path, rename_map)
        item = by_file.get(new_file_path)
        if item is None:
            warnings.append(
                f"mention target {old_file_path!r} not in new timeline; dropping"
            )
            continue
        mention = ev.get("mention") or {}
        time = str(ev.get("time") or "")
        author = event.split(" ", 1)[0] if event else "unknown"
        comment = _mention_to_comment(
            mention, time=time, author=author, users_repo=users_repo
        )
        item.setdefault("comments", []).append(comment)


def _rewrite_event_file(old_file_path: str, rename_map: dict[str, str]) -> str:
    """Apply rename_map to the basename of an event.file."""
    last_slash = old_file_path.rfind("/")
    if last_slash < 0:
        return old_file_path
    prefix, fname = old_file_path[: last_slash + 1], old_file_path[last_slash + 1 :]
    if fname in rename_map:
        return prefix + rename_map[fname]
    return old_file_path


def _mention_to_comment(
    mention: dict, *, time: str, author: str, users_repo
) -> dict:
    """Build a matter comment dict from any mention payload.

    Source can be:
      - "X created thread"/"X replied" event's `mention` field (carried at
        post creation), in which case time = event.time = file's created_at
        and author = file's creator.
      - "X mentioned" standalone event's `mention` field, in which case time
        is the mention's own timestamp and author is the mentioner.

    Per plan §4 Rule:
      created_at = time
      body       = mention.comments  (may be empty if user only @'d someone)
      mentions   = [open_id, ...] resolved via _resolve_mentions_for_index
                   (registered → pinyin, unregistered → keeps open_id)
      author     = author
    """
    body = str(mention.get("comments") or "")
    users = mention.get("users") or []
    open_ids = [
        str(u.get("open_id"))
        for u in users
        if isinstance(u, dict) and u.get("open_id")
    ]
    resolved = _resolve_mentions_for_index(open_ids, users_repo)

    comment: dict = {
        "created_at": time,
        "body": body,
        "author": author,
    }
    if resolved:
        comment["mentions"] = resolved
    return comment


# --------------------------------------------------------------------------- #
# Apply (IO orchestration)                                                    #
# --------------------------------------------------------------------------- #


def apply_migration(
    workspace: Path,
    legacy_paths: list[Path],
    *,
    dry_run: bool,
    users_repo=None,
) -> MigrationReport:
    """Drive the full migration. Returns a report regardless of mode.

    Order of operations (per legacy index, atomic per-thread):
      1. migrate_one (no IO writes)
      2. Idempotency: if new index already exists, compare contents
      3. Apply renames (os.rename) — git add -A picks them as R
      4. Write new index yaml (tmp+rename)
      5. Rewrite frontmatter type for renamed MDs
      6. Delete legacy yaml

    After all threads done, if --apply: single git commit (no push).
    """
    report = MigrationReport(
        workspace=str(workspace),
        dry_run=dry_run,
        legacy_count=len(legacy_paths),
    )

    if dry_run:
        # In dry-run we still preview migrate_one to populate report
        for legacy_path in legacy_paths:
            try:
                item = migrate_one(workspace, legacy_path, users_repo=users_repo)
            except Exception as e:
                report.errors.append(f"{legacy_path.name}: {e!r}")
                continue
            report.threads.append({
                "slug": slug_from_legacy_path(legacy_path),
                "current_status": item.new_index_data["matter"]["current_status"],
                "timeline_count": len(item.new_index_data["timeline"]),
                "rename_count": len(item.md_renames),
                "frontmatter_update_count": len(item.md_frontmatter_updates),
                "warnings": list(item.warnings),
                "would_skip": _idempotent_check(item) is True,
            })
        return report

    # --apply path
    items_to_commit: list[MigrationItem] = []
    for legacy_path in legacy_paths:
        try:
            item = migrate_one(workspace, legacy_path, users_repo=users_repo)
        except Exception as e:
            report.errors.append(f"{legacy_path.name}: {e!r}")
            continue

        idempotent = _idempotent_check(item)
        if idempotent is True:
            # Already migrated, content matches; just remove legacy.
            try:
                item.legacy_index_path.unlink(missing_ok=True)
            except Exception as e:
                report.errors.append(
                    f"{legacy_path.name}: failed to remove already-migrated "
                    f"legacy file: {e!r}"
                )
                continue
            report.skipped_count += 1
            report.threads.append({
                "slug": slug_from_legacy_path(legacy_path),
                "skipped": "already_migrated_identical",
                "warnings": list(item.warnings),
            })
            continue
        elif idempotent is False:
            # New index exists with DIFFERENT content; refuse to overwrite
            report.errors.append(
                f"{legacy_path.name}: new matter index "
                f"{item.new_index_path.name} already exists with different "
                f"content; refusing to overwrite. Manual inspection required."
            )
            continue

        # Check rename collisions before writing anything
        collision = _check_rename_collisions(item)
        if collision is not None:
            report.errors.append(
                f"{legacy_path.name}: rename target collision: {collision}"
            )
            continue

        try:
            _apply_one(item)
        except Exception as e:
            report.errors.append(f"{legacy_path.name}: apply failed: {e!r}")
            continue

        items_to_commit.append(item)
        report.migrated_count += 1
        report.threads.append({
            "slug": slug_from_legacy_path(legacy_path),
            "current_status": item.new_index_data["matter"]["current_status"],
            "timeline_count": len(item.new_index_data["timeline"]),
            "rename_count": len(item.md_renames),
            "frontmatter_update_count": len(item.md_frontmatter_updates),
            "warnings": list(item.warnings),
        })

    if items_to_commit and not report.errors:
        _commit_migration(workspace)
    elif report.errors:
        # Don't commit on partial failure — leave working tree dirty for the
        # operator to inspect; `git reset --hard` rolls back.
        pass

    return report


def _idempotent_check(item: MigrationItem) -> bool | None:
    """Return:
      True  → new index already exists with matching content (skip)
      False → new index exists but DIFFERENT content (error stop)
      None  → new index does not exist (proceed normally)
    """
    if not item.new_index_path.exists():
        return None
    try:
        with open(item.new_index_path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
    except Exception:
        return False
    return existing == item.new_index_data


def _check_rename_collisions(item: MigrationItem) -> str | None:
    """Return error message if any rename target already exists (and is not
    the source file itself); None if all renames are safe."""
    for old, new in item.md_renames:
        if old == new:
            continue
        if new.exists():
            return f"{new.name} already exists (target of rename from {old.name})"
    return None


def _apply_one(item: MigrationItem) -> None:
    """Apply a single MigrationItem to disk. Order matters:
      1. Rename MDs (working tree state changes; git rename detection)
      2. Write new index yaml (tmp+rename for atomicity)
      3. Rewrite frontmatter type on renamed MDs (preserves body)
      4. Delete legacy yaml
    """
    # 1. renames
    for old, new in item.md_renames:
        new.parent.mkdir(parents=True, exist_ok=True)
        os.rename(old, new)

    # 2. new index yaml (atomic tmp+rename)
    item.new_index_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(item.new_index_path, item.new_index_data)

    # 3. frontmatter rewrites
    for new_md_path, new_type in item.md_frontmatter_updates:
        try:
            post = read_post(new_md_path)
        except FileNotFoundError:
            # Either the rename pointed to a nonexistent source, or the user's
            # workspace has stale state; skip gracefully.
            continue
        fm = dict(post.frontmatter)
        fm["type"] = new_type
        write_post(new_md_path, frontmatter=fm, body=post.body)

    # 4. delete legacy yaml
    item.legacy_index_path.unlink(missing_ok=True)


def _atomic_write_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _commit_migration(workspace: Path) -> None:
    """Stage everything (renames included) and create a single commit. No push."""
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True, text=True, check=False,
        )

    add = _git("add", "-A")
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr}")
    diff = _git("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        # Nothing staged — defensive, shouldn't happen if items_to_commit > 0
        return
    commit = _git("commit", "-m", COMMIT_MESSAGE)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr}")


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


class _ReadOnlyUserView:
    """Read-only minimal view of the users table for mention pinyin resolution.

    **Why this isn't `UserRepo(Database(path))`:** `server.db.Database.__init__`
    runs `CREATE TABLE IF NOT EXISTS` + `_migrate(conn)` on construction, and
    `_migrate` may `ALTER TABLE` and even `DELETE FROM ai_conversations` on
    schema-version mismatch. If the migration operator points `--db-path` at a
    live production `data.db` whose schema lags the current code, those side
    effects would clobber production rows.

    This view bypasses `Database` entirely, opens the SQLite via the
    `file:...?mode=ro` URI (sqlite3 errors on any DDL/DML attempt), and exposes
    only `get_by_any_id` — the single method `_resolve_mentions_for_index`
    actually calls.
    """

    def __init__(self, db_path: Path) -> None:
        import sqlite3 as _sqlite3
        self._sqlite3 = _sqlite3
        # Resolve to absolute, sqlite URI requires forward slashes
        abs_path = Path(db_path).resolve().as_posix()
        self._uri = f"file:{abs_path}?mode=ro"
        # Probe-connect once to fail fast on missing file / unreadable DB
        # (mode=ro errors instead of creating, unlike default sqlite3.connect).
        conn = _sqlite3.connect(self._uri, uri=True)
        conn.close()

    def get_by_any_id(self, id_: str):
        if not id_:
            return None
        from server.users import _row_to_user
        conn = self._sqlite3.connect(self._uri, uri=True)
        try:
            conn.row_factory = self._sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE open_id=? OR union_id=? OR pinyin=?",
                (id_, id_, id_),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_user(row) if row else None


def _build_users_repo(db_path: Path | None = None) -> object | None:
    """Construct a read-only users view for mention pinyin resolution.

    `db_path` is required when called from CLI with `--db-path`; the env-derived
    fallback uses `.env`'s `DATA_DIR/data.db` so operators running on the prod
    server itself (where DATA_DIR points at the live db) don't have to copy.

    **Read-only invariant:** every code path here goes through
    `_ReadOnlyUserView`, which opens the SQLite via `file:...?mode=ro`. The
    underlying file is never written, never schema-migrated, never locked for
    write — safe to point at a live production data.db.

    Returns None on any failure (e.g., file missing, unreadable, no users table)
    — mention resolution then falls back to open_id literals, the documented
    degraded mode.
    """
    try:
        if db_path is not None:
            return _ReadOnlyUserView(db_path)
        from server.config import load_config  # local import (avoids hard dep)
        cfg = load_config()
        data_dir = Path(cfg.data_dir).resolve()
        return _ReadOnlyUserView(data_dir / "data.db")
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy thread index files to matter format."
    )
    parser.add_argument(
        "--workspace", required=True, type=Path,
        help="Path to the Pivot workspace (contains discussions/ and index/).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes; default is dry-run.",
    )
    parser.add_argument(
        "--slug", default=None,
        help="Migrate only this slug (for debugging a single thread).",
    )
    parser.add_argument(
        "--report", default="var/migration-report.json", type=Path,
        help="Path to write the JSON migration report.",
    )
    parser.add_argument(
        "--no-users-db", action="store_true",
        help="Skip loading UserRepo for pinyin resolution; mentions fall back "
             "to open_id literals.",
    )
    parser.add_argument(
        "--db-path", default=None, type=Path,
        help="Explicit path to the Pivot SQLite (data.db). Overrides .env's "
             "DATA_DIR-derived default. Use this when running rehearsal on a "
             "machine whose .env doesn't point at production data; copy a "
             "read-only snapshot of production data.db over and pass it here.",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"error: workspace path not found: {workspace}", file=sys.stderr)
        return 2

    failures = preflight_checks(workspace, strict=args.apply)
    if failures:
        print("preflight checks failed:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 2

    index_dir = workspace / "index"
    legacy_paths = discover_legacy(index_dir)
    if args.slug:
        target = index_dir / f"{args.slug}{LEGACY_INDEX_SUFFIX}"
        legacy_paths = [target] if target in legacy_paths else []
        if not legacy_paths:
            print(f"no legacy index found for slug={args.slug!r}", file=sys.stderr)
            return 2

    if not legacy_paths:
        print("no legacy index files found; nothing to migrate.")
        return 0

    users_repo = None if args.no_users_db else _build_users_repo(args.db_path)

    report = apply_migration(
        workspace, legacy_paths, dry_run=not args.apply, users_repo=users_repo,
    )

    # Write report
    report_path = args.report
    if not report_path.is_absolute():
        report_path = workspace / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Print human-readable summary
    mode = "dry-run" if not args.apply else "apply"
    print(f"[{mode}] workspace = {workspace}")
    print(
        f"[{mode}] legacy_count={report.legacy_count} "
        f"migrated={report.migrated_count} skipped={report.skipped_count} "
        f"errors={len(report.errors)}"
    )
    if report.errors:
        print(f"[{mode}] ERRORS:")
        for e in report.errors:
            print(f"  - {e}")
    print(f"[{mode}] report written to {report_path}")

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
