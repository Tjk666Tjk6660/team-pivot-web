"""List all drafts for the current user.

Returns the full canonical data for all drafts (no truncation). Channel
adapters are responsible for applying display-specific limits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import MAX_DRAFTS_PER_USER, draft_to_dict, list_drafts  # noqa: E402


def main():
    json.loads(sys.stdin.read())

    drafts = list_drafts()
    sys.stdout.write(json.dumps({
        "output": {
            "drafts": [draft_to_dict(d) for d in drafts],
            "count": len(drafts),
            "max_allowed": MAX_DRAFTS_PER_USER,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
