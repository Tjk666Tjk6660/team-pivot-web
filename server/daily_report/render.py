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

    # 注:不再渲染"📈 团队总览"统计行 —— 老板不爱看僵硬的统计数字,
    # 真正有价值的"5 人 / 4 个事项"等业务数字由 narrative 收尾段自己写。

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
# v2 admin alert card(漏跑 / 失败通知)                                       #
# --------------------------------------------------------------------------- #


def build_admin_alert_card(
    *,
    alert_type: str,                        # "missed" | "failed"
    job_name: str,
    job_view: str,
    expected_at: datetime | None = None,    # missed 用
    error: str | None = None,               # failed 用
    retry_count: int | None = None,         # failed 用
    failures: list[dict] | None = None,     # failed 用,每条 {to, error, name?}
) -> dict:
    """系统级告警卡:发到 admin_notify_chat_ids/open_ids 或 fallback 全部 bot 群。

    模板 'red'(若飞书不支持则 fallback 'wathet')使其与日常日报卡视觉
    显著区分。
    """
    if alert_type == "missed":
        header = f"⚠️ 日报漏跑提醒 · {job_name}"
        lines = [
            f"**任务**:{job_name}",
            f"**视角**:{job_view}",
        ]
        if expected_at:
            lines.append(f"**预期运行**:{_fmt_dt(expected_at)}")
        lines.append("")
        lines.append(f"已超过 30 分钟仍未运行,**未自动补跑**。")
        lines.append("")
        lines.append("请管理员检查:")
        lines.append("- 主服务是否在该时间段重启过")
        lines.append("- jobs 配置是否需要调整")
        lines.append("- 可在 `/admin → 日报配置` 立即手动触发补一次")
        body = "\n".join(lines)
    elif alert_type == "failed":
        header = f"⚠️ 日报失败提醒 · {job_name}"
        lines = [
            f"**任务**:{job_name}",
            f"**视角**:{job_view}",
        ]
        if retry_count is not None:
            lines.append(f"**重试**:{retry_count} 次后仍失败")
        if error:
            lines.append("")
            lines.append(f"**错误**:`{error[:200]}`")
        if failures:
            lines.append("")
            lines.append("**未送达明细**:")
            # 最多列前 8 条避免卡片过长;剩余作为 "+N more" 收尾
            for f in failures[:8]:
                lines.append(_format_failure_line(f))
            if len(failures) > 8:
                lines.append(f"- … 另 {len(failures) - 8} 条未列出")
        lines.append("")
        lines.append("请管理员检查:")
        lines.append("- 飞书目标 ID(open_id / chat_id)是否正确、bot 是否仍在该群 / 该用户对话内")
        lines.append("- 飞书 token 是否正常")
        lines.append("- AI 端点是否可用(超时 / 限流 / Key 失效)")
        lines.append("- 数据仓库 workspace 是否正常")
        body = "\n".join(lines)
    else:
        header = f"⚠️ 日报告警 · {job_name}"
        body = f"alert_type={alert_type}"

    return _card_shell(
        header=header,
        template="wathet",                  # 飞书 schema 2.0 安全色;red 在部分版本不支持
        markdown=body,
    )


def _format_failure_line(f: dict) -> str:
    """单条失败明细行。形如 '- 邓柯 (`ou_xxx`) — feishu_230015: receive_id invalid'"""
    to = f.get("to") or "?"
    name = f.get("name")
    err = (f.get("error") or "?")[:140]
    if name:
        return f"- {name} (`{to}`) — {err}"
    return f"- `{to}` — {err}"


# --------------------------------------------------------------------------- #
# format helpers                                                              #
# --------------------------------------------------------------------------- #


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
