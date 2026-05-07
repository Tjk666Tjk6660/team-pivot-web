"""Render daily report narratives to Feishu interactive cards (schema 2.0).

设计原则(2026-05-06 演示反馈后重构,2026-05-07 日报视觉微调):
- 飞书部分客户端不稳定支持 `note` / `hr`,所以继续使用单 markdown blob
- 方向标题暂用 markdown 二级标题 + 蓝色字体(`## 一、方向`)放大字号
- 子段标题只加粗序号 + 语义色(`**(1)** 子段`),避免抢过一级方向标题
- 时间窗口和免责声明用 markdown italic 模拟辅助文本

LLM 输出本身零改动(三大死禁 / 跨度稀缺 / owner 中心 / 中文化等),只是
渲染层接收 markdown 后切分成单 markdown 卡片,并加序号视觉装饰。
"""
from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Iterable

from server.daily_report.company_narrate import CompanyNarrative
from server.daily_report.personal_narrate import (
    NO_ACTIVITY_NARRATIVE,
    PersonalNarrative,
)
from server.daily_report.shared_facts import SharedFacts
from server.notify import _card_shell


# --------------------------------------------------------------------------- #
# Visual constants                                                             #
# --------------------------------------------------------------------------- #


# 方向段开头匹配:"第X是 Y。" + 可选剩余内容(可能是子段标题)。
# 不要求方向名以"方向"二字结尾 —— LLM 偶尔写"第二是 enclaws 与 OPC 项目
# 底座。" 没带"方向"二字也合法,识别为方向段标题。
_DIRECTION_HEADER_RE = re.compile(
    r"^第([一二三四五六七八九十])是\s*(.+?)。\s*(.*)$"
)

_DIRECTION_COLOR = "blue"


# --------------------------------------------------------------------------- #
# Markdown post-processing(LLM 输出 → 视觉装饰过的 markdown)                  #
# --------------------------------------------------------------------------- #


def _format_company_summary_for_card(text: str) -> str:
    """把 LLM 输出的公司视角叙事加视觉层次(一级标题 + 二级序号)。

    转换规则:
    1. 方向段开头"第X是 Y 方向。剩余" → ## <font color="blue">X、Y 方向</font>
    2. 子段标题(全角 ":" 结尾) → <font color="...">**(1)** X</font>
    3. 子段下方 ≥ 2 行事项逐行加 "- " 前缀变 markdown bullet list
    4. 普通段落不动

    内容(每个 matter 的事实陈述、跨度判断、把关人具名等)零改动。
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    subsection_index = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ---- 方向段标题 ----
        m = _DIRECTION_HEADER_RE.match(stripped)
        if m:
            ord_zh, direction, rest = m.groups()
            subsection_index = 0
            out.append(f"## {_color_text(f'{ord_zh}、{direction}', _DIRECTION_COLOR)}")
            out.append("")  # 方向标题后总是留空行,与后续子段或正文分开
            i += 1
            if rest:
                if _is_subsection_header(rest.rstrip()):
                    subsection_index += 1
                    out.append(_format_subsection_header(
                        rest.rstrip(),
                        subsection_index,
                    ))
                    i, block_lines = _collect_block(lines, i)
                    out.extend(_bulletize_if_multi(block_lines))
                else:
                    out.append(rest)
            continue

        # ---- 子段标题(全角 ":" 结尾) ----
        if _is_subsection_header(stripped):
            # 上一行非空时插空行,与前一段(子段或正文)分隔
            if out and out[-1].strip():
                out.append("")
            subsection_index += 1
            out.append(_format_subsection_header(line.rstrip(), subsection_index))
            i += 1
            i, block_lines = _collect_block(lines, i)
            out.extend(_bulletize_if_multi(block_lines))
            continue

        # ---- 普通行 ---- 但先尝试识别"行内串接式子段"
        # (LLM 偶尔把多 matter 串一行写成 "X的有:A;B;C。",绕过了换行规则)
        if stripped:
            inline_split = _try_split_inline_subsection(
                stripped,
                subsection_index + 1,
            )
            if inline_split is not None:
                if out and out[-1].strip():
                    out.append("")
                out.extend(inline_split)
                subsection_index += 1
                i += 1
                continue
        out.append(line)
        i += 1

    return "\n".join(out)


def _try_split_inline_subsection(
    stripped: str,
    subsection_index: int | None = None,
) -> list[str] | None:
    """识别行内串接式子段并拆成"(1) 子段头 + bullet list"。

    LLM 偶尔把多个 matter 串成一行(违反 prompt 的"≥4 matter 每行一个"
    规则),典型形态:
        "实施推进与待验收的有:yezaiyongA;terry.taoB;lishuaiC。"

    判定要素:
    1. 行内含全角中文冒号 ":"
    2. 冒号后至少有 2 个全角中文分号 ";"(切分至少 3 项)
    3. 第 1 项前缀(冒号前文本)长度 5-30 字符,符合"业务短语"
       (避免误伤"项目X:Y;Z" 这种非子段语义的句子)

    返回 None 表示不匹配。匹配时返回拆分好的多行(子段头 + 各项)。
    """
    # 找第一个 ":" / "：",前后切分。后续 ":" 算正文一部分
    cut_idx = -1
    for ch in ("：", ":"):
        idx = stripped.find(ch)
        if idx >= 0 and (cut_idx < 0 or idx < cut_idx):
            cut_idx = idx
    if cut_idx < 0:
        return None
    head = stripped[:cut_idx].strip()
    body = stripped[cut_idx + 1:].strip()
    if not (5 <= len(head) <= 30):
        return None
    # 按全角 / 半角分号切分;末项可能带 "。" 句号
    items = [s.strip() for s in re.split(r"[；;]", body) if s.strip()]
    if len(items) < 3:
        return None
    out_lines = [_format_subsection_header(head + "：", subsection_index)]
    for item in items:
        out_lines.append(f"- {item}")
    return out_lines


def _format_subsection_header(
    stripped: str,
    subsection_index: int | None = None,
) -> str:
    """子段标题 → "<font color='...'>**(1)** 文本</font>"。

    去掉行末全角 / 半角冒号。只加粗序号,标题文字用语义色,
    避免二级小节在视觉重量上压过一级方向标题。
    """
    text = stripped.rstrip()
    if text.endswith("：") or text.endswith(":"):
        text = text[:-1].rstrip()
    color = _subsection_color(text)
    if subsection_index is not None and subsection_index >= 1:
        label = f"**({subsection_index})** {text}"
        return _color_text(label, color)
    return f"**{_color_text(text, color)}**"


def _color_text(text: str, color: str) -> str:
    """Apply Feishu markdown font color to short headings.

    If a Feishu client ignores `<font>`, the original markdown heading/bold
    still preserves the visual hierarchy.
    """
    return f'<font color="{color}">{text}</font>'


def _subsection_color(text: str) -> str:
    """Choose a restrained semantic color for subsection headings only."""
    if any(k in text for k in ("需要关注", "需关注", "待关注", "风险", "失败", "未过", "卡住", "暂停")):
        return "red"
    if any(k in text for k in ("完成", "完毕", "收口", "闭环", "通过", "定稿", "落地")):
        return "green"
    if any(k in text for k in ("待验证", "验收", "评审", "确认")):
        return "orange"
    return "blue"


def _known_pinyins(facts: SharedFacts) -> tuple[str, ...]:
    """Known pinyin names that may appear in AI-generated daily-report text."""
    names: set[str] = set()
    for ua in facts.user_activities:
        if ua.pinyin:
            names.add(ua.pinyin)
    for m in facts.top_active_matters:
        names.update(p for p in m.participants if p)
    # Longest first prevents partial replacement when one pinyin prefixes another.
    return tuple(sorted(names, key=len, reverse=True))


def _bold_known_pinyins(text: str, pinyins: Iterable[str]) -> str:
    """Bold known pinyin names in free text without touching already-bold names."""
    out = text
    for p in pinyins:
        escaped = re.escape(p)
        out = re.sub(
            rf"(?<![A-Za-z0-9_.*])({escaped})(?![A-Za-z0-9_.*])",
            r"**\1**",
            out,
        )
    return out


def _is_subsection_header(stripped: str) -> bool:
    """子段标题判定:行尾全角 "：" 或半角 ":"。

    LLM 在中文叙事里压倒性偏好全角,但偶尔切换成半角("进入实施或待
    验收的有:"),实测两种都出现。两种都识别更 robust,误伤风险极低
    (普通中文段落几乎不以 ":" 结尾)。
    """
    if not stripped:
        return False
    return stripped.endswith("：") or stripped.endswith(":")


def _collect_block(lines: list[str], start: int) -> tuple[int, list[str]]:
    """从 start 起收集连续非空行,直到遇到空行 / 子段头 / 方向头 / 文件结束。

    遇到下一个子段头(:结尾)或方向头(第X是 Y。)也要提前停 —— 否则 LLM 在
    上一个 list 末尾紧贴一个新子段头(没插空行)时,新子段头会被吞进当前
    list 当成 item。返回新 i 和块。
    """
    block: list[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            break   # 空行
        if _is_subsection_header(stripped):
            break   # 下一个子段头
        if _DIRECTION_HEADER_RE.match(stripped):
            break   # 下一个方向头
        block.append(lines[i])
        i += 1
    return i, block


def _bulletize_if_multi(block: list[str]) -> list[str]:
    """块行数 ≥ 2 时,每行加 "- " 前缀;≤ 1 行时原样返回。

    ≤ 1 行的情况通常是 ≤3 matter 子段(LLM 用句号/分号在同一段串接),
    单点 bullet 没意义反而难看。
    """
    if len(block) < 2:
        return block
    return [f"- {b.strip()}" for b in block]


# --------------------------------------------------------------------------- #
# Section splitter:把 formatted markdown 切成"开场 / 各方向 / 收尾"            #
# --------------------------------------------------------------------------- #


def _split_into_card_sections(formatted: str) -> dict[str, list[str] | str]:
    """切分后处理过的 markdown 成卡片用的逻辑段落。

    returns {
        "opening": str,        # 开场段(到第一个方向标题之前的所有非空内容)
        "directions": list[str],  # 每个方向一段独立 markdown 文本
        "closing": str,        # 收尾段(最后一个方向之后的内容)
    }

    切分点是 "## <font color=\"blue\">一、X</font>" / "## 二、X" 这种方向行
    (_format_company_summary_for_card 已把方向标题转换成这个形态)。
    """
    blocks: list[str] = []
    direction_indices: list[int] = []   # 方向行在 blocks 列表里的下标

    # 把 formatted 按 "段落"(双换行分隔)切。每段一个 block。
    for raw in re.split(r"\n\s*\n", formatted.strip()):
        if not raw.strip():
            continue
        blocks.append(raw.rstrip())
        # 段首行匹配方向标题模式(markdown 二级标题 + 中文序号)
        first_line = raw.split("\n", 1)[0].strip()
        if re.match(
            r"^##\s+(?:<font color=\"[a-z]+\">)?[一二三四五六七八九十]、.+",
            first_line,
        ):
            direction_indices.append(len(blocks) - 1)

    if not direction_indices:
        # 没有方向标题(异常情况,比如 LLM 输出非常短) — 整段当 opening
        return {"opening": "\n\n".join(blocks), "directions": [], "closing": ""}

    # 开场 = 第一个方向之前的所有 blocks
    opening = "\n\n".join(blocks[: direction_indices[0]]).strip()

    # 每个方向 = 从该方向行到下一个方向行(或末尾)之间的 blocks 拼起来
    directions: list[str] = []
    for k, start in enumerate(direction_indices):
        end = direction_indices[k + 1] if k + 1 < len(direction_indices) else len(blocks)
        directions.append("\n\n".join(blocks[start:end]).strip())

    # 收尾 = 最后一个方向块里如果有"团队今日 X 人 / Y 个事项"这种总结句,
    # 已经包在最后那个 directions[-1] 里了。这里 closing 留空。
    # (老板反馈让收尾段跟最后一个方向一起渲染,不另起一段更紧凑。)
    closing = ""

    return {"opening": opening, "directions": directions, "closing": closing}


def _company_compact_markdown(formatted: str) -> str:
    """Feishu push version: short executive note, not the full report."""
    sections = _split_into_card_sections(formatted)
    opening = str(sections["opening"]).strip() or _first_meaningful_line(formatted)
    attention = _attention_lines(formatted, limit=3)

    parts = [
        _compact_heading("今日概况", "blue"),
        "",
        opening or "今日日报已生成,完整方向明细请查看页面版。",
        "",
        "---",
        "",
        _compact_heading("需要关注", "red"),
        "",
    ]
    if attention:
        parts.extend(attention)
    else:
        parts.append("- 暂无明显阻塞,完整方向明细请查看页面版。")
    parts.extend([
        "",
        "---",
        "",
        "_完整方向明细、事项列表和人员动作请查看完整日报。_",
    ])
    return "\n".join(parts).rstrip()


def _personal_compact_markdown(
    entries,
    *,
    active_count: int,
    inactive_count: int,
    pinyins: Iterable[str],
) -> str:
    active = [e for e in entries if e.has_activity]
    parts = [
        _compact_heading("团队动态摘要", "blue"),
        "",
        f"今日有 **{active_count}** 人产生输入或输出,**{inactive_count}** 人暂无记录。",
        "",
        "---",
        "",
        _compact_heading("重点人员动态", "green"),
        "",
    ]
    if active:
        for e in active[:3]:
            narrative = _bold_known_pinyins(e.narrative, pinyins)
            parts.append(f"- **{e.pinyin}**: {_truncate_text(narrative, 72)}")
        if len(active) > 3:
            parts.append(f"- 另有 **{len(active) - 3}** 人动态请查看完整日报。")
    else:
        parts.append("- 今日团队成员在 Pivot 上均无任何输入和输出。")
    parts.extend([
        "",
        "---",
        "",
        "_完整人员明细和无记录名单请查看完整日报。_",
    ])
    return "\n".join(parts).rstrip()


def _attention_lines(formatted: str, *, limit: int) -> list[str]:
    out: list[str] = []
    keywords = ("需要关注", "需关注", "待关注", "风险", "失败", "未过", "卡住", "暂停")
    for raw in formatted.splitlines():
        line = raw.strip()
        if not line or line.startswith("## ") or line == "---":
            continue
        plain = _strip_outline_number(
            _strip_inline_markup(line).lstrip("- ").strip()
        )
        if any(k in plain for k in keywords):
            out.append(f"- {_color_text(plain, 'red')}")
        if len(out) >= limit:
            break
    return out


def _compact_heading(text: str, color: str) -> str:
    return f"## {_color_text(text, color)}"


def _first_meaningful_line(text: str) -> str:
    for raw in text.splitlines():
        line = _strip_inline_markup(raw).strip()
        if line and line != "---" and not line.startswith("## "):
            return line
    return ""


def _strip_inline_markup(text: str) -> str:
    return re.sub(r"<font color=\"[^\"]+\">(.*?)</font>", r"\1", text).replace("**", "")


def _strip_outline_number(text: str) -> str:
    return re.sub(r"^\(\d+\)\s*", "", text).strip()


def _truncate_text(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Company-view card                                                            #
# --------------------------------------------------------------------------- #


def build_company_card(
    facts: SharedFacts,
    narrative: CompanyNarrative,
    *,
    report_url: str | None = None,
    compact: bool = False,
) -> dict:
    """飞书交互卡片字典,直接给 FeishuNotifier.broadcast_card。

    Schema 2.0 的 element 类型在不同飞书客户端版本支持度不一致(`note` /
    `hr` 元素被某些版本 reject 成 200861 错误)。最稳的做法是把所有视觉
    层次都做进**单个 markdown blob**:
    - markdown italic `_..._` 模拟"小灰字辅助文本"(替代 note)
    - markdown 水平线 `---`(替代 hr 元素)
    - ## 一、X 给方向分组并放大标题
    - **(1)** X + bullet list 做子段层次

    布局:
      header bar:📊 公司日报 · M-D
      _📅 时间窗口_                  (markdown italic)
      ---
      开场一句 + 方向段落,段落间空行 / `---` 分隔
      ---
      _本日报由 AI..._               (markdown italic)
    """
    s = facts.summary
    template = "blue" if narrative.status == "ai" else "wathet"
    header = f"📊 公司日报 · {_fmt_window(s.window.since, s.window.until)}"

    parts: list[str] = []

    # 2. 主体内容
    if narrative.status == "ai":
        formatted = _format_company_summary_for_card(narrative.summary)
        formatted = _bold_known_pinyins(formatted, _known_pinyins(facts))
        if compact:
            parts.append(_company_compact_markdown(formatted))
            return _card_shell(
                header=header,
                template=template,
                markdown="\n".join(parts).rstrip(),
                button_text="查看完整日报" if report_url else None,
                thread_url=report_url,
            )
        else:
            sections = _split_into_card_sections(formatted)
            chunks: list[str] = []
            if sections["opening"]:
                chunks.append(sections["opening"])
            chunks.extend(sections["directions"])
            if sections["closing"]:
                chunks.append(sections["closing"])
            # 各 chunk 间用 "---" 水平线分隔(段落空行 + hr 双重视觉断层)
            parts.append("\n\n---\n\n".join(chunks))
    else:
        parts.append(narrative.summary)

    # 3. Fallback 提示
    if narrative.status == "fallback":
        parts.append("")
        parts.append(
            f"_(AI 公司视角生成失败,以上仅展示统计"
            f"{'。原因:' + narrative.fallback_reason if narrative.fallback_reason else ''})_"
        )

    # 4. 免责声明 italic
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("_本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论。_")

    return _card_shell(
        header=header,
        template=template,
        markdown="\n".join(parts).rstrip(),
        button_text="查看完整日报" if report_url else None,
        thread_url=report_url,
    )


# --------------------------------------------------------------------------- #
# Personal-view card                                                           #
# --------------------------------------------------------------------------- #


def build_personal_card(
    facts: SharedFacts,
    narrative: PersonalNarrative,
    *,
    report_url: str | None = None,
    compact: bool = False,
) -> dict:
    """飞书交互卡片字典,Phase 4 个人视角报告。

    Schema 2.0 的 note / hr element 在飞书部分版本不可用(reject 200861),
    所以用单 markdown blob + 内部 markdown 语法做视觉层次。

    布局:
      header bar:    👥 个人日报 · M-D
      _📅 时间窗口_              (italic 小字)
      ---
      **👥 团队动态**
      - **pinyin**: narrative ...
      ---
      _无活动_:names             (inactive 合并行)
      ---
      _本日报..._                (免责声明 italic)
    """
    s = facts.summary
    template = "blue" if narrative.status == "ai" else "wathet"
    header = f"👥 个人日报 · {_fmt_window(s.window.since, s.window.until)}"

    parts: list[str] = []

    active = [e for e in narrative.entries if e.has_activity]
    inactive = [e for e in narrative.entries if not e.has_activity]
    entry_pinyins = tuple(e.pinyin for e in narrative.entries if e.pinyin)
    pinyins = tuple(dict.fromkeys((*_known_pinyins(facts), *entry_pinyins)))

    if compact:
        parts.append(_personal_compact_markdown(
            narrative.entries,
            active_count=len(active),
            inactive_count=len(inactive),
            pinyins=pinyins,
        ))
        return _card_shell(
            header=header,
            template=template,
            markdown="\n".join(parts).rstrip(),
            button_text="查看完整日报" if report_url else None,
            thread_url=report_url,
        )

    if narrative.status == "no_active_users":
        parts.append("**🌙 团队动态**")
        parts.append("")
        parts.append("今日团队成员在 Pivot 上均无任何输入和输出。")
    else:
        parts.append("**👥 团队动态**")
        parts.append("")
        for e in active:
            # pinyin 而非 display_name(memory: feedback_daily_report_use_pinyin_only)
            narrative_text = _bold_known_pinyins(e.narrative, pinyins)
            parts.append(f"- **{e.pinyin}**: {narrative_text}")
        if inactive:
            names = "、".join(f"**{e.pinyin}**" for e in inactive)
            parts.append("")
            parts.append("---")
            parts.append("")
            parts.append(f"_{NO_ACTIVITY_NARRATIVE}_:{names}")

    # Fallback 提示
    if narrative.status == "fallback":
        parts.append("")
        parts.append(
            f"_(AI 个人视角生成失败"
            f"{'。原因:' + narrative.fallback_reason if narrative.fallback_reason else ''})_"
        )

    # 免责声明
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(
        "_本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论;不用于绩效评价。_"
    )

    return _card_shell(
        header=header,
        template=template,
        markdown="\n".join(parts).rstrip(),
        button_text="查看完整日报" if report_url else None,
        thread_url=report_url,
    )


# --------------------------------------------------------------------------- #
# v2 admin alert card(漏跑 / 失败通知)                                       #
# --------------------------------------------------------------------------- #


def build_admin_alert_card(
    *,
    alert_type: str,                        # "missed" | "failed"
    job_name: str,
    job_view: str,
    expected_at: datetime | None = None,    # missed 用
    error: str | None = None,               # failed 用
    retry_count: int | None = None,         # failed 用
    failures: list[dict] | None = None,     # failed 用,每条 {to, error, name?}
) -> dict:
    """系统级告警卡:发到 admin_notify_chat_ids/open_ids 或 fallback 全部 bot 群。

    模板 'red'(若飞书不支持则 fallback 'wathet')使其与日常日报卡视觉
    显著区分。
    """
    if alert_type == "missed":
        header = f"⚠️ 日报漏跑提醒 · {job_name}"
        lines = [
            f"**任务**:{job_name}",
            f"**视角**:{job_view}",
        ]
        if expected_at:
            lines.append(f"**预期运行**:{_fmt_dt(expected_at)}")
        lines.append("")
        lines.append("已超过 30 分钟仍未运行,**未自动补跑**。")
        lines.append("")
        lines.append("请管理员检查:")
        lines.append("- 主服务是否在该时间段重启过")
        lines.append("- jobs 配置是否需要调整")
        lines.append("- 可在 `/admin → 日报配置` 立即手动触发补一次")
        body = "\n".join(lines)
    elif alert_type == "failed":
        header = f"⚠️ 日报失败提醒 · {job_name}"
        lines = [
            f"**任务**:{job_name}",
            f"**视角**:{job_view}",
        ]
        if retry_count is not None:
            lines.append(f"**重试**:{retry_count} 次后仍失败")
        if error:
            lines.append("")
            lines.append(f"**错误**:`{error[:200]}`")
        if failures:
            lines.append("")
            lines.append("**未送达明细**:")
            # 最多列前 8 条避免卡片过长;剩余作为 "+N more" 收尾
            for f in failures[:8]:
                lines.append(_format_failure_line(f))
            if len(failures) > 8:
                lines.append(f"- … 另 {len(failures) - 8} 条未列出")
        lines.append("")
        lines.append("请管理员检查:")
        lines.append("- 飞书目标 ID(open_id / chat_id)是否正确、bot 是否仍在该群 / 该用户对话内")
        lines.append("- 飞书 token 是否正常")
        lines.append("- AI 端点是否可用(超时 / 限流 / Key 失效)")
        lines.append("- 数据仓库 workspace 是否正常")
        body = "\n".join(lines)
    else:
        header = f"⚠️ 日报告警 · {job_name}"
        body = f"alert_type={alert_type}"

    return _card_shell(
        header=header,
        template="wathet",                  # 飞书 schema 2.0 安全色;red 在部分版本不支持
        markdown=body,
    )


def _format_failure_line(f: dict) -> str:
    """单条失败明细行。形如 '- 邓柯 (`ou_xxx`) — feishu_230015: receive_id invalid'"""
    to = f.get("to") or "?"
    name = f.get("name")
    err = (f.get("error") or "?")[:140]
    if name:
        return f"- {name} (`{to}`) — {err}"
    return f"- `{to}` — {err}"


# --------------------------------------------------------------------------- #
# format helpers                                                              #
# --------------------------------------------------------------------------- #


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _fmt_window(since: datetime, until: datetime) -> str:
    return f"{_fmt_dt(since)} → {_fmt_dt(until)}"
