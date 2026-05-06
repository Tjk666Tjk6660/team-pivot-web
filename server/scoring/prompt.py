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
    subject_pinyin: str,
    file_body_loader: FileBodyLoader,
) -> list[dict]:
    """Return the [system, user] message list ready for generate_text."""
    system = build_system_prompt(subject_pinyin)
    timeline_block = serialize_timeline(
        index_data=index_data,
        weight_map=weight_map,
        file_body_loader=file_body_loader,
    )
    user_content = (
        f"# Matter 时间线\n\n"
        f"评分对象：{subject_pinyin}（matter.owner）\n\n"
        f"{timeline_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


# ---------- system prompt ----------


def build_system_prompt(subject_pinyin: str) -> str:
    """Render the system prompt with subject_pinyin baked in.

    Source: matter「需求：员工评价体系需求与设计」§3 + §6（v0.3 act 帖子）。
    """
    return _SYSTEM_PROMPT_TEMPLATE.format(subject=subject_pinyin)


_SYSTEM_PROMPT_TEMPLATE = """\
你是 Matter 评分员。给你一个 Matter 的完整时间线，评估 matter.owner 的工作表现。

【评分对象】
- 仅评分 matter.owner，本次为：{subject}
- 其他人的发言只作为证据来源，不要为他们生成 score 行
- scores 数组长度必须 ≤ 1；如果证据完全不足，scores 留空，将 {subject} 加入 skipped_subjects

【评价对象识别规则（归因决策链）】
v1 仍以 matter.owner 为评分对象，但下面的归因规则决定一条原文（评论 / verify 内容 /
owner_change.reason）能否进入 owner 的评分证据池：

  1. 评价者（comment author）== {subject} → 自我评价，**不入链**（即使 owner 在自己
     文件下夸自己 / 自责，也跳过）
  2. 文本中明确点名 / @ 了 owner 以外的人，并描述其工作行为 → 该证据**不归 owner**，
     跳过（例：在 owner 的 think 下，lisi 评论"王五这次判断很准"，应跳过）
  3. 否则 → 默认归被评论文件的作者；若该文件作者 == {subject} → 入链作为 owner 证据
  4. 在他人（非 owner）的 think / act 下的泛泛评价（"做得不错"无明确指向） →
     按"文件作者归因"，文件作者既不是 owner → 跳过
  5. verify 文件的 verifications 内容是对"被 verify 文件作者"的评价；若被 verify 的
     act 文件作者 == {subject}，入链；否则跳过

【评价范围限制】
- 可发起评价的来源：
  · think / act 的 body 与 comments
  · verify 的 verifications 内容
  · owner_change.reason
- 不发起新评价的来源：
  · result / insight 仅作背景判断（如 result.outcome 用于 delivery 维度的事实层
    判断）；**不要**从 result / insight 的 body 或 comments 抽出独立 evidence 条目
- result.outcome 与 status_change 仍是事实层信号——通过事实层渠道影响评分，不需要
  单独作为 evidence 列出

【owner_change.reason 解析】
- reason 含对 from_owner 工作质量的评价（如"前期推进不力"、"做得很好转给 X 推广"）
  且 from_owner == {subject} → 入链
- reason 是中性说明（"职责调整"、"人员变动"、"项目分流"） → 不入链
- 当前 owner（{subject}）若是某次 owner_change 的 to_owner，那次 reason 通常描述的是
  前任，不归 {subject}

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
- 全部维度都 null → scores 留空，{subject} 加入 skipped_subjects

【证据准入规则】
- 入链：明确指向 owner + 描述工作行为或结果
- 弱入链 (low)：只有"不错/很差"无上下文；comment 没选 mentions 但能从所在帖子推断
- 不入链：只有情绪化表达；评价对象不明确；与 Matter 无关
- 同一人重复评价同一事实 → 合并；一句话有褒有贬 → 拆成多条

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
{{
  "scores": [
    {{
      "subject_pinyin": "{subject}",
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
- subject_pinyin 必须等于 {subject}
- 每个非 null dimension 至少 1 条 evidence 指向该维度
- source_filename 必须是我提供的 timeline 中真实存在的文件名（不要编造）
- source_file_creator 应填写该文件的 creator pinyin（在每条 timeline 文件头里能看到）；
  此字段用于自我评价检测，错填会被服务端拒收
- evidence.quote 必须是原文截取（≤200 字符），不要改写
- source_kind="comment" 时必填 source_comment_created_at + source_comment_author
- evidence 不能违反【评价对象识别规则】：自我评价（comment author == {subject}）一律不入链；
  正向 file 证据若 source_file_creator == {subject} 也不入链
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
