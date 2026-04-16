"""Format pipeline output as Feishu CardKit v2 card JSON.

Each pipeline type has its own formatter. The Runner calls format_as_card()
after business pipeline completion; the resulting card JSON is returned via
channelData.feishu.card so EC sends it directly without LLM reformatting.
"""
from __future__ import annotations

from typing import Any

from tools.config import get_version


def format_as_card(pipeline_name: str, output: dict) -> dict | None:
    """Convert pipeline output to a v2 card. Returns None if no formatter exists."""
    formatter = _FORMATTERS.get(pipeline_name)
    if not formatter:
        return None
    return formatter(output)


def _card(title: str, markdown: str) -> dict[str, Any]:
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
            "template": "blue",
        },
        "body": {"elements": elements},
    }


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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_FORMATTERS: dict[str, Any] = {
    "discuss-list": _format_discuss_list,
}
