#!/usr/bin/env python3
"""One-off relevance backfill for a matter index file or whole index dir.

Reuses scan_all by pointing a stub workspace at either the staged single
yaml (file mode) or the source directory (directory mode), then runs the
production users repo + relevance_events repo against `var/data2.db`.

Dry-run by default — pass --apply to actually insert rows.

Usage:
    # single file
    uv run python scripts/backfill_one_matter.py <path-to-index.yaml> [--apply]
    # whole directory of *.index.yaml files
    uv run python scripts/backfill_one_matter.py <path-to-index-dir> [--apply]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.config import load_config  # noqa: E402
from server.db import Database  # noqa: E402
from server.matter_index import read_matter_index  # noqa: E402
from server.relevance_events import RelevanceEventsRepo  # noqa: E402
from server.relevance_scanner import scan_all  # noqa: E402
from server.users import UserRepo  # noqa: E402


class _StubWorkspace:
    """Scan_all only needs `.index_dir`."""

    def __init__(self, *, index_dir: Path) -> None:
        self._index_dir = index_dir

    @property
    def index_dir(self) -> Path:
        return self._index_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "target",
        help="Path to a .index.yaml file OR a directory containing them",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually insert rows. Without it, runs scan against a throwaway "
             "DB to preview what would be written.",
    )
    args = parser.parse_args()

    src = Path(args.target)
    if src.is_file():
        mode = "file"
    elif src.is_dir():
        mode = "dir"
    else:
        print(f"error: not a file or directory: {src}", file=sys.stderr)
        return 2

    if mode == "file":
        parsed = read_matter_index(src)
        if parsed is None:
            print(f"error: could not parse yaml: {src}", file=sys.stderr)
            return 2
        matter_id = (parsed.get("matter") or {}).get("id") or ""
        timeline_n = len(parsed.get("timeline") or [])
        print(f"target matter_id={matter_id!r} timeline_items={timeline_n}")
    else:
        index_files = sorted(src.glob("*.index.yaml"))
        # Mirror scan_all's exclusion of legacy thread index files.
        index_files = [
            p for p in index_files if not p.name.endswith("-discuss.index.yaml")
        ]
        print(f"target dir={src} index_files={len(index_files)}")
        if not index_files:
            print("nothing to do")
            return 0

    cfg = load_config()
    prod_db = Database(cfg.data_dir / "data2.db")
    users_repo = UserRepo(prod_db)
    registered = users_repo.all()
    print(
        f"registered users in prod DB: "
        f"{[(u.pinyin, u.open_id) for u in registered]}"
    )

    with tempfile.TemporaryDirectory(prefix="pivot-backfill-") as tmp:
        tmp_root = Path(tmp)
        if mode == "file":
            staged = tmp_root / "index"
            staged.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, staged / src.name)
            ws = _StubWorkspace(index_dir=staged)
        else:
            ws = _StubWorkspace(index_dir=src)

        if args.apply:
            repo = RelevanceEventsRepo(prod_db)
            print(
                f"--apply: writing to prod DB at "
                f"{cfg.data_dir / 'data2.db'}"
            )
        else:
            # Dry-run: file-backed throwaway DB (sqlite in-memory loses
            # state across our per-call connect() because we open a fresh
            # connection each time).
            dry_db = Database(tmp_root / "dry.db")
            repo = RelevanceEventsRepo(dry_db)
            print("dry-run: scanning into a throwaway DB (use --apply to write)")
            dry_users = UserRepo(dry_db)
            for u in registered:
                dry_users.upsert_from_feishu(
                    open_id=u.open_id, union_id=u.union_id, name=u.name,
                    avatar_url=u.avatar_url or "",
                )
                if u.pinyin:
                    dry_users.update_profile(u.open_id, pinyin=u.pinyin)
            users_repo = dry_users

        report = scan_all(workspace=ws, users_repo=users_repo, repo=repo)

        target_db = prod_db if args.apply else repo._db  # noqa: SLF001
        with target_db.connect() as conn:
            if mode == "file":
                rows = conn.execute(
                    "SELECT user_open_id, matter_id, filename, kind, reason,"
                    "       event_at, actor_pinyin, read_at"
                    "  FROM relevance_events"
                    " WHERE matter_id = ?"
                    " ORDER BY user_open_id, kind, event_at",
                    (matter_id,),
                ).fetchall()
            else:
                # Dir mode: aggregate per matter rather than dumping every row.
                rows = conn.execute(
                    "SELECT matter_id, user_open_id, kind, COUNT(*) AS n"
                    "  FROM relevance_events"
                    " GROUP BY matter_id, user_open_id, kind"
                    " ORDER BY matter_id, user_open_id, kind",
                ).fetchall()

    print(
        f"\nscan report: matters={report.matters} "
        f"inserted={report.inserted} skipped={report.skipped}"
    )

    if not rows:
        print("(no rows)")
    elif mode == "file":
        print(f"\n{'user_open_id':<35s} {'kind':<8s} {'reason':<22s} "
              f"{'event_at':<28s} {'actor':<14s} {'filename'}")
        for r in rows:
            print(f"{r['user_open_id']:<35s} {r['kind']:<8s} "
                  f"{r['reason']:<22s} {r['event_at']:<28s} "
                  f"{r['actor_pinyin']:<14s} {r['filename']}")
    else:
        # Dir mode: per-matter, per-user, per-kind row counts.
        print(f"\n{'matter_id':<60s} {'user_open_id':<35s} {'kind':<8s} n")
        for r in rows:
            print(f"{r['matter_id'][:60]:<60s} {r['user_open_id']:<35s} "
                  f"{r['kind']:<8s} {r['n']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
