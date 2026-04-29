"""Initial-admin bootstrap endpoints.

GET /init/status     → {needs_init: bool}  (true when no active admin exists)
POST /init/complete  → create the very first admin user, persist credential,
                       open a session, set sid cookie

Feishu-flavored bootstrap goes through /auth/callback's count_active_admins
short-circuit path; this endpoint only covers the email/password method.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PINYIN_RE_PATTERN, PivotUserRepo

SESSION_COOKIE = "sid"


class InitCompleteEmailPassword(BaseModel):
    method: str = Field(default="email_password")
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    pinyin: str = Field(min_length=2, max_length=40, pattern=PINYIN_RE_PATTERN)


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.get("/init/status")
    def status() -> JSONResponse:
        return JSONResponse(
            {"needs_init": pivot_users.count_active_admins() == 0}
        )

    @router.post("/init/complete")
    def complete(body: InitCompleteEmailPassword) -> JSONResponse:
        if pivot_users.count_active_admins() > 0:
            raise HTTPException(status_code=409, detail="admin_already_exists")
        if body.method != "email_password":
            raise HTTPException(status_code=400, detail="unsupported_method")
        try:
            user = pivot_users.create(
                display_name=body.display_name,
                pinyin=body.pinyin,
                email=body.email,
                avatar_url="",
                role="admin",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        bindings.bind(
            pivot_user_id=user.id,
            provider="invite",
            external_id=body.email,
            external_union_id=None,
            raw_profile_json=None,
            password_hash=hash_password(body.password),
        )
        sid = sessions.create(pivot_user_id=user.id)
        resp = JSONResponse(
            {
                "user": {
                    "id": user.id,
                    "display_name": user.display_name,
                    "role": user.role,
                    "status": user.status,
                },
            }
        )
        resp.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite=samesite,
            secure=secure_cookie,
            path="/",
        )
        return resp

    return router
