from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException

from server.auth.session import SessionStore
from server.threads import ThreadMeta, get_thread, list_threads
from server.workspace import Workspace


def build_router(workspace: Workspace, sessions: SessionStore) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _require_auth(sid: str | None) -> None:
        if sessions.get(sid) is None:
            raise HTTPException(status_code=401, detail="not logged in")

    @router.get("/workspace/status")
    def status(sid: str | None = Cookie(default=None)):
        _require_auth(sid)
        return {
            "ready": workspace.is_cloned(),
            "path": str(workspace.path),
            "head": workspace.head(),
        }

    @router.get("/threads")
    def threads(category: str | None = None, sid: str | None = Cookie(default=None)):
        _require_auth(sid)
        items = list_threads(workspace.discussions_dir, category=category)
        return {"items": [_meta(m) for m in items]}

    @router.get("/threads/{category}/{slug}")
    def thread_detail(category: str, slug: str, sid: str | None = Cookie(default=None)):
        _require_auth(sid)
        detail = get_thread(workspace.discussions_dir, category, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail="thread not found")
        return {
            "meta": _meta(detail.meta),
            "posts": [
                {"filename": p.filename, "frontmatter": p.frontmatter, "body": p.body}
                for p in detail.posts
            ],
        }

    @router.post("/workspace/refresh")
    def refresh(sid: str | None = Cookie(default=None)):
        _require_auth(sid)
        try:
            workspace.refresh()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {"ok": True, "head": workspace.head()}

    return router


def _meta(m: ThreadMeta) -> dict:
    return {
        "category": m.category,
        "slug": m.slug,
        "title": m.title,
        "author": m.author,
        "status": m.status,
        "post_count": m.post_count,
    }
