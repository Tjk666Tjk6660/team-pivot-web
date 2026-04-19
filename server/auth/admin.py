"""Admin gate — MVP hardcoded password.

This guards routes whose audience is the operator/owner of the deployment
(AI settings, API token management). It is deliberately simple: a constant
shared secret sent in the X-Admin-Password header. Replace with a proper
admin role/RBAC once we have multi-user admin needs.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

ADMIN_PASSWORD = "000123"

ADMIN_PW_HEADER = "X-Admin-Password"


def require_admin(x_admin_password: str | None = Header(default=None, alias=ADMIN_PW_HEADER)) -> None:
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="admin_required")
