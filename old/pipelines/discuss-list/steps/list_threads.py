"""List all discussions, enriched with status + Chinese display name."""
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
    category = payload["input"].get("category") or None
    discussions_root = f"{ctx.data_space_dir}/discussions"
    found = threads.list_threads(discussions_root, category=category)

    enriched = []
    for t in found:
        idx_file = f"{ctx.data_space_dir}/index/{t['slug']}-discuss.index.yaml"
        status = "unknown"
        last_updated = ""
        summary = ""
        try:
            idx = index.load(idx_file)
            if idx.discussions:
                status = idx.discussions[0].status
                if idx.discussions[0].files:
                    summary = idx.discussions[0].files[-1].summary
            last_updated = idx.last_updated
        except Exception:
            pass
        enriched.append(
            {
                **t,
                "status": status,
                "status_display": get_status_display("discuss", status),
                "last_updated": last_updated,
                "summary": summary,
            }
        )

    sys.stdout.write(json.dumps({"output": {"threads": enriched}}))


if __name__ == "__main__":
    main()
