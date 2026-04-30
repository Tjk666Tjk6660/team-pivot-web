#!/usr/bin/env python
"""User-management migration — v2, single-script, end-to-end.

Replaces the v1 split (``migrate_user_management.py`` + post-hoc
``finalize_user_migration.py``) with a single transactional script that
takes a Pivot SQLite database from the legacy ``users`` table all the
way to the post-migration shape: 4 new identity tables created, every
downstream table reshaped to use ``pivot_user_id`` as the user reference
column (legacy ``user_open_id`` physically removed, indexes rebuilt),
``users`` table dropped.

What v2 fixes vs v1:

  - v1 only ADDed ``pivot_user_id``; it kept ``user_open_id`` NOT NULL
    "for transition", which broke at runtime because application code
    had already been migrated to insert only ``pivot_user_id``.
  - v1's ``USER_KEYED_TABLES`` list missed ``relevance_events`` and
    ``user_preferences`` — those tables didn't even get the new column.
  - The post-hoc ``finalize`` used ``executescript`` which issues an
    implicit COMMIT, breaking ``--dry-run``. v2 uses ``execute()`` per
    statement so ROLLBACK actually rolls back.

Usage::

    uv run python scripts/migrate_user_management_v2.py \\
        --db var/data.db \\
        --initial-admin <pinyin> \\
        [--dry-run]

The script is idempotent on a fully-finished database (it detects the
post-migration shape and exits with success); it is also resilient to
a partially-migrated database (e.g. someone ran v1 already) — it picks
up at whichever phase is incomplete.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from time import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ─── Schemas ────────────────────────────────────────────────────────────────


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


# Each downstream table gets a (rebuild-spec) entry: the new schema (sans
# user_open_id, with pivot_user_id NOT NULL and PK adjusted), the column
# list to copy from the old to the new (in order), and any indexes to
# rebuild against the new column. The script does:
#
#   ADD COLUMN pivot_user_id  → UPDATE backfill  → orphan check
#   → CREATE __new_T (new schema)
#   → INSERT __new_T (cols) SELECT cols FROM T
#   → DROP T → ALTER __new_T RENAME T
#   → re-create indexes
@dataclass
class DownstreamSpec:
    name: str
    new_schema: str
    copy_columns: list[str]
    indexes: list[str] = field(default_factory=list)


_DOWNSTREAM: list[DownstreamSpec] = [
    DownstreamSpec(
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
    DownstreamSpec(
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
    ),
    DownstreamSpec(
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
    DownstreamSpec(
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
    DownstreamSpec(
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
    ),
    DownstreamSpec(
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
    DownstreamSpec(
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
    DownstreamSpec(
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
    DownstreamSpec(
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
    ),
]


# ─── Result / errors ────────────────────────────────────────────────────────


@dataclass
class MigrationResult:
    success: bool
    error: str = ""
    note: str = ""
    pivot_users_created: int = 0
    bindings_created: int = 0
    initial_admin_id: str | None = None
    tables_rebuilt: list[str] = field(default_factory=list)


class MigrationError(Exception):
    pass


# ─── Helpers ────────────────────────────────────────────────────────────────


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, name: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]


def _execute_sql_block(conn: sqlite3.Connection, sql: str) -> None:
    """Execute a multi-statement SQL block via individual conn.execute() calls.

    Avoids ``executescript()``'s implicit COMMIT, which would break the
    enclosing transaction (and silently turn ``--dry-run`` into a real run).
    """
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def _shape(conn: sqlite3.Connection) -> str:
    """Classify the database into one of three states.

    * ``legacy``   — the legacy ``users`` table has rows; we have not
      started the migration yet.
    * ``mid``      — at least one downstream table still has the legacy
      ``user_open_id`` column (someone ran v1 but didn't finalize, or
      we crashed halfway through v2).
    * ``done``     — fully migrated; nothing to do.

    We treat an *empty* ``users`` table as already-done because
    ``server/db.py``'s ``executescript(SCHEMA)`` re-creates the table
    on every server boot until that schema string is also synced. An
    empty re-created shell is harmless and should not trigger a fresh
    migration run.
    """
    legacy_users_present = False
    if _table_exists(conn, "users"):
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if n > 0:
            legacy_users_present = True
    if legacy_users_present:
        return "legacy"
    for spec in _DOWNSTREAM:
        if _table_exists(conn, spec.name) and "user_open_id" in _table_columns(conn, spec.name):
            return "mid"
    return "done"


# ─── Phase 0: audit (read-only preconditions) ─────────────────────────────


def _audit(conn: sqlite3.Connection, initial_admin_pinyin: str) -> None:
    """Pre-flight checks. Raises MigrationError on any blocker."""
    if not _table_exists(conn, "users"):
        return  # nothing to audit if the users table is already gone

    rows = list(conn.execute("SELECT open_id, name, pinyin FROM users"))
    if not rows:
        raise MigrationError(
            "users table is empty — nothing to migrate. If this is a brand-new"
            " deployment, skip migration and let /init/complete create the"
            " first admin."
        )

    null_pinyin = [r["open_id"] for r in rows if not r["pinyin"]]
    if null_pinyin:
        raise MigrationError(
            f"{len(null_pinyin)} users have NULL pinyin — fix them in"
            f" /admin/users (legacy) before migrating: {null_pinyin}"
        )

    pinyin_count: dict[str, int] = {}
    for r in rows:
        pinyin_count[r["pinyin"]] = pinyin_count.get(r["pinyin"], 0) + 1
    duplicates = {p: n for p, n in pinyin_count.items() if n > 1}
    if duplicates:
        raise MigrationError(
            f"duplicate pinyin found: {duplicates} — pinyin uniqueness is"
            " required for --initial-admin to identify the user"
        )

    # The initial-admin pinyin must match exactly one user row.
    matches = [r for r in rows if r["pinyin"] == initial_admin_pinyin]
    if not matches:
        all_pinyins = sorted(r["pinyin"] for r in rows)
        raise MigrationError(
            f"--initial-admin '{initial_admin_pinyin}' does not match any"
            f" user; existing pinyins: {all_pinyins}"
        )
    if len(matches) > 1:
        raise MigrationError(
            f"--initial-admin '{initial_admin_pinyin}' matches"
            f" {len(matches)} users — this is impossible after the dup check"
            " above, indicating a race; aborting"
        )

    # Orphan check on every downstream table that still has user_open_id —
    # any row whose user_open_id has no matching users.open_id breaks the
    # later backfill. Surface it now with a clear message.
    for spec in _DOWNSTREAM:
        if not _table_exists(conn, spec.name):
            continue
        if "user_open_id" not in _table_columns(conn, spec.name):
            continue
        orphans = list(conn.execute(
            f"SELECT DISTINCT user_open_id FROM {spec.name}"
            " WHERE user_open_id NOT IN (SELECT open_id FROM users)"
            " LIMIT 5"
        ))
        if orphans:
            sample = [o["user_open_id"] for o in orphans]
            raise MigrationError(
                f"{spec.name}: rows reference user_open_id with no matching"
                f" users.open_id (sample: {sample}). Clean these up before"
                " migrating."
            )


# ─── Phase 2-4: identity-table backfills ──────────────────────────────────


def _backfill_pivot_user(conn: sqlite3.Connection) -> tuple[int, int]:
    """Seed pivot_user + feishu external_binding from the legacy users table.

    Idempotent on partial state: rows whose feishu binding already exists
    (someone re-ran v1) are skipped.
    """
    if not _table_exists(conn, "users"):
        return 0, 0

    users_rows = list(conn.execute("SELECT * FROM users"))
    now = time()
    created_users = 0
    created_bindings = 0
    for u in users_rows:
        existing = conn.execute(
            "SELECT pivot_user_id FROM external_binding"
            " WHERE provider='feishu' AND external_id=?",
            (u["open_id"],),
        ).fetchone()
        if existing:
            continue  # already migrated in a prior partial run
        new_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO pivot_user"
            " (id, display_name, pinyin, email, avatar_url, github_username,"
            "  role, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (new_id, u["name"], u["pinyin"], None, u["avatar_url"] or "",
             u["github_username"], "member", "active",
             u["created_at"], now),
        )
        created_users += 1
        raw = json.dumps({
            "name": u["name"], "avatar_url": u["avatar_url"],
            "union_id": u["union_id"],
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO external_binding"
            " (id, pivot_user_id, provider, external_id, external_union_id,"
            "  raw_profile, bound_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, new_id, "feishu", u["open_id"],
             u["union_id"], raw, u["created_at"]),
        )
        created_bindings += 1
    return created_users, created_bindings


def _set_initial_admin(
    conn: sqlite3.Connection, initial_admin_pinyin: str,
) -> str:
    matches = list(conn.execute(
        "SELECT id FROM pivot_user WHERE pinyin=?",
        (initial_admin_pinyin,),
    ))
    if not matches:
        raise MigrationError(
            f"no pivot_user with pinyin '{initial_admin_pinyin}' after"
            " backfill — this should have been caught by audit"
        )
    if len(matches) > 1:
        raise MigrationError(
            f"pinyin '{initial_admin_pinyin}' matches {len(matches)}"
            " pivot_user rows — ambiguous"
        )
    admin_id = matches[0]["id"]
    conn.execute(
        "UPDATE pivot_user SET role='admin' WHERE id=?", (admin_id,)
    )
    return admin_id


# ─── Phase 5: per-table backfill + rebuild + reindex ──────────────────────


def _process_downstream(
    conn: sqlite3.Connection, spec: DownstreamSpec,
) -> bool:
    """Backfill + rebuild one downstream table. Returns True if rebuilt
    (False if the table didn't exist or was already finalized)."""
    if not _table_exists(conn, spec.name):
        return False
    cols = _table_columns(conn, spec.name)

    # Step a: ADD COLUMN pivot_user_id if missing.
    if "user_open_id" not in cols and "pivot_user_id" not in cols:
        # Table doesn't have either column — it's not a user-keyed table.
        # Shouldn't happen for the tables in _DOWNSTREAM, but be safe.
        return False
    if "pivot_user_id" not in cols:
        conn.execute(f"ALTER TABLE {spec.name} ADD COLUMN pivot_user_id TEXT")
        cols.append("pivot_user_id")

    # Step b: backfill pivot_user_id from external_binding (only rows where
    # it's still null — preserves earlier successful fills on a partial run).
    if "user_open_id" in cols:
        conn.execute(
            f"UPDATE {spec.name} SET pivot_user_id = ("
            "  SELECT pivot_user_id FROM external_binding"
            f"  WHERE provider='feishu' AND external_id={spec.name}.user_open_id"
            ") WHERE pivot_user_id IS NULL"
        )
        # Step c: orphan check — every row that has a user_open_id must now
        # have a pivot_user_id.
        orphan = conn.execute(
            f"SELECT COUNT(*) AS n FROM {spec.name}"
            " WHERE pivot_user_id IS NULL AND user_open_id IS NOT NULL"
        ).fetchone()["n"]
        if orphan > 0:
            raise MigrationError(
                f"{spec.name}: {orphan} rows have user_open_id with no"
                " matching binding — would lose data on rebuild; aborting"
            )
    # If user_open_id is gone we're already finalized for this table.
    if "user_open_id" not in cols:
        return False

    # Step d-g: rebuild the table to drop user_open_id + adjust PK, then
    # re-create indexes.
    _execute_sql_block(conn, spec.new_schema)
    existing_cols = set(_table_columns(conn, spec.name))
    col_list = ", ".join(spec.copy_columns)
    select_list = ", ".join(
        col if col in existing_cols else _default_select_expr(col)
        for col in spec.copy_columns
    )
    conn.execute(
        f"INSERT INTO __new_{spec.name} ({col_list})"
        f" SELECT {select_list} FROM {spec.name}"
    )
    moved = conn.execute(
        f"SELECT COUNT(*) FROM __new_{spec.name}"
    ).fetchone()[0]
    original = conn.execute(
        f"SELECT COUNT(*) FROM {spec.name}"
    ).fetchone()[0]
    if moved != original:
        raise MigrationError(
            f"{spec.name}: row count mismatch on rebuild"
            f" (original={original}, moved={moved})"
        )
    conn.execute(f"DROP TABLE {spec.name}")
    conn.execute(f"ALTER TABLE __new_{spec.name} RENAME TO {spec.name}")
    for idx_sql in spec.indexes:
        conn.execute(idx_sql)
    return True


def _default_select_expr(column: str) -> str:
    """Default values for optional columns introduced by later schema versions.

    Production databases may be older than this migration script. During a
    rebuild we can safely seed these columns with the same defaults used by
    server/db.py's online migrations.
    """
    defaults = {
        "mentions_json": "NULL",
        "reply_to": "NULL",
        "references_json": "'[]'",
        "summary": "''",
        "matter_payload_json": "NULL",
        "user_access_token": "NULL",
        "context_files_json": "'[]'",
        "reference_files_json": "'[]'",
        "reply_target": "NULL",
        "schema_ver": "1",
    }
    if column not in defaults:
        raise MigrationError(
            f"cannot rebuild table: source column '{column}' is missing and"
            " no migration default is defined"
        )
    return defaults[column]


# ─── Top-level driver ─────────────────────────────────────────────────────


def migrate(
    *,
    db_path: Path,
    initial_admin_pinyin: str,
    dry_run: bool,
) -> MigrationResult:
    if not db_path.exists():
        return MigrationResult(success=False, error=f"DB not found: {db_path}")

    # isolation_level=None puts pysqlite in autocommit mode so we manage the
    # transaction envelope ourselves; otherwise CPython's hidden BEGIN /
    # implicit commits mess with explicit BEGIN / COMMIT / ROLLBACK calls.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Foreign keys OFF during the rebuild because dropping/re-creating tables
    # triggers FK validation against partial state. They're not enforced at
    # query time anyway; the integrity_check at the end is the safety net.
    conn.execute("PRAGMA foreign_keys=OFF")

    try:
        shape = _shape(conn)
        if shape == "done":
            return MigrationResult(
                success=True,
                note="database is already fully migrated (no users table,"
                     " no user_open_id columns); nothing to do",
            )

        conn.execute("BEGIN")

        # Phase 0: audit (only meaningful when users table exists)
        if shape == "legacy":
            _audit(conn, initial_admin_pinyin)

        # Phase 1: 4 new identity tables (idempotent — IF NOT EXISTS)
        _execute_sql_block(conn, _NEW_TABLES_SQL)

        # Phase 2-4: pivot_user + external_binding backfill + initial admin
        n_users, n_bindings = _backfill_pivot_user(conn)
        admin_id = _set_initial_admin(conn, initial_admin_pinyin)

        # Phase 5: rebuild every downstream table (drops user_open_id)
        rebuilt: list[str] = []
        for spec in _DOWNSTREAM:
            if _process_downstream(conn, spec):
                rebuilt.append(spec.name)

        # Phase 6: drop the legacy users table
        if _table_exists(conn, "users"):
            conn.execute("DROP TABLE users")

        # Phase 7: integrity check while still inside the transaction so a
        # failure aborts cleanly.
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise MigrationError(f"integrity_check failed: {check}")

        # Phase 8: commit or rollback
        if dry_run:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")

        return MigrationResult(
            success=True,
            pivot_users_created=n_users,
            bindings_created=n_bindings,
            initial_admin_id=admin_id,
            tables_rebuilt=rebuilt,
        )
    except MigrationError as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return MigrationResult(success=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return MigrationResult(success=False, error=f"unexpected: {e!r}")
    finally:
        conn.close()


def _main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--initial-admin", type=str, required=True,
        help="pinyin of the user to promote to admin",
    )
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
        if result.note:
            print(f"  {result.note}")
        else:
            print(f"  pivot_user rows created: {result.pivot_users_created}")
            print(f"  feishu bindings created: {result.bindings_created}")
            print(f"  initial admin id:        {result.initial_admin_id}")
            print(f"  downstream tables rebuilt: {len(result.tables_rebuilt)}")
            for name in result.tables_rebuilt:
                print(f"    - {name}")
        return 0
    print(f"[{mode}] FAILED: {result.error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
