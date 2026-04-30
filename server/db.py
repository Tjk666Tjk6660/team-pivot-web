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
    pivot_user_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('proposal', 'reply')),
    title TEXT,
    category TEXT,
    body_md TEXT NOT NULL DEFAULT '',
    thread_key TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(pivot_user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS read_state (
    pivot_user_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    last_read_post_filename TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (pivot_user_id, thread_key)
);
CREATE TABLE IF NOT EXISTS favorites (
    pivot_user_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (pivot_user_id, thread_key)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_created
ON favorites(pivot_user_id, created_at DESC);
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
    pivot_user_id TEXT NOT NULL,
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
    pivot_user_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    PRIMARY KEY (pivot_user_id, thread_key)
);
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(pivot_user_id);
CREATE TABLE IF NOT EXISTS file_reads (
    pivot_user_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    first_read_at REAL NOT NULL,
    PRIMARY KEY (pivot_user_id, matter_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_file_reads_matter
    ON file_reads(matter_id, filename);
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
CREATE TABLE IF NOT EXISTS relevance_events (
    pivot_user_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    kind          TEXT NOT NULL,
    reason        TEXT NOT NULL,
    event_at      TEXT NOT NULL,
    actor_pinyin  TEXT NOT NULL,
    created_at    REAL NOT NULL,
    read_at       REAL,
    PRIMARY KEY (pivot_user_id, matter_id, filename, kind, event_at, actor_pinyin)
);
CREATE INDEX IF NOT EXISTS idx_re_user_unread
    ON relevance_events(pivot_user_id, read_at, matter_id);
CREATE TABLE IF NOT EXISTS user_preferences (
    pivot_user_id TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    updated_at   REAL NOT NULL,
    PRIMARY KEY (pivot_user_id, key)
);
-- Scoring system (Matter 进入 finished 后由 AI 基于时间线生成 owner 评分)
-- See AI-docs/designs/scoring-system-v0.3.md for the design rationale.
-- pivot_user_id columns reference pivot_user(id) — informational only since
-- PRAGMA foreign_keys is not enabled; values are kept valid by construction
-- (resolve.py looks up pivot_user before writing).
CREATE TABLE IF NOT EXISTS matter_scoring_runs (
    run_id              TEXT PRIMARY KEY,
    matter_id           TEXT NOT NULL,
    matter_category     TEXT NOT NULL,
    subject_user_id     TEXT NOT NULL,
    triggered_by        TEXT NOT NULL,
    triggered_actor_id  TEXT,
    status              TEXT NOT NULL,
    error               TEXT,
    model               TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    started_at          REAL NOT NULL,
    finished_at         REAL,
    timeline_hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scoring_runs_matter
    ON matter_scoring_runs(matter_id, started_at DESC);
-- Partial unique index: only one in-flight run per (matter, timeline_hash).
-- Skipped/failed/success runs are excluded — we allow multiple success rows
-- (admin reruns are an audit trail; UI shows the latest). The has_success()
-- check in worker.py is what actually blocks duplicate auto-triggers; this
-- index only protects against concurrent in-flight collisions.
CREATE UNIQUE INDEX IF NOT EXISTS idx_scoring_runs_idempotency
    ON matter_scoring_runs(matter_id, timeline_hash)
    WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS matter_scores (
    run_id            TEXT NOT NULL,
    subject_user_id   TEXT NOT NULL,
    matter_id         TEXT NOT NULL,
    overall           REAL NOT NULL,
    confidence        TEXT NOT NULL,
    rationale         TEXT NOT NULL,
    delivery          REAL,
    accountability    REAL,
    collaboration     REAL,
    judgment          REAL,
    process           REAL,
    human_override_overall REAL,
    human_override_note    TEXT,
    human_override_by      TEXT,
    human_override_at      REAL,
    PRIMARY KEY (run_id, subject_user_id)
);
CREATE INDEX IF NOT EXISTS idx_matter_scores_matter
    ON matter_scores(matter_id, subject_user_id);
CREATE TABLE IF NOT EXISTS matter_score_evidence (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    matter_id                   TEXT NOT NULL,
    subject_user_id             TEXT NOT NULL,
    dimension                   TEXT NOT NULL,
    polarity                    TEXT NOT NULL,
    confidence                  TEXT NOT NULL,
    source_kind                 TEXT NOT NULL,
    source_filename             TEXT NOT NULL,
    source_file_type            TEXT NOT NULL,
    source_comment_created_at   TEXT,
    source_comment_author_id    TEXT,
    weight_applied              REAL NOT NULL DEFAULT 1.0,
    quote                       TEXT NOT NULL,
    explanation                 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_run_subject
    ON matter_score_evidence(run_id, subject_user_id, dimension);
CREATE TABLE IF NOT EXISTS scoring_commenter_weights (
    pivot_user_id   TEXT PRIMARY KEY,
    weight          REAL NOT NULL,
    label           TEXT NOT NULL,
    note            TEXT,
    updated_at      REAL NOT NULL,
    updated_by      TEXT NOT NULL
);
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
            "SELECT pivot_user_id, thread_key, context_files_json FROM ai_conversations"
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
                " WHERE pivot_user_id=? AND thread_key=?",
                (target, __import__("json").dumps(refs), row["pivot_user_id"], row["thread_key"]),
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
    # Scoring v0.3 → v0.3.1: relax idempotency idx (drop 'success' from the
    # active-statuses set) so admin reruns can record a new run alongside
    # prior successes. CREATE UNIQUE INDEX IF NOT EXISTS in SCHEMA wouldn't
    # change a pre-existing index definition; explicit DROP+CREATE forces
    # the new shape on dev DBs that were created against the old SCHEMA.
    conn.execute("DROP INDEX IF EXISTS idx_scoring_runs_idempotency")
    conn.execute(
        "CREATE UNIQUE INDEX idx_scoring_runs_idempotency"
        " ON matter_scoring_runs(matter_id, timeline_hash)"
        " WHERE status IN ('queued','running')"
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
