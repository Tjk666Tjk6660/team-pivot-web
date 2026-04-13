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


def _fail(msg: str) -> None:
    sys.stderr.write(f"prepare: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})
    ctx = from_env()

    category = inp.get("category", "")
    title = inp.get("title", "")
    if not category or not title:
        _fail("missing required params: category and title")

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
        _fail("missing draft_path or content, at least one is required")

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
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
