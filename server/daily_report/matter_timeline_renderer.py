"""Render a matter's full timeline as trimmed YAML text for LLM consumption.

设计目的(v0.4):

之前(v0.3)给 LLM 6 个简化字段,LLM 看不到 quote 因果链 / status_change
推进 / comments @ 协作触发等结构信号。结果是 LLM 能"叙事"但不能"理解
结构",写不出弧线感故事。

v0.4 直接把 Pivot 索引的原始 yaml(经最小裁剪)喂给 LLM,LLM 看到的是事项
推进过程的原始结构,不是程序压缩过的简化字段。配套 prompt 说明 yaml 字段
语义,让 LLM 自己推理。

裁剪只做防御性的:
  - summary 超长截断
  - comments 数过多截断
  - timeline 条数过多保留最近 N 条
  - 每条 timeline 加上 `in_window: true/false` 标记(原 yaml 没有,但对
    日报 LLM 极有用,免得它自己算时间戳)

字段全部保留(file / type / creator / owner / quote / refer / status_change /
verifications / comments / mentions),让 LLM 看到 Pivot 索引的真实结构。

参见 memory: project_daily_report_positioning.md(产品定位)。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import yaml

from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ


def render_matter_timeline_yaml(
    matter_index: dict,
    window: TimeWindow,
    *,
    max_timeline_items: int = 30,
    max_summary_chars: int = 250,
    max_comments_per_item: int = 3,
    max_comment_chars: int = 150,
) -> str:
    """Render matter index dict to trimmed YAML text for LLM input.

    Args:
        matter_index: dict from `read_matter_index()`,shape `{matter, timeline}`
        window: TimeWindow,用于在每条上加 in_window 标记
        max_timeline_items: 一份 matter 最多保留多少条(超过截最近 N 条)
        max_summary_chars: 单条 summary 最大字符数
        max_comments_per_item: 单条 timeline 最多保留多少 comments
        max_comment_chars: 单条 comment body 最大字符数

    Returns:
        YAML 字符串(allow_unicode + 块状风格,LLM 可读),可直接嵌入 input。
        malformed / 空 timeline → ""
    """
    if not isinstance(matter_index, dict):
        return ""
    matter = matter_index.get("matter") or {}
    timeline_raw = matter_index.get("timeline") or []
    if not timeline_raw:
        return ""

    # 截断 timeline 到最近 max_timeline_items 条(保留最近 N 条,保持原序)
    total_count = len(timeline_raw)
    truncated = total_count > max_timeline_items
    timeline = timeline_raw[-max_timeline_items:] if truncated else timeline_raw

    # 修剪每条 timeline 项 + 加 in_window 标记
    trimmed_timeline: list[dict] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        trimmed_timeline.append(_trim_item(
            item, window, max_summary_chars,
            max_comments_per_item, max_comment_chars,
        ))

    out: dict[str, Any] = {
        "matter": dict(matter),
        "timeline": trimmed_timeline,
    }
    if truncated:
        out["_note"] = (
            f"timeline 已截断,只显示最近 {max_timeline_items} 条"
            f"(原共 {total_count} 条)"
        )

    return yaml.dump(
        out,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )


def _trim_item(
    item: dict,
    window: TimeWindow,
    max_summary_chars: int,
    max_comments_per_item: int,
    max_comment_chars: int,
) -> dict:
    """Trim a single timeline item: cap summary/comment length, mark window."""
    new_item: dict[str, Any] = {}
    # 保持字段顺序:让 LLM 看到结构清晰的 yaml(file 在前,业务字段在中间)
    # 优先字段:file / type / creator / owner / created_at / in_window / summary / quote
    # / refer / status_change / verifications / comments
    priority = [
        "file", "type", "creator", "owner", "created_at",
        # in_window 由我们插入,放在 created_at 之后语义连贯
        "summary", "quote", "refer",
        "status_change", "verifications", "comments",
    ]

    # 算 in_window
    dt = _parse_iso(item.get("created_at"))
    in_window = bool(dt and window.since <= dt < window.until)

    for k in priority:
        if k not in item:
            continue
        v = item[k]
        if k == "summary":
            v = _trim_str(v, max_summary_chars)
        elif k == "comments":
            v = _trim_comments(v, max_comments_per_item, max_comment_chars)
        new_item[k] = v
        # 在 created_at 之后立刻插入 in_window
        if k == "created_at":
            new_item["in_window"] = in_window

    # in_window 兜底:如果 item 没有 created_at,in_window 仍要写出
    if "in_window" not in new_item:
        new_item["in_window"] = in_window

    # 把 priority 之外的字段也保留(防 schema 演进)
    for k, v in item.items():
        if k not in new_item:
            new_item[k] = v

    return new_item


def _trim_str(value: Any, max_chars: int) -> str:
    s = str(value or "").strip()
    if len(s) > max_chars:
        return s[:max_chars] + "…"
    return s


def _trim_comments(
    comments: Any,
    max_count: int,
    max_body_chars: int,
) -> list:
    if not isinstance(comments, list):
        return []
    shown = comments[:max_count]
    extra = len(comments) - len(shown)
    out = []
    for c in shown:
        if not isinstance(c, dict):
            continue
        new_c = dict(c)
        body = str(new_c.get("body") or "")
        if len(body) > max_body_chars:
            new_c["body"] = body[:max_body_chars] + "…"
        out.append(new_c)
    if extra > 0:
        out.append({"_note": f"另 {extra} 条评论省略"})
    return out


def _parse_iso(value: Any) -> datetime | None:
    """Parse ISO 8601 datetime. Naive inputs assumed Asia/Shanghai."""
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
        dt = dt.replace(tzinfo=CHINA_TZ)
    return dt
