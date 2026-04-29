"""Personal-view narrative generator (v0.2 / Phase 4).

dengke #013 原话:
    个人视角报告:按成员分别总结今天在 Pivot 时间线里的输入和输出,
    如果没有活动就明确写没有输入和输出。

本模块负责"个人视角报告"的 LLM 调用 + 解析 + 全员覆盖。

设计要点:
- **1 次 LLM 调用** 生成所有活跃成员的叙述(降低延迟与 token 成本,
  统一文风);无活动成员**不喂 LLM**,程序填固定字符串"今天没有任何
  输入和输出"(dengke 原话 / 反模糊话术保险)
- 全员都要在最终结果中出现,LLM 漏返回 / 多返回 → 防御性 fallback
- 与 company_narrate 共享 SharedFacts,但**不共享 LLM 中间结果**
  (dengke #013:报告之间保持独立)。
- 输出形态:per-user 一行,无活动者由渲染层合并(见 render.py)

Never raises — caller looks at `PersonalNarrative.status` 决定卡片走
ai/fallback 模板。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from server.ai.oneshot import AIError, generate_text
from server.daily_report.company_narrate import AISettings
from server.daily_report.shared_facts import SharedFacts
from server.daily_report.types import UserActivity

log = logging.getLogger("server.daily_report.personal_narrate")

# 程序侧固定无活动文案 —— 严禁让 LLM 生成此类描述,避免模糊话术
NO_ACTIVITY_NARRATIVE = "今天没有任何输入和输出"


@dataclass(frozen=True)
class PersonalEntry:
    """单个成员一条叙述。`has_activity = False` 时 narrative 固定为
    NO_ACTIVITY_NARRATIVE,由程序填,不经 LLM。"""
    pinyin: str
    display_name: str
    has_activity: bool
    narrative: str


@dataclass(frozen=True)
class PersonalNarrative:
    """全员个人视角叙述结果。`entries` 顺序 = users 表全员顺序。"""
    status: Literal["ai", "fallback", "no_active_users"]
    entries: tuple[PersonalEntry, ...]
    raw_response: str = ""
    fallback_reason: str | None = None


_SYSTEM_PROMPT = """\
你是 Pivot 个人视角日报生成器。基于成员今天 24 小时在 Pivot 时间线上的
输入和输出,为每位列出的活跃成员生成一段简短叙述。

规则(严格):
1. 只为输入数据中**列出**的成员生成叙述 —— 不要凭空增加成员
2. 单条叙述 1-2 句,中文,**直接陈述事实**(谁今天做了什么、参与了哪些 matter)
3. **反绩效化**:不打分、不排名、不对比、不评价"努力 / 高效"等主观判断
4. 不输出技术细节:不引用文件路径、commit hash、内部 ID
5. 严禁臆造:任何陈述必须基于输入字段;不允许编造未发生的动作 / 状态 / 人
6. 单条最长 60 中文字符
7. 输入与输出可混合叙述,不要强制分两栏

**重点**:可在叙述里点出"重点动作"(触发 status_change、给 verify 判定、
  对他人 matter 的关键贡献),但不要与其他成员对比。

输出格式(严格 JSON,无任何 markdown 包裹):
{
  "entries": [
    {"pinyin": "alice", "narrative": "在登录链路改造创建 verify..."}
  ]
}
"""


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def narrate_personal(
    facts: SharedFacts,
    *,
    ai_settings: AISettings | None,
    no_ai: bool = False,
) -> PersonalNarrative:
    """Generate per-user narratives. Never raises. 全员都进 entries。"""
    active = [ua for ua in facts.user_activities if ua.is_active]
    inactive = [ua for ua in facts.user_activities if not ua.is_active]

    # 全员 0 活动 short-circuit
    if not active:
        entries = tuple(
            PersonalEntry(
                pinyin=ua.pinyin,
                display_name=ua.display_name,
                has_activity=False,
                narrative=NO_ACTIVITY_NARRATIVE,
            )
            for ua in facts.user_activities
        )
        return PersonalNarrative(status="no_active_users", entries=entries)

    # AI disabled / not configured → fallback
    if no_ai:
        return _fallback(facts, "ai_disabled (--no-ai)")
    if ai_settings is None or not (ai_settings.api_key or "").strip():
        return _fallback(facts, "ai_disabled (no api_key configured)")

    # Call LLM
    try:
        raw = _call_ai(active, ai_settings)
    except (AIError, TimeoutError) as e:
        return _fallback(facts, f"ai_error: {type(e).__name__}: {e}",
                         raw_response="")
    except Exception as e:  # noqa: BLE001
        return _fallback(facts, f"ai_unexpected: {type(e).__name__}: {e}")

    # Parse + validate
    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return _fallback(facts, f"parse_error: {e}", raw_response=raw)

    try:
        return _build_from_ai(parsed, facts.user_activities, raw)
    except (KeyError, TypeError, ValueError) as e:
        return _fallback(facts, f"schema_error: {e}", raw_response=raw)


# --------------------------------------------------------------------------- #
# AI invocation                                                               #
# --------------------------------------------------------------------------- #


def _call_ai(active: list[UserActivity], ai_settings: AISettings) -> str:
    payload = {"users": [_serialize_user(ua) for ua in active]}
    user_msg = json.dumps(payload, ensure_ascii=False)
    return generate_text(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=ai_settings.model,
        api_key=ai_settings.api_key,
        base_url=ai_settings.base_url,
        timeout_seconds=180.0,
    )


def _serialize_user(ua: UserActivity) -> dict:
    """精简 UserActivity → AI 友好的 JSON。截断长 summary,限制条数。"""
    # 自己创建的 file 按 type 分桶。think 算输入,act/verify/result/insight 算输出。
    inputs: dict[str, list] = {"think_files": [], "comments_received_mentions": ua.mentions_received}
    outputs: dict[str, list] = {
        "act_files": [],
        "verify_files": [],
        "result_files": [],
        "insight_files": [],
        "status_transitions": [],
        "files_on_others_matters": [],   # file_owns: 别人的 matter,自己 owner
    }

    for ev in ua.file_creates[:8]:
        item = {
            "matter": ev.matter_title[:50],
            "summary": (ev.summary or "")[:80],
        }
        if ev.file_type == "think":
            inputs["think_files"].append(item)
        elif ev.file_type == "act":
            outputs["act_files"].append(item)
        elif ev.file_type == "verify":
            outputs["verify_files"].append(item)
        elif ev.file_type == "result":
            outputs["result_files"].append(item)
        elif ev.file_type == "insight":
            outputs["insight_files"].append(item)

    # file_owns: 派给我的 matter 的文件(creator != self)
    for ev in ua.file_owns[:5]:
        outputs["files_on_others_matters"].append({
            "matter": ev.matter_title[:50],
            "type": ev.file_type,
            "creator": ev.creator,
            "summary": (ev.summary or "")[:80],
        })

    # 状态推进:matter 名 + from→to(去重 by matter)
    seen_matters = set()
    for ev in ua.status_changes_triggered:
        if ev.matter_id in seen_matters or not ev.status_change:
            continue
        seen_matters.add(ev.matter_id)
        outputs["status_transitions"].append({
            "matter": ev.matter_title[:50],
            "from": ev.status_change.get("from"),
            "to": ev.status_change.get("to"),
        })

    return {
        "pinyin": ua.pinyin,
        "display_name": ua.display_name,
        "inputs": {
            "think_files": inputs["think_files"],
            "comments_count": len(ua.comments_given),
            "mentions_received": ua.mentions_received,
        },
        "outputs": outputs,
    }


# --------------------------------------------------------------------------- #
# JSON parsing + per-user fallback                                            #
# --------------------------------------------------------------------------- #


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json(raw: str) -> dict:
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty AI response")
    m = _JSON_FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    return json.loads(s)


def _build_from_ai(
    parsed: dict,
    all_users: tuple[UserActivity, ...],
    raw: str,
) -> PersonalNarrative:
    entries_in = parsed.get("entries")
    if not isinstance(entries_in, list):
        raise ValueError("entries must be a list")

    # LLM 返回的 narrative 按 pinyin 索引
    narrative_by_pinyin: dict[str, str] = {}
    for e in entries_in:
        if not isinstance(e, dict):
            continue
        p = str(e.get("pinyin") or "").strip()
        n = str(e.get("narrative") or "").strip()
        if p and n:
            # Defensive trim — LLM 偶尔超长
            if len(n) > 200:
                n = n[:200].rstrip() + "…"
            narrative_by_pinyin[p] = n

    # 拼最终 entries:全员顺序保留,有活动者用 LLM 文案,无活动者固定文案
    out_entries: list[PersonalEntry] = []
    for ua in all_users:
        if ua.is_active:
            ai_text = narrative_by_pinyin.get(ua.pinyin)
            if not ai_text:
                # LLM 漏返回该用户 — fallback 程序侧 stub
                ai_text = _stub_active_narrative(ua)
            out_entries.append(PersonalEntry(
                pinyin=ua.pinyin,
                display_name=ua.display_name,
                has_activity=True,
                narrative=ai_text,
            ))
        else:
            out_entries.append(PersonalEntry(
                pinyin=ua.pinyin,
                display_name=ua.display_name,
                has_activity=False,
                narrative=NO_ACTIVITY_NARRATIVE,
            ))

    return PersonalNarrative(
        status="ai",
        entries=tuple(out_entries),
        raw_response=raw,
    )


def _stub_active_narrative(ua: UserActivity) -> str:
    """LLM 漏返回单个活跃用户时的程序侧 stub:简短统计,无主观判断。"""
    bits: list[str] = []
    if ua.file_creates:
        types = {ev.file_type for ev in ua.file_creates}
        bits.append(f"创建 {len(ua.file_creates)} 篇文件 ({'/'.join(sorted(types))})")
    if ua.file_owns:
        bits.append(f"在 {len(ua.file_owns)} 个他人 matter 中担任 owner")
    if ua.status_changes_triggered:
        bits.append(f"触发 {len(ua.status_changes_triggered)} 次状态推进")
    if ua.comments_given:
        bits.append(f"参与 {len(ua.comments_given)} 条评论")
    if ua.mentions_received:
        bits.append(f"被 mention {ua.mentions_received} 次")
    return ";".join(bits) if bits else "今天有活动但 AI 未生成具体叙述"


# --------------------------------------------------------------------------- #
# Fallback (LLM unavailable for the WHOLE call)                               #
# --------------------------------------------------------------------------- #


def _fallback(
    facts: SharedFacts,
    reason: str,
    *,
    raw_response: str = "",
) -> PersonalNarrative:
    """LLM 整体失败时,所有活跃成员都走 stub;无活动成员仍走固定文案。"""
    log.info("personal narrative fallback: %s", reason)
    out_entries: list[PersonalEntry] = []
    for ua in facts.user_activities:
        if ua.is_active:
            out_entries.append(PersonalEntry(
                pinyin=ua.pinyin,
                display_name=ua.display_name,
                has_activity=True,
                narrative=_stub_active_narrative(ua),
            ))
        else:
            out_entries.append(PersonalEntry(
                pinyin=ua.pinyin,
                display_name=ua.display_name,
                has_activity=False,
                narrative=NO_ACTIVITY_NARRATIVE,
            ))
    return PersonalNarrative(
        status="fallback",
        entries=tuple(out_entries),
        raw_response=raw_response,
        fallback_reason=reason,
    )
