"""Cleanup step: delete the draft after successful reply publish."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import delete_draft  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    prepare = payload.get("steps", {}).get("prepare", {}).get("output", {})
    draft_id = prepare.get("draft_id", "")

    deleted = False
    if draft_id:
        try:
            deleted = delete_draft(draft_id)
        except Exception:
            deleted = False

    sys.stdout.write(json.dumps({
        "output": {
            "draft_id": draft_id,
            "deleted": deleted,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
