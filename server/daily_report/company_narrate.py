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
你是 Pivot 项目里的高级 PM,每天向老板做工作汇报。

──────────────────────────────────────
【任务】

对每个有进展的 matter,从 timeline_yaml 里读懂下面四件事:

1. **这件事是干啥的** —— 解决什么问题、价值在哪
2. **哪些人参与了、各自做了什么**
3. **推进过程是怎么样的** —— 谁起头、争论焦点、谁拍板、谁实施、谁验收
4. **现在推到哪了、下一步往哪走**

把上述信息按 category 归类成业务方向,组织成像高级 PM 当面跟老板真实口头
汇报的中文叙事 —— 直接、紧凑、有判断力,说事实不装有学问。

category 取值:`Pivot` / `enclaws` / `外部客户实施` / `probe`。其中 probe
是测试性目录,直接过滤掉。category 只有 1-2 个 matter 时可与相邻方向合并。

──────────────────────────────────────
【覆盖原则】(重要)

窗口内**所有非 probe 的活跃 matter 都必须在汇报中至少出现一次**——不能
因为字数问题省略,**漏报 = 不达标**。老板要从这份汇报回答"今天团队都干了
啥",任何活跃 matter 被隐匿都是错。

但要做**差别化展开**:
- **有重大弧线感的事项**(经过方案争论拍板 / 验收通过 / 状态推进 /
  跨需求影响等):正常展开 30-60 字,讲清楚"是干啥 / 谁推动 / 现在到哪 /
  下一步"
- **没有特别看点的事项**(就是常规一笔实施 / 一句确认 / 一次评审过):
  **一句话带过 15-30 字即可**(如"X 进入实施"、"Y 验收通过"、"Z 启动
  设计")

**完整覆盖 > 详尽展开**。宁可一句话提一下,也不要漏报。

──────────────────────────────────────
【输入字段】

每个 top_active_matters 含:
- title         事项内部代号(**不要直接念**,从 intent / timeline_yaml 提炼业务说法)
- category      业务方向(见上)
- intent        事项目标(空串=不可用)
- lifecycle     事项阶段(closed/just_started/decided/discussing/paused/planning)
                —— 仅你内部判断用,**不要在输出出现这些英文标签**
- participants  涉及人员的 pinyin 列表
- timeline_yaml 完整时间线 yaml,字段含义见下

──────────────────────────────────────
【timeline_yaml 字段含义】

顶层 `matter` + `timeline` 两块。每条 timeline 项的字段:

- type          think / act / verify / result / insight —— 推进的业务动作:
                · think:   讨论 / 评审 / 提反提议
                · act:     实施 / 动手 / 合入主线
                · verify:  验收(verifications.judgement: passed/failed/partial)
                · result:  事项正式收尾
                · insight: 复盘 / 沉淀
                **这五个英文字面词不能写进输出**,但**必须用它们的序列识别
                事项节奏**:
                · 全 think → 还在讨论
                · think → act → 收口实施
                · act + verify(passed) → 实施完成且通过验收
                · act + result → 整体闭环
- creator/owner 写的人 / 责任人(pinyin)。不同时表示代写
- in_window     true=今日窗口内 / false=窗口前的历史(写故事时**两段都要看**)
- summary       AI 生成的正文摘要 —— 你提取业务事实的主要来源
- quote         引用上一条文件路径(因果链:谁回应谁)
- status_change {from, to} —— 状态机转折节点(关键)
- comments      评论流。author / body / mentions(@ 谁=抛球给谁,短决断
                的评论通常是收口动作)
- verifications verify 特有:验收对象 + 判定 + 评语

──────────────────────────────────────
【表达基调】

像高级 PM 面对老板真实口头汇报。**不要写官腔,不要装会写字。**

- 用普通业务中文,**不用技术黑话**(联调 / 链路 / 越权 / 鉴权 / 触点 /
  端 / 侧 / 收敛到 ... / 熔断 等)
- **不用 AI 装会写字的套话**(赋能 / 沉淀 / 协同推进 / 平稳有序 / 深水区 /
  一体化 / 加速... / 强化...说服力 / ...能力底座 等)
- 用普通的中文动词:完成 / 上线 / 通过验收 / 进入开发 / 拍板 / 暂缓 /
  启动 / 验收未过 / 反提议
- 人名一律 pinyin(如 huangshengli / dengke,**不翻译为汉字**)
- 数字一律阿拉伯("10 人""20 个""7 条",不写"十人""二十个""七条")
- 事项**不写书名号**,用业务白话当代称(如"团队日报推送服务"而不是
  "《新需求-日报推送》")。如果 timeline 里有具体数字 / 关键人 / 关键
  动作,**保留下来**,不要抽象化。

【输出结构】

- 段落 1: 开场一句,归纳今天团队主要在 N 个方向上推进
- 段落 2..N+1: 每个方向一段,以"第一是 / 第二是"开头(只 1 个方向就直接讲)
- 段落 N+2(可选): 收尾一句,团队节奏。**只有当节奏真的有可点的业务事实
  时才写**(如"密集打磨""承诺压力大""人参与新高/新低""跨方向资源紧张"
  等)。如果只是空洞总结("完成阶段收口""无阻塞卡点""节奏稳健""协同推进
  顺畅"等套话),**直接省略整段**,不要硬凑。
- 段间用真换行(\\n)分隔。**段内默认不换行**。
- **段内换行例外**:一个方向段如果含 **6 个或更多 matter**(典型如 Pivot
  大方向 10+ 个),**段内可按节奏阶段分成 2-3 个子段**(否则 11 个 matter
  揉成一坨 400 字的文字墙,老板读不下去)。
  - 推荐子主题:"已闭环上线 / 进入开发 / 仍在设计 / 暂缓收尾" 这四类
    (或类似的节奏阶段切分),按本次窗口实际情况选 2-3 类
  - 每个子段 50-150 字,子段间用换行
  - 子段开头用**业务短语自然引导**,例如:
    "几项能力闭环上线 —— X 完成... ; Y 完成 ..."
    "几项进入开发 —— A 完成 ... ; B 启动 ..."
    "仍在设计或讨论的有 X、Y、Z..."
  - **不要**写"#"/"**"/Markdown 标题/列表符号/"已闭环:""进入开发:"
    这种独立标题行
- 不写"风险:""产出:""节奏:"这种小标题
- **总字数**(动态,按窗口 matter 总数自适应):
   · ≤5 个    → 250-400 字
   · 6-10 个  → 400-600 字
   · 11-20 个 → 600-900 字
   · >20 个   → 900-1200 字
- **单事项**:有弧线感的 30-60 字展开;没看点的 15-30 字一句话带过。
  任何事项**都不要超 60 字**(超了说明在写过程往返 / 技术细节 / 形容词)。

──────────────────────────────────────
【输出格式】

直接输出叙事正文,正文写完**单独一行**写 tone 标签:
[tone: active]   多个方向有清晰产出 / 重大决策 / 上线
[tone: steady]   少量推进,无明显风险也无重大决策
[tone: stalled]  几乎只有讨论中事项,无完成无产出推进

──────────────────────────────────────
【完整示例】(看清楚:数字阿拉伯 / 无书名号 / 段间真换行 / 收尾独立成段 /
人名 pinyin / 保留具体数字"7 条"和"3.5 小时"这种关键事实 / 没有黑话和套话)

今天团队主要在两个方向上推进。

Pivot 产品方向,数据隐私权限体系进入开发 —— yuebilin 完成多角色权限模型,
liuyu 提 7 条契约修订需关注,核心是把 admin 收敛为治理权而非业务读权。
员工 AI 评价方案启动设计 —— liuyu 出 admin 视角初版,dengke 反提议把范围
扩到协作 mention,评分权重交给 AI 派生。团队日报推送服务也在该方向上线 ——
经两天产品形态拉锯后,dengke 拍板停止争论先做后台可配置,huangshengli 在
拍板 3.5 小时内完成 v0.2 合入主线。

外部交付方向,面向碧桂园的产品介绍物料底稿完成 —— terry.tao 定下"标准
核心+定制 Agent"双层服务定位,dengke 进一步建议升级 AI Agent 定位。opc-dev
演示环境上线 —— lishuai 完成华为云部署。

团队今日 10 人 / 20 个事项,节奏紧凑。

[tone: active]
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
        parsed = _parse_response(raw)
    except ValueError as e:
        return _fallback(facts, f"parse_error: {e}", raw_response=raw)

    try:
        return _build_from_ai(parsed, raw, facts)
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
        timeout_seconds=360.0,
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
    # intent 限长(避免单条爆 prompt);timeline_yaml 已经在 renderer 里自带
    # 内部限长(max_summary_chars=250 / max_comments_per_item=3 等),
    # 这里不再二次截断,免得拦腰截断 markdown 结构。
    INTENT_LIMIT = 250

    def _trim_intent(t: str) -> str:
        t = (t or "").strip()
        return (t[:INTENT_LIMIT] + "…") if len(t) > INTENT_LIMIT else t

    return {
        "window": {
            "since": s.window.since.isoformat(),
            "until": s.window.until.isoformat(),
        },
        "team_metrics": {
            "active_users": facts.n_active,
            "inactive_users": len(s.inactive_users),
            "matters_touched": s.matters_touched,
        },
        "top_active_matters": [
            {
                "title": m.title,
                "category": m.category,
                "intent": _trim_intent(m.intent),
                "lifecycle": m.lifecycle,
                "participants": list(m.participants),
                # v0.4: 完整 timeline 的精简 yaml 字符串(Pivot 索引原始
                # 字段保留:file/type/creator/owner/quote/status_change/
                # verifications/comments/mentions),加 in_window 标记。
                # LLM 写故事的主要依据,看 yaml 字段语义说明部分了解每个
                # 字段含义。
                "timeline_yaml": m.timeline_yaml,
            }
            for m in facts.top_active_matters
        ],
    }


# --------------------------------------------------------------------------- #
# JSON parsing + validation                                                   #
# --------------------------------------------------------------------------- #


_FENCE_RE = re.compile(r"```(?:json|text)?\s*(.*?)\s*```", re.DOTALL)
# 末尾 tone 标签:[tone: active] / [tone:steady] / 中文冒号也兼容
_TONE_TAG_RE = re.compile(
    r"\[\s*tone\s*[:：]\s*(active|steady|stalled)\s*\]\s*$",
    re.IGNORECASE,
)


def _parse_response(raw: str) -> dict:
    """Parse LLM 纯文本叙事 + 末行 tone 标签。

    历史上用 JSON 包装,但 LLM 写中文长叙事时引号 / 换行 / 《》 容易把
    JSON 写崩(常见 ~500 字处 parse_error)。改成纯文本 + 标签后零结构风险。

    返回 {"summary": str, "tone": str};tone 缺失或越界时落空字符串,由
    _build_from_ai 用 facts 推断兜底。"""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty AI response")
    # 防御:LLM 仍可能多包一层 ```...``` markdown fence
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    # 抠末尾 tone 标签
    tone_match = _TONE_TAG_RE.search(s)
    if tone_match:
        tone = tone_match.group(1).lower()
        summary = s[: tone_match.start()].rstrip()
    else:
        tone = ""    # 让 _build_from_ai 用 facts 推断
        summary = s
    if not summary:
        raise ValueError("summary missing or empty")
    return {"summary": summary, "tone": tone}


def _build_from_ai(
    parsed: dict, raw: str, facts: SharedFacts,
) -> CompanyNarrative:
    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary missing or empty")
    tone = str(parsed.get("tone") or "").strip().lower()
    if tone not in VALID_TONES:
        # tone 标签缺失或越界 —— 不浪费 LLM 写好的叙事,用 facts 推断兜底
        tone = _derive_tone_from_facts(facts)
    # Defensive truncate — prompt 目标上限按 matter 数动态(覆盖原则:所有
    # 活跃 matter 都进 input,所以最大档 >20 → 1200 字)。截断阈值取最大
    # 上限的 1.25x:1500,兜底 LLM 失控超长。
    if len(summary) > 1500:
        summary = summary[:1500].rstrip() + "…"
    return CompanyNarrative(
        status="ai",
        summary=summary,
        tone=tone,  # type: ignore[arg-type]
        raw_response=raw,
    )


def _derive_tone_from_facts(
    facts: SharedFacts,
) -> Literal["active", "steady", "stalled"]:
    """tone 兜底规则:与 prompt 描述对齐。
    - active: 至少 2 个方向有清晰产出(closed / just_started / decided)
    - stalled: 几乎只有讨论中事项(无 closed/started/decided 且活跃成员稀少)
    - steady: 居中
    """
    progressing = sum(
        1 for m in facts.top_active_matters
        if m.lifecycle in ("closed", "just_started", "decided")
    )
    if progressing >= 2:
        return "active"
    if progressing == 0 and facts.n_active <= 2:
        return "stalled"
    return "steady"


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
