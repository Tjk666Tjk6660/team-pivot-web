from __future__ import annotations

import pytest

from server.scoring.prompt import (
    PromptTooLargeError,
    build_scoring_prompt,
    build_system_prompt,
    serialize_timeline,
)


# ---------- fixtures ----------


@pytest.fixture
def index_data():
    return {
        "matter": {
            "id": "eng/auth-redesign",
            "title": "客户验收流程优化",
            "current_status": "finished",
            "owner": "zhangsan",
            "created_at": "2026-04-20T10:00:00+08:00",
            "updated_at": "2026-04-29T18:30:00+08:00",
        },
        "timeline": [
            {
                "file": "discussions/eng/auth-redesign/001_zhangsan_act_xx.md",
                "type": "act",
                "creator": "zhangsan",
                "owner": "zhangsan",
                "created_at": "2026-04-20T10:00:00+08:00",
                "summary": "完成接口对接",
                "verifications_received": [
                    {"verify_file": "discussions/eng/auth-redesign/002_lisi_verify_xx.md",
                     "judgement": "passed", "verified_by": "lisi"},
                ],
                "comments": [
                    {
                        "author": "ceo",
                        "body": "这个交付质量很高",
                        "created_at": "2026-04-29T18:00:00+08:00",
                        "mentions": ["zhangsan_open_id"],
                    },
                    {
                        "author": "wangwu",
                        "body": "前期字段没确认",
                        "created_at": "2026-04-21T15:00:00+08:00",
                    },
                ],
            },
            {
                "file": "discussions/eng/auth-redesign/002_lisi_verify_xx.md",
                "type": "verify",
                "creator": "lisi",
                "owner": "lisi",
                "created_at": "2026-04-22T14:00:00+08:00",
                "summary": "验收通过",
                "verifications": [
                    {"target": "discussions/eng/auth-redesign/001_zhangsan_act_xx.md",
                     "judgement": "passed", "comment": "客户当天验收"},
                ],
            },
            {
                "file": "discussions/eng/auth-redesign/003_zhangsan_result_xx.md",
                "type": "result",
                "creator": "zhangsan",
                "owner": "zhangsan",
                "created_at": "2026-04-29T18:30:00+08:00",
                "summary": "客户已接受",
                "outcome": "finished",
                "status_change": {"from": "executing", "to": "finished"},
            },
        ],
    }


@pytest.fixture
def weight_map():
    return {
        "ceo": (2.0, "CEO"),
        "lisi": (1.5, "CTO"),
    }


def _no_body_loader(path: str) -> str:
    return ""


def _stub_body_loader(path: str) -> str:
    return f"BODY of {path.rsplit('/', 1)[-1]}"


# ---------- system prompt ----------


def test_system_prompt_bakes_in_subject():
    s = build_system_prompt("zhangsan")
    # Subject should be referenced multiple times (rule, hard constraint, schema)
    assert s.count("zhangsan") >= 3
    # Sanity: contains the dimension names
    for dim in ("delivery", "accountability", "judgment", "collaboration", "process"):
        assert dim in s


def test_system_prompt_mentions_weight_rules():
    s = build_system_prompt("anyone")
    assert "权重" in s or "weight" in s
    assert "2.0" in s


def test_system_prompt_does_not_leak_subject_into_template_braces():
    """Defensive: the {{ }} escapes in JSON examples should remain literal braces."""
    s = build_system_prompt("subj")
    # The output schema in prompt should have actual { and } characters
    assert '"subject_pinyin": "subj"' in s
    # But shouldn't have stray "{subject}" literal placeholders
    assert "{subject}" not in s
    assert "{{" not in s and "}}" not in s


def test_system_prompt_contains_attribution_rules():
    """Phase 1 / matter 005: prompt must guide AI on归因决策链."""
    s = build_system_prompt("zhangsan")
    # 三个新章节标题都在
    assert "评价对象识别规则" in s
    assert "评价范围限制" in s
    assert "owner_change.reason 解析" in s
    # 关键规则关键词
    assert "自我评价" in s
    assert "明确点名" in s or "@" in s
    # source_file_creator 字段在 schema 示例和硬约束中
    assert "source_file_creator" in s


def test_system_prompt_lists_evidence_source_constraints():
    """Phase 1: 范围限制要明确列出 think/act/verify 是来源、result/insight 不是。"""
    s = build_system_prompt("zhangsan")
    assert "think" in s and "act" in s
    # result / insight 应被显式标"不发起新评价"或类似含义
    assert "result" in s and "insight" in s


# ---------- timeline serialization ----------


def test_serialize_timeline_includes_all_files(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    assert "001_zhangsan_act_xx.md" in out
    assert "002_lisi_verify_xx.md" in out
    assert "003_zhangsan_result_xx.md" in out
    assert "type=act" in out
    assert "type=verify" in out
    assert "type=result" in out


def test_serialize_timeline_marks_file_roles(index_data, weight_map):
    """Phase 1: 文件类型角色标签——think/act 核心、verify 终点、result 背景。"""
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    # act 是核心
    assert "type=act（核心" in out
    # verify 是终点
    assert "type=verify（终点" in out
    # result 是背景
    assert "type=result（背景" in out


def test_serialize_timeline_marks_think_and_insight_roles():
    """Verify think→核心、insight→背景 also rendered."""
    index_data = {
        "matter": {"id": "m", "title": "t", "current_status": "finished", "owner": "x"},
        "timeline": [
            {
                "file": "discussions/x/m/001_x_think.md", "type": "think",
                "creator": "x", "owner": "x", "created_at": "2026-04-01",
                "summary": "s",
            },
            {
                "file": "discussions/x/m/002_x_insight.md", "type": "insight",
                "creator": "x", "owner": "x", "created_at": "2026-04-02",
                "summary": "s",
            },
        ],
    }
    out = serialize_timeline(
        index_data=index_data, weight_map={}, file_body_loader=_no_body_loader,
    )
    assert "type=think（核心" in out
    assert "type=insight（背景" in out


def test_serialize_timeline_annotates_high_weight_actor(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    # CTO appears in lisi's verify file as creator
    assert "lisi (CTO, 权重 1.5x)" in out
    # CEO appears as comment author in act file
    assert "ceo (CEO, 权重 2x)" in out


def test_serialize_timeline_no_annotation_when_pinyin_not_in_weight_map(
    index_data, weight_map,
):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    # zhangsan / wangwu have no weight — should appear bare
    assert "wangwu @" in out
    # zhangsan as creator should not have a weight annotation
    # (look for "creator=zhangsan " followed by something other than "(")
    assert "creator=zhangsan  at=" in out or "creator=zhangsan owner" in out or "creator=zhangsan\n" in out


def test_serialize_timeline_renders_verifications(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    assert "verifications:" in out
    assert "judgement=passed" in out


def test_serialize_timeline_renders_verifications_received(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    assert "verifications_received:" in out
    assert "by=lisi" in out


def test_serialize_timeline_renders_outcome_and_status_change(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    assert "outcome: finished" in out
    assert "executing → finished" in out


def test_serialize_timeline_renders_comments(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_no_body_loader,
    )
    assert "这个交付质量很高" in out
    assert "前期字段没确认" in out
    assert "mentions=[zhangsan_open_id]" in out


def test_serialize_timeline_loads_body(index_data, weight_map):
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=_stub_body_loader,
    )
    assert "BODY of 001_zhangsan_act_xx.md" in out


def test_serialize_timeline_truncates_long_body(index_data, weight_map):
    huge_body = "x" * 10_000
    out = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=lambda p: huge_body,
        max_body_chars=100,
    )
    assert "已截断" in out
    # Truncated body should not contain all 10000 chars in serial form
    assert "x" * 10_000 not in out


def test_serialize_timeline_handles_owner_change_event():
    index_data = {
        "matter": {"id": "m", "title": "t", "current_status": "executing", "owner": "lisi"},
        "timeline": [
            {
                "file": "discussions/x/m/001_zhangsan_act_xx.md",
                "type": "act",
                "creator": "zhangsan", "owner": "zhangsan",
                "created_at": "2026-04-01T10:00:00+08:00",
                "summary": "first act",
            },
            {
                "type": "owner_change",
                "actor": "zhangsan",
                "from_owner": "zhangsan", "to_owner": "lisi",
                "reason": "我休假，请李四接手",
                "created_at": "2026-04-15T10:00:00+08:00",
                "status_change": {"from": "executing", "to": "executing"},
            },
        ],
    }
    out = serialize_timeline(
        index_data=index_data,
        weight_map={},
        file_body_loader=_no_body_loader,
    )
    assert "owner_change" in out
    assert "from_owner=zhangsan" in out
    assert "to_owner=lisi" in out
    assert "我休假" in out


# ---------- truncation ----------


def test_drops_insight_first_when_over_budget(weight_map):
    """When timeline exceeds budget, insight files dropped before think."""
    index_data = {
        "matter": {"id": "m", "title": "t", "current_status": "finished", "owner": "x"},
        "timeline": [
            {"file": "discussions/x/m/001_act.md", "type": "act",
             "creator": "x", "summary": "core", "created_at": "2026-04-01"},
            {"file": "discussions/x/m/002_think.md", "type": "think",
             "creator": "x", "summary": "thinking", "created_at": "2026-04-02"},
            {"file": "discussions/x/m/003_insight.md", "type": "insight",
             "creator": "x", "summary": "later reflection", "created_at": "2026-04-30"},
        ],
    }
    body = "X" * 1000
    out = serialize_timeline(
        index_data=index_data,
        weight_map={},
        file_body_loader=lambda p: body,
        max_body_chars=900,
        max_total_chars=1500,  # tight budget
    )
    # core act must remain
    assert "001_act.md" in out
    # insight should be the first to go
    assert "003_insight.md" not in out


def test_drops_think_only_when_insight_already_dropped(weight_map):
    """If after dropping insight we still overflow, think drops next."""
    index_data = {
        "matter": {"id": "m", "title": "t", "current_status": "finished", "owner": "x"},
        "timeline": [
            {"file": "discussions/x/m/001_act.md", "type": "act",
             "creator": "x", "summary": "core", "created_at": "2026-04-01"},
            {"file": "discussions/x/m/002_think.md", "type": "think",
             "creator": "x", "summary": "thinking", "created_at": "2026-04-02"},
            {"file": "discussions/x/m/003_insight.md", "type": "insight",
             "creator": "x", "summary": "later", "created_at": "2026-04-30"},
        ],
    }
    body = "X" * 1000
    out = serialize_timeline(
        index_data=index_data,
        weight_map={},
        file_body_loader=lambda p: body,
        max_body_chars=1000,
        max_total_chars=1500,  # tight — only the core act fits after dropping
    )
    assert "001_act.md" in out
    assert "003_insight.md" not in out
    assert "002_think.md" not in out


def test_raises_when_core_evidence_exceeds_budget():
    """Two acts exceed budget — refuse to silently drop core."""
    index_data = {
        "matter": {"id": "m", "title": "t", "current_status": "finished", "owner": "x"},
        "timeline": [
            {"file": "discussions/x/m/001_act.md", "type": "act",
             "creator": "x", "summary": "first", "created_at": "2026-04-01"},
            {"file": "discussions/x/m/002_verify.md", "type": "verify",
             "creator": "x", "summary": "second", "created_at": "2026-04-02"},
        ],
    }
    body = "X" * 5000
    with pytest.raises(PromptTooLargeError):
        serialize_timeline(
            index_data=index_data,
            weight_map={},
            file_body_loader=lambda p: body,
            max_body_chars=5000,
            max_total_chars=500,  # absurd: even one item won't fit
        )


# ---------- end-to-end build_scoring_prompt ----------


def test_build_scoring_prompt_returns_two_messages(index_data, weight_map):
    msgs = build_scoring_prompt(
        index_data=index_data,
        weight_map=weight_map,
        subject_pinyin="zhangsan",
        file_body_loader=_no_body_loader,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "zhangsan" in msgs[0]["content"]
    assert "001_zhangsan_act_xx.md" in msgs[1]["content"]
    assert "评分对象：zhangsan" in msgs[1]["content"]
