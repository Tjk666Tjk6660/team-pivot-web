from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from datetime import datetime, timezone

from server.auth.deps import require_profile
from server.contacts import ContactRepo
from server.inbox import compute_unread_counts
from server.index_files import change_thread_status, get_mentions_by_file
from server.mentions import resolve_id, resolve_text
from server.notify import Notifier
from server.publish import (
    PublishError,
    add_standalone_mention,
    publish_proposal,
    publish_reply,
)
from server.read_state import ReadStateRepo
from server.status_machine import (
    REASON_MIN_LEN,
    VALID_STATES,
    can_transition,
    requires_reason,
)
from server.threads import ThreadMeta, get_thread, list_threads
from server.users import User, UserRepo
from server.workspace import Workspace


class MentionBlock(BaseModel):
    open_ids: list[str] = Field(default_factory=list, max_length=50)
    comments: str = Field(min_length=1, max_length=500)


class NewThreadBody(BaseModel):
    category: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    mentions: MentionBlock | None = None


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=50000)
    mentions: MentionBlock | None = None
    reply_to: str | None = Field(default=None, max_length=200)
    references: list[str] = Field(default_factory=list, max_length=10)


class StatusChangeBody(BaseModel):
    to: str = Field(min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


class StandaloneMentionBody(BaseModel):
    target_filename: str = Field(min_length=1, max_length=200)
    mentions: MentionBlock


def build_router(
    workspace: Workspace,
    users: UserRepo,
    contacts: ContactRepo,
    notifier: Notifier,
    read_states: ReadStateRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/workspace/status")
    def status(_: User = Depends(current_user)):
        return {
            "ready": workspace.is_cloned(),
            "path": str(workspace.path),
            "head": workspace.head(),
        }

    @router.get("/threads")
    def threads(
        category: str | None = None,
        user: User = Depends(current_user),
    ):
        items = list_threads(
            workspace.discussions_dir, workspace.index_dir, category=category
        )
        unread = compute_unread_counts(
            workspace.discussions_dir, workspace.index_dir, user.open_id, read_states
        )
        return {"items": [_meta(m, users, unread.get(f"{m.category}/{m.slug}", 0)) for m in items]}

    @router.get("/threads/{category}/{slug}")
    def thread_detail(
        category: str, slug: str,
        _: User = Depends(current_user),
    ):
        detail = get_thread(workspace.discussions_dir, workspace.index_dir, category, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail="thread not found")
        mentions_map = get_mentions_by_file(workspace.index_dir, slug)
        return {
            "meta": _meta(detail.meta, users, unread_count=0),
            "posts": [
                {
                    "filename": p.filename,
                    "frontmatter": p.frontmatter,
                    "body": resolve_text(p.body, users),
                    "author_display": resolve_id(p.frontmatter.get("author"), users),
                    "mentions": [
                        {**m, "author_display": resolve_id(m.get("author_id"), users)}
                        for m in mentions_map.get(p.filename, [])
                    ],
                }
                for p in detail.posts
            ],
        }

    @router.post("/threads")
    def new_thread(body: NewThreadBody, user: User = Depends(current_user)):
        require_profile(user)
        try:
            m = body.mentions
            return publish_proposal(
                workspace, user,
                category=body.category, title=body.title, body=body.body,
                mention_open_ids=(m.open_ids if m else None),
                mention_comments=(m.comments if m else None),
                contacts=contacts,
                notifier=notifier,
            )
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/threads/{category}/{slug}/posts")
    def new_reply(
        category: str, slug: str, body: ReplyBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        try:
            m = body.mentions
            return publish_reply(
                workspace, user, category=category, slug=slug, body=body.body,
                mention_open_ids=(m.open_ids if m else None),
                mention_comments=(m.comments if m else None),
                contacts=contacts,
                notifier=notifier,
                reply_to=body.reply_to,
                references=body.references,
            )
        except PublishError as e:
            raise HTTPException(
                status_code=404 if "not found" in str(e) else 400, detail=str(e)
            ) from e

    @router.post("/threads/{category}/{slug}/mentions")
    def add_mention(
        category: str, slug: str, body: StandaloneMentionBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        try:
            return add_standalone_mention(
                workspace, user,
                category=category, slug=slug,
                target_filename=body.target_filename,
                mention_open_ids=body.mentions.open_ids,
                mention_comments=body.mentions.comments,
                contacts=contacts,
                notifier=notifier,
            )
        except PublishError as e:
            detail = str(e)
            code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=code, detail=detail) from e

    @router.post("/threads/{category}/{slug}/status")
    def change_status(
        category: str, slug: str, body: StatusChangeBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        if body.to not in VALID_STATES:
            raise HTTPException(status_code=400, detail=f"invalid status: {body.to}")
        detail = get_thread(workspace.discussions_dir, workspace.index_dir, category, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail="thread not found")
        from_state = detail.meta.status or "open"
        if not can_transition(from_state, body.to):
            raise HTTPException(
                status_code=400,
                detail=f"transition {from_state} -> {body.to} not allowed",
            )
        reason = (body.reason or "").strip() or None
        if requires_reason(from_state, body.to):
            if not reason or len(reason) < REASON_MIN_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=f"reopen requires a reason of at least {REASON_MIN_LEN} characters",
                )
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with workspace.write_session(
            message=f"chore: status {slug} {from_state}->{body.to}",
            author_name=user.name,
            author_email=f"{user.pinyin}@pivot.local",
        ):
            change_thread_status(
                workspace.index_dir,
                category=category, slug=slug,
                from_state=from_state, to_state=body.to,
                author_id=user.pinyin or "",
                reason=reason,
                now_iso=now,
            )
        notifier.notify_status_change(
            category=category, slug=slug, thread_title=detail.meta.title,
            from_state=from_state, to_state=body.to,
            author_name=user.name, reason=reason,
        )
        return {"ok": True, "from": from_state, "to": body.to}

    @router.post("/workspace/refresh")
    def refresh(_: User = Depends(current_user)):
        try:
            workspace.refresh()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {"ok": True, "head": workspace.head()}

    return router


def _meta(m: ThreadMeta, users: UserRepo, unread_count: int = 0) -> dict:
    return {
        "category": m.category,
        "slug": m.slug,
        "title": m.title,
        "author": m.author,
        "author_display": resolve_id(m.author, users),
        "status": m.status,
        "last_updated": m.last_updated,
        "post_count": m.post_count,
        "unread_count": unread_count,
    }
