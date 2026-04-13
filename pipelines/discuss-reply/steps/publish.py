"""Publish step for discuss-reply: append new post to existing thread."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import git_ops, index, threads  # noqa: E402
from tools.atomicity import mark_indexed, read_business_file, write_business_file_pending  # noqa: E402
from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    prepare_out = payload["steps"]["prepare"]["output"]

    category = prepare_out["category"]
    thread = prepare_out["thread"]
    draft_path = prepare_out.get("draft_path", "")
    author = prepare_out["author"]
    mention_users = prepare_out.get("mention_users", "")
    mention_comments = prepare_out.get("mention_comments", "")

    repo_path = ctx.workspace_dir
    thread_dir = Path(repo_path) / "discussions" / category / thread
    if not thread_dir.is_dir():
        raise FileNotFoundError(f"Thread not found: {thread_dir}")

    # Resolve content + frontmatter: draft file mode vs content mode
    if draft_path:
        parsed = read_business_file(draft_path)
        frontmatter = parsed.frontmatter
        body = parsed.body
    else:
        body = prepare_out.get("content", "")
        summary_text = ""
        ws = payload.get("steps", {}).get("write_summary", {}).get("output", {})
        gs = payload.get("steps", {}).get("generate_summary", {}).get("output", {})
        summary_text = ws.get("summary", "") or gs.get("summary", "")
        frontmatter = {
            "type": "reply",
            "author": author,
            "summary": summary_text,
        }

    next_num = threads.next_post_number(str(thread_dir))
    short = threads.ensure_unique_filename_hash(repo_path)
    canonical_name = f"{next_num:03d}_{author}_reply_{short}.md"
    canonical_path = thread_dir / canonical_name

    write_business_file_pending(
        str(canonical_path),
        frontmatter=frontmatter,
        body=body,
    )

    summary_for_index = frontmatter.get("summary", "")

    index_path = Path(repo_path) / "index" / f"{thread}-discuss.index.yaml"
    idx = index.load(str(index_path))
    discussion_rel = f"discussions/{category}/{thread}/"

    idx = index.add_file_to_discussion(
        idx,
        discussion_path=discussion_rel,
        file_path=canonical_name,
        summary=summary_for_index,
        refs=[],
    )

    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    mentions = []
    if mention_users:
        for u in mention_users.split(","):
            mentions.append({"user": u.strip(), "comments": mention_comments})

    idx = index.add_timeline_entry(
        idx,
        time=now_iso,
        event=f"{author} replied",
        file=str(canonical_path.relative_to(repo_path).as_posix()),
        mentions=mentions,
    )
    index.save(idx)

    mark_indexed(str(canonical_path))

    try:
        os.remove(draft_path)
    except OSError:
        pass

    git_ops.commit(
        repo_path,
        message=f"reply: {category}/{thread} #{next_num:03d} by {author}",
        paths=[
            f"discussions/{category}/{thread}/{canonical_name}",
            f"index/{thread}-discuss.index.yaml",
        ],
    )
    git_ops.push(repo_path)

    # Phase 1.1: best-effort Feishu notification (spec 3.4)
    _send_reply_notification(
        category=category,
        thread=thread,
        author=author,
        post_number=next_num,
        summary=summary_for_index,
        mention_users=mention_users,
    )

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "committed": True,
                    "canonical_path": str(
                        canonical_path.relative_to(repo_path).as_posix()
                    ),
                    "post_number": next_num,
                }
            },
        )
    )


def _send_reply_notification(
    *,
    category: str,
    thread: str,
    author: str,
    post_number: int,
    summary: str,
    mention_users: str,
) -> None:
    """Best-effort Feishu notification. Failures logged and swallowed."""
    try:
        from tools.notify.feishu_adapter import FeishuAdapter
        from tools.config import build_thread_url

        notifier = FeishuAdapter.from_env()
    except Exception as e:
        sys.stderr.write(f"discuss-reply: notifier init skipped: {e}\n")
        return

    mention_list = [u.strip() for u in mention_users.split(",") if u.strip()]
    try:
        notifier.send_card(
            title=f"Reply: {category}/{thread} #{post_number:03d}",
            summary=summary or "(no summary)",
            thread_url=build_thread_url(category=category, thread=thread),
            author=author,
            mention_names=mention_list or None,
        )
    except Exception as e:
        sys.stderr.write(f"discuss-reply: notification failed: {e}\n")


if __name__ == "__main__":
    main()
