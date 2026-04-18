from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from server.auth.session import SessionStore
from server.index_files import append_reply_to_index, create_thread_index
from server.mentions import resolve_id, resolve_text
from server.posts import mark_indexed, write_post_pending
from server.threads import (
    ThreadMeta,
    generate_unique_hash,
    get_thread,
    list_threads,
    next_post_number,
    sanitize_slug,
)
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

    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

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
        now = _now_iso()

        cat_dir = workspace.discussions_dir / body.category
        slug = _make_unique_slug(cat_dir, body.title)
        thread_dir = cat_dir / slug
        filename = f"001_{user.pinyin}_proposal_{generate_unique_hash(thread_dir)}.md"

        fm = {"type": "proposal", "author": user.pinyin, "created_at": now}
        final_body = _ensure_h1(body.body, body.title)

        with workspace.write_session(
            message=f"feat: new discussion - {body.title}",
            author_name=user.name,
            author_email=f"{user.pinyin}@pivot.local",
        ):
            post_path = thread_dir / filename
            write_post_pending(post_path, frontmatter=fm, body=final_body)
            create_thread_index(
                workspace.index_dir,
                category=body.category,
                slug=slug,
                filename=filename,
                author_id=user.pinyin or "",
                now_iso=now,
            )
            mark_indexed(post_path)
        return {"category": body.category, "slug": slug, "filename": filename}

    @router.post("/threads/{category}/{slug}/posts")
    def new_reply(
        category: str, slug: str, body: ReplyBody,
        sid: str | None = Cookie(default=None),
    ):
        user = _current_user(sid)
        thread_dir = workspace.discussions_dir / category / slug
        if not thread_dir.is_dir():
            raise HTTPException(status_code=404, detail="thread not found")

        now = _now_iso()
        seq = next_post_number(thread_dir)
        filename = f"{seq:03d}_{user.pinyin}_reply_{generate_unique_hash(thread_dir)}.md"
        fm = {"type": "reply", "author": user.pinyin, "created_at": now}

        with workspace.write_session(
            message=f"chore: reply to {slug}",
            author_name=user.name,
            author_email=f"{user.pinyin}@pivot.local",
        ):
            post_path = thread_dir / filename
            write_post_pending(post_path, frontmatter=fm, body=body.body)
            append_reply_to_index(
                workspace.index_dir,
                category=category,
                slug=slug,
                filename=filename,
                author_id=user.pinyin or "",
                now_iso=now,
            )
            mark_indexed(post_path)
        return {"filename": filename}

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


def _make_unique_slug(category_dir, title: str) -> str:
    base = sanitize_slug(title)
    if not (category_dir / base).exists():
        return base
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}-{suffix}"


def _ensure_h1(body: str, title: str) -> str:
    stripped = body.lstrip()
    if stripped.startswith("# "):
        return body
    return f"# {title}\n\n{body.rstrip()}\n"
