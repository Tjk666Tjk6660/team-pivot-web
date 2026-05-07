"""Build the system + user prompt sent to the AI for one matter's scoring.

输入：matter index dict（YAML 解析后） + commenter weight 表 + subject pinyin
       + file body loader（从 git 取每个 timeline 文件正文）
输出：[{"role":"system",...}, {"role":"user",...}] 给 server.ai.oneshot.generate_text

Truncation strategy（design §6）：
- 每个文件 body ≤ 5000 字符（超出末尾加 "...(truncated)"）
- timeline 序列化总长 ≤ 50000 字符；超限按 think/insight 倒序丢弃，保留所有
  act/verify/result（核心证据来源）
- 极端情况仍超 → 抛 PromptTooLargeError，由 worker 标记 run failed

System prompt 是 design §3 评分规则的浓缩落地版。post 在 Pivot 是源头权威，
代码这里跟随其后。修改前请先在 matter 里跟一条 think 说明动机。
"""
from __future__ import annotations

from typing import Callable, Iterable

# Function that turns a file path (e.g. "discussions/eng/auth-redesign/001_x.md")
# into the file body string. Returns "" on missing/unreadable file.
FileBodyLoader = Callable[[str], str]


# Map: pinyin → (weight, label). pinyin keys correspond to the values written
# into git timeline at the time of comment creation (matter_index timeline
# items use creator/owner pinyin; comments use author pinyin).
WeightMap = dict[str, tuple[float, str]]


MAX_BODY_CHARS = 5000
MAX_TOTAL_CHARS = 50_000

# File types that may be dropped first when truncating (background / aftermath
# rather than core evidence). Order matters: leftmost = first to drop.
_DROPPABLE_TYPES_ORDER = ("insight", "think")
# File types that are core evidence and must NEVER be dropped.
_CORE_TYPES = frozenset({"act", "verify", "result"})

# Role hints rendered in each file item header so the AI can apply
# 【评价范围限制】 (matter 005) consistently. think/act are evaluation
# sources; verify is the evaluation endpoint about the *verified* file's
# author; result/insight are background only.
_FILE_TYPE_ROLE = {
    "think":   "（核心：可发起评价）",
    "act":     "（核心：可发起评价）",
    "verify":  "（终点：作为对被验文件作者的事实证据）",
    "result":  "（背景：不发起新评价，仅作 outcome 判断）",
    "insight": "（背景：不发起新评价）",
}


class PromptTooLargeError(Exception):
    """Even after dropping all droppable items, prompt exceeds the budget."""


# ---------- public entry ----------


def build_scoring_prompt(
    *,
    index_data: dict,
    weight_map: WeightMap,
    candidate_subjects: set[str],
    file_body_loader: FileBodyLoader,
) -> list[dict]:
    """Return the [system, user] message list ready for generate_text.

    v2.1 (Phase 2): `candidate_subjects` is a set of pinyins the AI may
    score — typically the think/act file creators in the timeline (matter
    005). Phase 1 callers pass a 1-element set (e.g. `{matter.owner}`).
    """
    if not candidate_subjects:
        raise ValueError("candidate_subjects must be non-empty")
    system = build_system_prompt(candidate_subjects)
    timeline_block = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=file_body_loader,
    )
    subjects_line = "、".join(sorted(candidate_subjects))
    user_content = (
        f"# Matter 时间线\n\n"
        f"评分候选集：{subjects_line}（按 think / act 文件作者解析得到）\n\n"
        f"{timeline_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


# ---------- system prompt ----------


def build_system_prompt(candidate_subjects: set[str]) -> str:
    """Render the system prompt with the candidate subject set baked in.

    Source: matter「需求：员工评价体系需求与设计」§3 + §6（v0.3 act 帖子）
    + 005 决策链 + v2.1 multi-subject expansion (Task 2.4).
    """
    if not candidate_subjects:
        raise ValueError("candidate_subjects must be non-empty")
    subjects_csv = ", ".join(sorted(candidate_subjects))
    return _SYSTEM_PROMPT_TEMPLATE.format(
        subjects=subjects_csv,
        subject_count=len(candidate_subjects),
    )


_SYSTEM_PROMPT_TEMPLATE = """\
你是 Matter 评分员。给你一个 Matter 的完整时间线，评估候选人员的工作表现。

【评分对象】（v2.1 多 subject）
- 候选集（{subject_count} 人）：{subjects}
- 候选集来自 timeline 中所有 think / act 文件的作者（matter 005 §4 归因模型）。
  对每个候选人**独立判断**是否有足够证据评分，分别输出一条 score 行；
  没有足够证据的候选人加入 skipped_subjects 数组（不要硬给 3）
- subject_pinyin 必须落在候选集内；不在候选集的人**不要**生成 score 行
- 同一个 subject 不能在 scores 数组里出现多次——把同一人的所有 evidence 合并到一行

【评价对象识别规则（归因决策链）】
对候选集里的**每个 subject**独立应用下面的决策链：

  1. 评价者（comment / annotation author）== 该 subject → 自我评价，**不入链**
  2. 文本中明确点名 / @ 了候选集里**别的**人，并描述其工作行为 → 该证据归被点名者，
     不归当前 subject（属于另一行 score 的 evidence；如果被点名者也在候选集，也要把
     这条作为他们那一行的 evidence）
  3. 否则 → 默认归被评论文件的作者；如果文件作者 == 当前 subject，入该 subject 的链
  4. 在文件作者**不在**候选集的文件下的泛泛评价（"做得不错"无明确指向）→ 跳过
  5. verify 文件的 verifications 内容是对**被 verify 的 act 文件作者**的评价；如果被
     verify 文件作者在候选集，作为该作者的 evidence 入链

【评价范围限制】
- 可发起评价的来源：
  · think / act 的 body 与 comments / annotations
  · verify 的 verifications 内容
  · owner_change.reason
- 不发起新评价的来源：
  · result / insight 仅作背景判断（如 result.outcome 用于 delivery 维度的事实层
    判断）；**不要**从 result / insight 的 body 或 comments 抽出独立 evidence 条目
- result.outcome 与 status_change 仍是事实层信号——通过事实层渠道影响评分，不需要
  单独作为 evidence 列出

【owner_change.reason 解析】
- reason 含对 from_owner 工作质量的评价（如"前期推进不力"、"做得很好转给 X 推广"）
  且 from_owner 在候选集 → 入 from_owner 的证据链（不是 to_owner 的！）
- reason 是中性说明（"职责调整"、"人员变动"、"项目分流"） → 不入链
- to_owner 不会因为这条 reason 增加证据，因为 reason 描述的是前任工作

【隐式评价规则（005 §4 表 / v2.1 Task 2.4）】
某些 timeline 结构变化本身就是评价信号，按下面映射归因：

  · `verify failed` / 多次 verify failed 后才 passed
    → 被 verify 的 act 文件作者的 **delivery 维度负向**
    → attribution_basis: `verify_outcome`
    → 至少 1 次 failed 即入链；后续 passed 不抹除负向（弱化即可）

  · 长期被 `@` 不回复（同一文件下别人 @ 该 subject 后该 subject 在 14 天内无任何
    timeline 动作 / 同文件 comment 回复）
    → 被 @ 的人的 **collaboration 维度负向**
    → attribution_basis: `at_target`

【双层证据模型】
- 事实层（硬证据，来自 timeline 结构）：verify 是否 passed、result.outcome、
  是否被 owner_change、timeline 节奏、文件类型完整度
- 语义层（软证据，来自 comments 文本）：评论的褒贬 / 具体度 / 作者权重

【三条核心原则】
P1. 事实先行：没有事实证据，光有评论不能给分
P2. 语义加权是调整器，不是发动机
P3. 维度对两层证据的依赖度不同（见下表）

【五维度（依赖度 + 权重）】
| 维度          | 看什么            | 事实层  | 语义层 | 权重 |
| delivery       | 是否通过验收      | 强      | 中     | 0.30 |
| accountability | 是否推到收口      | 强      | 弱     | 0.25 |
| judgment       | 判断是否准确      | 中      | 强     | 0.20 |
| collaboration  | 协作贡献          | 中      | 强     | 0.15 |
| process        | 过程规范          | 强      | 弱     | 0.10 |

【评分含义】
5=明确优秀；4=表现良好；3=正常完成；2=有明显问题；1=严重影响
- 任一维度证据不足 → 该维度填 null（不要硬给 3）
- overall = 已评维度的加权均值
- 某 subject 全部维度都 null → 不为他出 score 行，把该 subject 加入 skipped_subjects

【证据准入规则】
- 入链：明确指向 owner + 描述工作行为或结果
- 弱入链 (low)：只有"不错/很差"无上下文；comment 没选 mentions 但能从所在帖子推断
- 不入链：只有情绪化表达；评价对象不明确；与 Matter 无关
- 同一人重复评价同一事实 → 合并；一句话有褒有贬 → 拆成多条

【annotation 消费规则（v2.1）】
- annotation 是**强语义评价证据**——比 mention/comment 中的留言更明确表达"对该文件的评价"。AI 在归因清晰时应优先采用，confidence 上限可以更高
- 归因仍按上面的【评价对象识别规则】决策链：默认归被评论文件的作者；若 annotation 文本中明确点名他人则归被点名者
- **自我 annotation 一律不入链**：若 `annotation.author == 该行 subject`，必须跳过，无论极性正负——延续 Phase 1 给 comment 做的同款规则
- annotation 没有 `targets` / `@`，不要尝试从 annotation 解析 mentions
- 输出时设 `source_kind: "annotation"`，并填 `source_annotation_created_at` + `source_annotation_author`

【归因依据字段（v2.1）】
每条 evidence 必须标 `attribution_basis`，五选一：
- `file_creator`：默认归被评论文件作者（005 决策链兜底，最常见）
- `explicit_mention`：评论 / annotation 文本明确点名他人 → 归被点名者
- `at_target`：comment 的 mentions/targets 数组里 @ 了某人
- `owner_change_reason`：从 owner_change.reason 解析的对原 owner 的工作质量评价
- `verify_outcome`：verify 文件的 verifications 结果（passed / failed）作为对被验文件作者的事实证据

【评论权重规则】
评论作者标注权重时（如 1.5x、2.0x），该评论作为证据的 confidence 不能低于：
- weight ≥ 2.0：positive 证据 = high；negative 证据 = high
- 1.3 ≤ weight < 2.0：positive 证据 = medium；negative 证据 = high
- weight = 1.0：按通用证据规则判
权重不替代证据规则：
- 高权重的人若仅说"很好"/"+1"等程式化客套，仍按"弱入链或不入链"处理
- 事实层为负（verify failed），高权重评论也不能抬高该维度（P1 事实先行）
- 权重作用范围：影响 confidence 等级 + 微调分数（±0.5）；不影响维度可评性

【输出 JSON schema】严格 JSON，不要 markdown 代码块包裹：
注意 scores 是数组，候选集里每个有足够证据的人各一行；没有足够证据的人放
skipped_subjects。同一个 subject 不能出现两次。
{{
  "scores": [
    {{
      "subject_pinyin": "<候选集里的某 pinyin>",
      "overall": 4.2,
      "confidence": "high",
      "rationale": "一段 ≤200 字总结",
      "dimensions": {{
        "delivery": 4.5,
        "accountability": 4.0,
        "collaboration": 3.5,
        "judgment": null,
        "process": 4.0
      }},
      "evidence": [
        {{
          "dimension": "delivery",
          "polarity": "positive",
          "confidence": "high",
          "source_kind": "file",
          "source_filename": "003_lisi_verify_xxx.md",
          "source_file_type": "verify",
          "source_file_creator": "lisi",
          "source_comment_created_at": null,
          "source_comment_author": null,
          "source_annotation_created_at": null,
          "source_annotation_author": null,
          "attribution_basis": "verify_outcome",
          "weight_applied": 1.0,
          "quote": "原文截取，≤200 字符",
          "explanation": "为什么这条证据支持该维度"
        }}
      ]
    }}
  ],
  "skipped_subjects": []
}}

【硬约束】
- subject_pinyin 必须落在候选集 {{{subjects}}} 内
- 同一个 subject 在 scores 数组里最多出现一次
- 每个非 null dimension 至少 1 条 evidence 指向该维度
- 同一 quote 支持多个维度时，请复制为多条 evidence row，每条标一个 dimension。
  例如「李四二次提交补齐 C 风险」同时反映 delivery / accountability / judgment 时，
  请输出三条 evidence（quote / source_filename / source_kind 等字段相同，只换 dimension）。
  不要让某个维度的分数无 evidence 兜着——服务端会把无证据的维度丢分
- source_filename 必须是我提供的 timeline 中真实存在的文件名（不要编造）
- source_file_creator 应填写该文件的 creator pinyin（在每条 timeline 文件头里能看到）；
  此字段用于自我评价检测，错填会被服务端拒收
- evidence.quote 必须是原文截取（≤200 字符），不要改写
- source_kind="comment" 时必填 source_comment_created_at + source_comment_author
- source_kind="annotation" 时必填 source_annotation_created_at + source_annotation_author（v2.1）
- attribution_basis 必填，五选一（file_creator / explicit_mention / at_target /
  owner_change_reason / verify_outcome）；不要遗漏
- evidence 不能违反【评价对象识别规则】（对每行 score 各自判断）：
  - 自我评价 comment（comment author == 该行 subject）一律不入链
  - 自我 annotation（annotation author == 该行 subject）一律不入链（v2.1）
  - **subject 自己的 think / act / verify 文件**作为**工作产出**可以引用（正向负向均可），
    比如 lisi 写的 act 被 verify 通过 → 可以作为 lisi delivery 的事实证据；
    但**不要**引用为"自我背书评论"——你引用的是工作产物本身，不是 subject 在评自己
- 不评价私人态度，只评价工作行为
"""


# ---------- timeline serialization ----------


def serialize_timeline(
    *,
    index_data: dict,
    weight_map: WeightMap,
    file_body_loader: FileBodyLoader,
    max_body_chars: int = MAX_BODY_CHARS,
    max_total_chars: int = MAX_TOTAL_CHARS,
) -> str:
    """Render the matter timeline as plain text for the AI user message.

    Layout per file item:
        [文件 NNN] type=X creator=foo (LABEL, 权重 Wx) owner=bar
        summary: ...
        verifications: ...        (verify only)
        verifications_received: ... (act only)
        outcome: ...              (result only)
        status_change: from→to    (when present)
        body:
            ...truncated body...
        comments:
            - alice (CTO, 权重 1.5x) @ 2026-04-22 14:00 → mentions=[bob]
              "comment body"

    Owner_change events render as:
        [事件] owner_change actor=foo from=a to=b reason=...
    """
    matter = index_data.get("matter") or {}
    timeline = index_data.get("timeline") or []

    header_lines = [
        f"matter.id = {matter.get('id', '')}",
        f"matter.title = {matter.get('title', '')}",
        f"matter.current_status = {matter.get('current_status', '')}",
        f"matter.owner = {matter.get('owner', '')}",
        f"matter.created_at = {matter.get('created_at', '')}",
        f"matter.updated_at = {matter.get('updated_at', '')}",
        f"timeline 共 {len(timeline)} 条",
        "",
    ]
    header_block = "\n".join(header_lines)

    rendered_items = _render_all_items(
        timeline, weight_map, file_body_loader, max_body_chars,
    )
    selected = _drop_until_fits(
        rendered_items,
        budget=max_total_chars - len(header_block),
    )

    return header_block + "\n\n".join(s for _, _, s in selected)


def _render_all_items(
    timeline: list[dict],
    weight_map: WeightMap,
    file_body_loader: FileBodyLoader,
    max_body_chars: int,
) -> list[tuple[int, str, str]]:
    """Return [(seq, ftype, rendered_str)] for each timeline item."""
    out: list[tuple[int, str, str]] = []
    for i, item in enumerate(timeline):
        seq = i + 1
        ftype = str(item.get("type") or "")
        if ftype == "owner_change":
            out.append((seq, ftype, _render_owner_change(seq, item)))
        else:
            out.append((seq, ftype, _render_file_item(seq, item, weight_map, file_body_loader, max_body_chars)))
    return out


def _render_file_item(
    seq: int,
    item: dict,
    weight_map: WeightMap,
    file_body_loader: FileBodyLoader,
    max_body_chars: int,
) -> str:
    ftype = str(item.get("type") or "")
    creator = str(item.get("creator") or "")
    owner = str(item.get("owner") or "")
    created_at = str(item.get("created_at") or "")
    summary = str(item.get("summary") or "")
    file_path = str(item.get("file") or "")
    filename = file_path.rsplit("/", 1)[-1] if file_path else ""

    creator_tag = _annotate_actor(creator, weight_map)
    owner_tag = _annotate_actor(owner, weight_map) if owner and owner != creator else ""

    role_tag = _FILE_TYPE_ROLE.get(ftype, "")
    head = (
        f"[文件 {seq:03d}] type={ftype}{role_tag}  filename={filename}\n"
        f"  creator={creator_tag}"
    )
    if owner_tag:
        head += f"  owner={owner_tag}"
    head += f"  at={created_at}"

    lines = [head, f"  summary: {summary}"]

    if ftype == "verify":
        for v in item.get("verifications") or []:
            target = v.get("target", "")
            judgement = v.get("judgement", "")
            comment = v.get("comment", "")
            lines.append(
                f"  verifications: target={target}, judgement={judgement}, comment={_oneline(comment)}"
            )
    if ftype == "act":
        for v in item.get("verifications_received") or []:
            verify_file = v.get("verify_file", "")
            judgement = v.get("judgement", "")
            verified_by = v.get("verified_by", "")
            lines.append(
                f"  verifications_received: from={verify_file} judgement={judgement} by={verified_by}"
            )
    if ftype == "result":
        outcome = item.get("outcome")
        if outcome:
            lines.append(f"  outcome: {outcome}")

    sc = item.get("status_change")
    if sc:
        lines.append(
            f"  status_change: {sc.get('from','?')} → {sc.get('to','?')}"
        )

    quote = item.get("quote")
    if quote:
        lines.append(f"  quote: {quote}")
    refer = item.get("refer") or []
    if refer:
        lines.append(f"  refer: {', '.join(str(r) for r in refer)}")

    body = ""
    if file_path:
        body = file_body_loader(file_path) or ""
    body_block = _render_body(body, max_body_chars)
    if body_block:
        lines.append("  body:")
        for bl in body_block.splitlines():
            lines.append(f"    {bl}")

    # Reader normalizes legacy `comments[]` to `mentions[]`. Prompt label
    # "comments:" + helper name preserved on purpose: the scoring prompt's
    # output wording is deferred to a follow-up (see plan §5) so old
    # scoring runs stay diff-stable until the rewrite ships.
    comments = item.get("mentions") or []
    if comments:
        lines.append("  comments:")
        for c in comments:
            lines.append(_render_comment(c, weight_map))

    return "\n".join(lines)


def _render_owner_change(seq: int, item: dict) -> str:
    actor = str(item.get("actor") or "")
    from_owner = str(item.get("from_owner") or "")
    to_owner = str(item.get("to_owner") or "")
    reason = str(item.get("reason") or "")
    created_at = str(item.get("created_at") or "")
    sc = item.get("status_change") or {}
    sc_part = ""
    if sc:
        sc_part = f"  status_change: {sc.get('from','?')} → {sc.get('to','?')}"
    return (
        f"[事件 {seq:03d}] owner_change  at={created_at}\n"
        f"  actor={actor}  from_owner={from_owner}  to_owner={to_owner}\n"
        f"  reason: {_oneline(reason)}"
        + (f"\n{sc_part}" if sc_part else "")
    )


def _render_comment(c: dict, weight_map: WeightMap) -> str:
    author = str(c.get("author") or "")
    body = str(c.get("body") or "")
    created_at = str(c.get("created_at") or "")
    mentions = c.get("targets") or []
    author_tag = _annotate_actor(author, weight_map)
    mentions_part = (
        f" → mentions=[{','.join(str(m) for m in mentions)}]" if mentions else ""
    )
    # Quote body inline; keep line single — multiline comments collapsed.
    return f"    - {author_tag} @ {created_at}{mentions_part}\n      \"{_oneline(body)}\""


def _annotate_actor(pinyin: str, weight_map: WeightMap) -> str:
    """Append (LABEL, 权重 Wx) annotation for high-weight commenters."""
    if not pinyin:
        return ""
    info = weight_map.get(pinyin)
    if info is None:
        return pinyin
    weight, label = info
    return f"{pinyin} ({label}, 权重 {_format_weight(weight)}x)"


def _format_weight(w: float) -> str:
    """Render weight without trailing zeros (1.0 -> 1, 2.0 -> 2, 1.5 -> 1.5)."""
    if w == int(w):
        return str(int(w))
    return f"{w:.1f}"


def _render_body(body: str, max_body_chars: int) -> str:
    """Truncate file body to max_body_chars, append marker if cut."""
    if not body:
        return ""
    body = body.rstrip()
    if len(body) <= max_body_chars:
        return body
    return body[:max_body_chars].rstrip() + f"\n...（已截断，原文 {len(body)} 字符）"


def _oneline(s: str) -> str:
    """Collapse newlines + repeated whitespace to single spaces."""
    return " ".join((s or "").split())


def _drop_until_fits(
    rendered: list[tuple[int, str, str]],
    *,
    budget: int,
) -> list[tuple[int, str, str]]:
    """Drop droppable items (insight, then think) in reverse seq order until
    total fits within budget. Core types (act/verify/result) and owner_change
    are kept. If even after dropping everything droppable we still overflow,
    raise PromptTooLargeError."""
    keep = list(rendered)

    def total_size(items: Iterable[tuple[int, str, str]]) -> int:
        return sum(len(s) + 2 for _, _, s in items)  # +2 for "\n\n" separator

    if total_size(keep) <= budget:
        return keep

    for ftype_to_drop in _DROPPABLE_TYPES_ORDER:
        if total_size(keep) <= budget:
            break
        # Drop matching items from latest seq backwards (preserve early
        # context which usually frames the matter).
        keep = _drop_matching(keep, ftype_to_drop, budget, total_size)

    if total_size(keep) > budget:
        # Even after dropping all droppable items, we're over. Refuse to
        # silently truncate core evidence — that would mislead AI scoring.
        raise PromptTooLargeError(
            f"timeline too large after truncation: {total_size(keep)} > {budget}"
        )
    return keep


def _drop_matching(
    items: list[tuple[int, str, str]],
    ftype: str,
    budget: int,
    sizer: Callable[[Iterable[tuple[int, str, str]]], int],
) -> list[tuple[int, str, str]]:
    """Drop items of given ftype, latest seq first, until size fits or none left."""
    indices = [i for i, (_, t, _) in enumerate(items) if t == ftype]
    indices.sort(reverse=True)
    out = list(items)
    for idx in indices:
        if sizer(out) <= budget:
            break
        out.pop(idx)
    return out
