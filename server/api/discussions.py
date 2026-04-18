from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from server.auth.session import SessionStore
from server.mentions import resolve_id, resolve_text
from server.publish import PublishError, publish_proposal, publish_reply
from server.threads import ThreadMeta, get_thread, list_threads
from server.users import User, UserRepo
from server.workspace import Workspace


class NewThreadBody(BaseModel):
    category: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50000)


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=50000)


def build_router(workspace: Workspace, sessions: SessionStore, users: UserRepo) -> APIRouter:
    router = APIRouter(prefix="/api")

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

    @router.get("/workspace/status")
    def status(sid: str | None = Cookie(default=None)):
        _current_user(sid)
        return {
            "ready": workspace.is_cloned(),
            "path": str(workspace.path),
            "head": workspace.head(),
        }

    @router.get("/threads")
    def threads(category: str | None = None, sid: str | None = Cookie(default=None)):
        _current_user(sid)
        items = list_threads(
            workspace.discussions_dir, workspace.index_dir, category=category
        )
        return {"items": [_meta(m, users) for m in items]}

    @router.get("/threads/{category}/{slug}")
    def thread_detail(category: str, slug: str, sid: str | None = Cookie(default=None)):
        _current_user(sid)
        detail = get_thread(workspace.discussions_dir, workspace.index_dir, category, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail="thread not found")
        return {
            "meta": _meta(detail.meta, users),
            "posts": [
                {
                    "filename": p.filename,
                    "frontmatter": p.frontmatter,
                    "body": resolve_text(p.body, users),
                    "author_display": resolve_id(p.frontmatter.get("author"), users),
                }
                for p in detail.posts
            ],
        }

    @router.post("/threads")
    def new_thread(body: NewThreadBody, sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        try:
            return publish_proposal(
                workspace, user,
                category=body.category, title=body.title, body=body.body,
            )
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/threads/{category}/{slug}/posts")
    def new_reply(
        category: str, slug: str, body: ReplyBody,
        sid: str | None = Cookie(default=None),
    ):
        user = _current_user(sid)
        try:
            return publish_reply(
                workspace, user, category=category, slug=slug, body=body.body,
            )
        except PublishError as e:
            raise HTTPException(
                status_code=404 if "not found" in str(e) else 400, detail=str(e)
            ) from e

    @router.post("/workspace/refresh")
    def refresh(sid: str | None = Cookie(default=None)):
        _current_user(sid)
        try:
            workspace.refresh()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {"ok": True, "head": workspace.head()}

    return router


def _meta(m: ThreadMeta, users: UserRepo) -> dict:
    return {
        "category": m.category,
        "slug": m.slug,
        "title": m.title,
        "author": m.author,
        "author_display": resolve_id(m.author, users),
        "status": m.status,
        "last_updated": m.last_updated,
        "post_count": m.post_count,
    }
