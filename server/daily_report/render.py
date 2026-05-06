"""Render daily report narratives to Feishu interactive cards (schema 2.0).

v0.2 dengke #013 主张两份独立报告,**两张独立卡片**,共用 _card_shell 工厂。

Phase 3 实现公司视角卡 `build_company_card`;
Phase 4 实现个人视角卡 `build_personal_card`。

格式层后处理(2026-05-06 演示反馈):
- 删除 "整体节奏" 那一行(老板视为多余的主观判断)
- 方向段标题"第X是 Y 方向"渲染成 bold + 编号 emoji,与正文加视觉区分
- 子段标题(以 —— 结尾)下若有 ≥2 行事项,逐行加 "- " 前缀变成 markdown
  bullet list,提升层次感
内容(LLM 输出本身)零改动,只是渲染层加视觉装饰。
"""
from __future__ import annotations

import re
from datetime import datetime

from server.daily_report.company_narrate import CompanyNarrative
from server.daily_report.personal_narrate import (
    NO_ACTIVITY_NARRATIVE,
    PersonalNarrative,
)
from server.daily_report.shared_facts import SharedFacts
from server.notify import _card_shell

_ORDINAL_TO_EMOJI = {
    "一": "1️⃣", "二": "2️⃣", "三": "3️⃣", "四": "4️⃣", "五": "5️⃣",
    "六": "6️⃣", "七": "7️⃣", "八": "8️⃣", "九": "9️⃣", "十": "🔟",
}

# 方向段开头匹配:"第X是 Y。" + 可选剩余内容(可能是子段标题)。
# 匹配中文序号一/二/三...,方向名(到第一个句号 "。" 为止),句号后剩余文字。
# 注意:不要求方向名以"方向"二字结尾 —— LLM 偶尔写"第二是 enclaws 与
# OPC 项目底座。" 没带"方向"二字也合法,识别为方向段标题。
_DIRECTION_HEADER_RE = re.compile(
    r"^第([一二三四五六七八九十])是\s*(.+?)。\s*(.*)$"
)


def _format_company_summary_for_card(text: str) -> str:
    """格式层后处理 LLM 输出的公司视角叙事,加视觉层次。

    内容(每个 matter 的事实陈述、跨度判断、把关人具名等)零改动。

    转换规则:
    1. 方向段开头"第X是 Y 方向。剩余" → 单独一行 **emoji Y 方向**,
       剩余内容(可能含子段标题)放下一段
    2. 子段标题(以 —— 结尾)下方紧跟的多行事项(到空行截止),**当行数 ≥ 2
       时**逐行加 "- " 前缀。≤1 行的(≤3 matter 串接子段)不加,因为
       单点 bullet 没意义。
    3. 不是子段事项的普通段落(开头 / 结尾收束句)不动。
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ---- 方向段标题 ----
        m = _DIRECTION_HEADER_RE.match(stripped)
        if m:
            ord_zh, direction, rest = m.groups()
            emoji = _ORDINAL_TO_EMOJI.get(ord_zh, "▪️")
            out.append(f"**{emoji} {direction}**")
            i += 1
            # 剩余内容(可能是子段头或起始描述)放下一段
            if rest:
                out.append("")
                if _is_subsection_header(rest.rstrip()):
                    # 子段头用 bold 与正文加视觉区分
                    out.append(f"**{rest.rstrip()}**")
                    i, block_lines = _collect_block(lines, i)
                    out.extend(_bulletize_if_multi(block_lines))
                else:
                    out.append(rest)
            continue

        # ---- 子段标题(全角 ":" 结尾) ----
        # prompt 已规定子段头统一用全角 ":",渲染层把整行加粗,与正文区分。
        if _is_subsection_header(stripped):
            out.append(f"**{line.rstrip()}**")
            i += 1
            i, block_lines = _collect_block(lines, i)
            out.extend(_bulletize_if_multi(block_lines))
            continue

        # ---- 普通行 ----
        out.append(line)
        i += 1

    return "\n".join(out)


def _is_subsection_header(stripped: str) -> bool:
    """子段标题判定:**只看全角中文冒号 ":" (U+FF1A)**。

    Captain 反馈 "——" 看着怪,且半角 ":" 在中文叙事里几乎不出现。
    prompt 已统一要求子段头用 "几项 X:",渲染层只识别这一种,简单干净。
    """
    if not stripped:
        return False
    return stripped.endswith("：")  # U+FF1A only


def _collect_block(lines: list[str], start: int) -> tuple[int, list[str]]:
    """从 start 起收集连续非空行,直到遇到空行或文件结束。返回新 i 和块。"""
    block: list[str] = []
    i = start
    while i < len(lines) and lines[i].strip():
        block.append(lines[i])
        i += 1
    return i, block


def _bulletize_if_multi(block: list[str]) -> list[str]:
    """块行数 ≥ 2 时,每行加 "- " 前缀;≤ 1 行时原样返回。

    ≤ 1 行的情况通常是 ≤3 matter 子段(LLM 用句号/分号在同一段串接),
    单点 bullet 没意义反而难看。
    """
    if len(block) < 2:
        return block
    return [f"- {b.strip()}" for b in block]


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
        公司视角叙事(主体段落,经 _format_company_summary_for_card 加视觉层次)
        AI 缺席提示(仅 fallback 状态)
    """
    s = facts.summary
    # tone 仍解析(影响 template 冷暖色),但不再渲染"整体节奏: X"那行文字
    # —— 老板视其为多余的主观判断,直接陈述事实即可。
    template = "blue" if narrative.status == "ai" else "wathet"
    header = f"📊 公司日报 · {s.window.label}"

    parts: list[str] = []

    parts.append(
        f"📅 覆盖窗口:{_fmt_dt(s.window.since)} → {_fmt_dt(s.window.until)}"
    )
    parts.append("")

    # 注:不再渲染"📈 团队总览"统计行 —— 老板不爱看僵硬的统计数字,
    # 真正有价值的"5 人 / 4 个事项"等业务数字由 narrative 收尾段自己写。

    if narrative.status == "ai":
        # 后处理给方向标题 / 子段事项加视觉层次
        parts.append(_format_company_summary_for_card(narrative.summary))
    else:
        # fallback / no_activity 状态下 summary 是一句固定统计,不需要后处理
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
            # 显示 pinyin 而非 display_name —— 与公司日报 / company prompt
            # "人名一律 pinyin"口径一致(见 memory: feedback_daily_report_use_pinyin_only)。
            # display_name 是飞书名(如"Captain"),会和叙述里的 pinyin
            # 引用("huangshengli 推进...")混排,造成同一人两种名字感觉别扭。
            #
            # 用 "- " 列表前缀(markdown bullet list)而不是 "·"(普通中点字符)。
            # 飞书卡片会把 "- " 行渲染成真正的列表,左侧实心圆点 +
            # 缩进对齐,视觉层次明显;"·" 只是文字字符,挤在一起没层次感。
            parts.append(f"- **{e.pinyin}**: {e.narrative}")
        if inactive:
            names = "、".join(e.pinyin for e in inactive)
            # inactive 行用 italic 与 active 区分(还是 - 前缀维持列表整齐)
            parts.append(f"- _{NO_ACTIVITY_NARRATIVE}_: {names}")

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
