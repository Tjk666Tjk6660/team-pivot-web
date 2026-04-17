"""Edit an existing draft."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import load_draft, save_draft, draft_to_dict  # noqa: E402


def _fail(msg: str) -> None:
    sys.stderr.write(f"draft-edit: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})

    draft_id = inp.get("draft_id", "").strip()
    if not draft_id:
        _fail("missing required param: draft_id")

    existing = load_draft(draft_id)
    if not existing:
        _fail(f"draft not found: {draft_id}")

    new_title = (inp.get("title", "") or "").strip() or existing.title
    new_content = inp.get("content", "") or existing.content

    # Keep original draft_id, just overwrite
    updated = save_draft(
        type_=existing.type,
        title=new_title,
        content=new_content,
        thread=existing.thread,
        source=existing.source,
        draft_id=existing.draft_id,
    )

    sys.stdout.write(json.dumps({
        "output": {
            "draft": draft_to_dict(updated),
            "message": f"草稿 {draft_id} 已更新",
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
