"""Tests for `server.daily_report.render`. Snapshot-style assertions on key
card fields — we don't try to exactly match Feishu's card schema (the network
layer would catch real schema breaks).

Phase 3 covers `build_company_card`. Phase 4 will add `build_personal_card`.
"""
from __future__ import annotations

from datetime import datetime

from server.daily_report.company_narrate import CompanyNarrative
from server.daily_report.personal_narrate import PersonalEntry, PersonalNarrative
from server.daily_report.render import (
    build_admin_alert_card,
    build_company_card,
    build_personal_card,
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


def _ev(matter_id: str = "m1", file: str = "discussions/Pivot/m1/001.md") -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id, matter_title=matter_id,
        matter_current_status="executing",
        file=file, file_type="act",
        created_at=_w().since, file_in_window=True,
        creator="alice", owner="alice",
        summary="x", status_change=None,
        verifications=(), comments_in_window=(),
    )


def _ua(pinyin: str, *, active: bool = True) -> UserActivity:
    creates = (_ev(),) if active else ()
    return UserActivity(
        pinyin=pinyin, display_name=pinyin,
        file_creates=creates, file_owns=(),
        verifications_given=(), status_changes_triggered=(),
        comments_given=(), mentions_received=0,
    )


def _summary(**overrides) -> TeamSummary:
    base = dict(
        window=_w(), total_files=5, total_status_changes=1,
        total_comments=3, matters_touched=2, inactive_users=("zhang",),
    )
    base.update(overrides)
    return TeamSummary(**base)


def _facts():
    events = [_ev("m1"), _ev("m2", "discussions/enclaws/m2/001.md")]
    activities = [_ua("alice"), _ua("zhang", active=False)]
    return build_shared_facts(events, activities, _summary(), _w())


def _markdown_from(card: dict) -> str:
    for el in card["body"]["elements"]:
        if el.get("tag") == "markdown":
            return el["content"]
    raise AssertionError(f"no markdown element in card: {card}")


# --------------------------------------------------------------------------- #
# build_company_card                                                          #
# --------------------------------------------------------------------------- #


def test_ai_company_card_has_blue_template():
    nar = CompanyNarrative(
        status="ai",
        summary="团队聚焦于 Pivot 与 enclaws,主链路有实质闭环动作。",
        tone="active",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "blue"
    assert card["header"]["title"]["content"] == "📊 公司日报 · 4-28"


def test_fallback_company_card_uses_wathet_template():
    nar = CompanyNarrative(
        status="fallback",
        summary="今日团队触动 2 个 matter ...",
        tone="steady",
        fallback_reason="ai_error: TimeoutError",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "wathet"
    md = _markdown_from(card)
    assert "AI 公司视角生成失败" in md
    assert "TimeoutError" in md


def test_no_activity_card_uses_wathet_and_marks_stalled():
    nar = CompanyNarrative(
        status="no_activity",
        summary="今日团队在 Pivot 上无任何 matter 活动。",
        tone="stalled",
    )
    card = build_company_card(_facts(), nar)
    assert card["header"]["template"] == "wathet"
    md = _markdown_from(card)
    assert "偏停滞" in md


def test_ai_card_renders_window_and_stats():
    nar = CompanyNarrative(status="ai", summary="x", tone="steady")
    md = _markdown_from(build_company_card(_facts(), nar))
    assert "覆盖窗口" in md
    assert "2026-04-28 09:00" in md
    assert "2026-04-29 09:00" in md
    assert "matter 事件 **5** 篇" in md
    assert "状态推进 **1** 次" in md
    assert "评论 **3** 条" in md
    assert "活跃成员 **1** 人" in md   # _ua("alice") active, _ua("zhang") inactive


def test_tone_emoji_and_label_match():
    cases = [
        ("active",  "🚀", "积极推进"),
        ("steady",  "🌊", "平稳推进"),
        ("stalled", "⚠️", "偏停滞"),
    ]
    for tone, emoji, label in cases:
        nar = CompanyNarrative(status="ai", summary="x", tone=tone)
        md = _markdown_from(build_company_card(_facts(), nar))
        assert emoji in md, f"{tone} should render emoji {emoji}"
        assert label in md, f"{tone} should render label {label}"


def test_disclaimer_always_present():
    """提示这是 AI 分析不是结论 —— ai/fallback 都要有这一行。"""
    for status in ("ai", "fallback", "no_activity"):
        nar = CompanyNarrative(status=status, summary="x", tone="steady")
        md = _markdown_from(build_company_card(_facts(), nar))
        assert "AI" in md and "管理参考" in md


# --------------------------------------------------------------------------- #
# build_personal_card                                                         #
# --------------------------------------------------------------------------- #


def _personal_entries(*, n_active: int = 2, n_inactive: int = 3):
    entries: list[PersonalEntry] = []
    for i in range(n_active):
        entries.append(PersonalEntry(
            pinyin=f"a{i}", display_name=f"成员{i}",
            has_activity=True,
            narrative=f"成员{i}今天的输入和输出",
        ))
    for j in range(n_inactive):
        entries.append(PersonalEntry(
            pinyin=f"b{j}", display_name=f"无活动{j}",
            has_activity=False,
            narrative="今天没有任何输入和输出",
        ))
    return tuple(entries)


def test_personal_card_ai_template_blue():
    nar = PersonalNarrative(status="ai", entries=_personal_entries())
    card = build_personal_card(_facts(), nar)
    assert card["header"]["template"] == "blue"
    assert "👥" in card["header"]["title"]["content"]
    assert "4-28" in card["header"]["title"]["content"]


def test_personal_card_active_users_each_on_own_line():
    nar = PersonalNarrative(status="ai", entries=_personal_entries(
        n_active=3, n_inactive=0,
    ))
    md = _markdown_from(build_personal_card(_facts(), nar))
    for i in range(3):
        assert f"**成员{i}**" in md
        assert f"成员{i}今天的输入和输出" in md


def test_personal_card_inactive_users_merged_to_one_line():
    """无活动成员合并到一行,顿号串联。"""
    nar = PersonalNarrative(status="ai", entries=_personal_entries(
        n_active=1, n_inactive=3,
    ))
    md = _markdown_from(build_personal_card(_facts(), nar))
    # 合并行展示三个名字,中间用顿号
    assert "今天没有任何输入和输出:无活动0、无活动1、无活动2" in md
    # 不应该有"无活动X 今天没有任何输入和输出"独立成行的形式
    assert "**无活动0**" not in md


def test_personal_card_no_active_users_status():
    entries = tuple(
        PersonalEntry(pinyin=f"u{i}", display_name=f"u{i}",
                      has_activity=False,
                      narrative="今天没有任何输入和输出")
        for i in range(3)
    )
    nar = PersonalNarrative(status="no_active_users", entries=entries)
    card = build_personal_card(_facts(), nar)
    md = _markdown_from(card)
    assert card["header"]["template"] == "wathet"
    assert "团队成员在 Pivot 上均无任何输入和输出" in md


def test_personal_card_fallback_shows_reason():
    nar = PersonalNarrative(
        status="fallback",
        entries=_personal_entries(),
        fallback_reason="ai_error: TimeoutError",
    )
    card = build_personal_card(_facts(), nar)
    md = _markdown_from(card)
    assert card["header"]["template"] == "wathet"
    assert "AI 个人视角生成失败" in md
    assert "TimeoutError" in md


def test_personal_card_disclaimer_mentions_no_perf_eval():
    """免责声明特别强调"不用于绩效评价"——dengke #013 反复强调。"""
    nar = PersonalNarrative(status="ai", entries=_personal_entries())
    md = _markdown_from(build_personal_card(_facts(), nar))
    assert "不用于绩效评价" in md


# --------------------------------------------------------------------------- #
# admin alert card                                                            #
# --------------------------------------------------------------------------- #


def test_admin_alert_failed_renders_per_target_failures_with_names():
    card = build_admin_alert_card(
        alert_type="failed",
        job_name="个人早报",
        job_view="personal",
        error="2 failed: …a966fa55(http_400 …)",
        retry_count=3,
        failures=[
            {"to": "ou_1234", "name": "邓柯", "error": "http_400: invalid receive_id"},
            {"to": "ou_5678", "name": None, "error": "feishu_230015: receive_id invalid"},
        ],
    )
    md = _markdown_from(card)
    # 含汇总 error
    assert "2 failed" in md or "http_400" in md
    # 单条明细行
    assert "邓柯" in md and "ou_1234" in md
    assert "ou_5678" in md
    # 没有 name 时不会出现 None 字面
    assert "None" not in md


def test_admin_alert_failed_truncates_when_many_failures():
    failures = [
        {"to": f"ou_{i:04d}", "name": None, "error": "http_400"}
        for i in range(12)
    ]
    card = build_admin_alert_card(
        alert_type="failed",
        job_name="x", job_view="personal",
        error="12 failed", retry_count=3, failures=failures,
    )
    md = _markdown_from(card)
    # 只列前 8 条 + "…另 4 条未列出"
    assert "ou_0000" in md
    assert "ou_0007" in md  # 第 8 条 (0-indexed 7) 仍在
    assert "ou_0008" not in md
    assert "另 4 条未列出" in md


def test_admin_alert_missed_unchanged_no_failures_section():
    card = build_admin_alert_card(
        alert_type="missed",
        job_name="个人早报", job_view="personal",
        expected_at=datetime(2026, 4, 30, 9, 30, tzinfo=CHINA_TZ),
    )
    md = _markdown_from(card)
    assert "未自动补跑" in md
    assert "未送达明细" not in md  # missed 类型不展示这块
