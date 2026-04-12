"""Fetch all posts in a thread with thread-level status + display name."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import index, threads  # noqa: E402
from tools.config import from_env, get_status_display  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    category = payload["input"]["category"]
    thread = payload["input"]["thread"]

    thread_dir = f"{ctx.workspace_dir}/discussions/{category}/{thread}"
    posts = threads.list_posts(thread_dir)

    idx_file = f"{ctx.workspace_dir}/index/{thread}-discuss.index.yaml"
    status = "unknown"
    last_updated = ""
    try:
        idx = index.load(idx_file)
        if idx.discussions:
            status = idx.discussions[0].status
        last_updated = idx.last_updated
    except Exception:
        pass

    simplified_posts = [
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
                    "status": status,
                    "status_display": get_status_display("discuss", status),
                    "posts": simplified_posts,
                    "last_updated": last_updated,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
