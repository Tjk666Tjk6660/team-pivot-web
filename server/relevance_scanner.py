"""Full-history scanner for relevance_events.

Scans every matter index + timeline + comments and ensures that every
relevance row that *should* exist for any registered user does exist.
Each candidate row is checked first via Repo.exists; missing rows get
INSERTed individually. The explicit SELECT-then-INSERT (vs. INSERT OR
IGNORE) lets the scanner report inserted-vs-skipped counts so ops can
tell whether the real-time writer is healthy.

Run paths:
  1. startup hook (gated by env RELEVANCE_BACKFILL_ON_STARTUP, default on)
  2. hourly background task (`schedule_hourly_scan`)
  3. CLI: `python -m server.relevance_scanner` for ops / disaster recovery
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from server.matter_index import read_matter_index
from server.relevance import compute_relevance
from server.relevance_events import (
    KIND_FILE,
    KIND_MENTION,
    REASON_COMMENT_MENTION,
    RelevanceEventsRepo,
)
from server.users import UserRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)


HOURLY_INTERVAL_SECONDS = 3600
ENV_BACKFILL_ON_STARTUP = "RELEVANCE_BACKFILL_ON_STARTUP"


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
    users_repo: UserRepo,
    repo: RelevanceEventsRepo,
) -> ScanReport:
    inserted = 0
    skipped = 0
    matters = 0

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
                        user_open_id=user.open_id,
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
                    target = users_repo.get_by_any_id(str(mention_id))
                    if target is None:
                        continue
                    if target.pinyin and target.pinyin == comment_author:
                        continue  # self-exclusion
                    if repo.exists(
                        user_open_id=target.open_id,
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
                    ):
                        inserted += 1
                    else:
                        skipped += 1

    log.info(
        "relevance scan_all done matters=%d inserted=%d skipped=%d",
        matters, inserted, skipped,
    )
    return ScanReport(inserted=inserted, skipped=skipped, matters=matters)


def is_backfill_on_startup_enabled() -> bool:
    val = os.getenv(ENV_BACKFILL_ON_STARTUP, "true").strip().lower()
    return val not in ("0", "false", "no", "off")


async def schedule_hourly_scan(
    *,
    workspace: Workspace,
    users_repo: UserRepo,
    repo: RelevanceEventsRepo,
    interval_seconds: int = HOURLY_INTERVAL_SECONDS,
) -> None:
    """Background task: scan_all every `interval_seconds`. Runs forever
    until the task is cancelled. Each iteration runs in a thread (the scan
    is sync + I/O-bound) so it doesn't block the event loop.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
        try:
            await asyncio.to_thread(
                scan_all,
                workspace=workspace,
                users_repo=users_repo,
                repo=repo,
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


# ---------- CLI ----------


def _main() -> int:
    """`python -m server.relevance_scanner` — manual full scan for ops."""
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from server.config import load_config
    from server.db import Database
    from server.workspace_runtime import WorkspaceRuntime
    from server.settings import SettingsRepo

    cfg = load_config()
    db = Database(cfg.data_dir / "data.db")
    settings = SettingsRepo(db)
    workspace = WorkspaceRuntime(base_dir=cfg.data_dir / "git", settings=settings)
    users_repo = UserRepo(db)
    repo = RelevanceEventsRepo(db)

    report = scan_all(workspace=workspace, users_repo=users_repo, repo=repo)
    print(
        f"scan_all: matters={report.matters} "
        f"inserted={report.inserted} skipped={report.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
