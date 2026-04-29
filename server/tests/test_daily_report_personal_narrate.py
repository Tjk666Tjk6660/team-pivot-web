"""Tests for `server.daily_report.personal_narrate`.

Covers:
- 全员零活动 → status='no_active_users',全部走固定 "今天没有任何输入和输出"
- LLM 漏返回某活跃用户 → 用程序 stub fallback
- LLM 多返回不存在用户 → 忽略
- LLM 抛错 / 解析失败 → 全员 fallback,无活动者仍走固定文案
- 不在 LLM 输入中暴露 inactive 用户(避免 LLM 凭空生成)
- has_activity=False 的 entry narrative === NO_ACTIVITY_NARRATIVE
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from server.daily_report.company_narrate import AIError, AISettings
from server.daily_report.personal_narrate import (
    NO_ACTIVITY_NARRATIVE,
    narrate_personal,
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


def _ev(*, matter_id: str = "m1", file_type: str = "act",
        creator: str = "alice", owner: str | None = None,
        has_status_change: bool = False) -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id, matter_title=matter_id,
        matter_current_status="executing",
        file=f"discussions/Pivot/{matter_id}/001_{creator}_{file_type}.md",
        file_type=file_type,
        created_at=_w().since, file_in_window=True,
        creator=creator, owner=owner or creator,
        summary=f"{creator} {file_type} on {matter_id}",
        status_change=({"from": "planning", "to": "executing"}
                       if has_status_change else None),
        verifications=(), comments_in_window=(),
    )


def _ua(pinyin: str, *, active: bool = True,
        file_type: str = "act") -> UserActivity:
    creates = (_ev(creator=pinyin, file_type=file_type),) if active else ()
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


def _facts(activities: list[UserActivity]):
    matter_events = []
    for ua in activities:
        matter_events.extend(ua.file_creates)
    return build_shared_facts(matter_events, activities, _summary(), _w())


def _ai() -> AISettings:
    return AISettings(api_key="sk-test", base_url="https://x.test/v1",
                      model="test-model")


# --------------------------------------------------------------------------- #
# zero-activity short circuit                                                 #
# --------------------------------------------------------------------------- #


def test_all_inactive_short_circuits_no_ai_call():
    activities = [
        _ua("alice", active=False),
        _ua("bob", active=False),
    ]
    facts = _facts(activities)
    with patch("server.daily_report.personal_narrate.generate_text") as m:
        result = narrate_personal(facts, ai_settings=_ai(), no_ai=False)
    m.assert_not_called()
    assert result.status == "no_active_users"
    # 所有 entry 都标记无活动 + 固定文案
    assert all(not e.has_activity for e in result.entries)
    assert all(e.narrative == NO_ACTIVITY_NARRATIVE for e in result.entries)
    pinyins = [e.pinyin for e in result.entries]
    assert pinyins == ["alice", "bob"]


# --------------------------------------------------------------------------- #
# disabled / missing AI                                                       #
# --------------------------------------------------------------------------- #


def test_no_ai_flag_returns_fallback():
    activities = [_ua("alice", active=True), _ua("bob", active=False)]
    facts = _facts(activities)
    result = narrate_personal(facts, ai_settings=_ai(), no_ai=True)
    assert result.status == "fallback"
    # 活跃成员走 stub,无活动成员仍是固定文案
    by_p = {e.pinyin: e for e in result.entries}
    assert by_p["alice"].has_activity is True
    assert by_p["alice"].narrative != NO_ACTIVITY_NARRATIVE
    assert by_p["bob"].narrative == NO_ACTIVITY_NARRATIVE


def test_missing_ai_settings_returns_fallback():
    activities = [_ua("alice", active=True)]
    facts = _facts(activities)
    result = narrate_personal(facts, ai_settings=None, no_ai=False)
    assert result.status == "fallback"


# --------------------------------------------------------------------------- #
# happy AI path                                                               #
# --------------------------------------------------------------------------- #


def test_happy_ai_path_assigns_narratives():
    activities = [
        _ua("alice", active=True, file_type="verify"),
        _ua("bob", active=True, file_type="result"),
        _ua("zhang", active=False),
    ]
    facts = _facts(activities)
    fake_response = (
        '{"entries": ['
        '{"pinyin": "alice", "narrative": "在 Pivot 推进 verify"},'
        '{"pinyin": "bob", "narrative": "完成一篇 result"}'
        ']}'
    )
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value=fake_response,
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "ai"
    by_p = {e.pinyin: e for e in result.entries}
    assert by_p["alice"].narrative == "在 Pivot 推进 verify"
    assert by_p["bob"].narrative == "完成一篇 result"
    # 全员都在 entries 里(包括 inactive)
    assert by_p["zhang"].has_activity is False
    assert by_p["zhang"].narrative == NO_ACTIVITY_NARRATIVE


def test_llm_missing_user_uses_program_stub():
    """LLM 没返回某个活跃用户的 narrative → 程序侧 stub 兜底。"""
    activities = [
        _ua("alice", active=True),
        _ua("bob", active=True),
    ]
    facts = _facts(activities)
    fake_response = (
        '{"entries": ['
        '{"pinyin": "alice", "narrative": "alice 的叙述"}'
        ']}'   # bob 缺失
    )
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value=fake_response,
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "ai"  # status 仍是 ai(整体调用成功了)
    by_p = {e.pinyin: e for e in result.entries}
    assert by_p["alice"].narrative == "alice 的叙述"
    assert by_p["bob"].has_activity is True
    # bob 走 stub —— 应包含统计信息(创建文件数 / 类型)
    assert "创建" in by_p["bob"].narrative


def test_llm_returns_unknown_user_is_ignored():
    """LLM 凭空多返回一个不在 users 表的人 → 忽略不影响。"""
    activities = [_ua("alice", active=True)]
    facts = _facts(activities)
    fake_response = (
        '{"entries": ['
        '{"pinyin": "alice", "narrative": "alice"},'
        '{"pinyin": "ghost", "narrative": "non-existent user"}'
        ']}'
    )
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value=fake_response,
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    pinyins = [e.pinyin for e in result.entries]
    assert "ghost" not in pinyins
    assert pinyins == ["alice"]


# --------------------------------------------------------------------------- #
# AI failure paths                                                            #
# --------------------------------------------------------------------------- #


def test_ai_raises_returns_full_fallback():
    activities = [_ua("alice", active=True), _ua("bob", active=False)]
    facts = _facts(activities)
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        side_effect=AIError("boom"),
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "ai_error" in (result.fallback_reason or "")
    # 即使 fallback,无活动者仍是固定文案,活跃者走 stub
    by_p = {e.pinyin: e for e in result.entries}
    assert by_p["bob"].narrative == NO_ACTIVITY_NARRATIVE
    assert by_p["alice"].has_activity
    assert by_p["alice"].narrative != NO_ACTIVITY_NARRATIVE


def test_empty_response_returns_fallback():
    activities = [_ua("alice", active=True)]
    facts = _facts(activities)
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value="",
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "fallback"


def test_missing_entries_field_returns_fallback():
    activities = [_ua("alice", active=True)]
    facts = _facts(activities)
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value='{"users": []}',
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "fallback"
    assert "schema_error" in (result.fallback_reason or "")


def test_excessively_long_narrative_is_truncated():
    activities = [_ua("alice", active=True)]
    facts = _facts(activities)
    long_text = "a" * 250
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        return_value=f'{{"entries": [{{"pinyin": "alice", "narrative": "{long_text}"}}]}}',
    ):
        result = narrate_personal(facts, ai_settings=_ai())
    assert result.status == "ai"
    alice = result.entries[0]
    assert len(alice.narrative) <= 201   # 200 + ellipsis
    assert alice.narrative.endswith("…")


# --------------------------------------------------------------------------- #
# Defensive: inactive users never get LLM-generated text                      #
# --------------------------------------------------------------------------- #


def test_inactive_users_never_show_in_llm_input():
    """LLM 调用时 payload 里不应有 inactive 用户(避免 LLM 编叙述)。"""
    activities = [
        _ua("alice", active=True),
        _ua("zhang", active=False),
    ]
    facts = _facts(activities)
    captured = {}
    def fake_gen(*, messages, **_kw):
        captured["payload"] = messages[-1]["content"]
        return '{"entries": [{"pinyin": "alice", "narrative": "x"}]}'
    with patch(
        "server.daily_report.personal_narrate.generate_text",
        side_effect=fake_gen,
    ):
        narrate_personal(facts, ai_settings=_ai())
    payload = captured["payload"]
    assert "alice" in payload
    assert "zhang" not in payload
