"""Per-user preferences endpoints.

GET /api/me/preferences            → returns full {key: value} bag for caller.
PUT /api/me/preferences/{key}      → upsert one key. Only whitelisted keys
                                     are accepted (returns 400 otherwise).

Whitelist lives here in code, not the DB; that's intentional — adding a
new key requires a code change so it's reviewable. Values are short
strings (≤ 200 chars) so the table doesn't accumulate large blobs.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.user_preferences import UserPreferenceRepo
from server.users import User


# Allowed preference keys. Adding a new key = a code change, by design.
ALLOWED_KEYS: frozenset[str] = frozenset({
    "matter_list_filter",   # values: "all" | "mine"
})


class PreferenceBody(BaseModel):
    value: str = Field(min_length=0, max_length=200)


def build_router(
    prefs: UserPreferenceRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/me/preferences")
    def list_preferences(user: User = Depends(current_user)):
        return prefs.get_all(user.open_id)

    @router.put("/me/preferences/{key}")
    def set_preference(
        key: str,
        body: PreferenceBody,
        user: User = Depends(current_user),
    ):
        if key not in ALLOWED_KEYS:
            raise HTTPException(
                status_code=400,
                detail={"code": "unknown_preference_key", "key": key},
            )
        prefs.set(user.open_id, key, body.value)
        return {"key": key, "value": body.value}

    return router
