"""Admin: user management endpoints."""
from __future__ import annotations

from difflib import get_close_matches

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PivotUser, PivotUserRepo
from server.roles import PivotRole, PivotRoleRepo


class StatusChangeBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ConfirmedStatusChangeBody(StatusChangeBody):
    confirm_display_name: str


class RoleChangeBody(BaseModel):
    role: str | None = None
    roles: list[str] | None = None
    confirm_create_role: bool = False


class RoleCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=500)


class RoleActiveBody(BaseModel):
    active: bool


class RoleMembersBody(BaseModel):
    user_ids: list[str]


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    roles: PivotRoleRepo,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    def _refuse_self(user_id: str, admin: PivotUser) -> None:
        if admin.id == user_id:
            raise HTTPException(
                status_code=422, detail="cannot_modify_self_state_or_role"
            )

    def _refuse_last_admin(target_id: str) -> None:
        target = pivot_users.get(target_id)
        if target is None:
            raise HTTPException(status_code=404)
        if "admin" in target.roles and target.status == "active":
            if pivot_users.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=422, detail="last_active_admin_protected"
                )

    @router.get("/roles")
    def list_roles(_: PivotUser = Depends(admin_user_dep)):
        return {"items": [_role_dict(role) for role in roles.list(include_inactive=True)]}

    @router.post("/roles")
    def create_role(
        body: RoleCreateBody,
        _: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        try:
            role = roles.create(name=body.name, description=body.description)
        except ValueError as e:
            detail = str(e)
            status = 409 if detail == "role already exists" else 422
            raise HTTPException(status_code=status, detail={"code": detail}) from e
        return JSONResponse(_role_dict(role), status_code=201)

    @router.patch("/roles/{role_name}")
    def update_role_active(
        role_name: str,
        body: RoleActiveBody,
        _: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        try:
            role = roles.set_active(role_name, body.active)
        except KeyError as e:
            raise HTTPException(status_code=404, detail={"code": "role_not_found"}) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail={"code": str(e)}) from e
        return JSONResponse(_role_dict(role))

    @router.put("/roles/{role_name}/members")
    def update_role_members(
        role_name: str,
        body: RoleMembersBody,
        _: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        try:
            role = roles.set_members(role_name, body.user_ids)
        except KeyError as e:
            raise HTTPException(status_code=404, detail={"code": "role_not_found"}) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail={"code": str(e)}) from e
        members = [
            _user_dict(user, bindings)
            for user in pivot_users.list_for_admin(include_deleted=False)
            if role.name in user.roles
        ]
        return JSONResponse({"role": _role_dict(role), "members": members})

    @router.get("/users")
    def list_users(
        include_deleted: bool = False,
        search: str | None = None,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        users = pivot_users.list_for_admin(
            include_deleted=include_deleted, search=search,
        )
        return JSONResponse({"items": [_user_dict(u, bindings) for u in users]})

    @router.post("/users/{user_id}/suspend")
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

    @router.post("/users/{user_id}/resume")
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

    @router.post("/users/{user_id}/mark-deleted")
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

    @router.post("/users/{user_id}/restore")
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

    @router.post("/users/{user_id}/role")
    def change_role(
        user_id: str,
        body: RoleChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)

        requested = _requested_roles(body)
        known_roles = {item.name for item in roles.list(include_inactive=False)}
        known_roles.update({"admin", "member"})
        unknown = [role for role in requested if role not in known_roles]
        if unknown and not body.confirm_create_role:
            suggestions: list[str] = []
            candidates = sorted(known_roles)
            for role in unknown:
                suggestions.extend(get_close_matches(role, candidates, n=3, cutoff=0.4))
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_role",
                    "unknown_roles": unknown,
                    "suggestions": sorted(set(suggestions)),
                },
            )
        for role in unknown:
            roles.create(name=role)

        if "admin" in target.roles and "admin" not in requested:
            _refuse_self(user_id, admin)
            _refuse_last_admin(user_id)

        u = pivot_users.update_role(user_id=user_id, roles=requested)
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/users/{user_id}/reset-password")
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


def _role_dict(role: PivotRole) -> dict:
    return {
        "role": role.name,
        "name": role.name,
        "kind": role.kind,
        "description": role.description,
        "is_active": role.is_active,
        "user_count": role.user_count,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


def _requested_roles(body: RoleChangeBody) -> list[str]:
    raw = body.roles if body.roles is not None else ([body.role] if body.role else [])
    requested: list[str] = []
    seen: set[str] = set()
    for role in raw:
        value = str(role).strip()
        if not value:
            continue
        if value not in seen:
            requested.append(value)
            seen.add(value)
    if not requested:
        raise HTTPException(status_code=422, detail={"code": "role_required"})
    return requested


def _user_dict(u: PivotUser, bindings: ExternalBindingRepo) -> dict:
    binding_list = bindings.list_for_user(u.id)
    return {
        "id": u.id,
        "display_name": u.display_name,
        "pinyin": u.pinyin,
        "email": u.email,
        "avatar_url": u.avatar_url,
        "github_username": u.github_username,
        "role": u.role,
        "roles": u.roles,
        "status": u.status,
        "status_note": u.status_note,
        "created_at": u.created_at,
        "last_login_at": u.last_login_at,
        "status_changed_at": u.status_changed_at,
        # Backward-compat: list of provider names (frontend hadn't migrated yet).
        "providers": [b.provider for b in binding_list],
        # Detailed binding view — multiple entries on the same provider mean
        # the user has been merged with another join_application (e.g. same
        # person's old + new feishu open_id, or feishu + invite-email both
        # bound to one pivot_user). Each entry carries enough info for the
        # admin UI to show "feishu · 张三 (ou_xxx…)" chips.
        "bindings": [
            {
                "id": b.id,
                "provider": b.provider,
                "external_id": b.external_id,
                "external_union_id": b.external_union_id,
                "bound_at": b.bound_at,
                "raw_profile": _safe_load_raw_profile(b.raw_profile_json),
            }
            for b in binding_list
        ],
    }


def _safe_load_raw_profile(raw: str | None) -> dict | None:
    """raw_profile is stored as a JSON string (or NULL for invite bindings).
    Return the parsed dict on success; None on absence or parse failure —
    the admin UI degrades to showing just the provider + external_id."""
    if not raw:
        return None
    import json
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except (ValueError, TypeError):
        return None
