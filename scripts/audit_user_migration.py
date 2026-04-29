#!/usr/bin/env python
"""Read-only audit script for user-management migration feasibility.

Connects to a Pivot SQLite DB (default var/data.db) and reports:

- Per-table row counts (users + every user-keyed downstream table)
- pinyin null / duplicates in users (impacts --initial-admin matching)
- union_id coverage in users (raw_profile completeness)
- Orphan rows in downstream tables (user_open_id not in users.open_id)
- Contacts without matching user (informational; expected for "@-mentioned but never logged in")
- For a given --initial-admin pinyin, whether it would match exactly one user

The script never writes; it issues SELECT only. Intended to be run before
designing/running the real migration script in 2026-04-28-user-management-design.md §9.

Usage:
    uv run python scripts/audit_user_migration.py [--db PATH] [--initial-admin PINYIN]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 output so Chinese characters render correctly on Windows terminals
# whose default encoding is GBK.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


USER_KEYED_TABLES = (
    "drafts",
    "read_state",
    "favorites",
    "sessions",
    "ai_conversations",
    "api_tokens",
)


@dataclass
class TableReport:
    name: str
    rows: int
    orphans: int  # rows whose user_open_id is not in users.open_id


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"DB not found: {path}")
    # mode=ro forbids writes at the SQLite level
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def section(title: str) -> None:
    print()
    print("=" * 64)
    print(title)
    print("=" * 64)


def audit_users(conn: sqlite3.Connection) -> dict:
    rows = list(conn.execute(
        "SELECT open_id, union_id, name, pinyin, github_username FROM users"
    ))
    pinyins = [r["pinyin"] for r in rows]
    pinyin_counts = Counter(p for p in pinyins if p)
    null_pinyin_users = [r["open_id"] for r in rows if not r["pinyin"]]
    dup_pinyins = {p: c for p, c in pinyin_counts.items() if c > 1}
    null_union = sum(1 for r in rows if not r["union_id"])
    null_name = sum(1 for r in rows if not r["name"])

    section("users 表概况")
    print(f"  总数:           {len(rows)}")
    print(f"  union_id 为空:  {null_union}")
    print(f"  name 为空:      {null_name}")
    print(f"  pinyin 为空:    {len(null_pinyin_users)}")
    if null_pinyin_users:
        print(f"    {null_pinyin_users}")
    print(f"  pinyin 重复:    {len(dup_pinyins)} 组")
    if dup_pinyins:
        for p, c in sorted(dup_pinyins.items()):
            opens = [r["open_id"] for r in rows if r["pinyin"] == p]
            print(f"    '{p}' x{c} -> {opens}")
    return {
        "users": rows,
        "null_pinyin": null_pinyin_users,
        "dup_pinyins": dup_pinyins,
    }


def audit_downstream(conn: sqlite3.Connection, valid_open_ids: set[str]) -> list[TableReport]:
    section("下游表外键覆盖（user_open_id 是否在 users 中）")
    reports: list[TableReport] = []
    for table in USER_KEYED_TABLES:
        rows = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        orphan_rows = list(conn.execute(
            f"SELECT DISTINCT user_open_id FROM {table} "
            f"WHERE user_open_id NOT IN (SELECT open_id FROM users)"
        ))
        orphans = len(orphan_rows)
        marker = "[!]" if orphans else "[ok]"
        print(f"  {marker} {table:<20}  rows={rows:<6}  orphan_user_open_id={orphans}")
        if orphans:
            for row in orphan_rows[:5]:
                print(f"      未知 user_open_id: {row['user_open_id']}")
            if orphans > 5:
                print(f"      ... 另有 {orphans - 5} 个")
        reports.append(TableReport(name=table, rows=rows, orphans=orphans))
    return reports


def audit_contacts(conn: sqlite3.Connection, valid_open_ids: set[str]) -> None:
    section("contacts 表（飞书通讯录镜像，预期可能有未登录的同事）")
    rows = list(conn.execute("SELECT open_id, name FROM contacts"))
    matched = sum(1 for r in rows if r["open_id"] in valid_open_ids)
    unmatched = len(rows) - matched
    print(f"  总数:               {len(rows)}")
    print(f"  与 users 重合:      {matched}")
    print(f"  仅在 contacts 中:   {unmatched}  （这些人会通过 §7.1 的兜底链解析名字）")


def audit_initial_admin(conn: sqlite3.Connection, pinyin: str) -> str | None:
    """Returns a blocker description if the initial-admin parameter wouldn't work, else None."""
    section(f"--initial-admin '{pinyin}' 候选检查")
    matches = list(conn.execute(
        "SELECT open_id, name, pinyin FROM users WHERE pinyin = ?",
        (pinyin,),
    ))
    if not matches:
        print(f"  [x] 没有任何用户 pinyin 严格等于 '{pinyin}'——迁移会中止")
        print(f"     现有 pinyin 列表（用于参考）：")
        all_pinyins = list(conn.execute(
            "SELECT pinyin, name FROM users ORDER BY pinyin"
        ))
        for r in all_pinyins:
            print(f"       {r['pinyin']!r:<25} ({r['name']})")
        return f"--initial-admin '{pinyin}' 在现有 users.pinyin 中无匹配"
    elif len(matches) == 1:
        m = matches[0]
        print(f"  [ok] 命中唯一用户：open_id={m['open_id']}  name={m['name']}")
        return None
    else:
        print(f"  [!] 命中 {len(matches)} 个用户（pinyin 重复）——脚本必须改成更精确的指定方式")
        for m in matches:
            print(f"     open_id={m['open_id']}  name={m['name']}")
        return f"--initial-admin '{pinyin}' 命中 {len(matches)} 个用户，需更精确指定"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=Path("var/data.db"))
    parser.add_argument(
        "--initial-admin",
        type=str,
        default=None,
        help="模拟检查指定 pinyin 是否能在迁移时唯一匹配",
    )
    args = parser.parse_args()

    print(f"DB: {args.db.resolve()}  (read-only)")
    with connect_readonly(args.db) as conn:
        users_info = audit_users(conn)
        valid_ids = {r["open_id"] for r in users_info["users"]}
        downstream = audit_downstream(conn, valid_ids)
        audit_contacts(conn, valid_ids)
        initial_admin_blocker: str | None = None
        if args.initial_admin:
            initial_admin_blocker = audit_initial_admin(conn, args.initial_admin)

    section("结论")
    blockers: list[str] = []
    if users_info["null_pinyin"]:
        blockers.append(
            f"{len(users_info['null_pinyin'])} 个用户 pinyin 为空——迁移脚本要么补 pinyin，要么允许 NULL 写入 pivot_user.pinyin（spec 当前要求 NOT NULL）"
        )
    if users_info["dup_pinyins"]:
        blockers.append(
            f"{len(users_info['dup_pinyins'])} 组 pinyin 重复——`--initial-admin <pinyin>` 在重复组中会歧义；考虑增加 --initial-admin-open-id 备选"
        )
    orphan_total = sum(r.orphans for r in downstream)
    if orphan_total:
        blockers.append(
            f"下游表共有 {orphan_total} 条孤儿外键——必须先清理，否则迁移会回滚"
        )
    if initial_admin_blocker:
        blockers.append(initial_admin_blocker)
    if not blockers:
        print("  [ok] 未发现迁移阻塞项；可以按 spec §9 走")
    else:
        print("  [!] 发现以下阻塞项：")
        for b in blockers:
            print(f"     - {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
