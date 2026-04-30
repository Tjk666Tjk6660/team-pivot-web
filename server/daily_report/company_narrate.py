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
你是 Pivot 公司视角日报生成器。读者是公司管理层,他们要从一段简短叙事里
看出团队**昨天完成了什么、推进到哪里、有没有新启动**。

输入字段:
- top_active_matters:今日最活跃事项(降序),每条:
  · title:业务标题(直接引用,加书名号《》)
  · lifecycle:事项阶段提示,值为 closed / just_started / decided /
              discussing / paused / planning
              ⚠ 仅供你判断该用什么业务动词,**不要在输出里出现这几个英文标签**
  · today_summaries:今日新增工作记录的业务摘要列表
- team_metrics:active_users / inactive_users(只供 tone 判断,不要写入 summary)

────────────────────────────────────────────
**叙事结构**:150-350 字中文,**一段连续叙述**,无 markdown/无列表/无 emoji。
按下列顺序组织,每部分 1-2 句:

1. **完成**:点名 lifecycle=closed 的 1-3 条事项 —— 用"完成""上线""收口"
   "通过验收""归档"等业务动词。无 closed 项时跳过这一段。
2. **推进 / 启动**:点名 lifecycle=decided 或 just_started 的 1-3 条 —— 用
   "明确实施方案""达成方案共识""合入主线""启动开发""启动版本开发"等。
3. **暂缓 / 讨论中**(可选):lifecycle=paused 的事项若有阻塞信号,值得点出;
   discussing 的事项仅在 today_summaries 有实质结论时点 1 条。

────────────────────────────────────────────
**强制规则**:
1. 引用事项**必须**用 title 原文加书名号《》,不翻译/缩写/改名/拆字
2. 业务语言**只来自** today_summaries,不要扩展未提到的细节
3. 一个 matter 最多 1 句话(避免堆细节)
4. **严禁出现下列内容**(它们是系统元数据,管理层不需要):
   - ❌ 文件类型词:think / act / verify / result / insight(中英文都禁,
     包括"构思""执行""验收"作为类型计数时)
   - ❌ 系统状态名:planning / executing / paused / finished / cancelled / reviewed
   - ❌ 状态迁移:"X→Y""从 X 推进到 Y""由 ... 迁移至 ...""状态闭环"
   - ❌ 计数:"X 篇文件""Y 次 verify""N 条评论""M 篇交付物""K 次 passed"
   - ❌ 模板话术:"整体推进态势""实质闭环""结构上以...为主"
     "活跃强度分布""沉淀了..."
5. 信息不足时跳过该事项,不要硬凑套话。如果几乎所有 matter 的 summary
   都很空泛,可以只写一两句,**不要靠模板凑长度**。
6. tone 字段必须三选一:
   - active:多个 closed 或 decided
   - steady:少量 closed/decided
   - stalled:几乎只有 discussing/planning,无完成无推进

输出严格 JSON,无任何 markdown 包裹:
{ "summary": "一段连续叙事...", "tone": "active" | "steady" | "stalled" }
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
                "lifecycle": m.lifecycle,
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
    # Defensive truncate — prompt 上限 350 字,留 100 字 buffer 兜底超长
    if len(summary) > 450:
        summary = summary[:450].rstrip() + "…"
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
