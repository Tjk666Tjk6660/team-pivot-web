"""Prepare step: validate input and pass content through."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

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
    content = inp.get("content", "")

    if not category or not title:
        _fail("missing required params: category and title")
    if not content:
        _fail("missing required param: content")

    output = {
        "output": {
            "category": category,
            "title": title,
            "content": content,
            "has_summary": False,
            "author": ctx.user_id or "unknown",
            "mention_users": inp.get("mention_users", ""),
            "mention_comments": inp.get("mention_comments", ""),
        }
    }
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
