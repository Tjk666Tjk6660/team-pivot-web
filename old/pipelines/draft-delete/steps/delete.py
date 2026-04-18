"""Delete a draft by id."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import delete_draft  # noqa: E402


def _fail(msg: str) -> None:
    sys.stderr.write(f"draft-delete: {msg}\n")
    sys.exit(1)


def main():
    payload = json.loads(sys.stdin.read())
    draft_id = (payload.get("input", {}).get("draft_id", "") or "").strip()

    if not draft_id:
        _fail("missing required param: draft_id")

    ok = delete_draft(draft_id)
    if not ok:
        _fail(f"draft not found: {draft_id}")

    sys.stdout.write(json.dumps({
        "output": {
            "draft_id": draft_id,
            "message": f"草稿 {draft_id} 已删除",
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
