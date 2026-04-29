#!/usr/bin/env python
"""User-management migration script (one-shot, single transaction).

See AI-docs/designs/2026-04-28-user-management-design.md §9.

Usage:
    uv run python scripts/migrate_user_management.py \
        --db var/data.db \
        --initial-admin <pinyin> \
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS pivot_user (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pinyin TEXT,
    email TEXT UNIQUE,
    avatar_url TEXT NOT NULL DEFAULT '',
    github_username TEXT,
    role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
    status_note TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_login_at REAL,
    status_changed_at REAL,
    status_changed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pivot_user_role_status ON pivot_user(role, status);

CREATE TABLE IF NOT EXISTS external_binding (
    id TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL REFERENCES pivot_user(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT,
    password_hash TEXT,
    bound_at REAL NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_binding_user ON external_binding(pivot_user_id);

CREATE TABLE IF NOT EXISTS join_application (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT NOT NULL,
    suggested_match_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    applied_at REAL NOT NULL,
    reviewed_at REAL,
    reviewed_by TEXT,
    reject_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_join_app_pending_unique
    ON join_application(provider, external_id) WHERE status='pending';

CREATE TABLE IF NOT EXISTS invite (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    used_by_user_id TEXT
);
"""

_DOWNSTREAM_TABLES = (
    "drafts", "read_state", "favorites", "sessions",
    "ai_conversations", "api_tokens", "file_reads",
)


@dataclass
class MigrationResult:
    success: bool
    error: str = ""
    pivot_users_created: int = 0
    bindings_created: int = 0
    initial_admin_id: str | None = None


def _table_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _execute_sql_block(conn: sqlite3.Connection, sql: str) -> None:
    """Execute a multi-statement SQL block using individual conn.execute() calls.

    Unlike executescript(), individual execute() calls don't issue an implicit
    COMMIT, so the caller's transaction envelope stays intact and DDL can be
    rolled back (SQLite supports transactional DDL).
    """
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def migrate(
    *,
    db_path: Path,
    initial_admin_pinyin: str,
    dry_run: bool,
) -> MigrationResult:
    # isolation_level=None: autocommit mode so we manage transactions manually.
    # This prevents Python's implicit transaction management from interfering
    # with our explicit BEGIN/COMMIT/ROLLBACK envelope.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")

        # 1. New tables — use _execute_sql_block (not executescript) to keep
        # the transaction open. executescript() issues an implicit COMMIT even
        # with isolation_level=None (verified on CPython 3.14).
        _execute_sql_block(conn, _NEW_TABLES_SQL)

        # 2. Build mapping users.open_id → pivot_user.id and seed pivot_user
        users = list(conn.execute("SELECT * FROM users"))
        mapping: dict[str, str] = {}
        now = time()
        for u in users:
            new_id = uuid.uuid4().hex
            mapping[u["open_id"]] = new_id
            conn.execute(
                "INSERT INTO pivot_user"
                " (id, display_name, pinyin, email, avatar_url, github_username,"
                "  role, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id, u["name"], u["pinyin"], None, u["avatar_url"] or "",
                 u["github_username"], "member", "active",
                 u["created_at"], now),
            )
            raw_profile = json.dumps({
                "name": u["name"], "avatar_url": u["avatar_url"],
                "union_id": u["union_id"],
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO external_binding"
                " (id, pivot_user_id, provider, external_id, external_union_id,"
                "  raw_profile, bound_at) VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, new_id, "feishu", u["open_id"],
                 u["union_id"], raw_profile, u["created_at"]),
            )

        # 3. Add pivot_user_id column to downstream tables, populate, check orphans
        for table in _DOWNSTREAM_TABLES:
            if not _table_exists(conn, table):
                continue
            if not _table_has_column(conn, table, "user_open_id"):
                continue
            if not _table_has_column(conn, table, "pivot_user_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN pivot_user_id TEXT")
            conn.execute(
                f"UPDATE {table} SET pivot_user_id="
                " (SELECT id FROM pivot_user WHERE id IN ("
                "   SELECT pivot_user_id FROM external_binding"
                f"   WHERE provider='feishu' AND external_id={table}.user_open_id"
                " ))"
            )
            orphan_count = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
                " WHERE pivot_user_id IS NULL AND user_open_id IS NOT NULL"
            ).fetchone()["n"]
            if orphan_count > 0:
                raise _MigrationError(
                    f"orphan rows in {table}: {orphan_count} entries reference"
                    " open_id with no matching user"
                )

        # 4. Initial admin
        admin_row = conn.execute(
            "SELECT id FROM pivot_user WHERE pinyin=?",
            (initial_admin_pinyin,),
        ).fetchone()
        if admin_row is None:
            raise _MigrationError(
                f"no user with pinyin '{initial_admin_pinyin}'; cannot designate"
                " initial admin"
            )
        admin_matches = conn.execute(
            "SELECT COUNT(*) AS n FROM pivot_user WHERE pinyin=?",
            (initial_admin_pinyin,),
        ).fetchone()["n"]
        if admin_matches > 1:
            raise _MigrationError(
                f"pinyin '{initial_admin_pinyin}' matches {admin_matches} users"
                " — ambiguous; aborting"
            )
        admin_id = admin_row["id"]
        conn.execute(
            "UPDATE pivot_user SET role='admin' WHERE id=?", (admin_id,)
        )

        # 5. Drop legacy users table (only on real run)
        if not dry_run:
            conn.execute("DROP TABLE IF EXISTS users")

        if dry_run:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")

        return MigrationResult(
            success=True,
            pivot_users_created=len(users),
            bindings_created=len(users),
            initial_admin_id=admin_id,
        )
    except _MigrationError as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return MigrationResult(success=False, error=str(e))
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return MigrationResult(success=False, error=f"unexpected: {e}")
    finally:
        conn.close()


class _MigrationError(Exception):
    pass


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--initial-admin", type=str, required=True,
                        help="pinyin of the user to promote to admin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = migrate(
        db_path=args.db,
        initial_admin_pinyin=args.initial_admin,
        dry_run=args.dry_run,
    )
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    if result.success:
        print(f"[{mode}] OK")
        print(f"  pivot_user rows created: {result.pivot_users_created}")
        print(f"  feishu bindings created: {result.bindings_created}")
        print(f"  initial admin id: {result.initial_admin_id}")
        return 0
    else:
        print(f"[{mode}] FAILED: {result.error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
