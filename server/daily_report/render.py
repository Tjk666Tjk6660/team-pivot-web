"""Render daily report narratives to Feishu interactive cards (schema 2.0).

v0.2 dengke #013 主张两份独立报告,**两张独立卡片**,共用 _card_shell 工厂。

Phase 3 实现公司视角卡 `build_company_card`;
Phase 4 实现个人视角卡 `build_personal_card`。
"""
from __future__ import annotations

from datetime import datetime

from server.daily_report.company_narrate import CompanyNarrative
from server.daily_report.personal_narrate import (
    NO_ACTIVITY_NARRATIVE,
    PersonalNarrative,
)
from server.daily_report.shared_facts import SharedFacts
from server.notify import _card_shell


# --------------------------------------------------------------------------- #
# Company-view card (Phase 3)                                                 #
# --------------------------------------------------------------------------- #


def build_company_card(facts: SharedFacts, narrative: CompanyNarrative) -> dict:
    """飞书交互卡片字典,直接给 FeishuNotifier.broadcast_card。

    布局:
      header:📊 公司日报 · M-D
      template:blue(AI 成功)/ wathet(fallback / no_activity)
      body:
        覆盖窗口
        团队总览(简短统计行)
        公司视角叙事(主体段落)
        tone 提示(active/steady/stalled 配色 emoji)
        AI 缺席提示(仅 fallback 状态)
    """
    s = facts.summary
    template = "blue" if narrative.status == "ai" else "wathet"
    header = f"📊 公司日报 · {s.window.label}"

    parts: list[str] = []

    parts.append(
        f"📅 覆盖窗口:{_fmt_dt(s.window.since)} → {_fmt_dt(s.window.until)}"
    )
    parts.append("")

    # Team stats — 简短一行,公司视角不堆数字
    parts.append("**📈 团队总览**")
    parts.append(
        f"matter 事件 **{s.total_files}** 篇 · "
        f"状态推进 **{s.total_status_changes}** 次 · "
        f"评论 **{s.total_comments}** 条 · "
        f"涉及 matter **{s.matters_touched}** 个 · "
        f"活跃成员 **{facts.n_active}** 人"
    )
    parts.append("")

    # 整体定性 emoji(状态可视化)
    tone_emoji = {
        "active": "🚀",
        "steady": "🌊",
        "stalled": "⚠️",
    }.get(narrative.tone, "")
    tone_label = {
        "active": "积极推进",
        "steady": "平稳推进",
        "stalled": "偏停滞",
    }.get(narrative.tone, narrative.tone)

    parts.append(f"**{tone_emoji} 整体节奏:{tone_label}**")
    parts.append("")
    parts.append(narrative.summary)

    # Fallback 提示
    if narrative.status == "fallback":
        parts.append("")
        parts.append("_(AI 公司视角生成失败,以上仅展示统计;请管理员检查日志)_")
        if narrative.fallback_reason:
            parts.append(f"_原因:{narrative.fallback_reason}_")

    parts.append("")
    parts.append("_本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论。_")

    return _card_shell(
        header=header,
        template=template,
        markdown="\n".join(parts).rstrip(),
    )


# --------------------------------------------------------------------------- #
# Personal-view card (Phase 4 占位)                                            #
# --------------------------------------------------------------------------- #


def build_personal_card(facts: SharedFacts, narrative: PersonalNarrative) -> dict:
    """飞书交互卡片字典,Phase 4 个人视角报告。

    布局:
      header:👥 个人日报 · M-D
      template:blue(AI 成功)/ wathet(fallback / no_active_users)
      body:
        覆盖窗口
        活跃成员逐人一行(LLM 叙述)
        无活动成员合并到一行(顿号串联)—— dengke 原话"明确写没有
          输入和输出",但渲染层合并以避免 20+ 重复行撑爆篇幅
        AI 缺席提示(仅 fallback)
        AI 分析免责
    """
    s = facts.summary
    template = "blue" if narrative.status == "ai" else "wathet"
    header = f"👥 个人日报 · {s.window.label}"

    parts: list[str] = []
    parts.append(
        f"📅 覆盖窗口:{_fmt_dt(s.window.since)} → {_fmt_dt(s.window.until)}"
    )
    parts.append("")

    active = [e for e in narrative.entries if e.has_activity]
    inactive = [e for e in narrative.entries if not e.has_activity]

    if narrative.status == "no_active_users":
        parts.append("**🌙 团队动态**")
        parts.append("今日团队成员在 Pivot 上均无任何输入和输出。")
    else:
        parts.append("**👥 团队动态**")
        for e in active:
            parts.append(f"· **{e.display_name}**:{e.narrative}")
        if inactive:
            names = "、".join(e.display_name for e in inactive)
            parts.append(f"· {NO_ACTIVITY_NARRATIVE}:{names}")

    if narrative.status == "fallback":
        parts.append("")
        parts.append("_(AI 个人视角生成失败,以上为程序侧统计 stub;请管理员检查日志)_")
        if narrative.fallback_reason:
            parts.append(f"_原因:{narrative.fallback_reason}_")

    parts.append("")
    parts.append("_本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论;不用于绩效评价。_")

    return _card_shell(
        header=header,
        template=template,
        markdown="\n".join(parts).rstrip(),
    )


# --------------------------------------------------------------------------- #
# format helpers                                                              #
# --------------------------------------------------------------------------- #


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
