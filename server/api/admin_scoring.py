"""Admin API for the Matter scoring system (PR4).

All endpoints behind `admin_user_dep` (cookie session + role='admin' check via
`make_require_admin_user_cookie`). PATs cannot read/write scoring config or
trigger reruns — same gate as /api/admin/users/*, /api/admin/invites/*, etc.

Endpoints:
  GET    /api/admin/scoring/config                       开关 + 可见范围 + 模型 + 超时
  PUT    /api/admin/scoring/config
  GET    /api/admin/scoring/runs?status=&matter_id=&limit=&offset=
  GET    /api/admin/scoring/runs/{run_id}                完整 run + score + evidence
  POST   /api/admin/scoring/matters/{matter_id}/rerun    手动入队（绕过幂等）

  GET    /api/admin/scoring/commenter-weights
  POST   /api/admin/scoring/commenter-weights
  PUT    /api/admin/scoring/commenter-weights/{user_id}
  DELETE /api/admin/scoring/commenter-weights/{user_id}

设计取舍：
- list/detail 端点做服务端 enrichment（matter title / subject 显示名 / 头像）
  让前端不用二次查 — admin UI 列表里这些字段必显
- rerun 端点同步入队 + 立即返回 + matter_id；前端拿到后轮询 /runs 列表
- weights 增删改单独走，不和 config 端点混合（前端两块 UI 独立）
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUser, PivotUserRepo
from server.scoring.resolve import PinyinResolver
from server.scoring.store import (
    CommenterWeight,
    MatterScore,
    MatterScoreEvidence,
    ScoringJob,
    ScoringRun,
    ScoringStore,
)
from server.scoring.trigger import (
    KEY_ENABLED,
    KEY_MODEL,
    KEY_TIMEOUT_SECONDS,
    KEY_VISIBILITY,
    resolve_candidates,
)
from server.settings import SettingsRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)

DEFAULT_VISIBILITY = "admin_only"
DEFAULT_TIMEOUT_SECONDS = 180


# --------------------------------------------------------------------------- #
# Pydantic models                                                             #
# --------------------------------------------------------------------------- #


class ScoringConfig(BaseModel):
    enabled: bool = False
    visibility: Literal["admin_only", "subjects", "all"] = "admin_only"
    model: str = ""  # empty = inherit from main ai.model
    timeout_seconds: int = Field(default=120, ge=1, le=600)


class CommenterWeightIn(BaseModel):
    pivot_user_id: str = Field(min_length=1, max_length=100)
    weight: float = Field(ge=0.1, le=5.0)
    label: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=200)


class CommenterWeightUpdate(BaseModel):
    weight: float | None = Field(default=None, ge=0.1, le=5.0)
    label: str | None = Field(default=None, min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=200)


class RerunResponse(BaseModel):
    ok: bool
    matter_id: str
    queued: bool
    message: str


class HumanOverrideBody(BaseModel):
    overall: float = Field(ge=1.0, le=5.0)
    note: str = Field(min_length=1, max_length=500)


# --------------------------------------------------------------------------- #
# Router                                                                      #
# --------------------------------------------------------------------------- #


def build_router(
    *,
    store: ScoringStore,
    queue,                        # ScoringQueue (duck-typed .enqueue)
    workspace: Workspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/scoring")

    # ── Config ──────────────────────────────────────────────────────────

    @router.get("/config")
    def get_config(_: PivotUser = Depends(admin_user_dep)) -> ScoringConfig:
        return ScoringConfig(
            enabled=_read_bool(settings, KEY_ENABLED, default=False),
            visibility=_read_visibility(settings),
            model=(settings.get(KEY_MODEL) or "").strip(),
            timeout_seconds=_read_int(
                settings, KEY_TIMEOUT_SECONDS,
                default=DEFAULT_TIMEOUT_SECONDS, lo=1, hi=600,
            ),
        )

    @router.put("/config")
    def put_config(
        body: ScoringConfig,
        _: PivotUser = Depends(admin_user_dep),
    ):
        settings.set(KEY_ENABLED, "1" if body.enabled else "0")
        settings.set(KEY_VISIBILITY, body.visibility)
        settings.set(KEY_MODEL, body.model.strip())
        settings.set(KEY_TIMEOUT_SECONDS, str(body.timeout_seconds))
        return {"ok": True}

    # ── Runs ────────────────────────────────────────────────────────────

    @router.get("/runs")
    def list_runs(
        status: str | None = None,
        matter_id: str | None = None,
        matter_query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        _: PivotUser = Depends(admin_user_dep),
    ):
        if limit < 1 or limit > 200:
            raise HTTPException(400, "limit must be in [1, 200]")
        if offset < 0:
            raise HTTPException(400, "offset must be ≥ 0")
        runs = store.list_runs(
            status=status, matter_id=matter_id, matter_query=matter_query,
            limit=limit, offset=offset,
        )
        total = store.count_runs(
            status=status, matter_id=matter_id, matter_query=matter_query,
        )
        items = [_run_summary(r, store, workspace, pivot_users) for r in runs]
        return {
            "items": items,
            "total": total,
            "has_more": offset + len(items) < total,
        }

    @router.get("/runs/{run_id}")
    def get_run_detail(
        run_id: str,
        _: PivotUser = Depends(admin_user_dep),
    ):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run_not_found")
        summary = _run_summary(run, store, workspace, pivot_users)

        # v2.1: read all subject rows for the run (Phase 2 worker writes N).
        # Phase 1 / single-subject runs return a 1-element list. Build per-
        # subject score+evidence groups for the multi-row UI.
        all_pairs = store.get_scores(run.run_id)
        subject_scores = [
            {
                "score": _score_to_dict(score),
                "evidence": [
                    _evidence_to_dict(e, pivot_users) for e in evidence
                ],
                "subject_display": _resolve_subject_display(
                    score.subject_user_id, pivot_users,
                ),
                "subject_avatar_url": _resolve_subject_avatar(
                    score.subject_user_id, pivot_users,
                ),
            }
            for score, evidence in all_pairs
        ]

        # Back-compat: surface the primary subject's score / evidence at the
        # top level so existing single-subject UI keeps working without
        # reading subject_scores.
        primary = next(
            (s for s in subject_scores
             if s["score"]["subject_user_id"] == run.subject_user_id),
            subject_scores[0] if subject_scores else None,
        )

        # v2.2: surface skipped subjects (AI judged "evidence insufficient
        # → all dimensions null"). Translate pinyin → display_name where
        # we can; preserve raw pinyin for unresolved (deleted) users.
        skipped_subjects_payload = [
            {
                "pinyin": pinyin,
                "display": _pinyin_to_display(pinyin, pivot_users),
            }
            for pinyin in run.skipped_subjects
        ]

        return {
            "run": summary,
            "score": primary["score"] if primary else None,
            "evidence": primary["evidence"] if primary else [],
            "subject_scores": subject_scores,
            "skipped_subjects": skipped_subjects_payload,
        }

    @router.post("/matters/{matter_id}/rerun")
    def rerun_matter(
        matter_id: str,
        admin_user: PivotUser = Depends(admin_user_dep),
    ) -> RerunResponse:
        index = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if index is None:
            raise HTTPException(404, "matter_not_found")

        matter = index.get("matter") or {}
        owner_pinyin = (matter.get("owner") or "").strip()
        if not owner_pinyin:
            raise HTTPException(
                422,
                {
                    "code": "no_owner",
                    "message": "matter has no owner; cannot score",
                },
            )

        resolver = PinyinResolver(pivot_users._db)
        owner = resolver.resolve(owner_pinyin)
        if owner is None:
            raise HTTPException(
                422,
                {
                    "code": "owner_unknown",
                    "message": f"owner pinyin {owner_pinyin!r} could not be resolved to a pivot_user",
                },
            )

        category = _derive_category(index)
        if not category:
            raise HTTPException(
                422,
                {
                    "code": "no_category",
                    "message": "cannot derive category from timeline",
                },
            )

        # v2.1 (Task 2.4): resolve candidate set so admin rerun produces a
        # multi-subject run (otherwise worker falls back to {owner} and we
        # silently regress to Phase 1 single-row scoring on rerun).
        candidate_ids = resolve_candidates(index, resolver)
        # admin_user is already a PivotUser — its id is the audit trail value
        job = ScoringJob(
            matter_id=matter_id,
            matter_category=category,
            subject_user_id=owner.id,
            triggered_by="admin:rerun",
            triggered_actor_id=admin_user.id,
            candidate_user_ids=tuple(candidate_ids),
        )
        queue.enqueue(job)
        log.info(
            "scoring admin rerun enqueued matter=%s subject=%s candidates=%d admin=%s",
            matter_id, owner.id, len(candidate_ids), admin_user.id,
        )
        return RerunResponse(
            ok=True,
            matter_id=matter_id,
            queued=True,
            message="已入队，等待 worker 处理（约 1-3 分钟）",
        )

    @router.post("/scores/{run_id}/override")
    def override_score(
        run_id: str,
        body: HumanOverrideBody,
        admin_user: PivotUser = Depends(admin_user_dep),
    ):
        """Admin manual correction of an AI-generated score.

        Stores the override on the existing matter_scores row (no new run is
        created — overrides are an annotation, not a re-evaluation). If the
        run is non-existent or has no score (failed/skipped/queued), 404/422.
        Note is required so the audit trail captures *why* the admin disagreed
        with the AI.
        """
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run_not_found")
        got = store.get_score(run.run_id)
        if got is None:
            raise HTTPException(
                422,
                {
                    "code": "no_score_to_override",
                    "message": "this run has no score row (may be failed / queued / skipped)",
                },
            )
        try:
            store.apply_human_override(
                run_id, run.subject_user_id,
                overall=body.overall,
                note=body.note.strip(),
                by_user_id=admin_user.id,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        log.info(
            "scoring human override applied run=%s subject=%s overall=%.2f admin=%s",
            run_id, run.subject_user_id, body.overall, admin_user.id,
        )
        # Return the updated score for client-side cache update.
        got = store.get_score(run.run_id)
        assert got is not None
        score, _ = got
        return _score_to_dict(score)

    # ── Commenter weights ───────────────────────────────────────────────

    @router.get("/commenter-weights")
    def list_weights(_: PivotUser = Depends(admin_user_dep)):
        weights = store.list_weights()
        items = [_weight_to_dict(w, pivot_users) for w in weights]
        return {"items": items}

    @router.post("/commenter-weights")
    def upsert_weight(
        body: CommenterWeightIn,
        admin_user: PivotUser = Depends(admin_user_dep),
    ):
        target = pivot_users.get(body.pivot_user_id)
        if target is None:
            raise HTTPException(
                404, {"code": "user_not_found", "field": "pivot_user_id"},
            )
        try:
            w = store.upsert_weight(
                pivot_user_id=body.pivot_user_id,
                weight=body.weight,
                label=body.label,
                note=body.note,
                updated_by=admin_user.id,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _weight_to_dict(w, pivot_users)

    @router.put("/commenter-weights/{user_id}")
    def update_weight(
        user_id: str,
        body: CommenterWeightUpdate,
        admin_user: PivotUser = Depends(admin_user_dep),
    ):
        existing = store.get_weight(user_id)
        if existing is None:
            raise HTTPException(404, "weight_not_found")
        try:
            w = store.upsert_weight(
                pivot_user_id=user_id,
                weight=body.weight if body.weight is not None else existing.weight,
                label=body.label if body.label is not None else existing.label,
                note=body.note if body.note is not None else existing.note,
                updated_by=admin_user.id,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _weight_to_dict(w, pivot_users)

    @router.delete("/commenter-weights/{user_id}")
    def delete_weight(
        user_id: str,
        _: PivotUser = Depends(admin_user_dep),
    ):
        deleted = store.delete_weight(user_id)
        if not deleted:
            raise HTTPException(404, "weight_not_found")
        return {"ok": True, "deleted": user_id}

    # ── User search (for the "add commenter weight" picker) ─────────────

    @router.get("/users-search")
    def search_users(
        q: str = "",
        _: PivotUser = Depends(admin_user_dep),
    ):
        """Search pivot_users by display_name / email / pinyin (LIKE).
        Excludes soft-deleted. Capped at 20 results — admins type to refine.
        """
        users = pivot_users.list_for_admin(
            include_deleted=False, search=q.strip() or None,
        )
        return {
            "items": [
                {
                    "pivot_user_id": u.id,
                    "display_name": u.display_name,
                    "pinyin": u.pinyin,
                    "email": u.email,
                    "avatar_url": u.avatar_url,
                    "role": u.role,
                }
                for u in users[:20]
            ],
        }

    return router


# --------------------------------------------------------------------------- #
# Settings helpers                                                            #
# --------------------------------------------------------------------------- #


def _read_bool(settings: SettingsRepo, key: str, *, default: bool) -> bool:
    raw = settings.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def _read_int(
    settings: SettingsRepo, key: str, *, default: int, lo: int, hi: int,
) -> int:
    raw = settings.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        v = int(str(raw).strip())
        if lo <= v <= hi:
            return v
    except ValueError:
        pass
    return default


def _read_visibility(settings: SettingsRepo) -> str:
    raw = (settings.get(KEY_VISIBILITY) or DEFAULT_VISIBILITY).strip().lower()
    if raw in ("admin_only", "subjects", "all"):
        return raw
    return DEFAULT_VISIBILITY


# --------------------------------------------------------------------------- #
# Enrichment                                                                  #
# --------------------------------------------------------------------------- #


def _run_summary(
    run: ScoringRun,
    store: ScoringStore,
    workspace: Workspace,
    pivot_users: PivotUserRepo,
) -> dict:
    title = _matter_title(workspace, run.matter_id)
    subject = pivot_users.get(run.subject_user_id)
    score_brief: dict | None = None
    if run.status == "success":
        got = store.get_score(run.run_id)
        if got is not None:
            score, _ = got
            score_brief = {
                "overall": score.overall,
                "confidence": score.confidence,
                # When admin manually overrode, the list view should display
                # the override as the effective score (with a ✏ marker) so
                # admins don't have to drill into a drawer to learn the AI
                # number was superseded.
                "override_overall": score.human_override_overall,
            }
    return {
        "run_id": run.run_id,
        "matter_id": run.matter_id,
        "matter_title": title,
        "matter_category": run.matter_category,
        "subject_user_id": run.subject_user_id,
        "subject_display": subject.display_name if subject else None,
        "subject_avatar_url": subject.avatar_url if subject else None,
        "subject_status": subject.status if subject else None,
        "triggered_by": run.triggered_by,
        "triggered_actor_id": run.triggered_actor_id,
        "status": run.status,
        "error": run.error,
        "model": run.model,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "timeline_hash": run.timeline_hash,
        # v2.1 (Phase 2): 1 = single-subject (Phase 1 owner-only) — single
        # row in matter_scores; 2 = multi-subject — N rows. Frontend uses
        # this to decide whether to render single-card or multi-row layout.
        "schema_version": run.schema_version,
        "score": score_brief,
    }


def _score_to_dict(score: MatterScore) -> dict:
    return {
        "run_id": score.run_id,
        "subject_user_id": score.subject_user_id,
        "matter_id": score.matter_id,
        "overall": score.overall,
        "confidence": score.confidence,
        "rationale": score.rationale,
        "dimensions": {
            "delivery": score.delivery,
            "accountability": score.accountability,
            "collaboration": score.collaboration,
            "judgment": score.judgment,
            "process": score.process,
        },
        "human_override": (
            {
                "overall": score.human_override_overall,
                "note": score.human_override_note,
                "by": score.human_override_by,
                "at": score.human_override_at,
            }
            if score.human_override_overall is not None
            else None
        ),
    }


def _evidence_to_dict(
    e: MatterScoreEvidence, pivot_users: PivotUserRepo,
) -> dict:
    comment_author_display = None
    if e.source_comment_author_id:
        u = pivot_users.get(e.source_comment_author_id)
        if u is not None:
            comment_author_display = u.display_name
    annotation_author_display = None
    if e.source_annotation_author_id:
        u = pivot_users.get(e.source_annotation_author_id)
        if u is not None:
            annotation_author_display = u.display_name
    return {
        "id": e.id,
        "dimension": e.dimension,
        "polarity": e.polarity,
        "confidence": e.confidence,
        "source_kind": e.source_kind,
        "source_filename": e.source_filename,
        "source_file_type": e.source_file_type,
        "source_comment_created_at": e.source_comment_created_at,
        "source_comment_author_id": e.source_comment_author_id,
        "source_comment_author_display": comment_author_display,
        # v2.1: annotation evidence parallel to comment fields
        "source_annotation_created_at": e.source_annotation_created_at,
        "source_annotation_author_id": e.source_annotation_author_id,
        "source_annotation_author_display": annotation_author_display,
        # v2.1: 005 决策链 attribution (frontend renders 中文 label)
        "attribution_basis": e.attribution_basis,
        "weight_applied": e.weight_applied,
        "quote": e.quote,
        "explanation": e.explanation,
    }


def _resolve_subject_display(user_id: str, pivot_users: PivotUserRepo) -> str | None:
    u = pivot_users.get(user_id)
    return u.display_name if u else None


def _resolve_subject_avatar(user_id: str, pivot_users: PivotUserRepo) -> str | None:
    u = pivot_users.get(user_id)
    return u.avatar_url if u else None


def _pinyin_to_display(pinyin: str, pivot_users: PivotUserRepo) -> str | None:
    """v2.2: translate pinyin → display_name for skipped_subjects rendering.

    Returns None when the pinyin doesn't resolve (user deleted / pinyin
    renamed since the run); frontend falls back to the raw pinyin string.
    """
    u = pivot_users.get_by_pinyin(pinyin)
    return u.display_name if u else None


def _weight_to_dict(
    w: CommenterWeight, pivot_users: PivotUserRepo,
) -> dict:
    user = pivot_users.get(w.pivot_user_id)
    return {
        "pivot_user_id": w.pivot_user_id,
        "weight": w.weight,
        "label": w.label,
        "note": w.note,
        "updated_at": w.updated_at,
        "updated_by": w.updated_by,
        "user_display": user.display_name if user else None,
        "user_avatar_url": user.avatar_url if user else None,
        "user_pinyin": user.pinyin if user else None,
        "user_status": user.status if user else None,
    }


def _matter_title(workspace: Workspace, matter_id: str) -> str | None:
    """Read matter.title from the index. None if index missing — admin can
    still see the run row, just no title."""
    try:
        index = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
    except Exception:
        return None
    if index is None:
        return None
    return (index.get("matter") or {}).get("title")


def _derive_category(index: dict) -> str | None:
    """Mirror of trigger._derive_category — kept inline to avoid PR4↔PR3 import."""
    timeline = index.get("timeline") or []
    if not timeline:
        return None
    file_rel = timeline[0].get("file") or ""
    parts = file_rel.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]


