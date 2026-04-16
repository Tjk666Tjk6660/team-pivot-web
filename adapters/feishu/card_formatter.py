"""Feishu CardKit v2 adapter for team-pivot pipeline outputs.

Each pipeline type has its own formatter. The Runner calls format_as_card()
after business pipeline completion; the resulting card JSON is returned via
channelData.feishu.card so EC sends it directly without LLM reformatting.

This adapter contains ALL Feishu-specific presentation logic:
  - Card size budgeting (30KB hard limit)
  - Content truncation strategies
  - Markdown table rendering
  - Card UI elements (hr, blocks, buttons, ...)

Business logic (truncate business data, enforce limits, etc.) belongs in
the pipeline layer, not here. Adapters only handle channel-specific
constraints.
"""
from __future__ import annotations

from typing import Any

from tools.config import get_version


# ---------------------------------------------------------------------------
# Feishu card constants
# ---------------------------------------------------------------------------

# Feishu CardKit v2 total payload limit is ~30KB.
# Reserve ~2KB for card structure (header, footer, element wrappers, etc.)
CARD_CONTENT_BUDGET = 28_000

# Per-draft metadata overhead estimate (title + id + timestamp + separators)
DRAFT_META_CHARS = 200

# When truncating content, at least keep this many chars per item
MIN_CONTENT_PER_ITEM = 300


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_as_card(pipeline_name: str, output: dict) -> dict | None:
    """Convert pipeline output to a v2 card. Returns None if no formatter exists."""
    formatter = _FORMATTERS.get(pipeline_name)
    if not formatter:
        return None
    return formatter(output)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _card(title: str, markdown: str, template: str = "blue") -> dict[str, Any]:
    """Build a CardKit v2 card with title, markdown body, and version footer."""
    version = get_version()
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": markdown},
    ]
    if version and version != "unknown":
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"*Team-Pivot v{version}*"})

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {"elements": elements},
    }


def _smart_truncate(text: str, max_chars: int, suffix: str = "\n\n...（内容已截断）") -> str:
    """Truncate text at a paragraph/sentence boundary close to max_chars."""
    if len(text) <= max_chars:
        return text

    # Try to truncate at last newline before max_chars
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars * 0.6:
        # Newline too far back, try last period / sentence end
        for sep in ("。", ".", "！", "!", "？", "?"):
            cut = text.rfind(sep, 0, max_chars)
            if cut >= max_chars * 0.6:
                cut += 1
                break
    if cut < max_chars * 0.6:
        cut = max_chars

    return text[:cut].rstrip() + suffix


# ---------------------------------------------------------------------------
# Per-pipeline formatters
# ---------------------------------------------------------------------------

def _format_discuss_list(output: dict) -> dict:
    threads = output.get("threads", [])
    if not threads:
        return _card("讨论列表", "暂无讨论。")

    rows = ["| # | 类别 | 标题 | 状态 | 最后更新 |", "|---|---|---|---|---|"]
    for i, t in enumerate(threads, 1):
        rows.append(
            f"| {i} | {t.get('category', '')} | {t.get('slug', '')} "
            f"| {t.get('status_display', '')} | {t.get('last_updated', '')[:10]} |"
        )
    return _card("讨论列表", "\n".join(rows))


def _format_draft_list(output: dict) -> dict:
    """Format draft list as a Feishu card, with per-draft content budgeting."""
    drafts = output.get("drafts", [])
    count = output.get("count", len(drafts))
    max_allowed = output.get("max_allowed", 5)

    if not drafts:
        return _card(
            "我的草稿",
            f"当前没有草稿（0/{max_allowed}）。\n\n"
            f"运行 `draft-new` 创建新草稿，或上传 PDF/Word 文件自动转为草稿。",
        )

    # Allocate per-draft content quota: (BUDGET - N*META) / N
    n = len(drafts)
    per_draft_quota = max(
        MIN_CONTENT_PER_ITEM,
        (CARD_CONTENT_BUDGET - n * DRAFT_META_CHARS) // n,
    )

    sections: list[str] = [f"当前有 **{count}/{max_allowed}** 个草稿：\n"]
    for i, d in enumerate(drafts, 1):
        dtype = d.get("type", "proposal")
        type_label = "新讨论" if dtype == "proposal" else "回复"
        thread_info = f" · thread: `{d['thread']}`" if d.get("thread") else ""
        source = d.get("source", "text")
        source_label = f"（来源：{source}）" if source != "text" else ""

        content = d.get("content", "")
        truncated_content = _smart_truncate(content, per_draft_quota)

        section = (
            f"---\n"
            f"**#{i}｜{d.get('title', '(无标题)')}**{source_label}\n\n"
            f"- ID：`{d.get('draft_id', '')}`\n"
            f"- 类型：{type_label} · 分类：`{d.get('category', '')}`"
            f"{thread_info}\n"
            f"- 创建：{d.get('created_at', '')}\n\n"
            f"```\n{truncated_content}\n```"
        )
        sections.append(section)

    sections.append(
        "\n---\n"
        "*发布：`discuss-new` 或 `discuss-reply` + draft_id  ·  "
        "编辑：`draft-edit`  ·  删除：`draft-delete`*"
    )

    return _card("我的草稿", "\n".join(sections))


def _format_draft_read(output: dict) -> dict:
    """Format a single draft's full content."""
    d = output.get("draft") or {}
    if not d:
        return _card("草稿详情", "草稿不存在。", template="red")

    dtype = d.get("type", "proposal")
    type_label = "新讨论" if dtype == "proposal" else "回复"
    thread_info = f"\n- thread：`{d.get('thread', '')}`" if d.get("thread") else ""
    source = d.get("source", "text")

    body = (
        f"**{d.get('title', '(无标题)')}**\n\n"
        f"- ID：`{d.get('draft_id', '')}`\n"
        f"- 类型：{type_label} · 分类：`{d.get('category', '')}`"
        f"{thread_info}\n"
        f"- 来源：{source}\n"
        f"- 创建：{d.get('created_at', '')}\n\n"
        f"---\n\n"
        f"{d.get('content', '')}"
    )
    return _card("草稿详情", body)


def _format_draft_new(output: dict) -> dict:
    d = output.get("draft") or {}
    count = output.get("count", 0)
    max_allowed = output.get("max_allowed", 5)
    body = (
        f"✅ 草稿已创建（**{count}/{max_allowed}**）\n\n"
        f"- ID：`{d.get('draft_id', '')}`\n"
        f"- 标题：{d.get('title', '')}\n"
        f"- 类型：{'回复' if d.get('type') == 'reply' else '新讨论'}\n"
        f"- 分类：`{d.get('category', '')}`\n\n"
        f"---\n\n"
        f"下一步：\n"
        f"- 发布：回复"
        f" `discuss-{'reply' if d.get('type') == 'reply' else 'new'} draft_id={d.get('draft_id', '')}`\n"
        f"- 编辑：回复 `draft-edit draft_id={d.get('draft_id', '')}`\n"
        f"- 删除：回复 `draft-delete draft_id={d.get('draft_id', '')}`"
    )
    return _card("创建草稿", body, template="green")


def _format_check_env(output: dict) -> dict:
    available = output.get("available", [])
    missing = output.get("missing", [])
    if not missing:
        body = "✅ 所有依赖都已安装\n\n" + "\n".join(f"- ✅ `{t}`" for t in available)
        return _card("环境检查", body, template="green")

    lines = [
        f"⚠️ 有 {len(missing)} 个依赖未安装\n",
        "**已安装：**",
    ]
    lines.extend(f"- ✅ `{t}`" for t in available)
    lines.append("\n**缺失：**")
    for m in missing:
        lines.append(
            f"- ❌ `{m['name']}` — {m['purpose']}\n"
            f"  安装：`{m['install_hint']}`"
        )
    return _card("环境检查", "\n".join(lines), template="orange")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_FORMATTERS: dict[str, Any] = {
    "discuss-list": _format_discuss_list,
    "draft-list": _format_draft_list,
    "draft-read": _format_draft_read,
    "draft-new": _format_draft_new,
    "draft-new-from-file": _format_draft_new,   # 相同格式
    "check-env": _format_check_env,
}
