"""Gather all posts of a thread (with author-permission check)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import threads  # noqa: E402
from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    category = payload["input"]["category"]
    thread = payload["input"]["thread"]
    thread_dir = f"{ctx.workspace_dir}/discussions/{category}/{thread}"

    author = threads.get_thread_author(thread_dir)
    if author and author != ctx.user_id:
        raise PermissionError(
            f"Only the thread author ({author}) can summarize this discussion; "
            f"current user is {ctx.user_id}"
        )

    posts = threads.list_posts(thread_dir)
    simplified = [
        {
            "filename": p["filename"],
            "author": p["frontmatter"].get("author", "unknown"),
            "type": p["frontmatter"].get("type", ""),
            "summary": p["frontmatter"].get("summary", ""),
            "body": p["body"],
        }
        for p in posts
    ]

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "thread": thread,
                    "category": category,
                    "posts": simplified,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
