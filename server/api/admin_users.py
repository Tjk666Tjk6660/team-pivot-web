"""Admin: user management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PivotUser, PivotUserRepo


class StatusChangeBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ConfirmedStatusChangeBody(StatusChangeBody):
    confirm_display_name: str


class RoleChangeBody(BaseModel):
    role: str  # 'admin' | 'member'


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/users")

    def _refuse_self(user_id: str, admin: PivotUser) -> None:
        if admin.id == user_id:
            raise HTTPException(
                status_code=422, detail="cannot_modify_self_state_or_role"
            )

    def _refuse_last_admin(target_id: str) -> None:
        target = pivot_users.get(target_id)
        if target is None:
            raise HTTPException(status_code=404)
        if target.role == "admin" and target.status == "active":
            if pivot_users.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=422, detail="last_active_admin_protected"
                )

    @router.get("")
    def list_users(
        include_deleted: bool = False,
        search: str | None = None,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        users = pivot_users.list_for_admin(
            include_deleted=include_deleted, search=search,
        )
        return JSONResponse({"items": [_user_dict(u, bindings) for u in users]})

    @router.post("/{user_id}/suspend")
    def suspend(
        user_id: str,
        body: StatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        _refuse_self(user_id, admin)
        _refuse_last_admin(user_id)
        u = pivot_users.update_status(
            user_id=user_id, status="suspended",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/resume")
    def resume(
        user_id: str,
        body: StatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        u = pivot_users.update_status(
            user_id=user_id, status="active",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/mark-deleted")
    def mark_deleted(
        user_id: str,
        body: ConfirmedStatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        _refuse_self(user_id, admin)
        _refuse_last_admin(user_id)
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        if body.confirm_display_name != target.display_name:
            raise HTTPException(status_code=422, detail="display_name_mismatch")
        u = pivot_users.update_status(
            user_id=user_id, status="deleted",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/restore")
    def restore(
        user_id: str,
        body: ConfirmedStatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        if body.confirm_display_name != target.display_name:
            raise HTTPException(status_code=422, detail="display_name_mismatch")
        u = pivot_users.update_status(
            user_id=user_id, status="active",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/role")
    def change_role(
        user_id: str,
        body: RoleChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        if body.role not in ("admin", "member"):
            raise HTTPException(status_code=400, detail="invalid_role")
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        if body.role == "member":
            _refuse_self(user_id, admin)
            _refuse_last_admin(user_id)
        u = pivot_users.update_role(user_id=user_id, role=body.role)
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/reset-password")
    def reset_password(
        user_id: str,
        body: ResetPasswordBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        existing = [b for b in bindings.list_for_user(user_id) if b.provider == "invite"]
        if not existing:
            raise HTTPException(status_code=422, detail="no_invite_binding")
        bindings.update_password(
            pivot_user_id=user_id,
            new_password_hash=hash_password(body.new_password),
        )
        return JSONResponse({"reset": True})

    return router


def _user_dict(u: PivotUser, bindings: ExternalBindingRepo) -> dict:
    binding_list = bindings.list_for_user(u.id)
    return {
        "id": u.id,
        "display_name": u.display_name,
        "pinyin": u.pinyin,
        "email": u.email,
        "avatar_url": u.avatar_url,
        "role": u.role,
        "status": u.status,
        "status_note": u.status_note,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
        "status_changed_at": u.status_changed_at,
        "providers": [b.provider for b in binding_list],
    }
