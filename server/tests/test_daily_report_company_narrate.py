"""Tests for `server.daily_report.company_narrate`.

Covers:
- 全员零活动 → status='no_activity',固定文案,tone='stalled'
- no_ai=True → fallback
- ai_settings None / api_key 空 → fallback
- happy AI path:LLM 返回合法 JSON → status='ai',tone 来自 LLM
- LLM 抛异常 → fallback (ai_error)
- LLM 返回空响应 → fallback (parse_error)
- LLM 返回非 JSON / 无 ```json``` 包裹 → fallback
- LLM 返回缺字段 / tone 越界 → fallback (schema_error)
- summary 超长被截断
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from server.daily_report.company_narrate import (
    AISettings,
    AIError,
    CompanyNarrative,
    narrate_company,
)
from server.daily_report.shared_facts import build_shared_facts
from server.daily_report.types import (
    MatterEvent,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _w() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 28, 9, 0, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 29, 9, 0, tzinfo=CHINA_TZ),
    )


def _ev(matter_id: str = "m1", file: str = "discussions/Pivot/m1/001.md",
        creator: str = "alice", file_type: str = "act",
        status: str = "executing") -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id, matter_title=matter_id,
        matter_current_status=status,
        file=file, file_type=file_type,
        created_at=_w().since,
        file_in_window=True,
        creator=creator, owner=creator,
        summary=f"{matter_id} {file_type}",
        status_change=None, verifications=(), comments_in_window=(),
    )


def _ua(pinyin: str, *, active: bool = True) -> UserActivity:
    creates = (_ev(creator=pinyin),) if active else ()
    return UserActivity(
        pinyin=pinyin, display_name=pinyin,
        file_creates=creates, file_owns=(),
        verifications_given=(), status_changes_triggered=(),
        comments_given=(), mentions_received=0,
    )


def _summary(**overrides) -> TeamSummary:
    base = dict(
        window=_w(), total_files=0, total_status_changes=0,
        total_comments=0, matters_touched=0, inactive_users=(),
    )
    base.update(overrides)
    return TeamSummary(**base)


def _facts_with_activity():
    """构造一份"有活动"的 SharedFacts:5 文件 / 3 matter / 2 活跃成员。"""
    events = [
        _ev("m1", "discussions/Pivot/m1/001.md", "alice", "think"),
        _ev("m1", "discussions/Pivot/m1/002.md", "bob", "act"),
        _ev("m2", "discussions/Pivot/m2/001.md", "alice", "verify"),
        _ev("m2", "discussions/Pivot/m2/002.md", "alice", "result", status="finished"),
        _ev("m3", "discussions/enclaws/m3/001.md", "bob", "think", status="planning"),
    ]
    activities = [_ua("alice", active=True), _ua("bob", active=True)]
    summary = _summary(
        total_files=5, total_status_changes=1, total_comments=0,
        matters_touched=3,
    )
    return build_shared_facts(events, activities, summary, _w())


def _facts_zero():
    """全员零活动 SharedFacts。"""
    activities = [_ua("alice", active=False), _ua("bob", active=False)]
    return build_shared_facts(
        [], activities,
        _summary(inactive_users=("alice", "bob")),
        _w(),
    )


def _ai() -> AISettings:
    return AISettings(api_key="sk-test", base_url="https://x.test/v1",
                      model="test-model")


# --------------------------------------------------------------------------- #
# zero-activity short circuit                                                 #
# --------------------------------------------------------------------------- #


def test_zero_activity_short_circuits_without_calling_ai():
    facts = _facts_zero()
    with patch("server.daily_report.company_narrate.generate_text") as mock:
        result = narrate_company(facts, ai_settings=_ai(), no_ai=False)
    mock.assert_not_called()
    assert result.status == "no_activity"
    assert result.tone == "stalled"
    assert "无任何 matter 活动" in result.summary


# --------------------------------------------------------------------------- #
# disabled / missing AI                                                       #
# --------------------------------------------------------------------------- #


def test_no_ai_flag_returns_fallback():
    facts = _facts_with_activity()
    result = narrate_company(facts, ai_settings=_ai(), no_ai=True)
    assert result.status == "fallback"
    assert "ai_disabled" in (result.fallback_reason or "")


def test_missing_ai_settings_returns_fallback():
    facts = _facts_with_activity()
    result = narrate_company(facts, ai_settings=None, no_ai=False)
    assert result.status == "fallback"


def test_empty_api_key_returns_fallback():
    facts = _facts_with_activity()
    result = narrate_company(
        facts,
        ai_settings=AISettings(api_key="  ", base_url="x", model="y"),
        no_ai=False,
    )
    assert result.status == "fallback"


# --------------------------------------------------------------------------- #
# happy AI path                                                               #
# --------------------------------------------------------------------------- #


def test_happy_ai_path_returns_ai_status():
    facts = _facts_with_activity()
    fake_response = (
        '{"summary": "团队聚焦于 Pivot 与 enclaws 两个方向,主链路有实质闭环动作,'
        '整体节奏健康。", "tone": "active"}'
    )
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value=fake_response,
    ):
        result = narrate_company(facts, ai_settings=_ai(), no_ai=False)
    assert result.status == "ai"
    assert result.tone == "active"
    assert "聚焦于 Pivot" in result.summary


def test_ai_response_with_json_fence_is_parsed():
    facts = _facts_with_activity()
    fake_response = (
        "```json\n"
        '{"summary": "整体平稳推进。", "tone": "steady"}\n'
        "```"
    )
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value=fake_response,
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "ai"
    assert result.tone == "steady"


# --------------------------------------------------------------------------- #
# AI failure paths                                                            #
# --------------------------------------------------------------------------- #


def test_ai_raises_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        side_effect=AIError("boom"),
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "ai_error" in (result.fallback_reason or "")
    assert "AIError" in (result.fallback_reason or "")


def test_ai_timeout_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        side_effect=TimeoutError("too slow"),
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "TimeoutError" in (result.fallback_reason or "")


def test_ai_unexpected_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        side_effect=RuntimeError("network"),
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "ai_unexpected" in (result.fallback_reason or "")


def test_empty_response_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value="",
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "parse_error" in (result.fallback_reason or "")


def test_non_json_response_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value="this is not json at all",
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"


def test_missing_summary_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value='{"tone": "active"}',
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "schema_error" in (result.fallback_reason or "")


def test_invalid_tone_returns_fallback():
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value='{"summary": "ok", "tone": "amazing"}',
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "schema_error" in (result.fallback_reason or "")


def test_excessively_long_summary_is_truncated():
    facts = _facts_with_activity()
    long_text = "a" * 600
    with patch(
        "server.daily_report.company_narrate.generate_text",
        return_value=f'{{"summary": "{long_text}", "tone": "active"}}',
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.status == "ai"
    assert len(result.summary) <= 451   # 450 + ellipsis
    assert result.summary.endswith("…")


# --------------------------------------------------------------------------- #
# Tone inferred in fallback                                                   #
# --------------------------------------------------------------------------- #


def test_fallback_tone_steady_when_some_activity():
    """有 matter activity 但 AI 失败 → tone='steady'。"""
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        side_effect=AIError("boom"),
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert result.tone == "steady"


def test_fallback_summary_contains_stats():
    """Fallback summary 提一下数字,让管理者能从卡片直接看到统计。"""
    facts = _facts_with_activity()
    with patch(
        "server.daily_report.company_narrate.generate_text",
        side_effect=AIError("boom"),
    ):
        result = narrate_company(facts, ai_settings=_ai())
    assert "matter" in result.summary
    assert str(facts.summary.matters_touched) in result.summary
    assert str(facts.summary.total_files) in result.summary
