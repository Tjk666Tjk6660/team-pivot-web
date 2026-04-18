from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from server.auth.session import SessionStore
from server.drafts import Draft, DraftRepo
from server.publish import PublishError, publish_proposal, publish_reply
from server.users import User, UserRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)


class CreateDraftBody(BaseModel):
    type: Literal["proposal", "reply"]
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    body_md: str = Field(default="", max_length=50000)
    thread_key: str | None = Field(default=None, max_length=200)


class UpdateDraftBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    body_md: str | None = Field(default=None, max_length=50000)
    thread_key: str | None = Field(default=None, max_length=200)


def build_router(
    workspace: Workspace,
    sessions: SessionStore,
    users: UserRepo,
    drafts: DraftRepo,
) -> APIRouter:
    router = APIRouter(prefix="/api/drafts")

    def _current_user(sid: str | None) -> User:
        s = sessions.get(sid)
        if s is None:
            raise HTTPException(status_code=401, detail="not logged in")
        u = users.get(s.user_open_id)
        if u is None:
            sessions.delete(sid)
            raise HTTPException(status_code=401, detail="user not found")
        if not u.pinyin:
            raise HTTPException(status_code=400, detail="profile setup required")
        return u

    def _require_owner(draft: Draft | None, user: User) -> Draft:
        if draft is None:
            raise HTTPException(status_code=404, detail="draft not found")
        if draft.user_open_id != user.open_id:
            raise HTTPException(status_code=404, detail="draft not found")
        return draft

    @router.get("")
    def list_drafts(sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        return {"items": [_to_dict(d) for d in drafts.list_for_user(user.open_id)]}

    @router.post("")
    def create_draft(body: CreateDraftBody, sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        d = drafts.create(
            user_open_id=user.open_id,
            type_=body.type,
            title=body.title,
            category=body.category,
            body_md=body.body_md,
            thread_key=body.thread_key,
        )
        return _to_dict(d)

    @router.get("/{draft_id}")
    def get_draft(draft_id: str, sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        d = _require_owner(drafts.get(draft_id), user)
        return _to_dict(d)

    @router.patch("/{draft_id}")
    def update_draft(
        draft_id: str, body: UpdateDraftBody, sid: str | None = Cookie(default=None),
    ):
        user = _current_user(sid)
        _require_owner(drafts.get(draft_id), user)
        d = drafts.update(
            draft_id,
            title=body.title,
            category=body.category,
            body_md=body.body_md,
            thread_key=body.thread_key,
        )
        assert d is not None
        return _to_dict(d)

    @router.delete("/{draft_id}")
    def delete_draft(draft_id: str, sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        _require_owner(drafts.get(draft_id), user)
        drafts.delete(draft_id)
        return {"ok": True}

    @router.post("/{draft_id}/publish")
    def publish_draft(draft_id: str, sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        d = _require_owner(drafts.get(draft_id), user)
        try:
            if d.type == "proposal":
                if not d.title or not d.category:
                    raise HTTPException(
                        status_code=400, detail="proposal needs title and category"
                    )
                if not d.body_md.strip():
                    raise HTTPException(status_code=400, detail="body is empty")
                result = publish_proposal(
                    workspace, user,
                    category=d.category, title=d.title, body=d.body_md,
                )
            else:
                if not d.thread_key or "/" not in d.thread_key:
                    raise HTTPException(
                        status_code=400, detail="reply needs thread_key as '<category>/<slug>'"
                    )
                if not d.body_md.strip():
                    raise HTTPException(status_code=400, detail="body is empty")
                cat, slug = d.thread_key.split("/", 1)
                result = publish_reply(
                    workspace, user, category=cat, slug=slug, body=d.body_md,
                )
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        try:
            drafts.delete(draft_id)
        except Exception:
            log.warning("draft delete failed after publish", extra={"draft_id": draft_id})
        return {"published": result, "draft_id": draft_id}

    return router


def _to_dict(d: Draft) -> dict:
    return {
        "id": d.id,
        "type": d.type,
        "title": d.title,
        "category": d.category,
        "body_md": d.body_md,
        "thread_key": d.thread_key,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }
