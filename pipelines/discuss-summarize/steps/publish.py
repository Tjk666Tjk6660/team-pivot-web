"""Write SUMMARY.md into the thread dir and commit."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import git_ops, index  # noqa: E402
from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    gather_out = payload["steps"]["gather"]["output"]
    category = gather_out["category"]
    thread = gather_out["thread"]
    summary_text = payload["steps"]["generate_summary"]["output"]["summary"]

    repo_path = ctx.workspace_dir
    thread_dir = Path(repo_path) / "discussions" / category / thread
    summary_path = thread_dir / "SUMMARY.md"
    summary_path.write_text(summary_text, encoding="utf-8")

    index_path = Path(repo_path) / "index" / f"{thread}-discuss.index.yaml"
    if index_path.exists():
        idx = index.load(str(index_path))
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        idx = index.add_timeline_entry(
            idx,
            time=now_iso,
            event=f"{ctx.user_id} generated SUMMARY",
            file=str(summary_path.relative_to(repo_path).as_posix()),
        )
        index.save(idx)

    git_ops.commit(
        repo_path,
        message=f"summary: {category}/{thread} by {ctx.user_id}",
        paths=[
            f"discussions/{category}/{thread}/SUMMARY.md",
            f"index/{thread}-discuss.index.yaml",
        ],
    )
    git_ops.push(repo_path)

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "summary_path": str(summary_path.relative_to(repo_path).as_posix()),
                    "committed": True,
                }
            },
        )
    )


if __name__ == "__main__":
    main()
