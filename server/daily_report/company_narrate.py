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
你是 Pivot 公司视角日报生成器。基于今天 24 小时的整体推进事实,
生成一段简短的公司视角总结。

输入字段说明(只能基于这些事实写,严禁臆造):
- team_stats:整体计数 + file_type_breakdown(think / act / verify / result / insight)
              + verify_judgements(passed / failed / partial)
- matter_status_breakdown:被触动 matter 的 current_status 分布
- top_active_matters:**今日最活跃的若干 matter**,每条含:
  · path:形如 "Pivot/数据迁移方案" 的引用 token,**直接整段引用,不要拆字**
  · file_count / file_types:文件数 + 类型分布
  · status_change:状态迁移 from→to(可能 null)
  · verify_judgements:该 matter 的验收结论
  · activity_score:综合活跃分(降序排列)

规则(严格):
1. summary 字段是 2-4 句中文叙事段落,**一段连续叙述**,不切分子区块,不使用 markdown 标记
2. 必须**明确给出整体推进状态**:三选一 active / steady / stalled
   - active(积极推进):有实质闭环动作(verify passed / result 创建)、多 matter 状态推进
   - steady(平稳推进):有动作但偏维持、无明显闭环也无明显卡点
   - stalled(偏停滞):整体动作少、verify 少、推进信号弱
3. **整体推进了什么**:基于 file_type_breakdown 描述工作类型分布。例如:
   "30 篇 think + 12 篇 verify + 4 篇 result" 比 "55 篇文件" 信息量大得多。
   重点点出 verify_judgements:多少 passed / failed —— 这是"实质推进"最强信号
4. **今日最活跃事项**:从 top_active_matters 选出 1-3 条,**用强度话术**点名:
   - 允许写:"今日讨论最激烈的是 Pivot/数据迁移方案(N 篇文件 + 状态闭环到 finished)"
   - 允许写:"落地最快的是 enclaws/某 matter,verify passed 2 次"
   - 允许写:"评论密度最高的是 ..."
   - **禁止写**:"该 matter 今天讨论了 X 方案 / 解决了 Y 问题 / 提出了 Z 建议" —— 你看不到
     summary 内容,这种描述都是虚构。**只描述强度 / 节奏 / 类型,不描述内容**。
   - matter 引用必须用 path 原文(如 "Pivot/数据迁移方案"),不要改名 / 翻译 / 缩写
5. **不要把 path 中的 category 当方向归类** —— Pivot / enclaws 等是文件夹,不是产品方向。
   不要写"Pivot 方向有进展"这类基于路径的方向归纳;只用 path 当 matter 引用 token。
6. 严禁臆造:任何陈述必须基于输入字段;不允许编造未发生的动作 / 状态 / 人 / 事项内容
7. **明确这是 AI 分析,不是最终结论** —— 末尾不需要加免责声明,但叙事
   要克制不绝对(用"整体""主要""可能"等措辞)

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
    """Compact AI-friendly JSON.

    设计取舍:
    - **不喂 matter title 的自然语言列表** —— 防 LLM 把 title 自由聚类成"方向"
    - **不喂 matters_by_category 字典** —— 同上,类目结构会让 LLM 误以为这是
      产品方向
    - 改喂 top_active_matters 路径式引用 + 强度指标,LLM 写"讨论最激烈"
      "落地最快"等强度话术,写不出虚构内容
    - file_type_breakdown / verify_judgements 是"实质推进"的强信号
    """
    s = facts.summary
    return {
        "window": {
            "since": s.window.since.isoformat(),
            "until": s.window.until.isoformat(),
        },
        "team_stats": {
            "total_files": s.total_files,
            "total_status_changes": s.total_status_changes,
            "total_comments": s.total_comments,
            "matters_touched": s.matters_touched,
            "active_users": facts.n_active,
            "inactive_users": len(s.inactive_users),
            "file_type_breakdown": facts.file_type_breakdown,
            "verify_judgements": facts.verify_judgements,
        },
        "matter_status_breakdown": facts.matter_status_breakdown,
        "top_active_matters": [
            {
                "path": m.path,
                "current_status": m.current_status,
                "file_count": m.file_count,
                "file_types": m.file_types,
                "status_change": m.status_change,
                "verify_judgements": m.verify_judgements,
                "comments_count": m.comments_count,
                "activity_score": m.activity_score,
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
