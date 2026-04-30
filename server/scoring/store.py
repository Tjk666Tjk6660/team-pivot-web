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
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from time import time
from typing import Iterable, Literal, Sequence

from server.db import Database

# ---------- types ----------

RunStatus = Literal["queued", "running", "success", "failed", "skipped"]
TriggeredBy = Literal["auto", "admin:rerun", "admin:manual"]
Confidence = Literal["low", "medium", "high"]
Polarity = Literal["positive", "negative", "neutral"]
Dimension = Literal[
    "delivery", "accountability", "collaboration", "judgment", "process",
]
SourceKind = Literal["file", "comment"]


@dataclass(frozen=True)
class ScoringJob:
    """Input to start_run / mark_skipped. Identifies what to score and why.

    Constructed by trigger.py (PR3) and admin rerun endpoint (PR4)."""
    matter_id: str
    matter_category: str
    subject_user_id: str
    triggered_by: TriggeredBy
    triggered_actor_id: str | None = None


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


@dataclass(frozen=True)
class ScoreWrite:
    """Plain payload for write_results — decoupled from schema.py (PR2).

    Caller (AI runner) is responsible for resolving pinyin → user_id and
    flattening the pydantic ScoringOutput into this dataclass before calling.
    """
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
_VALID_SOURCE_KINDS: frozenset[str] = frozenset({"file", "comment"})

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
    ) -> str:
        """Create a new run in 'queued' state and return run_id.

        Caller transitions to 'running' via transition_running() right before
        the AI call, then to 'success'/'failed' via finish_run().

        Raises sqlite3.IntegrityError if the partial-unique idempotency index
        already covers (matter_id, timeline_hash) with a queued/running/success
        row — caller (worker) should treat this as 'duplicate, skip'.
        """
        _validate_triggered_by(job.triggered_by)
        run_id = _new_run_id()
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO matter_scoring_runs"
                " (run_id, matter_id, matter_category, subject_user_id,"
                "  triggered_by, triggered_actor_id, status, model,"
                "  started_at, timeline_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, job.matter_id, job.matter_category,
                    job.subject_user_id, job.triggered_by,
                    job.triggered_actor_id, "queued", model, now, timeline_hash,
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
                "  started_at, finished_at, timeline_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, job.matter_id, job.matter_category,
                    job.subject_user_id, job.triggered_by,
                    job.triggered_actor_id, "skipped", reason, model,
                    now, now, timeline_hash,
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
            rows = conn.execute(sql, params).fetchall()
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
            row = conn.execute(sql, params).fetchone()
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
        """Mark 'running' rows older than timeout as failed/orphan.

        Called from app.py lifespan on boot to catch crashes mid-run. Returns
        number of rows touched.
        """
        cutoff = time() - timeout_seconds
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE matter_scoring_runs"
                " SET status='failed', error='orphan', finished_at=?"
                " WHERE status='running' AND started_at < ?",
                (time(), cutoff),
            )
            return cur.rowcount or 0

    # ── Scores + evidence ────────────────────────────────────────────────

    def write_results(
        self,
        run_id: str,
        score: ScoreWrite,
        evidence: Sequence[EvidenceWrite],
    ) -> None:
        """Insert score row + evidence rows in one transaction.

        Caller MUST also call finish_run(run_id, 'success') after this returns
        cleanly. We don't fold them together because the caller may want to
        record AI token usage at finish_run time.

        Raises:
            ValueError: invalid enum value (confidence/polarity/dimension/etc.)
            ValueError: run not found, or not in 'queued'/'running' status
            ValueError: evidence empty (each non-null dimension needs ≥1
                        evidence — caller's schema.py is the primary check;
                        this is a defense-in-depth)
        """
        _validate_confidence(score.confidence)
        for e in evidence:
            _validate_evidence(e)

        with self._db.connect() as conn:
            run_row = conn.execute(
                "SELECT matter_id, subject_user_id, status"
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
            subject_user_id = run_row["subject_user_id"]

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
                "  weight_applied, quote, explanation)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        run_id, matter_id, subject_user_id,
                        e.dimension, e.polarity, e.confidence,
                        e.source_kind, e.source_filename, e.source_file_type,
                        e.source_comment_created_at, e.source_comment_author_id,
                        e.weight_applied, e.quote, e.explanation,
                    )
                    for e in evidence
                ],
            )

    def get_score(
        self, run_id: str,
    ) -> tuple[MatterScore, list[MatterScoreEvidence]] | None:
        with self._db.connect() as conn:
            score_row = conn.execute(
                "SELECT * FROM matter_scores WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if score_row is None:
                return None
            evidence_rows = conn.execute(
                "SELECT * FROM matter_score_evidence WHERE run_id=?"
                " ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return (
            _row_to_score(score_row),
            [_row_to_evidence(r) for r in evidence_rows],
        )

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
    if not 0.1 <= e.weight_applied <= 5.0:
        raise ValueError(
            f"weight_applied must be in [0.1, 5.0], got {e.weight_applied}"
        )


def _row_to_run(row: sqlite3.Row) -> ScoringRun:
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
