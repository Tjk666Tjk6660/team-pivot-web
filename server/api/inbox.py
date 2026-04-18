from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, HTTPException

from server.auth.session import SessionStore
from server.inbox import compute_inbox, latest_post_filename
from server.mentions import resolve_id
from server.read_state import ReadStateRepo
from server.users import User, UserRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)


def build_router(
    workspace: Workspace,
    sessions: SessionStore,
    users: UserRepo,
    read_states: ReadStateRepo,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _current_user(sid: str | None) -> User:
        s = sessions.get(sid)
        if s is None:
            raise HTTPException(status_code=401, detail="not logged in")
        u = users.get(s.user_open_id)
        if u is None:
            sessions.delete(sid)
            raise HTTPException(status_code=401, detail="user not found")
        return u

    @router.get("/inbox")
    def inbox(sid: str | None = Cookie(default=None)):
        user = _current_user(sid)
        items = compute_inbox(
            workspace.discussions_dir,
            workspace.index_dir,
            user.open_id,
            read_states,
        )
        return {
            "items": [
                {
                    "meta": {
                        "category": it.meta.category,
                        "slug": it.meta.slug,
                        "title": it.meta.title,
                        "author": it.meta.author,
                        "author_display": resolve_id(it.meta.author, users),
                        "status": it.meta.status,
                        "last_updated": it.meta.last_updated,
                        "post_count": it.meta.post_count,
                    },
                    "unread_count": it.unread_count,
                    "last_post_filename": it.last_post_filename,
                    "last_post_author_display": resolve_id(it.last_post_author, users),
                }
                for it in items
            ]
        }

    @router.post("/threads/{category}/{slug}/read")
    def mark_read(
        category: str, slug: str, sid: str | None = Cookie(default=None),
    ):
        user = _current_user(sid)
        tdir = workspace.discussions_dir / category / slug
        if not tdir.is_dir():
            raise HTTPException(status_code=404, detail="thread not found")
        latest = latest_post_filename(tdir)
        if latest is None:
            raise HTTPException(status_code=404, detail="no posts in thread")
        read_states.set(user.open_id, f"{category}/{slug}", latest)
        log.debug("read_state set user=%s thread=%s/%s last=%s",
                  user.open_id, category, slug, latest)
        return {"ok": True, "last_read_post_filename": latest}

    return router
