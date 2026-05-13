from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from time import time

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
    role TEXT NOT NULL DEFAULT '["member"]',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
    status_note TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_login_at REAL,
    status_changed_at REAL,
    status_changed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pivot_user_role_status ON pivot_user(role, status);

CREATE TABLE IF NOT EXISTS pivot_role (
    name TEXT PRIMARY KEY,
    label TEXT,
    kind TEXT NOT NULL DEFAULT 'business' CHECK(kind IN ('system','business')),
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pivot_role_active ON pivot_role(is_active, kind, name);

CREATE TABLE IF NOT EXISTS category_visibility_cache (
    category_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'public' CHECK(mode IN ('public','restricted')),
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS category_visibility_role_cache (
    category_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (category_id, role)
);
CREATE TABLE IF NOT EXISTS matter_visibility_cache (
    matter_id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'public' CHECK(mode IN ('public','restricted')),
    creator_id TEXT,
    owner_id TEXT,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_matter_visibility_cache_category
    ON matter_visibility_cache(category_id);
CREATE TABLE IF NOT EXISTS matter_visibility_role_cache (
    matter_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (matter_id, role)
);
CREATE TABLE IF NOT EXISTS matter_visibility_user_cache (
    matter_id TEXT NOT NULL,
    pivot_user_id TEXT NOT NULL,
    PRIMARY KEY (matter_id, pivot_user_id)
);

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
    reject_reason TEXT,
    via_invite_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_join_app_pending_unique
    ON join_application(provider, external_id) WHERE status='pending';

CREATE TABLE IF NOT EXISTS invite (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
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
    timeline_hash       TEXT NOT NULL,
    -- v2.1 (Phase 2): 1 = Phase 1 owner-only / single-row scoring;
    -- 2 = Phase 2 multi-subject. Frontend reads this to choose render mode.
    -- Default 1 means freshly inserted rows from the Phase 1 worker keep
    -- the legacy semantics; Phase 2 worker (Task 2.4) passes 2 explicitly.
    schema_version      INTEGER NOT NULL DEFAULT 1,
    -- v2.2: AI's skipped_subjects array (pinyin list, JSON-encoded).
    -- Candidates the AI considered but judged "evidence insufficient → all
    -- dimensions null → don't score". Surfaced in admin UI so the operator
    -- knows the AI saw that person and made an explicit decision, not a
    -- silent omission. NULL on legacy runs / runs that didn't capture this.
    skipped_subjects    TEXT
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
    -- AI-derived interpretation (matter 003 §4 / 007 §1.3 boundary):
    dimension                   TEXT NOT NULL,
    polarity                    TEXT NOT NULL,
    confidence                  TEXT NOT NULL,
    -- User original input (sourced from timeline / annotation YAML):
    source_kind                 TEXT NOT NULL,  -- 'file' | 'comment' | 'annotation' (v2.1)
    source_filename             TEXT NOT NULL,
    source_file_type            TEXT NOT NULL,
    source_comment_created_at   TEXT,
    source_comment_author_id    TEXT,
    source_annotation_created_at  TEXT,         -- v2.1: annotation evidence
    source_annotation_author_id   TEXT,         -- v2.1: annotation evidence
    -- v2.1 attribution: which 005 决策链 path put this evidence onto the
    -- subject. NULL on legacy rows. Enum values:
    --   'file_creator' | 'explicit_mention' | 'at_target' |
    --   'owner_change_reason' | 'verify_outcome'
    attribution_basis           TEXT,
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
-- =========================================================================
-- git push outbox (方案 A · Write Pipeline)
--
-- 写盘和 git push 解耦：write_session 完成本地 commit 后，往本表 enqueue 一行
-- pending；后台 GitWorker 串行消费，把若干 pending 合并为一次 push。
--
-- 设计要点：
--   * 表的存在 = "本地有 commit 等待推送"。Worker 拿到 N 条 pending → 一次
--     git push 解决全部 → 一并 mark_succeeded。多次 enqueue 只产生一次 push。
--   * tenant_id 为 SaaS 接口位（§9.1 #1），单租户期固定 'default'。
--   * status='in_flight' 用于 worker 在执行 push 期间的可见状态，崩溃恢复时
--     由 sweep_in_flight 回滚到 'pending'，下次自然重试。
--   * partial index 仅覆盖 pending/in_flight，让 worker poll 走索引 + 不让
--     succeeded 历史无限堆积影响查询；succeeded 行可由后续 vacuum 清理。
-- =========================================================================
CREATE TABLE IF NOT EXISTS git_push_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    enqueued_at     REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_flight', 'succeeded', 'failed')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL,
    last_error      TEXT,
    succeeded_at    REAL,
    -- 触发该入队的提交摘要，仅用于审计/调试，不参与 push 逻辑
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_git_push_outbox_pending
    ON git_push_outbox(tenant_id, status, enqueued_at)
    WHERE status IN ('pending', 'in_flight');
-- Daily report v2: 多任务管理
-- 字段值集合(view / status / push_freq / channel / receiver_type)统一在
-- 代码层校验:jobs_repo Literal + Pydantic JobIn/JobUpdateIn。SQLite CHECK
-- 不支持 ALTER,放在表里只会成为扩枚举的绊脚石。
CREATE TABLE IF NOT EXISTS daily_report_jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    view             TEXT NOT NULL,                                 -- 'company' | 'personal'
    status           TEXT NOT NULL DEFAULT 'active',                -- 'active' | 'paused' | 'archived'
    push_time        TEXT NOT NULL,                                 -- 'HH:MM' Asia/Shanghai
    push_freq        TEXT NOT NULL DEFAULT 'weekdays',              -- 见 jobs_repo.PushFreq(共 11 值)
    window_hours     INTEGER NOT NULL DEFAULT 24,                   -- Pydantic 层限定 1-168
    channel          TEXT NOT NULL DEFAULT 'feishu',                -- v1 仅 feishu
    receiver_type    TEXT NOT NULL,                                 -- 'groups' | 'users'
    receiver_ids     TEXT,                                          -- JSON 数组,NULL = 默认全部 bot 群
    next_run_at      REAL,                                          -- Unix epoch,active 时才有值
    last_run_id      INTEGER,                                       -- 引用 daily_report_runs(id),代码层维护
    last_status      TEXT,                                          -- 冗余 cache:succeeded/failed/partial/missed/skipped/running
    retry_count      INTEGER NOT NULL DEFAULT 0,
    last_notified_at REAL,                                          -- 上次"漏跑/失败通知"时间(去重)
    created_by       TEXT,                                          -- creator open_id
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_report_jobs_active_due
    ON daily_report_jobs(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_daily_report_jobs_status
    ON daily_report_jobs(status);

CREATE TABLE IF NOT EXISTS daily_report_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER,                                        -- NULL = 手动一次性触发(不绑 job)
    trigger_type    TEXT NOT NULL
                    CHECK(trigger_type IN ('scheduled', 'manual', 'retry', 'makeup')),
    view            TEXT NOT NULL,                                  -- 冗余:即使 job 删了也能查历史
    started_at      REAL NOT NULL,
    finished_at     REAL,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running', 'succeeded', 'failed', 'partial', 'skipped')),
    rc              INTEGER,
    cards_sent      INTEGER,
    cards_total     INTEGER,
    ai_tokens_in    INTEGER,
    ai_tokens_out   INTEGER,
    error           TEXT,
    debug_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_daily_report_runs_job_started
    ON daily_report_runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_report_runs_started
    ON daily_report_runs(started_at);
"""


_USER_KEYED_TABLES = (
    "drafts", "read_state", "favorites", "sessions",
    "ai_conversations", "api_tokens", "file_reads",
    "relevance_events", "user_preferences",
)


def _assert_no_legacy_user_open_id(conn) -> None:
    """Refuse to start when downstream tables still carry the legacy
    ``user_open_id`` column. Application code is fully on ``pivot_user_id``
    now (see commit 4b7035f); a database with the old column means the
    user-management migration hasn't been run yet, and silently ALTERing
    the schema here would mask data-quality issues. Tell the operator to
    run scripts/migrate_user_management_v2.py instead.
    """
    legacy_tables: list[str] = []
    for t in _USER_KEYED_TABLES:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,),
        ).fetchone()
        if row is None:
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "user_open_id" in cols:
            legacy_tables.append(t)
    if legacy_tables:
        raise RuntimeError(
            "Database still has legacy user_open_id column on: "
            f"{legacy_tables}. Run "
            "`uv run python scripts/migrate_user_management_v2.py "
            "--db <path> --initial-admin <pinyin>` before starting the "
            "server."
        )


def _migrate(conn) -> None:
    """执行数据库迁移。

    逐个检查旧表结构是否缺字段、缺索引或仍保留旧约束；
    如果发现老版本 schema，就补列、建索引、重建表或一次性回填数据，
    确保旧数据库能够平滑升级到当前版本。
    """
    _assert_no_legacy_user_open_id(conn)

    # join_application 表新增 via_invite_id，用于标记申请来自哪个邀请。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(join_application)")}
    if "via_invite_id" not in cols:
        conn.execute(
            "ALTER TABLE join_application ADD COLUMN via_invite_id TEXT"
        )

    # invite 表在新邀请模型里去掉了 email/display_name 字段，旧表直接重建。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(invite)")}
    if "email" in cols:
        conn.execute("DROP TABLE invite")
        conn.execute("""
            CREATE TABLE invite (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used_at REAL,
                used_by_user_id TEXT
            )
        """)

    # users 表增加 markdown_style，保存用户的 Markdown 渲染偏好。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "markdown_style" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN markdown_style TEXT")

    # drafts 表补充提及、回复和引用相关字段。
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
        # matter 草稿复用 drafts 表，专属结构化字段统一放到这一列中。
        conn.execute("ALTER TABLE drafts ADD COLUMN matter_payload_json TEXT")

    # sessions 表补充 user_access_token，便于会话关联飞书 access token。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "user_access_token" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_access_token TEXT")

    # AI 会话表补充上下文文件、回复目标和参考文件字段。
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
        # 一次性回填：把旧的 context_files_json 拆成 reply_target 和 reference_files_json。
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

    # tool-use 版本首次启动时清空旧 AI 对话，避免和新 schema 混用。
    if "schema_ver" not in cols:
        conn.execute(
            "ALTER TABLE ai_conversations ADD COLUMN schema_ver INTEGER NOT NULL DEFAULT 1"
        )
        conn.execute("DELETE FROM ai_conversations")

    # contacts 表补充拼音字段，并回填已有联系人拼音。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(contacts)")}
    if "pinyin" not in cols:
        conn.execute("ALTER TABLE contacts ADD COLUMN pinyin TEXT")
        from server.contacts import name_to_pinyin
        for row in conn.execute("SELECT open_id, name FROM contacts").fetchall():
            conn.execute(
                "UPDATE contacts SET pinyin=? WHERE open_id=?",
                (name_to_pinyin(row["name"] or ""), row["open_id"]),
            )

    # 联系人拼音索引：保证按拼音搜索更快，且对新旧库都幂等。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contacts_pinyin ON contacts(pinyin)"
    )

    # 重建评分幂等索引：让 running/queued 的判定符合新逻辑。
    conn.execute("DROP INDEX IF EXISTS idx_scoring_runs_idempotency")
    conn.execute(
        "CREATE UNIQUE INDEX idx_scoring_runs_idempotency"
        " ON matter_scoring_runs(matter_id, timeline_hash)"
        " WHERE status IN ('queued','running')"
    )

    # matter_scoring_runs / matter_score_evidence 补充新评分 schema 字段。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_scoring_runs)")}
    if "schema_version" not in cols:
        # 旧数据默认视为 v1。
        conn.execute(
            "ALTER TABLE matter_scoring_runs"
            " ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
        )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_score_evidence)")}
    if "source_annotation_created_at" not in cols:
        conn.execute(
            "ALTER TABLE matter_score_evidence"
            " ADD COLUMN source_annotation_created_at TEXT"
        )
    if "source_annotation_author_id" not in cols:
        conn.execute(
            "ALTER TABLE matter_score_evidence"
            " ADD COLUMN source_annotation_author_id TEXT"
        )
    if "attribution_basis" not in cols:
        conn.execute(
            "ALTER TABLE matter_score_evidence ADD COLUMN attribution_basis TEXT"
        )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_scoring_runs)")}
    if "skipped_subjects" not in cols:
        conn.execute(
            "ALTER TABLE matter_scoring_runs ADD COLUMN skipped_subjects TEXT"
        )

    # pivot_user 旧库可能还带着老的 role CHECK 约束，需要重建一次表。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pivot_user)")}
    if "role" in cols:
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='pivot_user'"
        ).fetchone()
        create_sql = str(sql_row["sql"] if sql_row else "")
        if "CHECK(role IN ('admin','member'))" in create_sql:
            conn.executescript(
                """
                ALTER TABLE pivot_user RENAME TO pivot_user_legacy_role_check;
                CREATE TABLE pivot_user (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    pinyin TEXT,
                    email TEXT UNIQUE,
                    avatar_url TEXT NOT NULL DEFAULT '',
                    github_username TEXT,
                    role TEXT NOT NULL DEFAULT '["member"]',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
                    status_note TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_login_at REAL,
                    status_changed_at REAL,
                    status_changed_by TEXT
                );
                INSERT INTO pivot_user
                    (id, display_name, pinyin, email, avatar_url, github_username,
                     role, status, status_note, created_at, updated_at, last_login_at,
                     status_changed_at, status_changed_by)
                SELECT id, display_name, pinyin, email, avatar_url, github_username,
                       role, status, status_note, created_at, updated_at, last_login_at,
                       status_changed_at, status_changed_by
                FROM pivot_user_legacy_role_check;
                DROP TABLE pivot_user_legacy_role_check;
                CREATE INDEX IF NOT EXISTS idx_pivot_user_role_status ON pivot_user(role, status);
                """
            )

    # matter_visibility_cache 新增 creator_id / owner_id，便于筛选与回溯。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matter_visibility_cache)")}
    if cols:
        if "creator_id" not in cols:
            conn.execute("ALTER TABLE matter_visibility_cache ADD COLUMN creator_id TEXT")
        if "owner_id" not in cols:
            conn.execute("ALTER TABLE matter_visibility_cache ADD COLUMN owner_id TEXT")

    # pivot_role 增加 label 字段，支持更友好的角色名称展示。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pivot_role)")}
    if cols and "label" not in cols:
        conn.execute("ALTER TABLE pivot_role ADD COLUMN label TEXT")

    # 补齐系统预置角色，确保迁移后角色数据完整。
    _ensure_pivot_roles(conn)


def _decode_role_cell(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return [raw]


def _ensure_pivot_roles(conn) -> None:
    now = time()
    system_role_labels = {
        "admin": "管理员",
        "member": "成员",
    }
    for name, label in system_role_labels.items():
        conn.execute(
            "INSERT OR IGNORE INTO pivot_role"
            " (name, label, kind, description, is_active, created_at, updated_at)"
            " VALUES (?, ?, 'system', NULL, 1, ?, ?)",
            (name, label, now, now),
        )
        conn.execute(
            "UPDATE pivot_role SET label=?, kind='system' WHERE name=?",
            (label, name),
        )
    rows = conn.execute("SELECT role FROM pivot_user").fetchall()
    for row in rows:
        for role in _decode_role_cell(row["role"]):
            kind = "system" if role in {"admin", "member"} else "business"
            conn.execute(
                "INSERT OR IGNORE INTO pivot_role"
                " (name, label, kind, description, is_active, created_at, updated_at)"
                " VALUES (?, ?, ?, NULL, 1, ?, ?)",
                (role, system_role_labels.get(role), kind, now, now),
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
