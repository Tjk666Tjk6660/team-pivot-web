"""Update the user's read_state for the given thread."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    fetched = payload["steps"]["fetch_posts"]["output"]
    category = fetched["category"]
    thread = fetched["thread"]
    last_updated = fetched["last_updated"] or datetime.now(timezone.utc).astimezone().isoformat()

    if not ctx.user_id:
        sys.stdout.write(json.dumps({"output": {"marked": False}}, ensure_ascii=False))
        return

    state_dir = Path(ctx.workspace_dir) / ".pivot-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"read_state_{ctx.user_id}.json"

    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    else:
        state = {}
    state.setdefault("user_id", ctx.user_id)
    read_threads = state.setdefault("read_threads", {})
    read_threads[f"{category}/{thread}"] = last_updated
    state["last_sync"] = datetime.now(timezone.utc).astimezone().isoformat()

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.stdout.write(json.dumps({"output": {"marked": True}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
