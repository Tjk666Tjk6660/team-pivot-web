"""Status change step. Handles close, pending, reopen."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import git_ops, index  # noqa: E402
from tools.config import from_env, get_status_display  # noqa: E402


ACTION_TO_STATUS = {
    "close": "closed",
    "pending": "pending",
    "reopen": "open",
}


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    inp = payload.get("input", {})
    action = inp.get("action", "")
    category = inp.get("category", "")
    thread = inp.get("thread", "")
    reason = inp.get("reason", "")

    if not action:
        raise ValueError("missing required param: action (close / pending / reopen)")
    if not category or not thread:
        raise ValueError("missing required params: category and thread")

    if action not in ACTION_TO_STATUS:
        raise ValueError(f"Unknown action: {action}")
    if action == "reopen" and not reason:
        raise ValueError("reopen requires a reason")

    target_status = ACTION_TO_STATUS[action]
    index_path = Path(ctx.data_space_dir) / "index" / f"{thread}-discuss.index.yaml"
    idx = index.load(str(index_path))

    discussion_path = f"discussions/{category}/{thread}/"
    entry = next((d for d in idx.discussions if d.path == discussion_path), None)
    if not entry:
        raise ValueError(f"No discussion entry for {discussion_path}")

    prev_state = entry.status
    idx = index.set_status(idx, discussion_path, target_status)

    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    if action == "reopen":
        event = f"reopen by {ctx.user_id}: from {prev_state} (reason: {reason})"
    else:
        event = f"{action} by {ctx.user_id}"
    idx = index.add_timeline_entry(idx, time=now_iso, event=event)
    index.save(idx)

    git_ops.commit(
        ctx.data_space_dir,
        message=f"status: {thread} {prev_state} -> {target_status}",
        paths=[f"index/{thread}-discuss.index.yaml"],
    )
    git_ops.push(ctx.data_space_dir)

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "prev_status": prev_state,
                    "prev_status_display": get_status_display("discuss", prev_state),
                    "new_status": target_status,
                    "new_status_display": get_status_display("discuss", target_status),
                }
            },
        )
    )


if __name__ == "__main__":
    main()
