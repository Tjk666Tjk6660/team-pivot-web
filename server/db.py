from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    open_id TEXT PRIMARY KEY,
    union_id TEXT,
    name TEXT NOT NULL,
    avatar_url TEXT NOT NULL DEFAULT '',
    pinyin TEXT,
    github_username TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    user_open_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('proposal', 'reply')),
    title TEXT,
    category TEXT,
    body_md TEXT NOT NULL DEFAULT '',
    thread_key TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_open_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS read_state (
    user_open_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    last_read_post_filename TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, thread_key)
);
CREATE TABLE IF NOT EXISTS favorites (
    user_open_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, thread_key)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_created
ON favorites(user_open_id, created_at DESC);
CREATE TABLE IF NOT EXISTS contacts (
    open_id TEXT PRIMARY KEY,
    union_id TEXT,
    name TEXT NOT NULL,
    en_name TEXT,
    pinyin TEXT,
    avatar_url TEXT NOT NULL DEFAULT '',
    synced_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
-- idx_contacts_pinyin lives in _migrate so it can sequence after the ALTER
-- TABLE that adds the pinyin column on legacy DBs (the column doesn't yet
-- exist when SCHEMA runs there).
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_open_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_conversations (
    user_open_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, thread_key)
);
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    user_open_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_open_id);
CREATE TABLE IF NOT EXISTS file_reads (
    user_open_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    first_read_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, matter_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_file_reads_matter
    ON file_reads(matter_id, filename);
"""


def _migrate(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "markdown_style" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN markdown_style TEXT")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
    if "mentions_json" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN mentions_json TEXT")
    if "reply_to" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN reply_to TEXT")
    if "references_json" not in cols:
        conn.execute(
            "ALTER TABLE drafts ADD COLUMN references_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "matter_payload_json" not in cols:
        # P4.6: matter 草稿复用 drafts 表，type 仍为 proposal|reply；
        # matter 专属结构化字段（doc_type/summary/owner/quote/refer/
        # verifications/outcome/status_change）统一落在这一列里。
        conn.execute("ALTER TABLE drafts ADD COLUMN matter_payload_json TEXT")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "user_access_token" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_access_token TEXT")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ai_conversations)")}
    if "context_files_json" not in cols:
        conn.execute(
            "ALTER TABLE ai_conversations ADD COLUMN context_files_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "reply_target" not in cols:
        conn.execute("ALTER TABLE ai_conversations ADD COLUMN reply_target TEXT")
    if "reference_files_json" not in cols:
        conn.execute(
            "ALTER TABLE ai_conversations ADD COLUMN reference_files_json TEXT NOT NULL DEFAULT '[]'"
        )
        # One-time backfill: split old context_files_json into (reply_target, reference_files)
        for row in conn.execute(
            "SELECT user_open_id, thread_key, context_files_json FROM ai_conversations"
        ).fetchall():
            try:
                import json as _j
                files = _j.loads(row["context_files_json"] or "[]")
            except Exception:
                files = []
            if not files:
                continue
            target = files[0]
            refs = files[1:]
            conn.execute(
                "UPDATE ai_conversations SET reply_target=?, reference_files_json=?"
                " WHERE user_open_id=? AND thread_key=?",
                (target, __import__("json").dumps(refs), row["user_open_id"], row["thread_key"]),
            )
    # Tool-use schema migration: clear all prior AI conversations on first
    # boot of the tool-use version. Threads/posts are untouched (Git is the
    # source of truth). Column presence acts as the migration marker so this
    # only fires once.
    if "schema_ver" not in cols:
        conn.execute(
            "ALTER TABLE ai_conversations ADD COLUMN schema_ver INTEGER NOT NULL DEFAULT 1"
        )
        conn.execute("DELETE FROM ai_conversations")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)")}
    if "pinyin" not in cols:
        conn.execute("ALTER TABLE contacts ADD COLUMN pinyin TEXT")
        # Backfill: compute pinyin from existing names so MCP @-by-pinyin
        # works immediately without waiting for the next contacts sync.
        from server.contacts import name_to_pinyin
        for row in conn.execute("SELECT open_id, name FROM contacts").fetchall():
            conn.execute(
                "UPDATE contacts SET pinyin=? WHERE open_id=?",
                (name_to_pinyin(row["name"] or ""), row["open_id"]),
            )
    # Idempotent: covers both freshly-created tables (column came from SCHEMA)
    # and migrated ones (column came from the ALTER above). Cheap on every boot.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contacts_pinyin ON contacts(pinyin)"
    )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            _migrate(conn)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
