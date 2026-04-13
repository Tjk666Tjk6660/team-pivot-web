"""Check inbox: return threads updated after the user's last_read timestamp.

read_state file layout: <workspace>/.pivot-state/read_state_<user_id>.json
{
  "user_id": "...",
  "read_threads": {"<cat>/<slug>": "<iso_time>"},
  "last_sync": "<iso_time>"
}
"""
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
    json.loads(sys.stdin.read())
    ctx = from_env()
    if not ctx.user_id:
        sys.stdout.write(json.dumps({"output": {"unread": []}}))
        return

    read_state_path = (
        Path(ctx.workspace_dir) / ".pivot-state" / f"read_state_{ctx.user_id}.json"
    )
    read_state: dict[str, str] = {}
    if read_state_path.exists():
        try:
            raw = json.loads(read_state_path.read_text(encoding="utf-8"))
            read_state = raw.get("read_threads", {})
        except json.JSONDecodeError:
            read_state = {}

    unread = []
    for t in threads.list_threads(f"{ctx.workspace_dir}/discussions"):
        idx_file = f"{ctx.workspace_dir}/index/{t['slug']}-discuss.index.yaml"
        try:
            idx = index.load(idx_file)
        except Exception:
            continue
        key = f"{t['category']}/{t['slug']}"
        last_read = read_state.get(key, "")
        if idx.last_updated > last_read:
            status = idx.discussions[0].status if idx.discussions else "unknown"
            unread.append(
                {
                    **t,
                    "status": status,
                    "status_display": get_status_display("discuss", status),
                    "last_updated": idx.last_updated,
                }
            )

    sys.stdout.write(json.dumps({"output": {"unread": unread}}))


if __name__ == "__main__":
    main()
