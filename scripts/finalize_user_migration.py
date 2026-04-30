#!/usr/bin/env python
"""Finalize the user-management migration: drop the legacy ``user_open_id``
column from every downstream table by rebuilding the table.

Background: ``scripts/migrate_user_management.py`` adds the new
``pivot_user_id`` column and back-fills it, but leaves ``user_open_id``
in place as a NOT NULL column for "transition". The application code,
however, was already updated (commit 4e93598) to insert only
``pivot_user_id`` — so any new INSERT into sessions / drafts / etc.
crashes with ``IntegrityError: NOT NULL constraint failed:
sessions.user_open_id``. This script closes that gap by physically
removing ``user_open_id`` from every affected table.

Tables rebuilt (each with the corresponding indexes):
  drafts / read_state / favorites / sessions / ai_conversations /
  api_tokens / file_reads / relevance_events / user_preferences

Pre-conditions (asserted before any write):
  - ``pivot_user_id`` column exists and is fully populated
  - no ``pivot_user_id IS NULL AND user_open_id IS NOT NULL`` rows

The whole rebuild runs in a single transaction with foreign_keys=OFF;
on any error it rolls back. Always back up ``var/data.db`` first.

Usage:
    uv run python scripts/finalize_user_migration.py --db var/data.db
        [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Each entry describes how to rebuild one downstream table.
#
# ``new_schema`` is the CREATE TABLE statement for the rebuilt table —
# named ``__new_<table>`` here so we can later DROP / RENAME without
# colliding with the live table.
#
# ``copy_columns`` lists the columns the temp table should pull from
# the old table; the order MUST match the column order in
# ``new_schema``. ``user_open_id`` is excluded everywhere; whenever the
# old table's PK or some non-PK column was ``user_open_id``, we
# replace it with ``pivot_user_id`` (which is back-filled to the same
# logical user reference, in ULID form).
#
# ``indexes`` lists CREATE INDEX statements to run after rename. The
# old indexes that referenced ``user_open_id`` are gone with the old
# table; we re-create them on ``pivot_user_id``.
@dataclass
class TableRebuild:
    name: str
    new_schema: str
    copy_columns: list[str]   # columns on the new table; same names on the old
    indexes: list[str] = None  # type: ignore[assignment]


REBUILDS: list[TableRebuild] = [
    TableRebuild(
        name="drafts",
        new_schema="""
        CREATE TABLE __new_drafts (
            id TEXT PRIMARY KEY,
            pivot_user_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('proposal','reply')),
            title TEXT,
            category TEXT,
            body_md TEXT NOT NULL DEFAULT '',
            thread_key TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            mentions_json TEXT,
            reply_to TEXT,
            references_json TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            matter_payload_json TEXT
        )
        """,
        copy_columns=[
            "id", "pivot_user_id", "type", "title", "category", "body_md",
            "thread_key", "created_at", "updated_at", "mentions_json",
            "reply_to", "references_json", "summary", "matter_payload_json",
        ],
        indexes=[
            "CREATE INDEX idx_drafts_user ON drafts(pivot_user_id, updated_at DESC)",
        ],
    ),
    TableRebuild(
        name="read_state",
        new_schema="""
        CREATE TABLE __new_read_state (
            pivot_user_id TEXT NOT NULL,
            thread_key TEXT NOT NULL,
            last_read_post_filename TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (pivot_user_id, thread_key)
        )
        """,
        copy_columns=[
            "pivot_user_id", "thread_key", "last_read_post_filename", "updated_at",
        ],
        indexes=[],
    ),
    TableRebuild(
        name="favorites",
        new_schema="""
        CREATE TABLE __new_favorites (
            pivot_user_id TEXT NOT NULL,
            thread_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (pivot_user_id, thread_key)
        )
        """,
        copy_columns=["pivot_user_id", "thread_key", "created_at"],
        indexes=[
            "CREATE INDEX idx_favorites_user_created"
            " ON favorites(pivot_user_id, created_at DESC)",
        ],
    ),
    TableRebuild(
        name="sessions",
        new_schema="""
        CREATE TABLE __new_sessions (
            id TEXT PRIMARY KEY,
            pivot_user_id TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL,
            user_access_token TEXT
        )
        """,
        copy_columns=[
            "id", "pivot_user_id", "expires_at", "created_at", "user_access_token",
        ],
        indexes=[
            "CREATE INDEX idx_sessions_expires ON sessions(expires_at)",
        ],
    ),
    TableRebuild(
        name="ai_conversations",
        new_schema="""
        CREATE TABLE __new_ai_conversations (
            pivot_user_id TEXT NOT NULL,
            thread_key TEXT NOT NULL,
            messages_json TEXT NOT NULL DEFAULT '[]',
            updated_at REAL NOT NULL,
            context_files_json TEXT NOT NULL DEFAULT '[]',
            reply_target TEXT,
            reference_files_json TEXT NOT NULL DEFAULT '[]',
            schema_ver INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (pivot_user_id, thread_key)
        )
        """,
        copy_columns=[
            "pivot_user_id", "thread_key", "messages_json", "updated_at",
            "context_files_json", "reply_target", "reference_files_json",
            "schema_ver",
        ],
        indexes=[],
    ),
    TableRebuild(
        name="api_tokens",
        new_schema="""
        CREATE TABLE __new_api_tokens (
            token_hash TEXT PRIMARY KEY,
            pivot_user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_used_at REAL,
            expires_at REAL NOT NULL
        )
        """,
        copy_columns=[
            "token_hash", "pivot_user_id", "name", "created_at",
            "last_used_at", "expires_at",
        ],
        indexes=[
            "CREATE INDEX idx_api_tokens_user ON api_tokens(pivot_user_id)",
        ],
    ),
    TableRebuild(
        name="file_reads",
        new_schema="""
        CREATE TABLE __new_file_reads (
            pivot_user_id TEXT NOT NULL,
            matter_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            first_read_at REAL NOT NULL,
            PRIMARY KEY (pivot_user_id, matter_id, filename)
        )
        """,
        copy_columns=[
            "pivot_user_id", "matter_id", "filename", "first_read_at",
        ],
        indexes=[
            "CREATE INDEX idx_file_reads_matter ON file_reads(matter_id, filename)",
        ],
    ),
    TableRebuild(
        name="relevance_events",
        new_schema="""
        CREATE TABLE __new_relevance_events (
            pivot_user_id TEXT NOT NULL,
            matter_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            kind TEXT NOT NULL,
            reason TEXT NOT NULL,
            event_at TEXT NOT NULL,
            actor_pinyin TEXT NOT NULL,
            created_at REAL NOT NULL,
            read_at REAL,
            PRIMARY KEY (pivot_user_id, matter_id, filename, kind, event_at, actor_pinyin)
        )
        """,
        copy_columns=[
            "pivot_user_id", "matter_id", "filename", "kind", "reason",
            "event_at", "actor_pinyin", "created_at", "read_at",
        ],
        indexes=[
            "CREATE INDEX idx_re_user_unread"
            " ON relevance_events(pivot_user_id, read_at, matter_id)",
        ],
    ),
    TableRebuild(
        name="user_preferences",
        new_schema="""
        CREATE TABLE __new_user_preferences (
            pivot_user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (pivot_user_id, key)
        )
        """,
        copy_columns=["pivot_user_id", "key", "value", "updated_at"],
        indexes=[],
    ),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _check_preconditions(conn: sqlite3.Connection) -> None:
    """Assert every table has pivot_user_id populated where needed."""
    for r in REBUILDS:
        cols = _table_columns(conn, r.name)
        if "user_open_id" not in cols:
            print(f"  [skip]   {r.name}: no user_open_id, already finalized")
            continue
        if "pivot_user_id" not in cols:
            raise SystemExit(
                f"  [abort]  {r.name}: pivot_user_id column missing — run "
                "scripts/migrate_user_management.py first"
            )
        gap = conn.execute(
            f"SELECT COUNT(*) FROM {r.name}"
            " WHERE pivot_user_id IS NULL AND user_open_id IS NOT NULL"
        ).fetchone()[0]
        if gap > 0:
            raise SystemExit(
                f"  [abort]  {r.name}: {gap} rows have user_open_id but no "
                "pivot_user_id — back-fill is incomplete"
            )


def _rebuild_one(conn: sqlite3.Connection, r: TableRebuild) -> None:
    cols = _table_columns(conn, r.name)
    if "user_open_id" not in cols:
        return  # already finalized

    conn.executescript(r.new_schema)
    col_list = ", ".join(r.copy_columns)
    conn.execute(
        f"INSERT INTO __new_{r.name} ({col_list}) SELECT {col_list} FROM {r.name}"
    )
    moved = conn.execute(f"SELECT COUNT(*) FROM __new_{r.name}").fetchone()[0]
    original = conn.execute(f"SELECT COUNT(*) FROM {r.name}").fetchone()[0]
    if moved != original:
        raise RuntimeError(
            f"{r.name}: moved {moved} rows, expected {original}"
        )
    conn.execute(f"DROP TABLE {r.name}")
    conn.execute(f"ALTER TABLE __new_{r.name} RENAME TO {r.name}")
    for sql in (r.indexes or []):
        conn.execute(sql)
    print(f"  [done]   {r.name}  rows={moved}  indexes={len(r.indexes or [])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=Path("var/data.db"))
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the rebuild inside a transaction and roll back at the end.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        sys.exit(f"DB not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        _check_preconditions(conn)
        conn.execute("BEGIN")
        for r in REBUILDS:
            _rebuild_one(conn, r)
        # integrity check while still inside the transaction
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"integrity_check failed: {check}")
        if args.dry_run:
            conn.execute("ROLLBACK")
            print("\n[DRY-RUN] OK — rolled back")
        else:
            conn.execute("COMMIT")
            print("\n[APPLY] OK")
        return 0
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        print(f"\n[error] rolled back: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())