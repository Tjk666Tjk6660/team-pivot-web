"""Publish step: move draft to canonical path, update INDEX, commit to git."""
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
from tools.atomicity import mark_indexed, write_business_file_pending  # noqa: E402
from tools.config import from_env  # noqa: E402


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    prepare_out = payload["steps"]["prepare"]["output"]

    category = prepare_out["category"]
    title = prepare_out["title"]
    author = prepare_out["author"]
    mention_users = prepare_out.get("mention_users", "")
    mention_comments = prepare_out.get("mention_comments", "")

    repo_path = ctx.workspace_dir
    body = prepare_out.get("content", "")

    summary_text = ""
    gs = payload.get("steps", {}).get("generate_summary", {}).get("output", {})
    summary_text = gs.get("summary", "")
    frontmatter = {
        "type": "proposal",
        "author": author,
        "summary": summary_text,
    }

    thread_dir = Path(repo_path) / "discussions" / category / title
    thread_dir.mkdir(parents=True, exist_ok=True)

    short = threads.ensure_unique_filename_hash(repo_path)
    canonical_name = f"001_{author}_proposal_{short}.md"
    canonical_path = thread_dir / canonical_name

    write_business_file_pending(
        str(canonical_path),
        frontmatter=frontmatter,
        body=body,
    )

    summary_for_index = frontmatter.get("summary", "")

    index_path = Path(repo_path) / "index" / f"{title}-discuss.index.yaml"
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    idx = index.create(
        index_path=str(index_path),
        origin_path=str(thread_dir.relative_to(repo_path).as_posix()) + "/",
        created=now_iso,
    )
    idx = index.add_discussion_entry(
        idx, str(thread_dir.relative_to(repo_path).as_posix()) + "/", "open"
    )
    idx = index.add_file_to_discussion(
        idx,
        discussion_path=str(thread_dir.relative_to(repo_path).as_posix()) + "/",
        file_path=canonical_name,
        summary=summary_for_index,
        refs=[],
    )

    mentions = []
    if mention_users:
        for u in mention_users.split(","):
            mentions.append({"user": u.strip(), "comments": mention_comments})

    idx = index.add_timeline_entry(
        idx,
        time=now_iso,
        event=f"{author} created thread",
        file=str(canonical_path.relative_to(repo_path).as_posix()),
        mentions=mentions,
    )
    index.save(idx)

    mark_indexed(str(canonical_path))

    git_ops.commit(
        repo_path,
        message=f"new thread: {category}/{title} by {author}",
        paths=[
            f"discussions/{category}/{title}/{canonical_name}",
            f"index/{title}-discuss.index.yaml",
        ],
    )
    git_ops.push(repo_path)

    # Phase 1.1: best-effort Feishu notification (spec 3.4)
    _send_publish_notification(
        category=category,
        title=title,
        author=author,
        summary=summary_for_index,
        mention_users=mention_users,
    )

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "committed": True,
                    "canonical_path": str(canonical_path.relative_to(repo_path).as_posix()),
                    "index_file": str(index_path.relative_to(repo_path).as_posix()),
                }
            },
        )
    )


def _send_publish_notification(
    *,
    category: str,
    title: str,
    author: str,
    summary: str,
    mention_users: str,
) -> None:
    """Best-effort Feishu Bot notification. Failures logged and swallowed."""
    try:
        from tools.notify.feishu_bot import FeishuBotAdapter
        from tools.config import build_thread_url

        notifier = FeishuBotAdapter.from_env()
    except Exception as e:
        sys.stderr.write(f"discuss-new: notifier init skipped: {e}\n")
        return

    mention_list = [u.strip() for u in (mention_users or "").split(",") if u.strip()]
    try:
        notifier.send_card_to_all(
            title=f"New thread: {category}/{title}",
            summary=summary or "(no summary)",
            thread_url=build_thread_url(category=category, thread=title),
            author=author,
            mention_names=mention_list or None,
        )
    except Exception as e:
        sys.stderr.write(f"discuss-new: notification failed: {e}\n")


if __name__ == "__main__":
    main()
