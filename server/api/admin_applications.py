"""Admin: join applications endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.external_bindings import ExternalBindingRepo
from server.join_applications import (
    JoinApplication,
    JoinApplicationRepo,
    compute_match_candidates,
)
from server.notify import Notifier
from server.pivot_users import PivotUser, PivotUserRepo


class ApproveBody(BaseModel):
    target_pivot_user_id: str | None = None  # None = create new user


class RejectBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


def build_router(
    applications: JoinApplicationRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    notifier: Notifier,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/applications")

    @router.get("")
    def list_applications(
        status: str | None = None,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        if status:
            apps = applications.list_with_filter(status=status)
        else:
            apps = applications.list_pending()
        return JSONResponse({"items": [_app_dict(a) for a in apps]})

    @router.get("/{application_id}/match-candidates")
    def candidates(
        application_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None:
            raise HTTPException(status_code=404)
        cands = compute_match_candidates(pivot_users, raw_profile=a.raw_profile)
        return JSONResponse({
            "candidates": [
                {
                    "user_id": c.user_id,
                    "display_name": c.display_name,
                    "email": c.email,
                    "avatar_url": c.avatar_url,
                    "reason": c.reason,
                }
                for c in cands
            ],
        })

    @router.post("/{application_id}/approve")
    def approve(
        application_id: str,
        body: ApproveBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None or a.status != "pending":
            raise HTTPException(status_code=404)

        if body.target_pivot_user_id is None:
            try:
                user = pivot_users.create(
                    display_name=a.raw_profile.get("name") or "Unknown",
                    pinyin=None,
                    email=a.raw_profile.get("email"),
                    avatar_url=a.raw_profile.get("avatar_url") or "",
                    role="member",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            target_id = user.id
            merge = False
        else:
            target = pivot_users.get(body.target_pivot_user_id)
            if target is None or target.status != "active":
                raise HTTPException(status_code=400, detail="invalid_merge_target")
            target_id = target.id
            merge = True
        try:
            bindings.bind(
                pivot_user_id=target_id,
                provider=a.provider,
                external_id=a.external_id,
                external_union_id=a.external_union_id,
                raw_profile_json=json.dumps(a.raw_profile, ensure_ascii=False),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        applications.approve(application_id=application_id, reviewed_by=admin.id)

        notifier.notify_application_approved(
            applicant_open_id=a.external_id if a.provider == "feishu" else "",
            merged=merge,
        )
        return JSONResponse({"approved": True, "user_id": target_id, "merged": merge})

    @router.post("/{application_id}/reject")
    def reject(
        application_id: str,
        body: RejectBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None or a.status != "pending":
            raise HTTPException(status_code=404)
        applications.reject(
            application_id=application_id,
            reviewed_by=admin.id,
            reason=body.reason,
        )
        notifier.notify_application_rejected(
            applicant_open_id=a.external_id if a.provider == "feishu" else "",
        )
        return JSONResponse({"rejected": True})

    @router.post("/{application_id}/unblock")
    def unblock(
        application_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None:
            raise HTTPException(status_code=404)
        if a.status != "rejected":
            raise HTTPException(status_code=422, detail="only_rejected_can_unblock")
        applications.unblock(application_id=application_id)
        return JSONResponse({"unblocked": True})

    return router


def _app_dict(a: JoinApplication) -> dict:
    return {
        "id": a.id,
        "provider": a.provider,
        "external_id": a.external_id,
        "external_union_id": a.external_union_id,
        "raw_profile": a.raw_profile,
        "suggested_match_user_id": a.suggested_match_user_id,
        "status": a.status,
        "applied_at": a.applied_at,
        "reviewed_at": a.reviewed_at,
        "reviewed_by": a.reviewed_by,
        "reject_reason": a.reject_reason,
    }
