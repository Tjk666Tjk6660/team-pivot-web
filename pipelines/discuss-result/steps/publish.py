"""Write RESULT_<hash>.md, transition status to concluded, commit."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import git_ops, index, threads  # noqa: E402
from tools.atomicity import mark_indexed, write_business_file_pending  # noqa: E402
from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    gather_out = payload["steps"]["gather"]["output"]
    category = gather_out["category"]
    thread = gather_out["thread"]
    result_body = payload["steps"]["generate_result"]["output"]["result_body"]

    repo_path = ctx.workspace_dir
    thread_dir = Path(repo_path) / "discussions" / category / thread

    short = threads.ensure_unique_filename_hash(repo_path)
    result_name = f"RESULT_{short}.md"
    result_path = thread_dir / result_name

    frontmatter = {
        "type": "result",
        "author": ctx.user_id or "unknown",
        "summary": "讨论结论",
    }
    write_business_file_pending(str(result_path), frontmatter=frontmatter, body=result_body)

    index_path = Path(repo_path) / "index" / f"{thread}-discuss.index.yaml"
    idx = index.load(str(index_path))
    discussion_rel = f"discussions/{category}/{thread}/"
    idx = index.add_file_to_discussion(
        idx,
        discussion_path=discussion_rel,
        file_path=result_name,
        summary="结论",
        refs=[],
    )
    idx = index.set_status(idx, discussion_rel, "concluded")

    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    idx = index.add_timeline_entry(
        idx,
        time=now_iso,
        event=f"{ctx.user_id} 生成 RESULT（状态 -> concluded）",
        file=str(result_path.relative_to(repo_path).as_posix()),
    )
    index.save(idx)

    mark_indexed(str(result_path))

    git_ops.commit(
        repo_path,
        message=f"result: {category}/{thread} concluded by {ctx.user_id}",
        paths=[
            f"discussions/{category}/{thread}/{result_name}",
            f"index/{thread}-discuss.index.yaml",
        ],
    )
    git_ops.push(repo_path)

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "result_path": str(result_path.relative_to(repo_path).as_posix()),
                    "status": "concluded",
                    "committed": True,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
