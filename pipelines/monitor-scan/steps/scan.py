"""Monitor scan: detect issues and push notifications.

Per 004 6.2 and 8.1, Phase 1 performs:
  1. un-indexed file detection and idempotent recovery
  2. stale-open thread detection
  3. un-replied mention detection (48h default)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools import index  # noqa: E402
from tools.atomicity import find_un_indexed_files, mark_indexed, read_business_file  # noqa: E402
from tools.config import from_env  # noqa: E402


def _try_recover_un_indexed(workspace: Path, business_file: str) -> bool:
    """Attempt idempotent recovery for a file stuck at index_state=un-indexed."""
    path = Path(business_file)
    try:
        parsed = read_business_file(business_file)
    except Exception:
        return False

    try:
        rel = path.relative_to(workspace)
        parts = rel.parts
        if len(parts) < 4 or parts[0] != "discussions":
            return False
        category, thread = parts[1], parts[2]
    except ValueError:
        return False

    idx_path = workspace / "index" / f"{thread}-discuss.index.yaml"
    if not idx_path.exists():
        return False

    idx = index.load(str(idx_path))
    discussion_rel = f"discussions/{category}/{thread}/"
    entry = next((d for d in idx.discussions if d.path == discussion_rel), None)
    if not entry:
        return False

    file_name = path.name
    if not any(f.path == file_name for f in entry.files):
        idx = index.add_file_to_discussion(
            idx,
            discussion_path=discussion_rel,
            file_path=file_name,
            summary=parsed.frontmatter.get("summary", ""),
            refs=[],
        )
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        idx = index.add_timeline_entry(
            idx,
            time=now_iso,
            event=f"recovery: re-indexed {file_name} after crash",
            file=str(path.relative_to(workspace).as_posix()),
        )
        index.save(idx)

    mark_indexed(business_file)
    return True


def _check_un_replied_mentions(
    idx: "index.IndexFile",
    workspace: Path,
    mention_window: timedelta,
    now: datetime,
) -> list[dict]:
    """Flag mentions whose target user hasn't replied within the window."""
    flagged: list[dict] = []
    for entry in idx.timeline:
        if not entry.mentions:
            continue
        try:
            mention_time = datetime.fromisoformat(entry.time)
        except ValueError:
            continue
        if (now - mention_time) < mention_window:
            continue
        if not idx.discussions:
            continue
        thread_rel = idx.discussions[0].path
        thread_dir = workspace / thread_rel
        if not thread_dir.is_dir():
            continue
        for mention in entry.mentions:
            user = mention.get("user")
            if not user:
                continue
            has_replied = False
            for post_file in thread_dir.glob("*.md"):
                parts = post_file.stem.split("_")
                if len(parts) < 2:
                    continue
                post_author = parts[1]
                if post_author != user:
                    continue
                try:
                    parsed = read_business_file(str(post_file))
                    post_time_str = parsed.frontmatter.get("created", "")
                    if post_time_str and datetime.fromisoformat(str(post_time_str)) > mention_time:
                        has_replied = True
                        break
                except Exception:
                    continue
            if not has_replied:
                flagged.append(
                    {
                        "thread": thread_rel,
                        "mentioned_user": user,
                        "mention_time": entry.time,
                        "comments": mention.get("comments", ""),
                    }
                )
    return flagged


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    window = int(payload["input"].get("window_hours") or 24)
    mention_window_hours = int(payload["input"].get("mention_window_hours") or 48)

    workspace = Path(ctx.workspace_dir)
    now = datetime.now(timezone.utc).astimezone()
    stale_threshold = now - timedelta(hours=window)
    mention_window = timedelta(hours=mention_window_hours)

    issues: dict[str, list] = {
        "un_indexed_recovered": [],
        "unrecoverable": [],
        "stale_open_threads": [],
        "un_replied_mentions": [],
    }

    discussions_root = workspace / "discussions"
    if discussions_root.is_dir():
        for f in find_un_indexed_files(str(discussions_root)):
            if _try_recover_un_indexed(workspace, f):
                issues["un_indexed_recovered"].append(f)
            else:
                issues["unrecoverable"].append(f)

    index_dir = workspace / "index"
    if index_dir.is_dir():
        for idx_file in index_dir.glob("*-discuss.index.yaml"):
            try:
                idx = index.load(str(idx_file))
            except Exception:
                continue
            try:
                last = datetime.fromisoformat(idx.last_updated)
            except ValueError:
                last = None
            if last and last < stale_threshold:
                for d in idx.discussions:
                    if d.status == "open":
                        issues["stale_open_threads"].append(
                            {
                                "thread": idx_file.stem.replace("-discuss.index", ""),
                                "last_updated": idx.last_updated,
                            }
                        )
            issues["un_replied_mentions"].extend(
                _check_un_replied_mentions(idx, workspace, mention_window, now)
            )

    # Phase 1.1: actual notifier wiring (spec 5.3)
    notifications_sent = _send_notifications(
        issues=issues,
        window_hours=window,
        mention_window_hours=mention_window_hours,
    )

    sys.stdout.write(
        json.dumps(
            {
                "output": {
                    "un_indexed_recovered_count": len(issues["un_indexed_recovered"]),
                    "unrecoverable_count": len(issues["unrecoverable"]),
                    "stale_open_threads_count": len(issues["stale_open_threads"]),
                    "un_replied_mentions_count": len(issues["un_replied_mentions"]),
                    "un_indexed_recovered": issues["un_indexed_recovered"],
                    "stale_open_threads": issues["stale_open_threads"],
                    "un_replied_mentions": issues["un_replied_mentions"],
                    "notifications_sent": notifications_sent,
                }
            },
        )
    )


def _send_notifications(
    *,
    issues: dict[str, list],
    window_hours: int,
    mention_window_hours: int,
) -> int:
    """Send best-effort Feishu Bot notifications for stale-open and un-replied mention issues.

    Returns the count of successful card sends (across all chats).
    Returns 0 when FEISHU_ACCESS_TOKEN is not configured.
    """
    try:
        from tools.notify.feishu_bot import FeishuBotAdapter
        from tools.config import build_thread_url

        notifier = FeishuBotAdapter.from_env()
    except Exception as e:
        sys.stderr.write(f"monitor-scan: notifier init skipped: {e}\n")
        return 0

    sent = 0
    for issue in issues.get("stale_open_threads", []):
        try:
            sent += notifier.send_card_to_all(
                title=f"Stale thread: {issue['thread']}",
                summary=(
                    f"No activity since {issue['last_updated']}, "
                    f"over {window_hours} hours."
                ),
                thread_url=build_thread_url(thread=issue["thread"]),
                author="Pivot Monitor",
            )
        except Exception as e:
            sys.stderr.write(f"monitor-scan: stale-open notify failed: {e}\n")

    for m in issues.get("un_replied_mentions", []):
        try:
            sent += notifier.send_card_to_all(
                title=f"Awaiting reply from {m['mentioned_user']}",
                summary=(
                    f"Mentioned over {mention_window_hours} hours ago, no reply yet. "
                    f"Comment: {m.get('comments', '')}"
                ),
                thread_url=build_thread_url(
                    thread=m["thread"].rstrip("/").split("/")[-1]
                ),
                author="Pivot Monitor",
                mention_names=[m["mentioned_user"]],
            )
        except Exception as e:
            sys.stderr.write(f"monitor-scan: mention notify failed: {e}\n")

    return sent


if __name__ == "__main__":
    main()
