from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException

from server.inbox import (
    compute_inbox,
    compute_matter_inbox,
    latest_post_filename,
)
from server.mentions import resolve_id
from server.read_state import ReadStateRepo
from server.users import User, UserRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)


def build_router(
    workspace: Workspace,
    users: UserRepo,
    contacts,
    read_states: ReadStateRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/inbox")
    def inbox(user: User = Depends(current_user)):
        items = compute_inbox(
            workspace.discussions_dir,
            workspace.index_dir,
            user.open_id,
            read_states,
        )
        matter_items = compute_matter_inbox(
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
                        "author_display": resolve_id(it.meta.author, users, contacts),
                        "status": it.meta.status,
                        "last_updated": it.meta.last_updated,
                        "post_count": it.meta.post_count,
                    },
                    "unread_count": it.unread_count,
                    "last_post_filename": it.last_post_filename,
                    "last_post_author_display": resolve_id(it.last_post_author, users, contacts),
                }
                for it in items
            ],
            "matters": [
                {
                    "matter_id": m.matter_id,
                    "category": m.category,
                    "title": m.title,
                    "current_status": m.current_status,
                    "updated_at": m.updated_at,
                    "file_count": m.file_count,
                    "unread_count": m.unread_count,
                    "last_file_type": m.last_file_type,
                    "last_summary": m.last_summary,
                    "last_file_author_display": resolve_id(m.last_file_author, users, contacts),
                }
                for m in matter_items
            ],
        }

    @router.post("/threads/{category}/{slug}/read")
    def mark_read(
        category: str, slug: str,
        user: User = Depends(current_user),
    ):
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
