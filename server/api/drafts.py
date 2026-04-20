from __future__ import annotations

import logging
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import json as _json

from server.auth.deps import require_profile
from server.contacts import ContactRepo
from server.drafts import Draft, DraftRepo
from server.notify import Notifier
from server.publish import PublishError, publish_proposal, publish_reply
from server.users import User
from server.workspace import Workspace

log = logging.getLogger(__name__)


class DraftMentions(BaseModel):
    open_ids: list[str] = Field(default_factory=list, max_length=50)
    comments: str = ""


class CreateDraftBody(BaseModel):
    type: Literal["proposal", "reply"]
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r'^[^/\\:*?"<>|\t\n\r]{1,20}$',
    )
    body_md: str = Field(default="", max_length=50000)
    thread_key: str | None = Field(default=None, max_length=200)
    mentions: DraftMentions | None = None
    reply_to: str | None = Field(default=None, max_length=200)
    references: list[str] = Field(default_factory=list, max_length=10)


class UpdateDraftBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r'^[^/\\:*?"<>|\t\n\r]{1,20}$',
    )
    body_md: str | None = Field(default=None, max_length=50000)
    thread_key: str | None = Field(default=None, max_length=200)
    mentions: DraftMentions | None = None
    reply_to: str | None = Field(default=None, max_length=200)
    references: list[str] | None = Field(default=None, max_length=10)


def build_router(
    workspace: Workspace,
    drafts: DraftRepo,
    contacts: ContactRepo,
    notifier: Notifier,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/drafts")

    def _require_owner(draft: Draft | None, user: User) -> Draft:
        if draft is None:
            raise HTTPException(status_code=404, detail="draft not found")
        if draft.user_open_id != user.open_id:
            raise HTTPException(status_code=404, detail="draft not found")
        return draft

    @router.get("")
    def list_drafts(user: User = Depends(current_user)):
        require_profile(user)
        return {"items": [_to_dict(d) for d in drafts.list_for_user(user.open_id)]}

    @router.post("")
    def create_draft(body: CreateDraftBody, user: User = Depends(current_user)):
        require_profile(user)
        log.debug("draft create user=%s type=%s", user.open_id, body.type)
        d = drafts.create(
            user_open_id=user.open_id,
            type_=body.type,
            title=body.title,
            category=body.category,
            body_md=body.body_md,
            thread_key=body.thread_key,
            mentions_json=_json.dumps(body.mentions.model_dump()) if body.mentions else None,
            reply_to=body.reply_to,
            references_json=_json.dumps(body.references),
        )
        return _to_dict(d)

    @router.get("/{draft_id}")
    def get_draft(draft_id: str, user: User = Depends(current_user)):
        require_profile(user)
        d = _require_owner(drafts.get(draft_id), user)
        return _to_dict(d)

    @router.patch("/{draft_id}")
    def update_draft(
        draft_id: str, body: UpdateDraftBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        _require_owner(drafts.get(draft_id), user)
        log.debug("draft update id=%s user=%s", draft_id, user.open_id)
        d = drafts.update(
            draft_id,
            title=body.title,
            category=body.category,
            body_md=body.body_md,
            thread_key=body.thread_key,
            mentions_json=_json.dumps(body.mentions.model_dump()) if body.mentions else None,
            reply_to=body.reply_to,
            references_json=_json.dumps(body.references) if body.references is not None else None,
        )
        assert d is not None
        return _to_dict(d)

    @router.delete("/{draft_id}")
    def delete_draft(draft_id: str, user: User = Depends(current_user)):
        require_profile(user)
        _require_owner(drafts.get(draft_id), user)
        drafts.delete(draft_id)
        return {"ok": True}

    @router.post("/{draft_id}/publish")
    def publish_draft(draft_id: str, user: User = Depends(current_user)):
        require_profile(user)
        d = _require_owner(drafts.get(draft_id), user)
        log.info("draft publish start id=%s user=%s type=%s", draft_id, user.open_id, d.type)
        try:
            if d.type == "proposal":
                if not d.title or not d.category:
                    raise HTTPException(
                        status_code=400, detail="proposal needs title and category"
                    )
                if not d.body_md.strip():
                    raise HTTPException(status_code=400, detail="body is empty")
                m = _parse_mentions(d.mentions_json)
                result = publish_proposal(
                    workspace, user,
                    category=d.category, title=d.title, body=d.body_md,
                    mention_open_ids=(m and m.get("open_ids")) or None,
                    mention_comments=(m and m.get("comments")) or None,
                    contacts=contacts,
                    notifier=notifier,
                )
            else:
                if not d.thread_key or "/" not in d.thread_key:
                    raise HTTPException(
                        status_code=400, detail="reply needs thread_key as '<category>/<slug>'"
                    )
                if not d.body_md.strip():
                    raise HTTPException(status_code=400, detail="body is empty")
                cat, slug = d.thread_key.split("/", 1)
                m = _parse_mentions(d.mentions_json)
                refs = _parse_references(d.references_json)
                result = publish_reply(
                    workspace, user, category=cat, slug=slug, body=d.body_md,
                    mention_open_ids=(m and m.get("open_ids")) or None,
                    mention_comments=(m and m.get("comments")) or None,
                    contacts=contacts,
                    notifier=notifier,
                    reply_to=d.reply_to,
                    references=refs,
                )
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        try:
            drafts.delete(draft_id)
        except Exception:
            log.warning("draft delete_after_publish_failed id=%s", draft_id)
        log.info("draft published id=%s", draft_id)
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
        "mentions": _parse_mentions(d.mentions_json),
        "reply_to": d.reply_to,
        "references": _parse_references(d.references_json),
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


def _parse_mentions(s: str | None) -> dict | None:
    if not s:
        return None
    try:
        data = _json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _parse_references(s: str | None) -> list[str]:
    if not s:
        return []
    try:
        data = _json.loads(s)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []
