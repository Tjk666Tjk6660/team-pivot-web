"""Prepare step for discuss-reply: load draft, validate, and pass content through."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.config import from_env  # noqa: E402
from tools.drafts import load_draft  # noqa: E402


def _fail(msg: str) -> None:
    sys.stderr.write(f"prepare: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})
    ctx = from_env()

    draft_id = (inp.get("draft_id", "") or "").strip()
    if not draft_id:
        _fail(
            "missing required param: draft_id\n"
            "必须先创建回复草稿（draft-new type=reply 或 draft-new-from-file），"
            "再用草稿 ID 发布回复。"
        )

    draft = load_draft(draft_id)
    if not draft:
        _fail(
            f"草稿不存在: {draft_id}\n"
            f"运行 draft-list 查看你的草稿列表。"
        )

    if draft.type != "reply":
        _fail(
            f"草稿类型不匹配: 期望 'reply'，实际 '{draft.type}'。\n"
            f"此草稿是为发起新讨论准备的，请用 discuss-new 发布。"
        )

    if not draft.thread:
        _fail(f"回复草稿缺少 thread 字段: {draft_id}")

    output = {
        "output": {
            "draft_id": draft.draft_id,
            "category": draft.category,
            "thread": draft.thread,
            "content": draft.content,
            "has_summary": False,
            "author": ctx.user_id or "unknown",
            "mention_users": inp.get("mention_users", ""),
            "mention_comments": inp.get("mention_comments", ""),
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
