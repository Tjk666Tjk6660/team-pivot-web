"""Prepare step: read the draft file and extract metadata."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.atomicity import read_business_file  # noqa: E402
from tools.config import from_env  # noqa: E402


def _error(msg: str) -> None:
    sys.stdout.write(json.dumps({"output": {"error": msg}}, ensure_ascii=False))


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})
    ctx = from_env()

    category = inp.get("category", "")
    title = inp.get("title", "")
    if not category or not title:
        return _error("缺少必填参数 category 或 title")

    draft_path = inp.get("draft_path", "")
    content = inp.get("content", "")

    if draft_path:
        parsed = read_business_file(draft_path)
        body = parsed.body
        has_summary = bool(parsed.frontmatter.get("summary"))
        existing_summary = parsed.frontmatter.get("summary", "")
    elif content:
        body = content
        has_summary = False
        existing_summary = ""
    else:
        return _error("缺少 draft_path 或 content，至少提供其中之一")

    output = {
        "output": {
            "category": category,
            "title": title,
            "content": body,
            "existing_summary": existing_summary,
            "has_summary": has_summary,
            "draft_path": draft_path,
            "author": ctx.user_id or "unknown",
            "mention_users": inp.get("mention_users", ""),
            "mention_comments": inp.get("mention_comments", ""),
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
