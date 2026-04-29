"""AI scoring step. Builds compact JSON of UserActivity[] + TeamSummary,
asks AI for 5-star scores along 4 sub-dimensions, parses strict JSON
output, falls back to a count-based heuristic when anything goes wrong.

Never raises — callers use `ScoringResult.status` + `.fallback_reason` to
decide whether to add a "⚠️ AI 评分缺失" hint to the card."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from server.ai.oneshot import AIError, generate_text
from server.daily_report.types import (
    ScoringResult,
    TeamSummary,
    UserActivity,
    UserScore,
)

log = logging.getLogger("server.daily_report.score")

SUB_DIMENSIONS: tuple[str, ...] = ("output", "progress", "blocker", "collab")

_SYSTEM_PROMPT = """\
你是 Pivot 团队日报评分助手。基于下面 24 小时的工作活动数据,
为每个成员和团队整体给出客观评价。

评分规则:
- 5 分制,允许 0.5 步进 (1.0 / 1.5 / 2.0 / ... / 5.0)
- 4 个维度独立打分,然后给出总分 (可不等于平均):
  · output    = 产出量    (写了多少 file,体量是否充足;commit 量作为辅助参考)
  · progress  = 推进结果  (status_change、verify passed、result 文件等"事项闭环"信号)
  · blocker   = 阻塞情况  (5=完全无阻塞;有 paused 或长时间未推进则扣分)
  · collab    = 协作密度  (mention、quote 引用、verify 给他人的判断)

⭐ matter 是主线,commits 是辅助:
- matter index 上的 think / act / verify / result / insight 文件 + 状态变更
  + verifications + comments + mentions 是评估事项推进的**主要依据**
- git commits 仅辅助 output 维度的判断(代码贡献量化、commit subject 提示工作内容),
  **不应单独主导任何维度**
- 没 matter 活动只有大量 commits 的人:output 可中等(他在写代码),但 progress
  应该低分(没事项闭环信号)
- 反过来:没 commits 但 matter 推进充分的人(比如以 think / verify / result 为主的
  角色),output 可中等到高(讨论 / 验证 / 收口都是产出),不要因为 commit 少就压分

输出约束(严格):
- 没有任何活动的成员不要进 per_user
- "team.summary" 是 <= 40 字的一句话团队总结。**如果今天有需要管理者
  关注的事项(进展异常 / 协作卡点 / 关键阻塞 / 未识别贡献过多等),
  优先在这里点出来**,而不是泛泛说"全员有节奏"
- 严格输出下面 JSON 格式,不要 markdown 包裹,不要任何解释文字

{
  "team": {
    "score": 4.0,
    "sub_scores": {"output": 4.0, "progress": 3.5, "blocker": 4.5, "collab": 4.0},
    "summary": "一句话总结(<=40 字)"
  },
  "per_user": [
    {
      "pinyin": "dengke",
      "score": 4.5,
      "sub_scores": {"output": 5.0, "progress": 4.0, "blocker": 5.0, "collab": 4.0},
      "summary": "1-2 句简评(<=60 字)",
      "highlights": ["完成 auth-redesign 收口", "verify 了 liuyu 的 act"]
    }
  ]
}
"""


@dataclass(frozen=True)
class AISettings:
    """Bundle of OpenAI-compatible endpoint config that score_team needs.
    Built by runner.py from server.settings (keys defined in server/api/ai.py)."""
    api_key: str
    base_url: str
    model: str


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def score_team(
    activities: list[UserActivity],
    summary: TeamSummary,
    *,
    ai_settings: AISettings | None,
    no_ai: bool = False,
) -> ScoringResult:
    """Score the team. Never raises.

    Fallback triggers (in priority order):
      - `no_ai=True` (CLI flag)
      - `ai_settings is None` (config not present)
      - `ai_settings.api_key` empty
      - `generate_text` raises AIError or TimeoutError
      - response not parseable as JSON
      - parsed JSON missing required keys / scores out of range
    """
    if no_ai:
        return _fallback(activities, "ai_disabled (--no-ai)")
    if ai_settings is None or not (ai_settings.api_key or "").strip():
        return _fallback(activities, "ai_disabled (no api_key configured)")

    try:
        raw = _call_ai(activities, summary, ai_settings)
    except (AIError, TimeoutError) as e:
        return _fallback(activities, f"ai_error: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001  (network surprise, etc.)
        return _fallback(activities, f"ai_unexpected: {type(e).__name__}: {e}")

    try:
        parsed = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return _fallback(activities, f"parse_error: {e}", raw_response=raw)

    try:
        return _build_from_ai(parsed, raw)
    except (KeyError, TypeError, ValueError) as e:
        return _fallback(activities, f"schema_error: {e}", raw_response=raw)


# --------------------------------------------------------------------------- #
# AI invocation                                                               #
# --------------------------------------------------------------------------- #


def _call_ai(
    activities: list[UserActivity],
    summary: TeamSummary,
    ai_settings: AISettings,
) -> str:
    payload = _build_input(activities, summary)
    user_msg = json.dumps(payload, ensure_ascii=False)
    # 实测 dashscope qwen3.6-plus 在 11 active users 的 prompt 上 90s 不够,稳定
    # 在 120s 左右返回。给 240s 留足余量,避免一次抖动就降级到统计卡片。
    return generate_text(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=ai_settings.model,
        api_key=ai_settings.api_key,
        base_url=ai_settings.base_url,
        timeout_seconds=240.0,
    )


def _build_input(
    activities: list[UserActivity], summary: TeamSummary,
) -> dict:
    """Compact, AI-friendly JSON. Truncate long strings to keep tokens tight."""
    per_user = []
    for ua in activities:
        if not ua.is_active:
            continue
        per_user.append({
            "pinyin": ua.pinyin,
            "name": ua.display_name,
            "files_created": [
                {
                    "matter": e.matter_id,
                    "type": e.file_type,
                    "summary": (e.summary or "")[:120],
                }
                for e in ua.file_creates
            ],
            "files_owned": [
                {
                    "matter": e.matter_id,
                    "type": e.file_type,
                    "summary": (e.summary or "")[:120],
                }
                for e in ua.file_owns
            ],
            "verifications_given": [
                {
                    "target": str(v.get("target") or "")[:80],
                    "judgement": v.get("judgement"),
                    "comment": str(v.get("comment") or "")[:80],
                }
                for v in ua.verifications_given
            ],
            "status_changes": [
                f"{e.matter_id}: "
                f"{(e.status_change or {}).get('from')} -> "
                f"{(e.status_change or {}).get('to')}"
                for e in ua.status_changes_triggered
                if e.status_change
            ],
            "comments_given": len(ua.comments_given),
            "mentions_received": ua.mentions_received,
            "commits": [
                {
                    "sha": c.sha[:7],
                    "subject": (c.subject or "")[:120],
                    "stats": f"+{c.insertions}/-{c.deletions} "
                             f"{c.files_changed}f",
                }
                for c in ua.commits
            ],
        })
    return {
        "window": {
            "since": summary.window.since.isoformat(),
            "until": summary.window.until.isoformat(),
        },
        "team_stats": {
            "matters_touched": summary.matters_touched,
            "files": summary.total_files,
            "commits": summary.total_commits,
            "status_changes": summary.total_status_changes,
            "comments": summary.total_comments,
            "active_users": len(per_user),
            "inactive_users": len(summary.inactive_users),
            "unattributed_commits": len(summary.unattributed_commits),
        },
        "per_user": per_user,
    }


# --------------------------------------------------------------------------- #
# JSON parsing + validation                                                   #
# --------------------------------------------------------------------------- #


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json(raw: str) -> dict:
    """Strip optional ```json``` markdown fence, then parse. AI sometimes
    wraps JSON in fences despite system prompt forbidding it — be lenient."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty AI response")
    m = _JSON_FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    return json.loads(s)


def _validate_score(v) -> float:
    """Coerce a numeric score; require [1.0, 5.0]. Fractional 0.5 step is
    not enforced server-side — we trust whatever AI returns within range."""
    f = float(v)
    if not (1.0 <= f <= 5.0):
        raise ValueError(f"score out of [1.0, 5.0]: {f}")
    return f


def _validate_subs(d: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in SUB_DIMENSIONS:
        if k not in d:
            raise KeyError(f"sub_scores missing dimension: {k}")
        out[k] = _validate_score(d[k])
    return out


def _build_from_ai(parsed: dict, raw: str) -> ScoringResult:
    team = parsed["team"]
    team_score = _validate_score(team["score"])
    team_subs = _validate_subs(team["sub_scores"])
    team_summary = str(team.get("summary") or "").strip()

    per_user_in = parsed.get("per_user") or []
    user_scores: list[UserScore] = []
    for u in per_user_in:
        user_scores.append(UserScore(
            pinyin=str(u["pinyin"]),
            score=_validate_score(u["score"]),
            sub_scores=_validate_subs(u["sub_scores"]),
            summary=str(u.get("summary") or "").strip(),
            highlights=tuple(
                str(h).strip() for h in (u.get("highlights") or [])[:3]
            ),
        ))

    return ScoringResult(
        status="ai",
        team_score=team_score,
        team_sub_scores=team_subs,
        team_summary=team_summary,
        per_user=tuple(user_scores),
        raw_response=raw,
    )


# --------------------------------------------------------------------------- #
# Fallback                                                                    #
# --------------------------------------------------------------------------- #


def _fallback(
    activities: list[UserActivity],
    reason: str,
    *,
    raw_response: str = "",
) -> ScoringResult:
    """Crude count-based scoring used when AI is unavailable.

    - Team score is fixed 3.0 (neutral) — we don't pretend to know.
    - Per-user score is bucketed by activity count (file_creates + file_owns
      + commits + verifications_given): ≤3 → 2.5, ≤7 → 3.5, 8+ → 4.5.
    - sub_scores are all None — the renderer should hide the sub-score
      breakdown in fallback mode.
    """
    log.info("daily-report scoring fallback: %s", reason)
    nones: dict[str, float | None] = {k: None for k in SUB_DIMENSIONS}

    user_scores: list[UserScore] = []
    for ua in activities:
        if not ua.is_active:
            continue
        count = (
            len(ua.file_creates) + len(ua.file_owns)
            + len(ua.commits) + len(ua.verifications_given)
        )
        if count == 0:
            # Active by mentions / comments only — give a low neutral score
            # rather than skip (still appears in card).
            score = 2.0
        elif count <= 3:
            score = 2.5
        elif count <= 7:
            score = 3.5
        else:
            score = 4.5
        user_scores.append(UserScore(
            pinyin=ua.pinyin,
            score=score,
            sub_scores=nones,
            summary="(AI 评分缺失,按活动量粗分)",
            highlights=(),
        ))

    return ScoringResult(
        status="fallback",
        team_score=3.0,
        team_sub_scores=nones,
        team_summary="(AI 评分缺失,以下仅展示统计)",
        per_user=tuple(user_scores),
        raw_response=raw_response,
        fallback_reason=reason,
    )
