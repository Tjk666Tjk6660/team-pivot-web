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


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload["input"]
    ctx = from_env()

    draft_path = inp["draft_path"]
    parsed = read_business_file(draft_path)
    has_summary = bool(parsed.frontmatter.get("summary"))

    output = {
        "output": {
            "category": inp["category"],
            "title": inp["title"],
            "content": parsed.body,
            "existing_summary": parsed.frontmatter.get("summary", ""),
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
