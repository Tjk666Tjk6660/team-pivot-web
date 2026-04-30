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
你是 Pivot 公司视角日报生成器,读者是公司管理层。
你输出**一段连续的叙述性总结**(不是清单、不是分段标题、不是 bullet),
让管理层一口气读下来就能理解:今天团队整体在搞几个方向、各方向的目标
是什么、每件具体的事谁在做、推到哪了、下一步要干嘛。

────────────────────────────────────────────
**输入字段**
- top_active_matters:今日最活跃事项(降序),每条:
  · title:业务标题(直接引用,加书名号《》)
  · category:**业务方向硬骨架**,来自仓库 path 的产品线分类。
              常见值:`Pivot`(Pivot 产品自身)/ `enclaws`(enclaws 业务线)
              / `外部客户实施`(具体客户项目)/ `probe`(测试性产物)。
              **这是你做"方向归纳"的唯一权威信号** —— 不要自己从 title
              推方向把不同 category 的事合并到一起(常见错误:把 enclaws 下的
              OPC 项目和"外部客户实施"下的碧桂园合并写成"对外推广")。
  · intent:**这件事是干啥的、解决什么问题**(第一条 think.summary)。
            是你提炼"方向价值"和"事项目标"的主要来源。
            空串 = 信号不可用,不要硬凑价值描述。
  · prev_summary:**窗口之前最后一条 timeline.summary** —— 上一步推到哪了。
                  空串 = 这条 matter 是窗口内才出生。
  · today_summaries:**今日新增的工作记录摘要** —— 今天又做了什么、谁做的、
                     怎么定的。
  · lifecycle:事项阶段提示,值为 closed / just_started / decided /
              discussing / paused / planning
              ⚠ 仅供你判断业务动词与"下一步",**不要在输出里出现英文标签**
  · participants:窗口内涉及到的人,以 **pinyin** 形式给出
                 (如 huangshengli / terry.tao / dengke / yezaiyong)
- team_metrics:active_users / inactive_users / matters_touched

────────────────────────────────────────────
**叙事骨架**(总长 250-450 字,**短促有力**,严格控制每个方向的字数)

**段落结构**(用真正的换行符 \\n 分段,共 N+2 段,N=方向数):
  · 第 1 段:开场一句,归纳今天团队主要在几个方向上工作
  · 第 2..N+1 段:每个方向单独一段(60-100 字),以"第一是"/"第二是"/
    "第三是"/"第四是"开头
  · 最后 1 段:简短收尾(可选,15-30 字),如"团队今日 N 人参与、N 个事项,
    整体节奏 ..."

每段之间**必须用真正的换行**(\\n),让卡片显示成多个段落。
**不要把所有方向连成一段长文本**——这会让人读起来很累。

**方向归纳骨架规则**(category 是硬信号,不要从 title 自己推):
- 默认按 category 切方向。一个 category 一段。category 名直接保留原值(如
  `Pivot` / `enclaws` / `外部客户实施`),**enclaws 不要中文化**。
- **小 category(≤ 2 个 matter)合并**:把单独成段会显得单薄的小 category
  合并到相邻方向段里写一句话带过,例如 enclaws 只有 1-2 个事项时可在
  Pivot 段后用一段"在 enclaws 业务线上,《X》进入实施"统一处理;**或者**
  把 enclaws 与外部客户实施这种业务关联近的合并成一段。
- **probe 类 / 测试性产物**:看 title + intent 判断,如果是探针性 / 测试
  性 matter(如 title 含 `probe`、`测试`、intent 看起来像测试用),**直接
  从叙事里过滤掉,不要写进任何方向段**。
- **同一 category 内部的二级归纳**:Pivot 这种大桶内可能有 20+ matter,
  你要在段内按子主题再归纳(如"MCP 工具"/"数据隐私"/"已读状态"等),
  挑 1-2 个最有看点的 matter 点名,其余用半句话带过。这一层归纳由你判断,
  没有硬骨架。

────────────────────────────────────────────
**每段内容规范**

(1) **开场段**(15-30 字):一句话归纳方向数。例:
"今天团队主要在三个方向上推进。"

(2) **方向段**(每段 60-100 字):每个方向自成一段,内部走以下小骨架:
   a. **方向名 + 在搞什么**(15-25 字):点出方向 + 核心事项《X》《Y》《Z》,
      可附半句价值描述(从 intent 提炼;intent 空就省略)。
   b. **具体推进**(30-50 字):点出核心事项今天**谁做了什么**,只点 1-2 个
      最重要的事项,**不要把方向下所有 matter 都列**:
      「[pinyin] 完成 ...,[pinyin] 给出 ... 意见」
      多个事项可合并:「《X》《Y》两项已通过验收并上线」
   c. **进展 + 下一步**(15-25 字):一句话点出当前状态 + 下一步,例如:
      「目前已具备实施条件,下一步开展代码改造」
      「目前仍在收敛分歧,下一步等评审定案」

(3) **风险**(可选,融入对应方向段尾的一个分句即可,不要单起一段):
   有对外承诺时间压力 / 跨需求影响 / 阻塞 / 资源过载时点一句,例:
   「,需注意 ...」
   没有真风险就不提,不硬凑。

(4) **收尾段**(15-30 字,单独一段):一句话点出团队节奏,例:
"团队今日 10 人参与、20 个活跃事项,整体节奏 ......。"
(数字一律用阿拉伯数字,不要写"十人""二十个")。
节奏没什么特别的就完全省略这段。

────────────────────────────────────────────
**下一步推断规则**(自然融入"下一步 ..."分句,不要写"下一步推断"四个字):
   - lifecycle=closed → 观察上线效果 / 进入下一阶段
   - lifecycle=just_started 或 decided → 按方案开发到完成
   - lifecycle=discussing → 收敛方案 / 等拍板
   - lifecycle=paused → 等 [today 里说的某条件] 重启
   - today_summaries 里若有"接下来""后续""下一步"等明确信号,优先采用

**取舍**:每个方向只点 1-2 个最有看点的 matter,其余略过。**宁可少不要多**。
top_active_matters 列出来的不一定都要写进去 —— 总长不能超 450 字是硬约束。

────────────────────────────────────────────
**强制规则**:
1. 引用事项**必须**用 title 原文加书名号《》,不翻译/缩写/改名/拆字
2. **人名一律使用 participants 字段中的 pinyin 形式**(如 huangshengli /
   terry.tao / dengke),**严禁**翻译/推测为汉字(不要写"黄圣力""叶在勇"
   "刘昱"等,即便你能猜出对应汉字)。
   例外:若 today_summaries 文本里**已经原样出现**汉字姓名(例如某条
   summary 写"由李帅跟进..."),你可以原样引用那段汉字,但不要把别处
   pinyin 转成同一汉字。能用 pinyin 时就只用 pinyin。
3. 业务语言**只来自** intent / prev_summary / today_summaries,不要扩展
   未提到的细节;价值描述也只能从 intent 提炼,不许编造
4. 一个 matter 最多在一段方向叙述里点名一次
5. **段落之间用真正的换行符分隔**(每个"第一是 / 第二是"前换行,收尾句
   单独换行成段),但**段内不换行 / 不写小标题**(如"风险:""产出:"
   "节奏:"是禁的)、不要列表、不要 emoji、不要 markdown 标题(# / ##)
6. **统计数字 / 计数一律用阿拉伯数字**:写"10 人参与""20 个活跃事项"
   "7 条契约修订",**不要**写成"十人""二十个""七条"。
   例外:序数词("第一""第二")、固定中文短语("五一前""一批")可保留。
7. **严禁出现下列系统元数据**:
   - ❌ 文件类型词:think / act / verify / result / insight(中英文都禁)
   - ❌ 系统状态名:planning / executing / paused / finished / cancelled / reviewed
   - ❌ 状态迁移箭头:"X→Y""从 X 推进到 Y""状态闭环"
   - ❌ 计数:"X 篇文件""Y 次 verify""K 次 passed"等纯系统计数
     (收尾里"N 个事项 / N 人参与"这种业务计数允许)
   - ❌ 模板话术:"整体推进态势""实质闭环""活跃强度分布""沉淀了..."
8. 信息不足时跳过该事项 / 该方向 / 该价值描述,不靠模板凑长度
9. tone 字段必须三选一:
   - active:多个方向有清晰产出,或有重大决策 / 上线
   - steady:少量推进,无明显风险也无重大决策
   - stalled:几乎只有讨论中事项,无完成、无产出推进

────────────────────────────────────────────
**输出格式**(严格,不要包成 JSON,不要任何 markdown 包裹):

直接输出叙事正文,各段之间用真正的换行符分隔(\\n),正文写完**单独一行**
写一个 tone 标签:
[tone: active]
或 [tone: steady]
或 [tone: stalled]

完整示例(注意每个"第N是"前的换行,以及收尾段独立成行):

今天团队主要在三个方向上推进。
第一是 Pivot 产品的 MCP 增强,《X》《Y》两项闭环上线。huangshengli 完成
实施,liuyu 完成验收,目前已通过验收,下一步观察线上效果。
第二是面向碧桂园的对外材料,《Z》底稿完成。terry.tao 与 dengke 厘清"标准
核心 + 定制 Agent"双层服务定位,目前底稿已完成,下一步出客户场景大纲。
第三是数据隐私基建,《W》刚启动。yuebilin 完成多角色权限模型,liuyu 给出
7 条契约修订,目前方案具备实施条件,下一步开展代码改造。
团队今日 10 人参与、20 个活跃事项,整体节奏清晰。
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
        timeout_seconds=240.0,
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

    def _trim(t: str) -> str:
        t = (t or "").strip()
        return (t[:SUM_LIMIT] + "…") if len(t) > SUM_LIMIT else t

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
                "intent": _trim(m.intent),
                "prev_summary": _trim(m.prev_summary),
                "lifecycle": m.lifecycle,
                "participants": list(m.participants),
                "today_summaries": [
                    _trim(sm) for sm in m.today_summaries[:PER_MATTER_LIMIT]
                ],
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
    # Defensive truncate — prompt 目标上限 450 字,留 250 字 buffer 兜底超长
    if len(summary) > 700:
        summary = summary[:700].rstrip() + "…"
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
