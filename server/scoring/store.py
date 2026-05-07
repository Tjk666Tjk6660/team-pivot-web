"""SQLite repo for the Scoring system.

四张表的读写都集中在这里：
    matter_scoring_runs       一次评分任务（queued → running → success/failed/skipped）
    matter_scores              单 matter 单 owner 的评分行（每 run 至多 1 行）
    matter_score_evidence      证据条目，外键挂在 (run_id, subject_user_id)
    scoring_commenter_weights  高权重发言人配置

Design notes:
- write_results(score, evidence) 一个事务里同时写 score 和 evidence，杜绝半成品
- has_success() 配合 idx_scoring_runs_idempotency 部分唯一索引做幂等控制
- sweep_orphans() 启动时清理 running 超时的 run，配合 server/app.py 的 lifespan

PR1 范围 (本模块)：基础 CRUD + 幂等 + sweep。
PR2/3 会再加：从 schema.py 的 ScoringOutput 适配到 ScoreWrite/EvidenceWrite 的胶水。

Phase 2（v2.1）演进：
- matter_scoring_runs 增加 `schema_version`（v1 = Phase 1 owner-only / 单行；
  v2 = Phase 2 multi-subject），让前端按版本号选择渲染逻辑
- matter_score_evidence 增加 `source_annotation_*` + `attribution_basis` 三列
  覆盖 v2.1 的 annotation 强语义证据 + 005 §决策链 attribution 数据
- 字段分两层（matter 003 §4 / 007 §1.3）：
    用户原始输入：source_filename / source_file_type / source_*_author_id /
                  source_*_created_at / quote
    AI 派生解释：dimension / polarity / confidence / attribution_basis /
                  weight_applied / explanation
  下游消费者（admin override / audit / 前端展示）必须分两栏，不能让派生分
  冒充原始输入。
"""
from __future__ import annotations

import logging
import sqlite3
import time as _time
import uuid
from dataclasses import dataclass, field
from time import time
from typing import Iterable, Literal, Sequence

from server.db import Database

log = logging.getLogger(__name__)

# Threshold for warning when a runs-list / count query stalls. Substring
# matter_query goes through LIKE '%xxx%' which can't use the matter_id
# index — full scan, so cost grows ~linearly with table size. Logging
# this lets us notice the day it actually starts mattering and switch
# to FTS5 / denormalized title columns proactively rather than after a
# user complaint.
_SLOW_QUERY_WARN_MS = 200

# ---------- types ----------

RunStatus = Literal["queued", "running", "success", "failed", "skipped"]
TriggeredBy = Literal["auto", "admin:rerun", "admin:manual"]
Confidence = Literal["low", "medium", "high"]
Polarity = Literal["positive", "negative", "neutral"]
Dimension = Literal[
    "delivery", "accountability", "collaboration", "judgment", "process",
]
# v2.1: annotation joins file/comment as a third evidence source kind.
SourceKind = Literal["file", "comment", "annotation"]
# v2.1: how this evidence got attributed to the subject (005 决策链 +
# verify_outcome). Optional column; older runs (Phase 1) leave it NULL.
AttributionBasis = Literal[
    "file_creator",
    "explicit_mention",
    "at_target",
    "owner_change_reason",
    "verify_outcome",
]

# Phase 2 worker (Task 2.4) stamps new runs with version 2; the schema column
# default is also 2 for forward-compat. Existing Phase 1 runs migrated to 1.
RUN_SCHEMA_VERSION_PHASE_1 = 1
RUN_SCHEMA_VERSION_PHASE_2 = 2


@dataclass(frozen=True)
class ScoringJob:
    """Input to start_run / mark_skipped. Identifies what to score and why.

    Constructed by trigger.py (PR3) and admin rerun endpoint (PR4).

    v2.1 (Phase 2): `subject_user_id` is the run's PRIMARY subject — kept as
    matter.owner.id for backward-compat single-row queries (`get_score`, admin
    "score for this owner" UI). `candidate_user_ids` is the full set of
    candidates the AI is allowed to score (think/act file creators per matter
    005); when this is non-empty the worker passes the corresponding pinyin set
    to parse_and_validate, enabling multi-subject scores per run. Phase 1
    callers leave it as `(subject_user_id,)`.
    """
    matter_id: str
    matter_category: str
    subject_user_id: str
    triggered_by: TriggeredBy
    triggered_actor_id: str | None = None
    candidate_user_ids: tuple[str, ...] = field(default_factory=tuple)
    # 2026-05-07 fix: when admin rerun creates the queued row synchronously
    # (so the UI shows the run immediately rather than waiting for worker
    # pickup), it stamps run_id here. Worker reads it instead of calling
    # _try_start_run again. None on auto-trigger path — worker creates the
    # run row itself.
    run_id: str | None = None


@dataclass(frozen=True)
class ScoringRun:
    run_id: str
    matter_id: str
    matter_category: str
    subject_user_id: str
    triggered_by: str
    triggered_actor_id: str | None
    status: str
    error: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    started_at: float
    finished_at: float | None
    timeline_hash: str
    # v2.1: 1 = Phase 1 owner-only / single-row; 2 = Phase 2 multi-subject.
    # Frontend uses this to decide whether to expect a single MatterScore row
    # or N rows for the run.
    schema_version: int = RUN_SCHEMA_VERSION_PHASE_1
    # v2.2: pinyin list of subjects the AI explicitly skipped (insufficient
    # evidence → all dimensions null). Surfaced in admin UI so an empty
    # subject_scores doesn't look like "the system silently ignored this
    # person" — it was a deliberate AI decision.
    skipped_subjects: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreWrite:
    """Plain payload for write_results — decoupled from schema.py (PR2).

    Caller (AI runner) is responsible for resolving pinyin → user_id and
    flattening the pydantic ScoringOutput into this dataclass before calling.

    v2.1 (Phase 2): `subject_user_id` is required and may differ from the
    run's primary subject — under multi-subject mode the run row carries the
    matter.owner as `run.subject_user_id`, but each scored candidate gets its
    own MatterScore row with its own `score.subject_user_id`.
    """
    subject_user_id: str
    overall: float
    confidence: Confidence
    rationale: str
    delivery: float | None = None
    accountability: float | None = None
    collaboration: float | None = None
    judgment: float | None = None
    process: float | None = None


@dataclass(frozen=True)
class EvidenceWrite:
    """Evidence row payload — split into two layers:

    User original input (immutable, sourced from timeline / annotation):
        source_filename, source_file_type, source_comment_*, source_annotation_*,
        quote
    AI-derived interpretation (computed by AI):
        dimension, polarity, confidence, attribution_basis, weight_applied,
        explanation

    Don't blur the line in admin UI / audit — see store.py module docstring.
    """
    dimension: Dimension
    polarity: Polarity
    confidence: Confidence
    source_kind: SourceKind
    source_filename: str
    source_file_type: str
    quote: str
    explanation: str
    source_comment_created_at: str | None = None
    source_comment_author_id: str | None = None
    # v2.1 annotation evidence (parallel to comment fields):
    source_annotation_created_at: str | None = None
    source_annotation_author_id: str | None = None
    # v2.1 attribution: how this evidence got hooked to the subject. Optional;
    # old runs and older AI outputs may leave it NULL.
    attribution_basis: AttributionBasis | None = None
    weight_applied: float = 1.0


@dataclass(frozen=True)
class MatterScore:
    run_id: str
    subject_user_id: str
    matter_id: str
    overall: float
    confidence: str
    rationale: str
    delivery: float | None
    accountability: float | None
    collaboration: float | None
    judgment: float | None
    process: float | None
    human_override_overall: float | None
    human_override_note: str | None
    human_override_by: str | None
    human_override_at: float | None


@dataclass(frozen=True)
class MatterScoreEvidence:
    """Read-side mirror of EvidenceWrite + DB id. Same two-layer split."""
    id: int
    run_id: str
    matter_id: str
    subject_user_id: str
    dimension: str
    polarity: str
    confidence: str
    source_kind: str
    source_filename: str
    source_file_type: str
    source_comment_created_at: str | None
    source_comment_author_id: str | None
    source_annotation_created_at: str | None  # v2.1
    source_annotation_author_id: str | None   # v2.1
    attribution_basis: str | None             # v2.1
    weight_applied: float
    quote: str
    explanation: str


@dataclass(frozen=True)
class CommenterWeight:
    pivot_user_id: str
    weight: float
    label: str
    note: str | None
    updated_at: float
    updated_by: str


# ---------- repo ----------

_VALID_STATUSES: frozenset[str] = frozenset(
    {"queued", "running", "success", "failed", "skipped"}
)
_VALID_TRIGGERED_BY: frozenset[str] = frozenset(
    {"auto", "admin:rerun", "admin:manual"}
)
_VALID_CONFIDENCE: frozenset[str] = frozenset({"low", "medium", "high"})
_VALID_POLARITY: frozenset[str] = frozenset(
    {"positive", "negative", "neutral"}
)
_VALID_DIMENSIONS: frozenset[str] = frozenset(
    {"delivery", "accountability", "collaboration", "judgment", "process"}
)
_VALID_SOURCE_KINDS: frozenset[str] = frozenset({"file", "comment", "annotation"})
_VALID_ATTRIBUTION_BASIS: frozenset[str] = frozenset({
    "file_creator",
    "explicit_mention",
    "at_target",
    "owner_change_reason",
    "verify_outcome",
})

_DEFAULT_ORPHAN_TIMEOUT_SECONDS = 600  # 10 min


class ScoringStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Runs ─────────────────────────────────────────────────────────────

    def start_run(
        self,
        job: ScoringJob,
        *,
        timeline_hash: str,
        model: str,
        schema_version: int = RUN_SCHEMA_VERSION_PHASE_1,
    ) -> str:
        """Create a new run in 'queued' state and return run_id.

        Caller transitions to 'running' via transition_running() right before
        the AI call, then to 'success'/'failed' via finish_run().

        Raises sqlite3.IntegrityError if the partial-unique idempotency index
        already covers (matter_id, timeline_hash) with a queued/running/success
        row — caller (worker) should treat this as 'duplicate, skip'.

        schema_version defaults to 1 (Phase 1 owner-only). Phase 2 worker
        (Task 2.4) bumps this to 2 when emitting multi-subject runs.
        """
        _validate_triggered_by(job.triggered_by)
        run_id = _new_run_id()
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO matter_scoring_runs"
                " (run_id, matter_id, matter_category, subject_user_id,"
                "  triggered_by, triggered_actor_id, status, model,"
                "  started_at, timeline_hash, schema_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, job.matter_id, job.matter_category,
                    job.subject_user_id, job.triggered_by,
                    job.triggered_actor_id, "queued", model, now, timeline_hash,
                    schema_version,
                ),
            )
        return run_id

    def transition_running(self, run_id: str) -> None:
        """Move queued → running. Idempotent if already running."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE matter_scoring_runs SET status='running'"
                " WHERE run_id=? AND status IN ('queued','running')",
                (run_id,),
            )

    def set_skipped_subjects(
        self, run_id: str, skipped: Sequence[str],
    ) -> None:
        """v2.2: persist AI-decided skipped pinyin list onto the run row.

        Worker calls this once after AI returns parsed output but before
        finish_run. Stored as JSON array (sqlite TEXT). Empty list also
        written explicitly so consumers can distinguish "AI said skip = []"
        from "this is a legacy run that didn't capture skipped".
        """
        import json as _j
        payload = _j.dumps(list(skipped), ensure_ascii=False)
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE matter_scoring_runs SET skipped_subjects=?"
                " WHERE run_id=?",
                (payload, run_id),
            )

    def finish_run(
        self,
        run_id: str,
        status: Literal["success", "failed"],
        *,
        error: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        if status not in ("success", "failed"):
            raise ValueError(
                f"finish_run status must be 'success' or 'failed', got {status!r}"
            )
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE matter_scoring_runs"
                " SET status=?, error=?, prompt_tokens=?, completion_tokens=?,"
                "     finished_at=?"
                " WHERE run_id=?",
                (status, error, prompt_tokens, completion_tokens, time(), run_id),
            )

    def mark_skipped(
        self,
        job: ScoringJob,
        *,
        timeline_hash: str,
        reason: str,
        model: str | None = None,
        schema_version: int = RUN_SCHEMA_VERSION_PHASE_1,
    ) -> str:
        """Record a 'we got the trigger but didn't run AI' row for observability.

        Skipped rows do NOT participate in the idempotency partial index, so
        multiple skips for the same (matter_id, timeline_hash) are allowed.
        """
        _validate_triggered_by(job.triggered_by)
        run_id = _new_run_id()
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO matter_scoring_runs"
                " (run_id, matter_id, matter_category, subject_user_id,"
                "  triggered_by, triggered_actor_id, status, error, model,"
                "  started_at, finished_at, timeline_hash, schema_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, job.matter_id, job.matter_category,
                    job.subject_user_id, job.triggered_by,
                    job.triggered_actor_id, "skipped", reason, model,
                    now, now, timeline_hash, schema_version,
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> ScoringRun | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM matter_scoring_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def has_success(self, matter_id: str, timeline_hash: str) -> bool:
        """True if a (queued | running | success) run already covers this
        timeline version. Used by worker to short-circuit auto reruns."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM matter_scoring_runs"
                " WHERE matter_id=? AND timeline_hash=?"
                "   AND status IN ('queued','running','success')"
                " LIMIT 1",
                (matter_id, timeline_hash),
            ).fetchone()
        return row is not None

    def latest_success_for_matter(self, matter_id: str) -> ScoringRun | None:
        """Most recent successful run for a matter — what the UI shows by default."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM matter_scoring_runs"
                " WHERE matter_id=? AND status='success'"
                " ORDER BY started_at DESC"
                " LIMIT 1",
                (matter_id,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def list_matter_groups(
        self,
        *,
        matter_query: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[str], int]:
        """Matter-centric pagination for the admin list view.

        Returns (matter_ids_for_this_page, total_distinct_matter_count).
        Matters are sorted by their most-recent run's started_at desc — so
        the user sees freshly-active matters first, regardless of how many
        reruns each has accumulated.

        Status filter is intentionally left out: at the matter level, a
        single status (e.g. "失败") is misleading — a matter typically has
        a mix of run statuses across reruns. Status filtering belongs on
        the per-run history view (kept on list_runs).
        """
        where = ""
        params: list[object] = []
        if matter_query:
            escaped = (
                matter_query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where = " WHERE matter_id LIKE ? ESCAPE '\\'"
            params.append(f"%{escaped}%")

        with self._db.connect() as conn:
            t0 = _time.perf_counter()
            count_row = conn.execute(
                f"SELECT COUNT(DISTINCT matter_id) AS n"
                f"  FROM matter_scoring_runs{where}",
                params,
            ).fetchone()
            total = int(count_row["n"])

            page_rows = conn.execute(
                f"SELECT matter_id, MAX(started_at) AS latest"
                f"  FROM matter_scoring_runs{where}"
                f" GROUP BY matter_id"
                f" ORDER BY latest DESC"
                f" LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            _warn_if_slow(
                "list_matter_groups", t0, matter_query=matter_query,
            )
        return [r["matter_id"] for r in page_rows], total

    def list_runs_for_matter(self, matter_id: str) -> list[ScoringRun]:
        """All runs for a single matter, latest first. Used by the matter
        rollup view to render rerun history under each matter row."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM matter_scoring_runs"
                " WHERE matter_id=?"
                " ORDER BY started_at DESC",
                (matter_id,),
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def list_runs(
        self,
        *,
        status: str | None = None,
        matter_id: str | None = None,
        matter_query: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScoringRun]:
        sql, params = self._runs_filter_sql(
            status=status, matter_id=matter_id, matter_query=matter_query,
        )
        sql = f"SELECT * FROM matter_scoring_runs WHERE 1=1{sql}"
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._db.connect() as conn:
            t0 = _time.perf_counter()
            rows = conn.execute(sql, params).fetchall()
            _warn_if_slow(
                "list_runs", t0,
                status=status, matter_id=matter_id, matter_query=matter_query,
            )
        return [_row_to_run(r) for r in rows]

    def count_runs(
        self,
        *,
        status: str | None = None,
        matter_id: str | None = None,
        matter_query: str | None = None,
    ) -> int:
        sql, params = self._runs_filter_sql(
            status=status, matter_id=matter_id, matter_query=matter_query,
        )
        sql = f"SELECT COUNT(*) AS n FROM matter_scoring_runs WHERE 1=1{sql}"
        with self._db.connect() as conn:
            t0 = _time.perf_counter()
            row = conn.execute(sql, params).fetchone()
            _warn_if_slow(
                "count_runs", t0,
                status=status, matter_id=matter_id, matter_query=matter_query,
            )
        return int(row["n"])

    @staticmethod
    def _runs_filter_sql(
        *,
        status: str | None,
        matter_id: str | None,
        matter_query: str | None,
    ) -> tuple[str, list[object]]:
        """Build the WHERE-fragment shared by list_runs / count_runs.

        - status: exact match
        - matter_id: exact match (kept for precise back-end lookups)
        - matter_query: case-insensitive LIKE match on matter_id, with %
          and _ in user input escaped so a paste like "10%" doesn't
          accidentally turn into a wildcard.
        """
        sql = ""
        params: list[object] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if matter_id:
            sql += " AND matter_id=?"
            params.append(matter_id)
        if matter_query:
            escaped = (
                matter_query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            sql += " AND matter_id LIKE ? ESCAPE '\\'"
            params.append(f"%{escaped}%")
        return sql, params

    def sweep_orphans(
        self, *, timeout_seconds: float = _DEFAULT_ORPHAN_TIMEOUT_SECONDS,
    ) -> int:
        """Mark abandoned 'running' / 'queued' rows as failed/orphan.

        Called from app.py lifespan on boot to catch crashes mid-run. Both
        statuses are considered orphan because:
          * 'running' — worker died mid-AI-call and never wrote success/failed.
          * 'queued'  — admin pre-created via rerun endpoint; in-memory queue
            was lost on restart and worker never picked up.

        On startup callers pass `timeout_seconds=0` so every active row from
        the previous process gets swept immediately (single-worker
        deployment — no in-flight run can legitimately survive a restart).
        Returns number of rows touched.
        """
        cutoff = time() - timeout_seconds
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE matter_scoring_runs"
                " SET status='failed', error='orphan', finished_at=?"
                " WHERE status IN ('running', 'queued') AND started_at < ?",
                (time(), cutoff),
            )
            return cur.rowcount or 0

    def supersede_active_runs(self, matter_id: str) -> int:
        """Mark all queued/running runs for a matter as failed/superseded.

        Called by the admin rerun endpoint: clicking "重跑" is an explicit
        intent to take over from any in-flight run. Without this, a stuck
        'running' row (e.g. left over from a server crash inside the 10-min
        sweep window) would block new reruns via the partial unique idx
        (matter_id, timeline_hash) WHERE status IN ('queued','running',
        'success') — the new attempt would surface as race_lost.

        Returns number of rows touched.
        """
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE matter_scoring_runs"
                " SET status='failed', error='superseded_by_rerun', finished_at=?"
                " WHERE matter_id=? AND status IN ('queued', 'running')",
                (time(), matter_id),
            )
            return cur.rowcount or 0

    # ── Scores + evidence ────────────────────────────────────────────────

    def write_results(
        self,
        run_id: str,
        score: ScoreWrite,
        evidence: Sequence[EvidenceWrite],
    ) -> None:
        """Insert one subject's score row + evidence rows in one transaction.

        v2.1 (Phase 2): a single run can call this multiple times — once per
        scored candidate. The score's subject_user_id (which may or may not
        match run.subject_user_id) determines which subject row is written.
        Evidence rows carry the same subject_user_id as the score they back.

        Caller MUST also call finish_run(run_id, 'success') after the LAST
        write_results returns cleanly. We don't fold them together because
        the caller may want to record AI token usage + write multiple subjects
        before finishing.

        Raises:
            ValueError: invalid enum value (confidence/polarity/dimension/etc.)
            ValueError: run not found, or not in 'queued'/'running' status
            ValueError: subject_user_id collision (already wrote this subject
                        under this run — caller logic bug)
        """
        _validate_confidence(score.confidence)
        for e in evidence:
            _validate_evidence(e)

        with self._db.connect() as conn:
            run_row = conn.execute(
                "SELECT matter_id, status"
                " FROM matter_scoring_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise ValueError(f"run not found: {run_id}")
            if run_row["status"] not in ("queued", "running"):
                raise ValueError(
                    f"run {run_id} is in status {run_row['status']!r}, "
                    "cannot write results"
                )
            matter_id = run_row["matter_id"]
            subject_user_id = score.subject_user_id

            conn.execute(
                "INSERT INTO matter_scores"
                " (run_id, subject_user_id, matter_id, overall, confidence,"
                "  rationale, delivery, accountability, collaboration,"
                "  judgment, process)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, subject_user_id, matter_id, score.overall,
                    score.confidence, score.rationale,
                    score.delivery, score.accountability, score.collaboration,
                    score.judgment, score.process,
                ),
            )
            conn.executemany(
                "INSERT INTO matter_score_evidence"
                " (run_id, matter_id, subject_user_id, dimension, polarity,"
                "  confidence, source_kind, source_filename, source_file_type,"
                "  source_comment_created_at, source_comment_author_id,"
                "  source_annotation_created_at, source_annotation_author_id,"
                "  attribution_basis,"
                "  weight_applied, quote, explanation)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        run_id, matter_id, subject_user_id,
                        e.dimension, e.polarity, e.confidence,
                        e.source_kind, e.source_filename, e.source_file_type,
                        e.source_comment_created_at, e.source_comment_author_id,
                        e.source_annotation_created_at, e.source_annotation_author_id,
                        e.attribution_basis,
                        e.weight_applied, e.quote, e.explanation,
                    )
                    for e in evidence
                ],
            )

    def get_score(
        self, run_id: str,
    ) -> tuple[MatterScore, list[MatterScoreEvidence]] | None:
        """Return ONE score row + its evidence for backward-compat callers.

        Preference order: matter.owner (run.subject_user_id) first, then any
        other candidate by subject_user_id ascending. Multi-subject runs where
        the owner has no think/act file (and therefore no score row) still
        surface another candidate's score so admin UI doesn't show a blank.
        Use get_scores() to read all candidates.
        """
        with self._db.connect() as conn:
            score_row = conn.execute(
                "SELECT s.* FROM matter_scores s"
                " JOIN matter_scoring_runs r ON r.run_id = s.run_id"
                " WHERE s.run_id=?"
                " ORDER BY (s.subject_user_id = r.subject_user_id) DESC,"
                "   s.subject_user_id ASC"
                " LIMIT 1",
                (run_id,),
            ).fetchone()
            if score_row is None:
                return None
            subject = score_row["subject_user_id"]
            evidence_rows = conn.execute(
                "SELECT * FROM matter_score_evidence"
                " WHERE run_id=? AND subject_user_id=?"
                " ORDER BY id ASC",
                (run_id, subject),
            ).fetchall()
        return (
            _row_to_score(score_row),
            [_row_to_evidence(r) for r in evidence_rows],
        )

    def get_scores(
        self, run_id: str,
    ) -> list[tuple[MatterScore, list[MatterScoreEvidence]]]:
        """v2.1 multi-subject: return ALL score rows for the run, each with
        its own evidence list. Empty list if the run hasn't written results
        yet (or AI explicitly skipped). Order: matter.owner first if present,
        then by subject_user_id ascending for stability."""
        with self._db.connect() as conn:
            score_rows = conn.execute(
                "SELECT s.*,"
                "  (s.subject_user_id = r.subject_user_id) AS is_primary"
                " FROM matter_scores s"
                " JOIN matter_scoring_runs r ON r.run_id = s.run_id"
                " WHERE s.run_id=?"
                " ORDER BY is_primary DESC, s.subject_user_id ASC",
                (run_id,),
            ).fetchall()
            if not score_rows:
                return []
            evidence_rows = conn.execute(
                "SELECT * FROM matter_score_evidence WHERE run_id=?"
                " ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        # Bucket evidence by subject_user_id
        by_subject: dict[str, list[MatterScoreEvidence]] = {}
        for r in evidence_rows:
            by_subject.setdefault(r["subject_user_id"], []).append(_row_to_evidence(r))
        return [
            (_row_to_score(s), by_subject.get(s["subject_user_id"], []))
            for s in score_rows
        ]

    def apply_human_override(
        self,
        run_id: str,
        subject_user_id: str,
        *,
        overall: float,
        note: str,
        by_user_id: str,
    ) -> None:
        """v1.1 endpoint backing — leave the implementation here so v1 schema
        already supports it. v1 admin UI keeps the button disabled."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE matter_scores"
                " SET human_override_overall=?, human_override_note=?,"
                "     human_override_by=?, human_override_at=?"
                " WHERE run_id=? AND subject_user_id=?",
                (overall, note, by_user_id, time(), run_id, subject_user_id),
            )

    # ── Commenter weights ────────────────────────────────────────────────

    def list_weights(self) -> list[CommenterWeight]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scoring_commenter_weights"
                " ORDER BY weight DESC, label ASC",
            ).fetchall()
        return [_row_to_weight(r) for r in rows]

    def get_weight(self, pivot_user_id: str) -> CommenterWeight | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM scoring_commenter_weights WHERE pivot_user_id=?",
                (pivot_user_id,),
            ).fetchone()
        return _row_to_weight(row) if row else None

    def upsert_weight(
        self,
        *,
        pivot_user_id: str,
        weight: float,
        label: str,
        note: str | None,
        updated_by: str,
    ) -> CommenterWeight:
        if not 0.1 <= weight <= 5.0:
            raise ValueError(
                f"weight must be in [0.1, 5.0], got {weight}"
            )
        if not label or not label.strip():
            raise ValueError("label is required")
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO scoring_commenter_weights"
                " (pivot_user_id, weight, label, note, updated_at, updated_by)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(pivot_user_id) DO UPDATE SET"
                "   weight=excluded.weight,"
                "   label=excluded.label,"
                "   note=excluded.note,"
                "   updated_at=excluded.updated_at,"
                "   updated_by=excluded.updated_by",
                (pivot_user_id, weight, label.strip(), note, now, updated_by),
            )
        got = self.get_weight(pivot_user_id)
        assert got is not None
        return got

    def delete_weight(self, pivot_user_id: str) -> bool:
        with self._db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM scoring_commenter_weights WHERE pivot_user_id=?",
                (pivot_user_id,),
            )
            return (cur.rowcount or 0) > 0


# ---------- helpers ----------


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _warn_if_slow(query_name: str, start_perf: float, **filters: object) -> None:
    """Emit WARNING when a list / count query crosses _SLOW_QUERY_WARN_MS.

    Filters dict is passed for quick triage — typically tells you whether a
    matter_query substring search is dragging the page (LIKE '%x%' bypasses
    the matter_id index and full-scans the runs table).
    """
    elapsed_ms = (_time.perf_counter() - start_perf) * 1000.0
    if elapsed_ms < _SLOW_QUERY_WARN_MS:
        return
    nonempty = {k: v for k, v in filters.items() if v}
    log.warning(
        "scoring %s slow: %.0fms (filters=%r) — consider FTS5 / denormalized title",
        query_name, elapsed_ms, nonempty,
    )


def _validate_triggered_by(v: str) -> None:
    if v not in _VALID_TRIGGERED_BY:
        raise ValueError(
            f"triggered_by must be one of {sorted(_VALID_TRIGGERED_BY)}, "
            f"got {v!r}"
        )


def _validate_confidence(v: str) -> None:
    if v not in _VALID_CONFIDENCE:
        raise ValueError(
            f"confidence must be one of {sorted(_VALID_CONFIDENCE)}, got {v!r}"
        )


def _validate_evidence(e: EvidenceWrite) -> None:
    if e.dimension not in _VALID_DIMENSIONS:
        raise ValueError(f"invalid dimension: {e.dimension!r}")
    if e.polarity not in _VALID_POLARITY:
        raise ValueError(f"invalid polarity: {e.polarity!r}")
    if e.confidence not in _VALID_CONFIDENCE:
        raise ValueError(f"invalid confidence: {e.confidence!r}")
    if e.source_kind not in _VALID_SOURCE_KINDS:
        raise ValueError(f"invalid source_kind: {e.source_kind!r}")
    if e.source_kind == "comment" and not e.source_comment_created_at:
        raise ValueError(
            "comment-kind evidence requires source_comment_created_at"
        )
    if e.source_kind == "annotation" and not e.source_annotation_created_at:
        raise ValueError(
            "annotation-kind evidence requires source_annotation_created_at"
        )
    if e.attribution_basis is not None and e.attribution_basis not in _VALID_ATTRIBUTION_BASIS:
        raise ValueError(
            f"invalid attribution_basis: {e.attribution_basis!r}"
        )
    if not 0.1 <= e.weight_applied <= 5.0:
        raise ValueError(
            f"weight_applied must be in [0.1, 5.0], got {e.weight_applied}"
        )


def _row_to_run(row: sqlite3.Row) -> ScoringRun:
    # schema_version may be NULL on legacy migrated rows pre-v2.1; treat as 1.
    keys = row.keys()
    raw_sv = row["schema_version"] if "schema_version" in keys else None
    schema_version = int(raw_sv) if raw_sv is not None else RUN_SCHEMA_VERSION_PHASE_1
    skipped: tuple[str, ...] = ()
    if "skipped_subjects" in keys and row["skipped_subjects"]:
        try:
            import json as _j
            parsed = _j.loads(row["skipped_subjects"])
            if isinstance(parsed, list):
                skipped = tuple(str(p) for p in parsed)
        except (ValueError, TypeError):
            pass  # corrupt JSON — treat as empty
    return ScoringRun(
        run_id=row["run_id"],
        matter_id=row["matter_id"],
        matter_category=row["matter_category"],
        subject_user_id=row["subject_user_id"],
        triggered_by=row["triggered_by"],
        triggered_actor_id=row["triggered_actor_id"],
        status=row["status"],
        error=row["error"],
        model=row["model"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        timeline_hash=row["timeline_hash"],
        schema_version=schema_version,
        skipped_subjects=skipped,
    )


def _row_to_score(row: sqlite3.Row) -> MatterScore:
    return MatterScore(
        run_id=row["run_id"],
        subject_user_id=row["subject_user_id"],
        matter_id=row["matter_id"],
        overall=row["overall"],
        confidence=row["confidence"],
        rationale=row["rationale"],
        delivery=row["delivery"],
        accountability=row["accountability"],
        collaboration=row["collaboration"],
        judgment=row["judgment"],
        process=row["process"],
        human_override_overall=row["human_override_overall"],
        human_override_note=row["human_override_note"],
        human_override_by=row["human_override_by"],
        human_override_at=row["human_override_at"],
    )


def _row_to_evidence(row: sqlite3.Row) -> MatterScoreEvidence:
    keys = row.keys()
    return MatterScoreEvidence(
        id=row["id"],
        run_id=row["run_id"],
        matter_id=row["matter_id"],
        subject_user_id=row["subject_user_id"],
        dimension=row["dimension"],
        polarity=row["polarity"],
        confidence=row["confidence"],
        source_kind=row["source_kind"],
        source_filename=row["source_filename"],
        source_file_type=row["source_file_type"],
        source_comment_created_at=row["source_comment_created_at"],
        source_comment_author_id=row["source_comment_author_id"],
        # v2.1 columns; NULL on rows written before the migration.
        source_annotation_created_at=(
            row["source_annotation_created_at"]
            if "source_annotation_created_at" in keys
            else None
        ),
        source_annotation_author_id=(
            row["source_annotation_author_id"]
            if "source_annotation_author_id" in keys
            else None
        ),
        attribution_basis=(
            row["attribution_basis"] if "attribution_basis" in keys else None
        ),
        weight_applied=row["weight_applied"],
        quote=row["quote"],
        explanation=row["explanation"],
    )


def _row_to_weight(row: sqlite3.Row) -> CommenterWeight:
    return CommenterWeight(
        pivot_user_id=row["pivot_user_id"],
        weight=row["weight"],
        label=row["label"],
        note=row["note"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )
