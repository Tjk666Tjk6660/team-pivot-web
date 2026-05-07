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

from server.daily_report.matter_timeline_renderer import render_matter_timeline_yaml
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
    matter_owner = str(matter.get("owner") or "")
    timeline = data.get("timeline") or []
    matter_intent = _derive_intent(timeline)
    matter_prev_summary = _derive_prev_summary(timeline, window)
    # v0.4: 把整段 timeline 精简成 yaml 字符串,作为 matter 级语境跟着每个 event 走
    matter_timeline_yaml = render_matter_timeline_yaml(data, window)

    out: list[MatterEvent] = []
    for item in timeline:
        ev = _convert_item(
            item,
            matter_id=matter_id,
            matter_title=matter_title,
            matter_status=matter_status,
            matter_owner=matter_owner,
            matter_intent=matter_intent,
            matter_prev_summary=matter_prev_summary,
            matter_timeline_yaml=matter_timeline_yaml,
            window=window,
        )
        if ev is not None:
            out.append(ev)
    return out


def _derive_intent(timeline: list[dict]) -> str:
    """第一条 think.summary —— 该 matter 当初为什么开。

    timeline 按 created_at 升序;取第一个 type=='think' 且 summary 非空的。
    无 think 时回落到第一个非空 summary 的 item;都没有则返回空串。"""
    for item in timeline:
        if str(item.get("type") or "") == "think":
            s = str(item.get("summary") or "").strip()
            if s:
                return s
    for item in timeline:
        s = str(item.get("summary") or "").strip()
        if s:
            return s
    return ""


def _derive_prev_summary(timeline: list[dict], window: TimeWindow) -> str:
    """窗口之前最后一条非空 summary —— 上一步推到哪了。

    遍历 timeline 找 created_at < window.since 的 item,取最后一个非空 summary。
    matter 在窗口内才出生 / 仅有 think_intent 自身 → 返回空串。"""
    last = ""
    for item in timeline:
        dt = _parse_iso(item.get("created_at"))
        if dt is None or dt >= window.since:
            continue
        s = str(item.get("summary") or "").strip()
        if s:
            last = s
    return last


def _convert_item(
    item: dict,
    *,
    matter_id: str,
    matter_title: str,
    matter_status: str,
    matter_owner: str,
    matter_intent: str,
    matter_prev_summary: str,
    matter_timeline_yaml: str,
    window: TimeWindow,
) -> MatterEvent | None:
    file_path = str(item.get("file") or "")
    if not file_path:
        return None
    # 失效语义:已失效文件不计入日报事件流。日报场景下 LLM 不应看到失效
    # 文件,避免写出"X 起草后自行失效""X 标记 Y 为无效"等失效行为陈述,
    # 也避免把失效文件 summary 当今日成果。详见 matter_timeline_renderer.py
    # 内 `_is_invalidated_or_invalidation_event` 注释。
    if item.get("invalidated") is True:
        return None
    file_type = str(item.get("type") or "")

    file_dt = _parse_iso(item.get("created_at"))
    file_in_window = (
        file_dt is not None
        and window.since <= file_dt < window.until
    )

    # Comments: filter to in-window only (comments can land much later than
    # the file's own created_at, e.g. someone @-mentioning today on a 3-day-
    # old proposal).
    comments_in: list[MatterEventComment] = []
    for c in item.get("comments") or []:
        c_dt = _parse_iso(c.get("created_at"))
        if c_dt is None:
            continue
        if window.since <= c_dt < window.until:
            comments_in.append(MatterEventComment(
                created_at=c_dt,
                author=str(c.get("author") or ""),
                body=str(c.get("body") or ""),
                mentions=tuple(str(m) for m in (c.get("mentions") or [])),
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
        matter_intent=matter_intent,
        matter_prev_summary=matter_prev_summary,
        matter_timeline_yaml=matter_timeline_yaml,
        matter_owner=matter_owner,
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
