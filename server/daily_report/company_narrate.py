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

⚠⚠⚠ **三大死禁** —— 出现一次都视为不达标:

1. **把 think / act / verify / result / insight 五个英文词写进输出**
   → 用中文(讨论 / 实施 / 验证 / 收尾结果 / 复盘)。

2. **用 收尾 / 收口 / 流转 / 落地 这类空洞动词**(包括所有变体词组):
   ❌ "X 完成收尾"  ❌ "判定完成收尾"  ❌ "X 判定收尾"  ❌ "X 完成验证收尾"
   ❌ "推动状态流转"  ❌ "状态流转准备 X"  ❌ "X 流转完成"  ❌ "进入验证流转"
   ❌ "X 收口"  ❌ "推动 X 收口"  ❌ "X 收尾"(动词)  ❌ "落地 X"  ❌ "X 落地完成"
   ❌ "X 闭环了"(动词,X 是事项名时)
   ✅ 必须用具体动词:
   · 负责人做完 → 完成 / 上线 / 合入主线 / 交付 / 关闭 / 取消 / 终止 /
                 拍板 / 暂缓
   · 把关人判定 → 验收通过 / 验证通过 / 审定通过 / 判定关闭 / 验证未过 /
                 确认无产出
   写法对比:
   ❌ "terry.tao 推动产品分析报告, 经 liuyu 判定完成收尾"
   ✅ "terry.tao 确认产品分析报告与 SaaS 主线重叠, liuyu 判定关闭"
   ❌ "yezaiyong 完成历史验证并收尾"
   ✅ "yezaiyong 已完成 MCP 接入, liuyu 验证通过"
   ❌ "推动 MVP 文档状态流转准备最终关闭"
   ✅ "MVP 文档与 SaaS 主线重复, terry.tao 推进到验证阶段, 等 liuyu 关闭"

3. **写"N 天连写 N 篇 act / 产出 X 篇 think / 写了 N 次 verify"这种活动量计数**
   → 管理层不关心 file 数量。只关心事项有没有动 / 拍没拍板 / 闭没闭环。

注意:作为名词的"闭环"(描述事项已完成的状态)可以用,如"3 天闭环"
"9 项闭环";但作为动词的"X 闭环了"不行。

──────────────────────────────────────
【任务】

对每个有进展的 matter,从 timeline_yaml 里读懂下面五件事:

1. **这件事是干啥的** —— 解决什么问题、价值在哪
2. **负责人是谁、推得怎么样** —— `matter.owner` 是对此事负责到底的人,
   每个事项必点负责人(用 pinyin 名字)。判断推进情况**只看实际推进结果,
   不数 file 作者**:

   强信号:
   · status_change 推进了一步
   · 出现 result(完成 / 取消 = 整事项闭环)
   · verifications.judgement = passed(实施被独立认可)
   · 评论里负责人在拍板 / 收口

   弱/负信号:
   · 长跨度仍在讨论中未拍板
   · 长期无验证进入收口
   · 验证未通过后无后续实施
   · @ 抛球后负责人长期无回应

   ⚠ 不要用 file 作者判断负责人 —— 实施一般负责人写但允许中途换人;
     讨论是多人知识碰撞;验证 / 收尾本就由第三方(非负责人本人,如同事 /
     上级 / 下游)写,不是负责人失声证据
   ⚠ **禁止**写"N 天连写 N 篇 act / 写了 X 个 verify"这种活动量计数,
     管理层不关心活动量,只关心事项有没有动 / 拍没拍板 / 闭没闭环
3. **推进过程是怎么样的** —— 谁起头、争论焦点、谁拍板、谁实施、谁验收
4. **现在推到哪了、下一步往哪走**
5. **生命周期跨度(只看显著值)** —— `matter.created_at → matter.updated_at`
   的天数(收口的看到 result / insight 那条)。**只在显著异常时才写进叙事**:
   · 显著快闭环(≤ 3 天 / 当天) = 强信号,写出来(如"当天合入"、"3 天闭环")
   · 显著长停滞(同一状态 ≥ 7 天无推进 / ≥ 14 天仍未拍板 / ≥ 21 天仍未
     收口) = 节奏警告,写出来(如"讨论 14 天未拍板"、"执行中 3 周仍无验证")
   · **落在两者之间的常规节奏 → 不写跨度**,直接讲事项进展就行
   常规节奏强行贴跨度数字会让汇报变成"X 天 Y / X 天 Z"的流水账,
   读者会麻木 —— 跨度数字应该是稀缺信号,不是默认装饰

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
- creator       写这条文件的人(pinyin):
                · 第一条 think 的 creator    = 需求提出方
                · 后续 think 的 creator      = 协作讨论者(多人知识碰撞)
                · act 的 creator             = 实施者(通常 = 负责人,允许换人)
                · verify / result 的 creator = 第三方评估者(非负责人本人)
- owner         单条 timeline 项的责任人(多数 = matter.owner;落差 = 协作)。
                **顶层 `matter.owner` 才是叙事核心** —— "对此事负责到底的人"。
                ⚠ creator 与 owner 经常不同(提出方 ≠ 实施方),不要写成"代写"。
                  叙事不用 creator 计数判断负责人表现,看 status_change /
                  verifications / result 等推进结果
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
- 区分"负责人动作"和"把关人判定"两套动词(详见开头【三大死禁】#2):
  · 负责人 → 完成 / 上线 / 合入主线 / 交付 / 关闭 / 取消 / 拍板 / 暂缓
  · 把关人(verify / result 作者)→ 验收通过 / 验证通过 / 审定通过 /
    判定关闭 / 验证未过 / 确认无产出
- 用普通的中文动词:完成 / 上线 / 通过验收 / 进入开发 / 拍板 / 暂缓 /
  启动 / 验收未过 / 反提议
- **YAML 字段值的英文不要写进输出**(老问题,涵盖范围扩到全部结构词):
  · current_status:planning / executing / paused / finished / cancelled / reviewed
    → 中文(讨论中 / 执行中 / 暂停 / 完成 / 取消 / 已收口)
  · verifications.judgement:passed / failed / partial
    → 中文(验证通过 / 验证未通过 / 部分通过)
  · result.outcome:finished / cancelled
    → 中文(完成收尾 / 中止)
  · 结构性词:owner → 负责人(或直接带出 pinyin 名字);matter → 事项;
    creator → 写的人 / 提出方
  · status_change 描述用中文动词("从讨论中推进到执行中"),不写"planning → executing"
- 验证 / 收尾这类动作要**点名实际写这条文件的人**(pinyin,从 verify /
  result 文件的 creator 字段读),不要抽象成"管理层 / 同事 / 有人 / 第三方"
  这种泛指
- 人名一律 pinyin(如 huangshengli / dengke,**不翻译为汉字**)
- 数字一律阿拉伯("10 人""20 个""7 条",不写"十人""二十个""七条")
- 事项**不写书名号**,用业务白话当代称(如"团队日报推送服务"而不是
  "《新需求-日报推送》")。如果 timeline 里有具体数字 / 关键人 / 关键
  动作,**保留下来**,不要抽象化。

【输出结构】

- 段落 1: 开场一句,**点名今天主要的业务方向**(不要只说"两个方向""三个
  方向",要写出方向名字),例如:
  ✅ "今天团队主要在 Pivot 产品、enclaws 底层 与 外部客户交付 三个方向
     上推进。"
  ✅ "今天团队主要在 Pivot 产品方向打磨,外部交付有两项事项进展。"
  ❌ "今天团队主要在两个方向上推进。"(空话,没信息)
  方向名字用业务白话(Pivot 产品 / enclaws 底层 / 外部客户交付),不直接
  念 category 字面值
- 段落 2..N+1: 每个方向一段,以"第一是 / 第二是"开头(只 1 个方向就直接讲)
- 段落 N+2(可选): 收尾一句,团队节奏。**只有当节奏真的有可点的业务事实
  时才写**(如"密集打磨""承诺压力大""人参与新高/新低""跨方向资源紧张"
  等)。如果只是空洞总结("完成阶段收口""无阻塞卡点""节奏稳健""协同推进
  顺畅"等套话),**直接省略整段**,不要硬凑。
- 段间用真换行(\\n)分隔。**段内默认不换行**(用句号 / 分号衔接)。
- **段内换行例外** —— 防止管理层看见一坨 400 字的分号串子:
  · 一个方向段含 **≥ 6 个 matter**(典型如 Pivot 大方向 10+ 个):**先按
    节奏阶段切 2-3 个子段**(已闭环 / 进入开发 / 仍在设计 / 暂缓 等),
    每个子段 50-150 字,子段间用换行
  · **子段含 ≥ 4 个 matter** → **必须每个 matter 单独成一行**(纯换行
    隔开,不加 bullet / 符号 / 标题)。**这是硬规则,不要把多个 matter
    用句号 / 分号串成一段** —— 视觉上像段诗,不像列表,管理层一行
    扫一个事项,可以快速看完
  · 子段开头用业务短语自然引导 + **全角中文冒号 ":"**,接换行符,
    然后每行写一个 matter。**统一用全角 ":",不用 "——"**(渲染层依据
    全角冒号识别子段头并加视觉层次):
    几项老需求集中闭环:
    X(pinyin)完成 ...
    Y(pinyin)上线 ...
    Z(pinyin)合入主线,W 验收通过 ...
  · 子段含 ≤ 3 个 matter 时,按句号 / 分号在同一段内串接(不必每行一个)
  · ⚠ 即使是"暂停"/"启动设计"这种"看起来都很相似的子段",只要 matter
    数 ≥ 4,**也必须每行一个**,不要因为"反正都是暂停"就揉成一段
  · **不要**写 # / ** / Markdown 标题 / 列表符号这种独立标题行
    (渲染层会基于"业务短语 + 全角冒号 + 多行事项"模式自动添加视觉层次,
    你只管写自然口语)
- 不写"风险:""产出:""节奏:"这种小标题
- **每个有弧线感的事项必须点名负责人**(写 pinyin,数据从 `matter.owner`
  字段取),并写明负责人把事项推到哪一步、拍没拍板、闭没闭环(只看
  status_change / verifications / result / 评论里的拍板,**不看 file 计数**)。
  creator(需求提出方)默认不写,除非他在事项弧线里有关键动作(拍板 /
  反提议 / 验收)
- **跨度数字只在显著时点出,不要每个事项都贴 N 天**:
  · 显著快闭环(≤ 3 天 / 当天) → 写("当天合入"、"3 天闭环")
  · 显著长停滞(≥ 7 天无推进 / ≥ 14 天未拍板 / ≥ 21 天未收口) → 写
    ("讨论 14 天未拍板"、"执行中 3 周仍无验证")
  · 常规节奏(4-13 天正常推进) → **不要写跨度**,直接讲事项进展即可
  ⚠ **一份汇报里"X 天"出现的次数应该远少于事项总数**(30 个 matter
    提跨度 ≤ 5 个比较合理)。如果你觉得每个事项都该贴 N 天,那就是
    写流水账了 —— 跨度是稀缺信号,不是默认装饰
- **总字数 = 自然涌现,不要凑**:
   · 字数应该由"每事项有多少业务事实"决定,不由"看起来像份正经日报"决定
   · **上限按 matter 数兜底**:
     - ≤5 个    → 不超 400 字
     - 6-10 个  → 不超 600 字
     - 11-20 个 → 不超 900 字
     - >20 个   → 不超 1200 字
   · **没有下限** —— 如果今天只有 2 个 matter 各推进一小步,写 80-150 字
     就够了。**绝不要为了"看起来像份完整日报"凑长度**。诚实的短报告
     比 AI 套话凑出来的长报告好得多
   · 低活动日的开头可以直接说"今日活动较少,主要在 X 方向"或"今天只有
     2 个事项推进",不需要硬塞"积极推进""节奏稳健"等套话
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
人名 pinyin / 每个事项必点负责人 / 验证作者具名(用 pinyin) / **跨度数字
只在显著异常时才写**(示例里 10 个事项只 2 处提跨度,常规节奏不贴 N 天) /
不写 file 计数 / 字段值全中文 / 没有黑话和套话)

今天团队主要在 Pivot 产品 与 外部客户交付 两个方向上推进。

第一是 Pivot 产品方向。多项老需求集中闭环:
数据隐私权限体系 yuebilin 把多角色权限模型推到验收,dengke 验证通过。
员工 AI 评价方案 liuyu 抛出 admin 视角初版,dengke 反提议扩到协作 mention,核心争议在评分权重 AI 派生 vs 人工。
团队日报推送 huangshengli 在 dengke 拍板后当天合入 v0.2。
事项列表筛选 tangkun 完成红点清退逻辑上线,liuyu 验收通过。

执行中或待验收的有:Owner 机制 lishuai 实施后,liuyu 验证未过指出接口字段需切换为用户表 ID,卡 8 天仍在修复。

第二是外部交付方向。面向碧桂园的产品介绍物料底稿完成,terry.tao 定下"标准核心+定制 Agent"双层服务定位,3 天交底稿。opc-dev 演示环境上线,lishuai 部署华为云。CRM Agent 客户演示,xiaoming 抛出方案后 14 天仍未推进,terry.tao 介入推动,xiaoming 节奏偏慢。

团队今日 10 人 / 18 个事项,2 个事项节奏偏慢。

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
    # 内部限长(max_summary_chars=250 / max_comment_chars=150 / max_timeline_items=30),
    # comments 数量不截断 —— 评论里的拍板/@/异议都是关键决策信号。
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
    # 活跃 matter 都进 input,所以最大档 >20 → 1200 字)。新格式"每行一个
    # matter"天然多 ~300 字开销,且 LLM 常轻微超目标 —— 截断阈值放宽到
    # 2200(目标 1200 的 1.83x),给视觉换行留余量,仍兜底失控超长(>2200
    # 一般是 LLM 写出"风险/产出/节奏"小标题或长形容词堆,直接砍掉无损)。
    if len(summary) > 2200:
        summary = summary[:2200].rstrip() + "…"
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
