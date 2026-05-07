"""Admin: invite management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.invites import InviteRepo
from server.pivot_users import PivotUser


class CreateInviteBody(BaseModel):
    ttl_days: int = Field(default=7, ge=1, le=90)


def build_router(invites: InviteRepo, admin_user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/admin/invites")

    @router.get("")
    def list_invites(
        include_used: bool = False,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        items = invites.list_for_admin(include_used=include_used)
        return JSONResponse({
            "items": [
                {
                    "id": i.id,
                    "created_by": i.created_by,
                    "created_at": i.created_at,
                    "expires_at": i.expires_at,
                    "used_at": i.used_at,
                }
                for i in items
            ],
        })

    @router.post("")
    def create_invite(
        body: CreateInviteBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        token, record = invites.create(
            created_by=admin.id,
            ttl_sec=body.ttl_days * 86400,
        )
        return JSONResponse({
            "id": record.id,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "token": token,
            "link_path": f"/invite/{token}",
        })

    @router.delete("/{invite_id}")
    def revoke(
        invite_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        invites.revoke(invite_id=invite_id)
        return JSONResponse({"revoked": True})

    return router
