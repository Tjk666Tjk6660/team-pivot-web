"""Email + password login for invite-code users.

Looks up the `invite` external binding by email, verifies the bcrypt hash,
then opens a session. All failure modes (no such email, wrong password,
non-active user) collapse into 401 invalid_credentials so callers can't
enumerate which emails are registered.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import verify_password
from server.pivot_users import PivotUserRepo

SESSION_COOKIE = "sid"


class EmailPasswordLogin(BaseModel):
    email: EmailStr
    password: str


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.post("/auth/login_email_password")
    def login(body: EmailPasswordLogin) -> JSONResponse:
        binding = bindings.lookup(provider="invite", external_id=body.email)
        if binding is None or binding.password_hash is None:
            raise HTTPException(status_code=401, detail="invalid_credentials")
        if not verify_password(body.password, binding.password_hash):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        user = pivot_users.get(binding.pivot_user_id)
        if user is None or user.status != "active":
            raise HTTPException(status_code=401, detail="invalid_credentials")
        pivot_users.touch_last_login(user.id)
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
