"""Read full content of a single draft."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import draft_to_dict, load_draft  # noqa: E402


def _fail(msg: str) -> None:
    sys.stderr.write(f"draft-read: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    draft_id = (payload.get("input", {}).get("draft_id", "") or "").strip()

    if not draft_id:
        _fail("missing required param: draft_id")

    d = load_draft(draft_id)
    if not d:
        _fail(f"草稿不存在: {draft_id}")

    sys.stdout.write(json.dumps({
        "output": {
            "draft": draft_to_dict(d),
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
