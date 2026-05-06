"""Tests for `server.daily_report.matter_timeline_renderer`.

v0.4 改造后,renderer 输出 yaml 字符串(精简过的 Pivot 索引原始结构)。
测试通过 yaml.safe_load 解析输出,断言结构正确。"""
from __future__ import annotations

from datetime import datetime

import yaml

from server.daily_report.matter_timeline_renderer import (
    render_matter_timeline_yaml,
)
from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _w() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 29, 0, 0, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 30, 0, 0, tzinfo=CHINA_TZ),
    )


def _matter(
    *,
    title: str = "新需求-X",
    status: str = "executing",
    timeline: list[dict] | None = None,
) -> dict:
    return {
        "matter": {"id": title, "title": title, "current_status": status},
        "timeline": timeline or [],
    }


def _think(
    *,
    file: str,
    creator: str,
    summary: str,
    created_at: str,
    quote: str | None = None,
    comments: list[dict] | None = None,
    owner: str | None = None,
) -> dict:
    item = {
        "file": file,
        "type": "think",
        "creator": creator,
        "owner": owner or creator,
        "summary": summary,
        "created_at": created_at,
    }
    if quote:
        item["quote"] = quote
    if comments:
        item["comments"] = comments
    return item


def _act(
    *,
    file: str,
    creator: str,
    summary: str,
    created_at: str,
    quote: str | None = None,
    status_change: dict | None = None,
) -> dict:
    item = {
        "file": file,
        "type": "act",
        "creator": creator,
        "owner": creator,
        "summary": summary,
        "created_at": created_at,
    }
    if quote:
        item["quote"] = quote
    if status_change:
        item["status_change"] = status_change
    return item


def _parse(rendered: str) -> dict:
    """Helper: parse renderer output as yaml,return the dict."""
    if not rendered:
        return {}
    return yaml.safe_load(rendered) or {}


# --------------------------------------------------------------------------- #
# Empty / malformed                                                           #
# --------------------------------------------------------------------------- #


def test_empty_index_returns_empty_string():
    assert render_matter_timeline_yaml({}, _w()) == ""


def test_empty_timeline_returns_empty_string():
    assert render_matter_timeline_yaml(_matter(timeline=[]), _w()) == ""


def test_non_dict_input_returns_empty_string():
    assert render_matter_timeline_yaml(None, _w()) == ""  # type: ignore[arg-type]
    assert render_matter_timeline_yaml("string", _w()) == ""  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Top-level structure preserved                                               #
# --------------------------------------------------------------------------- #


def test_matter_block_preserved():
    rendered = render_matter_timeline_yaml(
        _matter(
            title="新需求-日报推送",
            status="executing",
            timeline=[
                _think(
                    file="discussions/Pivot/X/001_alice_think_a.md",
                    creator="alice", summary="提案",
                    created_at="2026-04-28T10:00:00+08:00",
                ),
            ],
        ),
        _w(),
    )
    parsed = _parse(rendered)
    assert parsed["matter"]["title"] == "新需求-日报推送"
    assert parsed["matter"]["current_status"] == "executing"
    assert len(parsed["timeline"]) == 1


def test_in_window_marker_added_per_item():
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="a.md", creator="alice", summary="历史",
                created_at="2026-04-28T10:00:00+08:00",  # 窗口前
            ),
            _think(
                file="b.md", creator="bob", summary="今日",
                created_at="2026-04-29T10:00:00+08:00",  # 窗口内
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    assert parsed["timeline"][0]["in_window"] is False
    assert parsed["timeline"][1]["in_window"] is True


# --------------------------------------------------------------------------- #
# Original yaml fields preserved                                              #
# --------------------------------------------------------------------------- #


def test_quote_field_preserved_as_path():
    """v0.4: 不再翻译成"引用 #M",直接保留 yaml 原字段 quote: <path>"""
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
            ),
            _think(
                file="002.md", creator="bob", summary="回应 A",
                created_at="2026-04-28T11:00:00+08:00",
                quote="001.md",
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    assert parsed["timeline"][1]["quote"] == "001.md"


def test_status_change_field_preserved():
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _act(
                file="001.md", creator="alice", summary="实施完成",
                created_at="2026-04-29T17:00:00+08:00",
                status_change={"from": "planning", "to": "executing"},
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    sc = parsed["timeline"][0]["status_change"]
    assert sc["from"] == "planning"
    assert sc["to"] == "executing"


def test_creator_owner_both_preserved_when_different():
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", owner="bob", summary="代写",
                created_at="2026-04-28T10:00:00+08:00",
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    assert parsed["timeline"][0]["creator"] == "alice"
    assert parsed["timeline"][0]["owner"] == "bob"


def test_type_field_preserved():
    """v0.4: yaml 原始 type 字段保留(英文标签),prompt 教 LLM 不要写到输出"""
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
            ),
            _act(
                file="002.md", creator="alice", summary="B",
                created_at="2026-04-29T10:00:00+08:00",
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    assert parsed["timeline"][0]["type"] == "think"
    assert parsed["timeline"][1]["type"] == "act"


# --------------------------------------------------------------------------- #
# Comments + mentions                                                         #
# --------------------------------------------------------------------------- #


def test_comments_with_mentions_preserved():
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
                comments=[
                    {
                        "author": "alice",
                        "body": "看一下这个方案",
                        "mentions": ["bob", "carol"],
                        "created_at": "2026-04-28T10:01:00+08:00",
                    },
                ],
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    c = parsed["timeline"][0]["comments"][0]
    assert c["author"] == "alice"
    assert c["body"] == "看一下这个方案"
    assert c["mentions"] == ["bob", "carol"]


def test_all_comments_preserved_no_count_cap():
    """评论不再按数量截断 —— 每条都进 yaml 喂给 LLM。
    评论里常有拍板/@抛球/异议等关键决策信号,丢一条都可能让 LLM 漏掉
    弧线。仅 body 超长时截断单条 body。"""
    comments = [
        {"author": f"u{i}", "body": f"评论 {i}", "mentions": [],
         "created_at": "2026-04-28T10:00:00+08:00"}
        for i in range(20)
    ]
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
                comments=comments,
            ),
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    cs = parsed["timeline"][0]["comments"]
    # 全部 20 条都保留,没有 _note 占位
    assert len(cs) == 20
    assert cs[0]["body"] == "评论 0"
    assert cs[19]["body"] == "评论 19"
    assert all("_note" not in c for c in cs)


def test_long_comment_body_truncated():
    long_body = "x" * 300
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
                comments=[{"author": "alice", "body": long_body,
                           "mentions": [],
                           "created_at": "2026-04-28T10:01:00+08:00"}],
            ),
        ]),
        _w(),
        max_comment_chars=50,
    )
    parsed = _parse(rendered)
    body = parsed["timeline"][0]["comments"][0]["body"]
    assert len(body) <= 51    # 50 + ellipsis "…"
    assert body.endswith("…")


# --------------------------------------------------------------------------- #
# Truncation                                                                  #
# --------------------------------------------------------------------------- #


def test_summary_truncated_at_max_summary_chars():
    long = "x" * 500
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary=long,
                created_at="2026-04-28T10:00:00+08:00",
            ),
        ]),
        _w(),
        max_summary_chars=50,
    )
    parsed = _parse(rendered)
    s = parsed["timeline"][0]["summary"]
    assert len(s) <= 51
    assert s.endswith("…")


def test_timeline_truncated_keeps_most_recent_items_with_note():
    items = [
        _think(
            file=f"{i:03d}.md", creator="u",
            summary=f"think {i}",
            created_at=f"2026-04-{28 if i < 5 else 29}T{(10+i):02d}:00:00+08:00",
        )
        for i in range(10)
    ]
    rendered = render_matter_timeline_yaml(
        _matter(timeline=items),
        _w(),
        max_timeline_items=3,
    )
    parsed = _parse(rendered)
    # 只保留最近 3 条(7 / 8 / 9)
    assert len(parsed["timeline"]) == 3
    summaries = [t["summary"] for t in parsed["timeline"]]
    assert summaries == ["think 7", "think 8", "think 9"]
    assert "_note" in parsed
    assert "已截断" in parsed["_note"]
    assert "10 条" in parsed["_note"]


# --------------------------------------------------------------------------- #
# Verifications                                                               #
# --------------------------------------------------------------------------- #


def test_verifications_preserved():
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            {
                "file": "001.md",
                "type": "verify",
                "creator": "liuyu",
                "owner": "liuyu",
                "summary": "验收",
                "created_at": "2026-04-29T18:00:00+08:00",
                "verifications": [
                    {
                        "target": "discussions/Pivot/X/008.md",
                        "judgement": "passed",
                        "comment": "符合需求预期",
                    },
                ],
            },
        ]),
        _w(),
    )
    parsed = _parse(rendered)
    v = parsed["timeline"][0]["verifications"][0]
    assert v["judgement"] == "passed"
    assert v["target"] == "discussions/Pivot/X/008.md"
    assert v["comment"] == "符合需求预期"


# --------------------------------------------------------------------------- #
# Field order priority                                                        #
# --------------------------------------------------------------------------- #


def test_in_window_inserted_after_created_at():
    """字段顺序对 LLM 阅读体验有影响:in_window 紧跟 created_at 更连贯。"""
    rendered = render_matter_timeline_yaml(
        _matter(timeline=[
            _think(
                file="001.md", creator="alice", summary="A",
                created_at="2026-04-28T10:00:00+08:00",
            ),
        ]),
        _w(),
    )
    # 在 yaml 文本中,created_at 后紧跟 in_window
    idx_created = rendered.index("created_at")
    idx_in_window = rendered.index("in_window")
    idx_summary = rendered.index("summary")
    assert idx_created < idx_in_window < idx_summary
