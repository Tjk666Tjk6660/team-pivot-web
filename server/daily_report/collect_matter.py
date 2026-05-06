"""Collect matter timeline events that fall in a time window.

Walks `<workspace>/index/*.index.yaml`, returns a flat list of `MatterEvent`
objects. An event is emitted when EITHER:
  - the file's `created_at` is in window, OR
  - the file has any `comments[i].created_at` in window

This way a comment posted today on someone's old matter still counts as
today's collaboration (per pivot-product.md §四 — comments don't bump
matter.updated_at, but they ARE meaningful daily activity)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from server.daily_report.types import (
    MatterEvent,
    MatterEventComment,
    TimeWindow,
)
from server.daily_report.window import CHINA_TZ
from server.matter_index import read_matter_index

log = logging.getLogger("server.daily_report.collect_matter")


def collect_matter_events(
    index_dir: Path,
    window: TimeWindow,
) -> list[MatterEvent]:
    """Scan all matter index files in `index_dir`, return events touching
    the window. Failures on individual files are logged + skipped — one
    bad yaml file doesn't kill the whole report."""
    if not index_dir.is_dir():
        log.warning("index_dir not found: %s", index_dir)
        return []

    events: list[MatterEvent] = []
    for path in sorted(index_dir.glob("*.index.yaml")):
        try:
            events.extend(_scan_one_matter(path, window))
        except Exception as e:
            log.warning("failed to scan %s: %s", path.name, e)
            continue
    return events


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _scan_one_matter(path: Path, window: TimeWindow) -> list[MatterEvent]:
    data = read_matter_index(path)
    if not data:
        return []
    matter = data.get("matter") or {}
    matter_id = str(matter.get("id") or path.stem.replace(".index", ""))
    matter_title = str(matter.get("title") or matter_id)
    matter_status = str(matter.get("current_status") or "")

    out: list[MatterEvent] = []
    for item in data.get("timeline") or []:
        ev = _convert_item(
            item,
            matter_id=matter_id,
            matter_title=matter_title,
            matter_status=matter_status,
            window=window,
        )
        if ev is not None:
            out.append(ev)
    return out


def _convert_item(
    item: dict,
    *,
    matter_id: str,
    matter_title: str,
    matter_status: str,
    window: TimeWindow,
) -> MatterEvent | None:
    file_path = str(item.get("file") or "")
    if not file_path:
        return None
    file_type = str(item.get("type") or "")

    file_dt = _parse_iso(item.get("created_at"))
    file_in_window = (
        file_dt is not None
        and window.since <= file_dt < window.until
    )

    # Mentions: filter to in-window only (mentions can land much later than
    # the file's own created_at, e.g. someone @-mentioning today on a 3-day-
    # old proposal). Reader normalizes legacy `comments[].mentions` shape to
    # `mentions[].targets`, so we always read the post-rename shape here.
    comments_in: list[MatterEventComment] = []
    for c in item.get("mentions") or []:
        c_dt = _parse_iso(c.get("created_at"))
        if c_dt is None:
            continue
        if window.since <= c_dt < window.until:
            comments_in.append(MatterEventComment(
                created_at=c_dt,
                author=str(c.get("author") or ""),
                body=str(c.get("body") or ""),
                mentions=tuple(str(m) for m in (c.get("targets") or [])),
            ))

    # Skip items that contribute neither a fresh file nor an in-window comment.
    if not file_in_window and not comments_in:
        return None

    creator = str(item.get("creator") or "")
    owner = str(item.get("owner") or creator)
    summary = str(item.get("summary") or "")
    status_change = item.get("status_change")
    if not isinstance(status_change, dict):
        status_change = None
    verifications = tuple(
        v for v in (item.get("verifications") or []) if isinstance(v, dict)
    )

    # `created_at` for the event (used for sorting / display): prefer file's
    # own time; else first in-window comment; else fall back to window.since
    # (we know the item touches window somehow).
    if file_dt is not None:
        ev_dt = file_dt
    elif comments_in:
        ev_dt = min(c.created_at for c in comments_in)
    else:
        ev_dt = window.since   # unreachable given the early return above

    return MatterEvent(
        matter_id=matter_id,
        matter_title=matter_title,
        matter_current_status=matter_status,
        file=file_path,
        file_type=file_type,
        created_at=ev_dt,
        file_in_window=file_in_window,
        creator=creator,
        owner=owner,
        summary=summary,
        status_change=status_change,
        verifications=verifications,
        comments_in_window=tuple(comments_in),
    )


def _parse_iso(value) -> datetime | None:
    """Parse an ISO 8601 datetime. Naive inputs (no tz) are assumed to be
    Asia/Shanghai — defensive for legacy data migrated from the old thread
    format where `created_at` may have been stored without tz."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CHINA_TZ)
    return dt
