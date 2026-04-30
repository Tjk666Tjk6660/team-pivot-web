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
)
from server.settings import SettingsRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)

DEFAULT_VISIBILITY = "admin_only"
DEFAULT_TIMEOUT_SECONDS = 120


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
        score_payload = None
        evidence_payload: list[dict] = []
        got = store.get_score(run.run_id)
        if got is not None:
            score, evidence = got
            score_payload = _score_to_dict(score)
            evidence_payload = [
                _evidence_to_dict(e, pivot_users) for e in evidence
            ]
        return {
            "run": summary,
            "score": score_payload,
            "evidence": evidence_payload,
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

        # admin_user is already a PivotUser — its id is the audit trail value
        job = ScoringJob(
            matter_id=matter_id,
            matter_category=category,
            subject_user_id=owner.id,
            triggered_by="admin:rerun",
            triggered_actor_id=admin_user.id,
        )
        queue.enqueue(job)
        log.info(
            "scoring admin rerun enqueued matter=%s subject=%s admin=%s",
            matter_id, owner.id, admin_user.id,
        )
        return RerunResponse(
            ok=True,
            matter_id=matter_id,
            queued=True,
            message="已入队，等待 worker 处理（约 1-2 分钟）",
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
    author_display = None
    if e.source_comment_author_id:
        u = pivot_users.get(e.source_comment_author_id)
        if u is not None:
            author_display = u.display_name
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
        "source_comment_author_display": author_display,
        "weight_applied": e.weight_applied,
        "quote": e.quote,
        "explanation": e.explanation,
    }


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


