"""Company-view narrative generator (v0.2 / Phase 3).

dengke #013 原话:
    第一版只做两个报告 ——
    公司视角报告:站在整体公司/团队角度,总结今天整体推进了什么、
                  哪些方向有进展、整体状态如何;
    个人视角报告:按成员分别总结今天在 Pivot 时间线里的输入和输出。

本模块负责"公司视角报告"的 LLM 调用 + 解析。

不调用 read_matter_file 工具(matter 视角废弃后,深度因果叙事不再需要);
只读 SharedFacts 中的整体计数和派生分桶,生成一段 2-3 句的整体定性。

Never raises — caller looks at `CompanyNarrative.status` 决定卡片走 ai/
fallback 模板。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from server.ai.oneshot import AIError, generate_text
from server.daily_report.shared_facts import SharedFacts

log = logging.getLogger("server.daily_report.company_narrate")


VALID_TONES = ("active", "steady", "stalled")


@dataclass(frozen=True)
class AISettings:
    """OpenAI-compatible endpoint config bundle."""
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class CompanyNarrative:
    """LLM 输出,公司视角报告的核心叙事单元。"""
    status: Literal["ai", "fallback", "no_activity"]
    summary: str                                  # 2-3 句叙事段落
    tone: Literal["active", "steady", "stalled"]  # 必含三选一
    raw_response: str = ""
    fallback_reason: str | None = None


_SYSTEM_PROMPT = """\
你是 Pivot 公司视角日报生成器。读者是公司管理层,他们想知道
**"团队昨天推进了哪些业务事项"**,而不是系统层的工作量数字。

输入字段:
- top_active_matters:**今日最活跃的若干事项**(降序),每条含:
  · title:事项的业务标题(中文,直接引用)
  · today_summaries:今日新增工作记录的摘要列表(已经是中文业务描述)
- team_metrics:仅含 active_users(活跃成员数)和 inactive_users(无活动数),
  供你判断 tone,不要写进 summary

────────────────────────────────────────────
**强制规则**(读者已经能从其他卡片区域看到统计数字,你不能重复罗列):

1. summary 是 2-4 句中文叙事段落,**一段连续叙述**,无标题、无列表、
   无 markdown、无 emoji
2. 内容**只能围绕业务事项**:
   - ✅ 用 title 点名事项,用 today_summaries 提炼业务进展
   - ✅ 例:"团队推进了《Pivot MCP 应支持创建新 Matter》并完成验证落地;
     《团队日报推送》启动了产品讨论"
3. **严禁出现下列内容**(它们是系统元数据,读者不需要):
   - ❌ 文件类型计数:"X 篇 think""Y 篇 act""Z 篇 verify""N 篇 result"
   - ❌ 状态名 / 状态迁移:"executing→finished""planning→executing"
     "由 ... 状态迁移到 ...""状态闭环""verify passed N 次"
   - ❌ 抽象工作量话术:"产出 N 篇文件""沉淀 X 篇交付物"
     "结构上以 ... 为主""推进呈现 ... 态势"
   - ❌ 验收信号统计:"X 次 verify""N 次 passed""验收闭环"
   - ❌ 路径 / category 归类:"Pivot 方向""enclaws 类目"
4. 引用事项时使用 title 原文(中文标题),不要翻译 / 改名 / 缩写;
   如果有多个事项要点名,**最多点 3 个**
5. 如果 today_summaries 为空 / 信息不足以总结某事项 —— **跳过该事项,不要硬凑**;
   宁可只写一两句也不要兜底套话。完全没有可写时,summary 写一句:
   "今日团队的推进已记录在统计区域,具体业务事项详见各 matter 时间线。"
6. 严禁臆造:不允许编造 title 中没有的事项、不允许扩展 summary 之外的细节
7. tone 字段必须三选一,基于活跃度大致判断:
   - active:多个事项有实质业务进展(看 today_summaries 充实程度)
   - steady:有事项推进但量不大
   - stalled:几乎没有活跃事项

输出格式(严格 JSON,无任何 markdown 包裹):
{
  "summary": "一段连续叙事...",
  "tone": "active" | "steady" | "stalled"
}
"""


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def narrate_company(
    facts: SharedFacts,
    *,
    ai_settings: AISettings | None,
    no_ai: bool = False,
) -> CompanyNarrative:
    """Generate company-view narrative. Never raises.

    Triggers (in priority order):
      - 全员 + 全 matter 0 活动 → status="no_activity",固定文案
      - no_ai=True / ai_settings missing / api_key empty → fallback
      - LLM raises / parse fails / schema invalid → fallback
    """
    if _is_zero_activity(facts):
        return CompanyNarrative(
            status="no_activity",
            summary="今日团队在 Pivot 上无任何 matter 活动。可能是节假日 / 集中放空 / 工作流动在 Pivot 之外。",
            tone="stalled",
        )

    if no_ai:
        return _fallback(facts, "ai_disabled (--no-ai)")
    if ai_settings is None or not (ai_settings.api_key or "").strip():
        return _fallback(facts, "ai_disabled (no api_key configured)")

    try:
        raw = _call_ai(facts, ai_settings)
    except (AIError, TimeoutError) as e:
        return _fallback(facts, f"ai_error: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        return _fallback(facts, f"ai_unexpected: {type(e).__name__}: {e}")

    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return _fallback(facts, f"parse_error: {e}", raw_response=raw)

    try:
        return _build_from_ai(parsed, raw)
    except (KeyError, TypeError, ValueError) as e:
        return _fallback(facts, f"schema_error: {e}", raw_response=raw)


# --------------------------------------------------------------------------- #
# AI invocation                                                               #
# --------------------------------------------------------------------------- #


def _call_ai(facts: SharedFacts, ai_settings: AISettings) -> str:
    payload = _build_input(facts)
    user_msg = json.dumps(payload, ensure_ascii=False)
    return generate_text(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=ai_settings.model,
        api_key=ai_settings.api_key,
        base_url=ai_settings.base_url,
        timeout_seconds=120.0,
    )


def _build_input(facts: SharedFacts) -> dict:
    """喂给 LLM 的 JSON。

    设计原则:**只喂业务信号,不喂系统元数据**。
    - title + today_summaries 是 LLM 写"做了什么业务"的唯一来源
    - file_type_breakdown / verify_judgements / status_change /
      file_count / matter_status_breakdown 等 **统统不喂** —— 即便
      喂了,LLM 也容易写出"X 篇 think、Y 次 verify passed"这种
      读者不需要的元数据,prompt 已禁止
    - team_metrics 仅给 active_users / inactive_users 让 LLM 判断 tone
    """
    s = facts.summary
    # today_summaries 单条限制长度,避免 prompt 爆;每条 matter 取前 6 条
    SUM_LIMIT = 200
    PER_MATTER_LIMIT = 6
    return {
        "window": {
            "since": s.window.since.isoformat(),
            "until": s.window.until.isoformat(),
        },
        "team_metrics": {
            "active_users": facts.n_active,
            "inactive_users": len(s.inactive_users),
        },
        "top_active_matters": [
            {
                "title": m.title,
                "today_summaries": [
                    (sm[:SUM_LIMIT] + "…") if len(sm) > SUM_LIMIT else sm
                    for sm in m.today_summaries[:PER_MATTER_LIMIT]
                ],
            }
            for m in facts.top_active_matters
        ],
    }


# --------------------------------------------------------------------------- #
# JSON parsing + validation                                                   #
# --------------------------------------------------------------------------- #


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json(raw: str) -> dict:
    """Strip optional ```json``` markdown fence, then parse."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty AI response")
    m = _JSON_FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    return json.loads(s)


def _build_from_ai(parsed: dict, raw: str) -> CompanyNarrative:
    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary missing or empty")
    tone = str(parsed.get("tone") or "").strip().lower()
    if tone not in VALID_TONES:
        raise ValueError(f"tone must be one of {VALID_TONES}, got {tone!r}")
    # Defensive truncate — even if LLM exceeded prompt's 200-char limit
    if len(summary) > 400:
        summary = summary[:400].rstrip() + "…"
    return CompanyNarrative(
        status="ai",
        summary=summary,
        tone=tone,  # type: ignore[arg-type]
        raw_response=raw,
    )


# --------------------------------------------------------------------------- #
# Fallback                                                                    #
# --------------------------------------------------------------------------- #


def _is_zero_activity(facts: SharedFacts) -> bool:
    s = facts.summary
    return (
        s.total_files == 0
        and s.total_status_changes == 0
        and s.total_comments == 0
        and facts.n_active == 0
    )


def _fallback(
    facts: SharedFacts,
    reason: str,
    *,
    raw_response: str = "",
) -> CompanyNarrative:
    """统计性兜底文案,告诉读者 AI 缺席,只给数字。"""
    log.info("company narrative fallback: %s", reason)
    s = facts.summary
    sentence = (
        f"今日团队触动 {s.matters_touched} 个 matter,产生 {s.total_files} 篇文件、"
        f"{s.total_status_changes} 次状态推进、{s.total_comments} 条评论;"
        f"活跃成员 {facts.n_active} 人。AI 公司视角生成失败,以上仅为统计数据。"
    )
    # tone 兜底按硬规则给:有活动给 steady,无活动给 stalled
    tone: Literal["active", "steady", "stalled"] = "steady"
    if s.matters_touched == 0 and facts.n_active == 0:
        tone = "stalled"
    return CompanyNarrative(
        status="fallback",
        summary=sentence,
        tone=tone,
        raw_response=raw_response,
        fallback_reason=reason,
    )
