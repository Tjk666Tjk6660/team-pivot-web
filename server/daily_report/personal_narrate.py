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
你是 Pivot 个人视角日报生成器,向老板汇报每位活跃成员今天做了什么、
做得怎么样。读者是公司老板,目的是让老板对每个人的当日产出有具体认知,
**不用于绩效评估、打分、排名**。

⚠⚠⚠ **三大死禁** —— 出现一次都视为不达标:

1. **把 think / act / verify / result / insight 五个英文词写进输出**
   → 用中文(讨论 / 实施 / 验证 / 收尾结果 / 复盘)。

2. **用 收尾 / 收口 / 流转 / 落地 这类空洞动词**(包括所有变体词组):
   ❌ "X 完成收尾"  ❌ "X 落地完成"  ❌ "推动 X 流转"  ❌ "X 收口"
   ❌ "X 闭环了"(动词)
   ✅ 必须用具体动词:
   · 自己做完 → 完成 / 上线 / 合入主线 / 交付 / 关闭 / 取消 / 终止 /
                拍板 / 暂缓
   · 给别人工作判定 → 验证通过 / 验收通过 / 审定通过 / 判定关闭 /
                      验证未过 / 确认无产出
   注意:作为名词的"闭环"可以用("3 天闭环""推到闭环阶段")。

3. **打分 / 排名 / 对比 / 评价"积极""高效""努力"等主观判断**
   → 反绩效化原则:只陈述客观事实,不下评语。
   ❌ "积极推进""配合默契""保持高效""贡献突出"
   ✅ "完成 X 上线""把 Y 推到验证阶段""卡 8 天未推进"等可验证事实

──────────────────────────────────────
【角色化叙事】

每位成员同时承担多种角色,输入数据已按角色分桶。**当天有数据的角色才写,
没有的不强求**。三个角色 + 字段对照:

1. **as_owner.matters[]** —— 自己作为负责人的事项(matter.owner == self),
   每个 matter 一段叙述:
   · 看 today_events[] 里**自己写的**事件(by_self=true)推到哪一步
   · 看 today_events[] 里**别人写的**事件(by_self=false):
     - 别人的 verify(验证通过 / 验证未过)→ 我的工作有没有被认可
     - 别人在我事项的评论 / @ 抛球 → 我有没有响应
   · 别人 verify 我的工作时,**仍要点出验证作者的 pinyin**(不要写"管理层")
   · current_status / prev_summary 是上下文,可帮助你写"从 X 推到 Y"
   · 一个 matter 的所有今天事件**揉成一句**叙述,不要按动作分散写

2. **as_verifier.verifications_today[] / results_today[]** —— 我作为
   把关人对别人事项的判定:
   · verifications_today:每条带 matter + judgement
     (passed/failed/partial),写"对 X 验证通过 / 验证未过"
   · results_today:我写的收尾(用作 matter 闭环动作判定)
   · 这是**评判别人工作**,措辞用"验证 / 判定 / 审定",不是"做完 X"

3. **as_collaborator.thinks_in_others_matters[]** —— 我在**别人事项**里
   写的讨论(think,但 matter_owner != 我):
   · 这是协作贡献,通常是"提反提议 / 给关键反馈 / 拍板暂停"等
   · matter_owner 字段告诉你这事项实际负责人是谁

  另外还有 **as_collaborator.mentions_received_contexts[]** —— 我被 @ 抛球的
  上下文(by + body),如果有响应可以提一句"X 抛球的 Y 已接住";没有就不提。

不必硬塞所有角色;只写当天真实发生的。一个人某天可能只是负责人 /
只是把关人 / 三种都有。

**覆盖原则**:`as_owner.matters[]` **里有几个事项,叙述里就要带到几个**——
即使是"暂停开放讨论""判定关闭"这种简短的拍板,也要点出。老板要从这一行
看到这个人今天作为负责人推了哪些事(每个事项都要可识别),不能合并漏报。
verifications_today / results_today 同理,**有几条就要点几条**(同一事项
多条判定可合写)。

**去重原则**:**同一事项在你的叙述里最多出现一次**。如果一个事项跨多个
角色(如对同一事项既写过 verify 也在评论里拍板,或既是负责人也是把关人),
合并到一句话讲完,**不要在不同角色段子里重复提及**。

⚠ **关键陷阱**:同一事项可能在不同角色桶里以**略不同的名字**出现(如
"Pivot UI 全新重构"和 "UI 重构"是同一事项),要按**同一 matter_id /
business 含义**去重,不能因字面差就当成两个事项。判断方法:**关键词
重叠就当同一事项**(如都含 "UI 重构"、都含 "商业化")。

❌ 反例(同事项写 2 次):
   "判定取消 UI 重构需求...在 UI 重构事项中参与...卡片模式改造"
   (前后两个 "UI 重构" 是同一事项,只是后半截带了别的话题)
✅ 正例:
   "判定取消 UI 重构需求(与现有功能重复,卡片模式改造方向已转移)"
   (一句话讲完该事项的所有动作)

❌ 反例(同事项不同名):
   "拍板关闭商业化挑战讨论事项;验证无效...无实质产出的商业化探讨;
    关闭相关商业化与碧桂园物料讨论"
   (商业化挑战讨论 / 商业化探讨 / 商业化 都指向同一事项)
✅ 正例:
   "判定关闭无实质产出的商业化探讨事项"
   (合并到一次)

**写完后自检**:扫描自己的草稿。一个事项的关键词如果出现 ≥ 2 次,必须
合并;不要害怕一句话变长(单条 ≤ 150 字仍有空间),也不要拆成两句。

──────────────────────────────────────
【表达基调】

- 单条 1-3 句,30-150 字之间(没干啥的就 30-50 字,事多的可到 150 字)
- 不写文件路径 / commit hash / 内部 ID
- 不写"X 创建了 N 篇 think,M 篇 act"这种活动量计数
- 人名一律用 pinyin(huangshengli / dengke / liuyu,**不翻译为汉字**)
- 数字一律阿拉伯("3 个事项""8 天",不写"三个事项""八天")
- 事项名**不用任何符号包起来**(《》「」'' "" 都不要),直接用业务白话
  当代称。如"团队日报推送服务"而不是"《新需求-日报推送》"或
  "「失效自己文档」"
- **写业务结果,不写技术实现细节** —— 老板不懂代码,只关心事项有没有
  动 / 拍没拍板 / 闭没闭环。开发名词不要写出来:
  ❌ "完成失效恢复事件、反写字段、通知提醒、界面更新与文档同步开发,
     修复 strip 节点归位问题并将代码合入主线"
  ✅ "完成作者失效文档功能开发并合入主线 v2"
  ❌ "补全并发原子性验证、修复评论丢失字段缺失问题"
  ✅ "完成已读状态功能开发并上线"
  ❌ "P1-P5 落地、反写 4 字段、SSE thin payload"
  ✅ "完成功能合入并推到验证阶段"

**字段值的英文不要写进输出**:
- current_status:planning / executing / paused / finished / cancelled / reviewed
  → 中文(讨论中 / 执行中 / 暂停 / 完成 / 取消 / 已收口)
- judgement:passed / failed / partial → 验证通过 / 验证未通过 / 部分通过
- 结构性词:owner → 负责人 / matter → 事项 / creator → 写的人

──────────────────────────────────────
【硬约束】

- 只为输入数据中**列出**的成员生成叙述 —— 不凭空增加成员
- 严禁臆造:任何陈述必须基于输入字段;不编造未发生的动作 / 状态 / 人

──────────────────────────────────────
【输出格式】

严格 JSON,无任何 markdown 包裹:
{
  "entries": [
    {"pinyin": "alice", "narrative": "..."}
  ]
}

──────────────────────────────────────
【示例】

{
  "entries": [
    {"pinyin": "huangshengli", "narrative": "作为作者失效文档需求的负责人当天合入主线 v2;在 Owner 机制事项中接住接口字段问题(验证未过卡 8 天仍在修复);在 EC 与 APP 形态讨论中拍板暂停。"},
    {"pinyin": "liuyu", "narrative": "完成多项验证:产品分析报告判定关闭、列表筛选验证通过、通知卡片验证通过、Owner 机制验证未过指出接口字段需切换;主导员工评价体系方案设计与底层架构选型评估。"},
    {"pinyin": "tangkun", "narrative": "作为事项列表筛选负责人完成红点清退上线(liuyu 验证通过);启动 comments 重命名方案设计;因方向调整暂停 benchmark SaaS 迭代。"},
    {"pinyin": "dengke", "narrative": "拍板暂停 EC 底层改造与 AI 客服 S1(要求重估架构与商业化定位);新立 5 月底 SaaS 推出项目;判定关闭无产出的商业化探讨。"},
    {"pinyin": "yezaiyong", "narrative": "完成 MCP 数据完整性修复并合入用户管理分支;启动 MCP 可见范围改造方案设计。"}
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
    """精简 UserActivity → AI 友好的 JSON,按"三种角色"分桶。

    v0.16 重构:从"按动作类型分桶(think_files/act_files/...)"改成
    "按角色分桶(as_owner / as_verifier / as_collaborator)",让 LLM 输出
    按事项叙述("作为 X 事项负责人推到 Y")而不是按动作堆砌。

    三种角色:
    - as_owner    matter.owner == self 的事项,今天有活动的清单
                  (含别人在我事项上做的事 —— 我是被动负责人也要看到)
    - as_verifier 我写的 verify / result 文件 —— 第三方判定动作
                  (扁平列出,每条带 matter title + judgement)
    - as_collaborator 我在别人事项里做的事(think 评审 / 评论参与 / 被 @ 抛球)
    """
    return {
        "pinyin": ua.pinyin,
        "as_owner": {
            "matters": [_serialize_owned_matter(d, ua.pinyin)
                        for d in ua.matters_as_owner],
        },
        "as_verifier": _serialize_verifier_actions(ua),
        "as_collaborator": _serialize_collaborator_actions(ua),
    }


def _serialize_owned_matter(d, self_pinyin: str) -> dict:
    """OwnedMatterDigest → JSON。每个事项一个对象,含今天的事件清单。"""
    return {
        "matter": (d.title or "")[:50],
        "current_status": d.current_status,
        "prev_summary": (d.prev_summary or "")[:120],
        "today_events": [
            _serialize_event(ev, self_pinyin)
            for ev in d.today_events[:12]
        ],
    }


def _serialize_event(ev, self_pinyin: str) -> dict:
    """单条 timeline 事件 → JSON。标 by_self 让 LLM 区分"我做的"和"别人做的"。"""
    out: dict = {
        "by": ev.creator,
        "by_self": ev.creator == self_pinyin,
        "type": ev.file_type,
        "summary": (ev.summary or "")[:80],
    }
    if ev.status_change:
        out["status_change"] = {
            "from": ev.status_change.get("from"),
            "to": ev.status_change.get("to"),
        }
    if ev.file_type == "verify" and ev.verifications:
        out["judgements"] = [
            v.get("judgement") for v in ev.verifications if v.get("judgement")
        ]
    if ev.comments_in_window:
        out["comments_in_window"] = [
            {
                "by": c.author,
                "body": (c.body or "")[:80],
                "mentions": list(c.mentions),
            }
            for c in ev.comments_in_window[:5]
        ]
    return out


def _serialize_verifier_actions(ua: UserActivity) -> dict:
    """我写的 verify / result 文件 —— 第三方判定动作,按事项扁平列出。"""
    verifications = []
    results = []
    for ev in list(ua.file_creates) + list(ua.file_owns):
        if not ev.file_in_window:
            continue
        if ev.file_type == "verify" and ev.verifications:
            for v in ev.verifications:
                judgement = v.get("judgement")
                if not judgement:
                    continue
                verifications.append({
                    "matter": (ev.matter_title or "")[:50],
                    "judgement": judgement,
                    "comment": (v.get("comment") or "")[:80],
                })
        elif ev.file_type == "result":
            results.append({
                "matter": (ev.matter_title or "")[:50],
                "summary": (ev.summary or "")[:80],
            })
    return {
        "verifications_today": verifications[:8],
        "results_today": results[:5],
    }


def _serialize_collaborator_actions(ua: UserActivity) -> dict:
    """在别人事项里做的事(think / 评论 / 被 @ 抛球)。

    "别人事项" = matter.owner 不是 self。落差用 matter_owner 字段判断;
    matter_owner 缺失(老 matter)时按"非自己的 matter"保守归类:看 ev.creator
    或 ev.owner 是否等于 self。
    """
    self_pinyin = ua.pinyin
    thinks_in_others = []
    for ev in ua.file_creates[:8]:
        if ev.file_type != "think":
            continue
        owner = ev.matter_owner or ev.owner
        if owner and owner != self_pinyin:
            thinks_in_others.append({
                "matter": (ev.matter_title or "")[:50],
                "matter_owner": ev.matter_owner or ev.owner,
                "summary": (ev.summary or "")[:80],
            })

    # mentions 不数计数,给 LLM 看抛球的事项 + body 上下文
    mention_contexts = []
    seen_keys = set()
    for ev in ua.file_creates + ua.file_owns:
        for c in ev.comments_in_window:
            if self_pinyin in c.mentions:
                key = (ev.matter_id, c.created_at)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                mention_contexts.append({
                    "matter": (ev.matter_title or "")[:50],
                    "by": c.author,
                    "body": (c.body or "")[:80],
                })
                if len(mention_contexts) >= 5:
                    break
        if len(mention_contexts) >= 5:
            break

    return {
        "thinks_in_others_matters": thinks_in_others,
        "comments_count": len(ua.comments_given),
        "mentions_received_contexts": mention_contexts,
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
