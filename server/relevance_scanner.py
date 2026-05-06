"""Full-history scanner for relevance_events.

Scans every matter index + timeline + comments and ensures that every
relevance row that *should* exist for any registered user does exist.
Each candidate row is checked first via Repo.exists; missing rows get
INSERTed individually. The explicit SELECT-then-INSERT (vs. INSERT OR
IGNORE) lets the scanner report inserted-vs-skipped counts so ops can
tell whether the real-time writer is healthy.

Run paths:
  1. startup hook — always runs; cold vs warm is derived from whether
     relevance_events is empty (cold_start writes rows as already-read so
     historical activity doesn't surface as retroactive unread).
  2. hourly background task (`schedule_hourly_scan`)
  3. CLI: `python -m server.relevance_scanner` for ops / disaster recovery
"""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from dataclasses import dataclass
from pathlib import Path

from server.matter_index import read_matter_index
from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUser, PivotUserRepo
from server.relevance import compute_relevance
from server.relevance_events import (
    KIND_FILE,
    KIND_MENTION,
    REASON_COMMENT_MENTION,
    RelevanceEventsRepo,
)
from server.workspace import Workspace

log = logging.getLogger(__name__)


HOURLY_INTERVAL_SECONDS = 3600
ENV_SCAN_INTERVAL_MINUTES = "RELEVANCE_SCAN_INTERVAL_MINUTES"
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 1


@dataclass(frozen=True)
class ScanReport:
    """Result of a single scan_all run.

    inserted: rows newly INSERTed across the whole repo.
    skipped:  rows whose PK already existed (already covered by writer).
    matters:  number of matter indexes walked.
    """

    inserted: int
    skipped: int
    matters: int


def scan_all(
    *,
    workspace: Workspace,
    users_repo: PivotUserRepo,
    repo: RelevanceEventsRepo,
    bindings: ExternalBindingRepo | None = None,
    mark_as_read: bool = False,
) -> ScanReport:
    """Walk every matter and insert any missing relevance rows.

    ``mark_as_read`` — when True, every newly-inserted row is stamped with
    ``read_at = now`` instead of unread. Intended for the very first
    cold-start backfill against an empty ``relevance_events`` table, so
    historical timeline activity doesn't show up as a tsunami of red unread
    badges on first login. Subsequent scans (periodic compensation, manual
    re-runs against a non-empty table) leave it False so genuinely-missed
    events surface as unread, matching the real-time writer."""
    log.info(
        "relevance scan_all starting index_dir=%s mark_as_read=%s",
        workspace.index_dir, mark_as_read,
    )
    inserted = 0
    skipped = 0
    matters = 0
    insert_read_at: float | None = _time.time() if mark_as_read else None

    users = users_repo.all()
    if not users:
        log.info("relevance scan_all: no users registered, nothing to do")
        return ScanReport(inserted=0, skipped=0, matters=0)

    for index_path in _list_matter_index_paths(workspace.index_dir):
        data = read_matter_index(index_path)
        if data is None:
            continue
        matter_id = str((data.get("matter") or {}).get("id") or "")
        if not matter_id:
            continue
        matters += 1

        for item in data.get("timeline") or []:
            file_rel = item.get("file") or ""
            if not file_rel:
                continue
            filename = file_rel.rsplit("/", 1)[-1]
            item_created_at = str(item.get("created_at") or "")
            item_creator = str(item.get("creator") or "")

            # ---- file-level rows ----
            if item_created_at and item_creator:
                for user in users:
                    ok, reason = compute_relevance(item, data, user)
                    if not ok or reason is None:
                        continue
                    if repo.exists(
                        pivot_user_id=user.open_id,
                        matter_id=matter_id,
                        filename=filename,
                        kind=KIND_FILE,
                        event_at=item_created_at,
                        actor_pinyin=item_creator,
                    ):
                        skipped += 1
                        continue
                    if repo.insert_file(
                        user.open_id,
                        matter_id,
                        filename,
                        reason=reason,
                        event_at=item_created_at,
                        actor_pinyin=item_creator,
                        read_at=insert_read_at,
                    ):
                        inserted += 1
                    else:
                        # Race with real-time writer: someone slipped a row in
                        # between exists() and insert(). PK conflict caught by
                        # INSERT OR IGNORE inside insert_file, counted as skip.
                        skipped += 1

            # ---- mention-level rows ----
            for comment in item.get("comments") or []:
                comment_at = str(comment.get("created_at") or "")
                comment_author = str(comment.get("author") or "")
                if not comment_at or not comment_author:
                    continue
                for mention_id in comment.get("mentions") or []:
                    target = _resolve_user_ref(str(mention_id), users_repo, bindings)
                    if target is None:
                        continue
                    if target.pinyin and target.pinyin == comment_author:
                        continue  # self-exclusion
                    if repo.exists(
                        pivot_user_id=target.open_id,
                        matter_id=matter_id,
                        filename=filename,
                        kind=KIND_MENTION,
                        event_at=comment_at,
                        actor_pinyin=comment_author,
                    ):
                        skipped += 1
                        continue
                    if repo.insert_mention(
                        target.open_id,
                        matter_id,
                        filename,
                        comment_at=comment_at,
                        actor_pinyin=comment_author,
                        read_at=insert_read_at,
                    ):
                        inserted += 1
                    else:
                        skipped += 1

    log.info(
        "relevance scan_all done matters=%d inserted=%d skipped=%d",
        matters, inserted, skipped,
    )
    return ScanReport(inserted=inserted, skipped=skipped, matters=matters)


def get_scan_interval_minutes() -> int:
    """Read the periodic scan interval from env, in minutes.

    Default: 60 (i.e. hourly). Non-numeric or sub-minimum values fall back
    to the default; values below MIN_SCAN_INTERVAL_MINUTES are clamped up
    to prevent runaway scan loops from a typo.
    """
    raw = os.getenv(ENV_SCAN_INTERVAL_MINUTES)
    if raw is None or not raw.strip():
        return DEFAULT_SCAN_INTERVAL_MINUTES
    try:
        minutes = int(raw.strip())
    except ValueError:
        log.warning(
            "invalid %s=%r, falling back to default %d",
            ENV_SCAN_INTERVAL_MINUTES, raw, DEFAULT_SCAN_INTERVAL_MINUTES,
        )
        return DEFAULT_SCAN_INTERVAL_MINUTES
    if minutes < MIN_SCAN_INTERVAL_MINUTES:
        log.warning(
            "%s=%d below minimum %d, clamping",
            ENV_SCAN_INTERVAL_MINUTES, minutes, MIN_SCAN_INTERVAL_MINUTES,
        )
        return MIN_SCAN_INTERVAL_MINUTES
    return minutes


async def schedule_hourly_scan(
    *,
    workspace: Workspace,
    users_repo: PivotUserRepo,
    repo: RelevanceEventsRepo,
    bindings: ExternalBindingRepo | None = None,
    interval_seconds: int = HOURLY_INTERVAL_SECONDS,
) -> None:
    """Background task: scan_all every `interval_seconds`. Runs forever
    until the task is cancelled. Each iteration runs in a thread (the scan
    is sync + I/O-bound) so it doesn't block the event loop.
    """
    log.info(
        "relevance periodic scan loop started interval=%ds (%dmin)",
        interval_seconds, interval_seconds // 60,
    )
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
        log.info(
            "relevance periodic scan tick firing (interval=%ds)",
            interval_seconds,
        )
        try:
            await asyncio.to_thread(
                scan_all,
                workspace=workspace,
                users_repo=users_repo,
                repo=repo,
                bindings=bindings,
            )
        except Exception:
            log.exception("relevance hourly scan_all failed")


# ---------- helpers ----------


def _list_matter_index_paths(index_dir: Path) -> list[Path]:
    p = Path(index_dir)
    if not p.is_dir():
        return []
    out: list[Path] = []
    for f in p.glob("*.index.yaml"):
        # Exclude legacy `{slug}-discuss.index.yaml` (thread model).
        if f.name.endswith("-discuss.index.yaml"):
            continue
        out.append(f)
    return out


def _resolve_user_ref(
    ref: str,
    users_repo: PivotUserRepo,
    bindings: ExternalBindingRepo | None,
) -> PivotUser | None:
    target = users_repo.get_by_any_id(ref)
    if target is not None:
        return target
    if bindings is None:
        return None
    binding = bindings.lookup_any_provider(ref)
    return users_repo.get(binding.pivot_user_id) if binding is not None else None


# ---------- CLI ----------


def _main() -> int:
    """`python -m server.relevance_scanner` — manual full scan for ops."""
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from server.config import load_config
    from server.db import Database
    from server.external_bindings import ExternalBindingRepo
    from server.workspace_runtime import WorkspaceRuntime
    from server.settings import SettingsRepo

    cfg = load_config()
    db = Database(cfg.data_dir / "data.db")
    settings = SettingsRepo(db)
    workspace = WorkspaceRuntime(base_dir=cfg.data_dir / "git", settings=settings)
    users_repo = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    repo = RelevanceEventsRepo(db)

    report = scan_all(
        workspace=workspace, users_repo=users_repo, bindings=bindings, repo=repo,
    )
    print(
        f"scan_all: matters={report.matters} "
        f"inserted={report.inserted} skipped={report.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
