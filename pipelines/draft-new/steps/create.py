"""Create a new draft file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import (  # noqa: E402
    DraftLimitExceeded,
    MAX_DRAFTS_PER_USER,
    draft_to_dict,
    list_drafts,
    save_draft,
)


def _fail(msg: str) -> None:
    sys.stderr.write(f"draft-new: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})

    type_ = inp.get("type", "").strip().lower() or "proposal"
    category = inp.get("category", "").strip()
    title = inp.get("title", "").strip()
    content = inp.get("content", "")
    thread = inp.get("thread", "").strip() or None

    if type_ not in ("proposal", "reply"):
        _fail(f"invalid type: {type_!r} (must be 'proposal' or 'reply')")
    if not category:
        _fail("missing required param: category")
    if not title:
        _fail("missing required param: title")
    if not content.strip():
        _fail("missing required param: content")
    if type_ == "reply" and not thread:
        _fail("type=reply requires 'thread'")

    try:
        draft = save_draft(
            type_=type_,
            category=category,
            title=title,
            content=content,
            thread=thread,
        )
    except DraftLimitExceeded as e:
        _fail(str(e))
    except Exception as e:
        _fail(str(e))

    count = len(list_drafts())
    sys.stdout.write(json.dumps({
        "output": {
            "draft": draft_to_dict(draft),
            "count": count,
            "max_allowed": MAX_DRAFTS_PER_USER,
            "message": f"草稿已创建（ID: {draft.draft_id}，{count}/{MAX_DRAFTS_PER_USER}）",
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
