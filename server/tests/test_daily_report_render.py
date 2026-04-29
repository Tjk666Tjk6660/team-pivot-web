"""Tests for `server.daily_report.render.build_daily_report_card`. Snapshot-
style assertions on key card fields — we don't try to exactly match Feishu's
card schema (the network layer would catch real schema breaks)."""
from __future__ import annotations

from datetime import datetime

import pytest

from server.daily_report.render import _stars, build_daily_report_card
from server.daily_report.types import (
    CommitRecord,
    ScoringResult,
    TeamReport,
    TeamSummary,
    TimeWindow,
    UserActivity,
    UserScore,
)
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _w() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ),
    )


def _summary(**overrides) -> TeamSummary:
    base = dict(
        window=_w(),
        total_files=23, total_commits=41, total_status_changes=3,
        total_comments=18, matters_touched=7,
        unattributed_commits=(), inactive_users=(),
        fetch_warning=None,
    )
    base.update(overrides)
    return TeamSummary(**base)


def _activity(pinyin: str, name: str = "", *, active: bool = True) -> UserActivity:
    if active:
        # Give them ONE file_create so is_active=True
        from server.daily_report.types import MatterEvent
        ev = MatterEvent(
            matter_id="m", matter_title="m", matter_current_status="planning",
            file=f"{pinyin}.md", file_type="think",
            created_at=datetime(2026, 4, 26, 12, tzinfo=CHINA_TZ),
            file_in_window=True, creator=pinyin, owner=pinyin,
            summary="", status_change=None, verifications=(),
            comments_in_window=(),
        )
        creates = (ev,)
    else:
        creates = ()
    return UserActivity(
        pinyin=pinyin, display_name=name or pinyin,
        file_creates=creates, file_owns=(), verifications_given=(),
        status_changes_triggered=(), comments_given=(),
        mentions_received=0, commits=(),
    )


def _score_ai(per_user: list[UserScore]) -> ScoringResult:
    return ScoringResult(
        status="ai",
        team_score=4.0,
        team_sub_scores={"output": 4.0, "progress": 3.5, "blocker": 4.5, "collab": 4.0},
        team_summary="全员推进有节奏",
        per_user=tuple(per_user),
    )


def _score_fallback(per_user: list[UserScore], reason: str = "ai_disabled") -> ScoringResult:
    return ScoringResult(
        status="fallback",
        team_score=3.0,
        team_sub_scores={k: None for k in ("output", "progress", "blocker", "collab")},
        team_summary="(AI 评分缺失,以下仅展示统计)",
        per_user=tuple(per_user),
        fallback_reason=reason,
    )


# --------------------------------------------------------------------------- #
# happy AI path                                                               #
# --------------------------------------------------------------------------- #


def test_ai_card_has_blue_template_and_full_layout():
    user_score = UserScore(
        pinyin="dengke", score=4.5,
        sub_scores={"output": 4.5, "progress": 5.0, "blocker": 5.0, "collab": 4.0},
        summary="完成 auth-redesign 收口",
        highlights=("auth-redesign · finished", "verify ×2"),
    )
    report = TeamReport(
        summary=_summary(),
        user_activities=(_activity("dengke", "邓柯"),),
        scoring=_score_ai([user_score]),
    )
    card = build_daily_report_card(report)

    # Header + template
    assert card["header"]["title"]["content"] == "📊 团队日报 · 4-26"
    assert card["header"]["template"] == "blue"

    # Body markdown contains all expected blocks
    md = _markdown_from(card)
    assert "📅 覆盖窗口" in md
    assert "📈 团队总览" in md
    # matter 主线在前
    assert "matter 事件 **23**" in md
    # 代码侧已降级为辅助参考(斜体),不在主统计行
    assert "配套代码提交 41 个" in md
    assert "⭐ 团队评分" in md
    assert "(4.0)" in md
    assert "产出 4.0 · 推进 3.5 · 阻塞 4.5 · 协作 4.0" in md
    assert "全员推进有节奏" in md
    assert "👥 个人评分" in md
    assert "邓柯" in md
    assert "(4.5)" in md
    assert "完成 auth-redesign 收口" in md
    assert "auth-redesign · finished / verify ×2" in md

    # No CTA button — daily report is decoupled from the Pivot product
    # (no in-product page supports this task).
    assert _has_button(card) is False


def test_ai_card_uses_users_display_name_not_pinyin():
    """If pinyin == 'dengke' but users.name == '邓柯', card shows 邓柯."""
    user_score = UserScore(
        pinyin="dengke", score=4.5,
        sub_scores={"output": 4.5, "progress": 5.0, "blocker": 5.0, "collab": 4.0},
        summary="x", highlights=(),
    )
    report = TeamReport(
        summary=_summary(),
        user_activities=(_activity("dengke", "邓柯"),),
        scoring=_score_ai([user_score]),
    )
    md = _markdown_from(build_daily_report_card(report))
    assert "**邓柯**" in md
    assert "**dengke**" not in md     # raw pinyin not used as display


def test_inactive_users_listed():
    report = TeamReport(
        summary=_summary(inactive_users=("张博", "佘耀君")),
        user_activities=(),
        scoring=_score_ai([]),
    )
    md = _markdown_from(build_daily_report_card(report))
    assert "😴 今日 0 活动" in md
    assert "张博" in md and "佘耀君" in md


def test_unattributed_commits_show_count_only():
    """Card surfaces total count of unattributed commits as an ops hint
    (matter is main line, code is auxiliary — these are author-mapping
    issues for the admin to fix, not "team anomalies")."""
    secret_email_commit = CommitRecord(
        sha="x"*40, author_name="External", author_email="someone@private.com",
        committed_at=datetime(2026, 4, 26, 12, tzinfo=CHINA_TZ),
        subject="leak me", files_changed=1, insertions=1, deletions=0,
    )
    report = TeamReport(
        summary=_summary(unattributed_commits=(secret_email_commit,)*3),
        user_activities=(),
        scoring=_score_ai([]),
    )
    md = _markdown_from(build_daily_report_card(report))
    # 数字仍展示,但用"运维提示"措辞而非主异常符号
    assert "运维提示" in md
    assert "3 个 commit 暂未关联" in md
    # 个人邮箱 / commit subject 仍不外泄
    assert "private.com" not in md
    assert "leak me" not in md


# --------------------------------------------------------------------------- #
# fallback path                                                               #
# --------------------------------------------------------------------------- #


def test_fallback_card_uses_wathet_template():
    user_score = UserScore(
        pinyin="alice", score=3.5,
        sub_scores={k: None for k in ("output", "progress", "blocker", "collab")},
        summary="(AI 评分缺失,按活动量粗分)", highlights=(),
    )
    report = TeamReport(
        summary=_summary(),
        user_activities=(_activity("alice"),),
        scoring=_score_fallback([user_score], reason="ai_error: TimeoutError: too slow"),
    )
    card = build_daily_report_card(report)
    assert card["header"]["template"] == "wathet"

    md = _markdown_from(card)
    assert "AI 评分缺失" in md
    assert "TimeoutError" in md
    # 4 sub-dimension numbers should NOT appear (AI block skipped)
    assert "产出 4.0" not in md
    # but per-user fallback summary still surfaces
    assert "alice" in md


def test_fallback_card_omits_team_sub_scores_block():
    report = TeamReport(
        summary=_summary(),
        user_activities=(),
        scoring=_score_fallback([]),
    )
    md = _markdown_from(build_daily_report_card(report))
    # Team sub-score line "产出 X · 推进 Y · 阻塞 Z · 协作 W" must be absent
    assert "产出" not in md or "推进" not in md  # at least one missing


# --------------------------------------------------------------------------- #
# zero-activity                                                               #
# --------------------------------------------------------------------------- #


def test_zero_activity_short_circuits_with_napping_label():
    """All zero stats → card stops at 团队无活动 row, no scoring blocks."""
    report = TeamReport(
        summary=_summary(
            total_files=0, total_commits=0, total_comments=0,
            total_status_changes=0, matters_touched=0,
            inactive_users=("Alice", "Bob"),
        ),
        user_activities=(_activity("alice", active=False),),
        scoring=_score_fallback([]),
    )
    md = _markdown_from(build_daily_report_card(report))
    assert "今日团队无活动" in md
    assert "团队评分" not in md
    assert "个人评分" not in md


# --------------------------------------------------------------------------- #
# fetch warning                                                               #
# --------------------------------------------------------------------------- #


def test_fetch_warning_surfaces_in_card():
    report = TeamReport(
        summary=_summary(fetch_warning="git fetch 失败:network unreachable"),
        user_activities=(),
        scoring=_score_ai([]),
    )
    md = _markdown_from(build_daily_report_card(report))
    assert "⚠️ 代码仓库未刷新" in md
    assert "network unreachable" in md


# --------------------------------------------------------------------------- #
# stars helper                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("score,expected", [
    (5.0, "★★★★★"),
    (4.5, "★★★★☆"),
    (4.0, "★★★★☆"),
    (3.5, "★★★☆☆"),
    (1.0, "★☆☆☆☆"),
    # out of range — clamp
    (0.0, "☆☆☆☆☆"),
    (10.0, "★★★★★"),
])
def test_stars_rendering(score, expected):
    assert _stars(score) == expected


# --------------------------------------------------------------------------- #
# helpers (extract elements from card dict for assertions)                    #
# --------------------------------------------------------------------------- #


def _markdown_from(card: dict) -> str:
    """Pull the `markdown` element content out of `_card_shell`'s body."""
    for el in card["body"]["elements"]:
        if el.get("tag") == "markdown":
            return el["content"]
    raise AssertionError(f"no markdown element in card: {card}")


def _has_button(card: dict) -> bool:
    return any(el.get("tag") == "button" for el in card["body"]["elements"])
