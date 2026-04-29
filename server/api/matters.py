from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth.deps import require_profile
from server.contacts import ContactRepo
from server.favorites import FavoriteRepo
from server.inbox import (
    compute_matter_unread_counts,
    latest_matter_post_filename,
)
from server.matter_index import (
    matter_index_path,
    read_matter_index,
)
from server.matter_validator import validate_append
from server.mentions import resolve_avatar_url, resolve_id, resolve_text
from server.notify import Notifier
from server.posts import read_post
from server.publish import (
    AmbiguousMentionError,
    MatterAlreadyExistsError,
    MatterNotFoundError,
    PublishError,
    publish_matter_append,
    publish_matter_comment,
    publish_matter_create,
)
from server.read_state import ReadStateRepo
from server.users import User, UserRepo
from server.workspace import Workspace


# ---------- Request bodies ----------


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    mentions: list[str] | None = None


class InitialFileIn(BaseModel):
    type: str = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50000)
    owner: str | None = Field(default=None, max_length=50)
    comments: list[CommentIn] | None = None


class NewMatterBody(BaseModel):
    # `category` is not in pivot-interface.md §POST /api/matters, but is required
    # to place the MD files on disk under discussions/<category>/<slug>/.
    # Recorded as a non-core deviation in deviations.md.
    category: str = Field(
        min_length=1, max_length=20,
        pattern=r'^[^/\\:*?"<>|\t\n\r]{1,20}$',
    )
    title: str = Field(min_length=1, max_length=200)
    initial_file: InitialFileIn


class NewFileBody(BaseModel):
    type: str = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50000)
    owner: str | None = Field(default=None, max_length=50)
    quote: str | None = Field(default=None, max_length=500)
    refer: list[str] | None = None
    comments: list[CommentIn] | None = None
    # Type-specific fields are accepted as loose dicts so the matter_validator
    # can produce precise error codes per interface.md.
    verifications: list[dict] | None = None
    outcome: str | None = Field(default=None, max_length=20)
    status_change: dict | None = None


class NewResultBody(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50000)
    outcome: str = Field(min_length=1, max_length=20)
    comments: list[CommentIn] | None = None


class CommentBody(BaseModel):
    target_file: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=2000)
    mentions: list[str] | None = None


class FavoriteToggleBody(BaseModel):
    favorite: bool


# ---------- Router ----------


def build_router(
    workspace: Workspace,
    users: UserRepo,
    contacts: ContactRepo,
    notifier: Notifier,
    read_states: ReadStateRepo,
    favorites: FavoriteRepo,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/matters")
    def list_matters(
        status: str | None = None,
        owner: str | None = None,
        q: str | None = None,
        user: User = Depends(current_user),
    ):
        # Per-user overlays: unread counts + favorites. Keyed by category/slug
        # (matter_id == slug), reusing the thread read_state / favorites tables
        # with no schema change.
        unread = compute_matter_unread_counts(
            workspace.discussions_dir, workspace.index_dir,
            user.open_id, read_states,
        )
        favorite_keys = favorites.all_for_user(user.open_id)

        items = []
        for path in _list_index_files(workspace.index_dir):
            data = read_matter_index(path)
            if data is None:
                continue
            summary = _summarize_matter(data, users, contacts)
            if status and summary.get("current_status") != status:
                continue
            if owner and not _matter_has_owner(data, owner):
                continue
            if q and q.lower() not in (summary.get("title") or "").lower():
                continue
            category = _matter_category(data)
            key = f"{category}/{summary['id']}" if category else summary["id"]
            summary["unread_count"] = unread.get(key, 0)
            summary["favorite"] = key in favorite_keys
            summary["category"] = category
            items.append(summary)
        items.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
        return {"items": items}

    @router.get("/matters/{matter_id}")
    def get_matter(matter_id: str, user: User = Depends(current_user)):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        rendered = _render_matter_detail(workspace, data, users, contacts)
        category = _matter_category(data)
        key = f"{category}/{matter_id}" if category else matter_id
        rendered["matter"]["category"] = category
        rendered["matter"]["favorite"] = favorites.has(user.open_id, key)
        return rendered

    @router.post("/matters/{matter_id}/read")
    def mark_read(matter_id: str, user: User = Depends(current_user)):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        category = _matter_category(data)
        if not category:
            raise HTTPException(
                status_code=404,
                detail={"code": "matter_category_unknown"},
            )
        tdir = workspace.discussions_dir / category / matter_id
        latest = latest_matter_post_filename(tdir)
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "no_files_in_matter"},
            )
        read_states.set(user.open_id, f"{category}/{matter_id}", latest)
        return {"ok": True, "last_read_post_filename": latest}

    @router.post("/matters/{matter_id}/favorite")
    def toggle_favorite(
        matter_id: str,
        body: FavoriteToggleBody,
        user: User = Depends(current_user),
    ):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        category = _matter_category(data)
        if not category:
            raise HTTPException(
                status_code=404,
                detail={"code": "matter_category_unknown"},
            )
        key = f"{category}/{matter_id}"
        if body.favorite:
            favorites.set(user.open_id, key)
        else:
            favorites.delete(user.open_id, key)
        return {"ok": True, "thread_key": key, "favorite": body.favorite}

    @router.post("/matters")
    def create_matter(body: NewMatterBody, user: User = Depends(current_user)):
        require_profile(user)
        initial = {
            "type": body.initial_file.type,
            "summary": body.initial_file.summary,
            "body": body.initial_file.body,
            "owner": body.initial_file.owner,
            "comments": _comments_to_dict(body.initial_file.comments),
        }
        _preflight_initial(initial)
        try:
            result = publish_matter_create(
                workspace, user,
                category=body.category,
                title=body.title,
                initial_item=initial,
                contacts=contacts,
                notifier=notifier,
                users=users,
            )
        except MatterAlreadyExistsError as e:
            raise HTTPException(
                status_code=409,
                detail={"code": "matter_already_exists", "message": str(e)},
            ) from e
        except AmbiguousMentionError as e:
            # 422 + structured candidate list lets MCP clients show "你想 @
            # 哪个 zhangbo?" and re-issue with the chosen open_id; collapsed
            # to PublishError's generic 400 the AI loses the candidates.
            raise HTTPException(
                status_code=422,
                detail={"code": "ambiguous_mention", "ambiguities": e.ambiguities},
            ) from e
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "matter": result["matter"],
            "initial_timeline_item": result["item"],
            "matter_id": result["matter_id"],
            "file": result["file"],
        }

    @router.post("/matters/{matter_id}/files")
    def append_file(
        matter_id: str,
        body: NewFileBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        index_path = matter_index_path(workspace.index_dir, matter_id)
        data = read_matter_index(index_path)
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})

        item_preview = _body_to_item_preview(body, user=user)
        _preflight(data, item_preview)

        try:
            result = publish_matter_append(
                workspace, user,
                matter_id=matter_id,
                item_body=item_preview,
                contacts=contacts,
                notifier=notifier,
                users=users,
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
        except AmbiguousMentionError as e:
            # 422 + structured candidate list lets MCP clients show "你想 @
            # 哪个 zhangbo?" and re-issue with the chosen open_id; collapsed
            # to PublishError's generic 400 the AI loses the candidates.
            raise HTTPException(
                status_code=422,
                detail={"code": "ambiguous_mention", "ambiguities": e.ambiguities},
            ) from e
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"item": result["item"], "matter": result["matter"]}

    @router.post("/matters/{matter_id}/result")
    def append_result(
        matter_id: str,
        body: NewResultBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        index_path = matter_index_path(workspace.index_dir, matter_id)
        data = read_matter_index(index_path)
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})

        current_status = (data.get("matter") or {}).get("current_status")
        # result always implies a status_change to the selected outcome
        status_change = {"from": current_status, "to": body.outcome}
        item_preview = {
            "type": "result",
            "summary": body.summary,
            "body": body.body,
            "outcome": body.outcome,
            "status_change": status_change,
            "comments": _comments_to_dict(body.comments),
        }
        _preflight(data, item_preview)

        try:
            result = publish_matter_append(
                workspace, user,
                matter_id=matter_id,
                item_body=item_preview,
                contacts=contacts,
                notifier=notifier,
                users=users,
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
        except AmbiguousMentionError as e:
            # 422 + structured candidate list lets MCP clients show "你想 @
            # 哪个 zhangbo?" and re-issue with the chosen open_id; collapsed
            # to PublishError's generic 400 the AI loses the candidates.
            raise HTTPException(
                status_code=422,
                detail={"code": "ambiguous_mention", "ambiguities": e.ambiguities},
            ) from e
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"item": result["item"], "matter": result["matter"]}

    @router.post("/matters/{matter_id}/comments")
    def append_comment_route(
        matter_id: str,
        body: CommentBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        try:
            result = publish_matter_comment(
                workspace, user,
                matter_id=matter_id,
                target_file=body.target_file,
                body=body.body,
                mentions=body.mentions,
                contacts=contacts,
                notifier=notifier,
                users=users,
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
        except ValueError as e:
            # matter_index.append_comment raises ValueError on missing target
            raise HTTPException(
                status_code=404,
                detail={"code": "comment_target_not_found", "message": str(e)},
            ) from e
        except AmbiguousMentionError as e:
            # 422 + structured candidate list lets MCP clients show "你想 @
            # 哪个 zhangbo?" and re-issue with the chosen open_id; collapsed
            # to PublishError's generic 400 the AI loses the candidates.
            raise HTTPException(
                status_code=422,
                detail={"code": "ambiguous_mention", "ambiguities": e.ambiguities},
            ) from e
        except PublishError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return result

    return router


# ---------- helpers ----------


def _preflight_initial(initial: dict) -> None:
    """Run validator against a freshly-born planning matter so we can return 422
    with precise error codes before the writer gets invoked."""
    fake_index = {
        "matter": {"current_status": "planning"},
        "timeline": [],
    }
    _preflight(fake_index, initial)


def _preflight(index_data: dict, item: dict) -> None:
    r = validate_append(index_data, item)
    if r.ok:
        return
    raise HTTPException(
        status_code=422,
        detail={"code": r.code, "field": r.field, "message": r.message},
    )


def _body_to_item_preview(body: NewFileBody, *, user: User) -> dict:
    """Build a dict compatible with matter_validator.validate_append + publish."""
    out: dict[str, Any] = {
        "type": body.type,
        "summary": body.summary,
        "body": body.body,
        "owner": body.owner or (user.pinyin or ""),
    }
    if body.quote is not None:
        out["quote"] = body.quote
    if body.refer is not None:
        out["refer"] = list(body.refer)
    if body.comments is not None:
        out["comments"] = _comments_to_dict(body.comments)
    if body.verifications is not None:
        out["verifications"] = list(body.verifications)
    if body.outcome is not None:
        out["outcome"] = body.outcome
    if body.status_change is not None:
        out["status_change"] = dict(body.status_change)
    return out


def _comments_to_dict(comments: list[CommentIn] | None) -> list[dict] | None:
    if comments is None:
        return None
    return [
        {"body": c.body, **({"mentions": list(c.mentions)} if c.mentions else {})}
        for c in comments
    ]


def _list_index_files(index_dir: Path) -> list[Path]:
    p = Path(index_dir)
    if not p.is_dir():
        return []
    result: list[Path] = []
    for f in p.glob("*.index.yaml"):
        # Exclude legacy `{slug}-discuss.index.yaml` files (thread model).
        if f.name.endswith("-discuss.index.yaml"):
            continue
        result.append(f)
    return result


def _summarize_matter(
    data: dict,
    users: UserRepo | None = None,
    contacts: ContactRepo | None = None,
) -> dict:
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []
    last = timeline[-1] if timeline else {}
    out: dict = {
        "id": matter.get("id"),
        "title": matter.get("title"),
        "current_status": matter.get("current_status"),
        "created_at": matter.get("created_at"),
        "updated_at": matter.get("updated_at"),
        "file_count": len(timeline),
        "last_file_type": last.get("type"),
        "last_summary": last.get("summary"),
    }
    if users is not None:
        first = timeline[0] if timeline else {}
        creator = first.get("creator")
        out["creator"] = creator
        out["creator_display"] = resolve_id(creator, users, contacts)
        out["creator_avatar_url"] = resolve_avatar_url(creator, users, contacts)
    return out


def _matter_has_owner(data: dict, owner: str) -> bool:
    for item in data.get("timeline") or []:
        if item.get("owner") == owner:
            return True
    return False


def _matter_category(data: dict) -> str | None:
    timeline = data.get("timeline") or []
    if not timeline:
        return None
    first = timeline[0].get("file") or ""
    parts = first.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]


def _render_matter_detail(
    workspace: Workspace,
    data: dict,
    users: UserRepo,
    contacts: ContactRepo,
) -> dict:
    matter = data.get("matter") or {}
    timeline_out = []
    for item in data.get("timeline") or []:
        rendered = _render_item(workspace, item, users, contacts)
        timeline_out.append(rendered)
    return {
        "matter": {
            **matter,
            "file_count": len(timeline_out),
            "last_file_type": timeline_out[-1]["type"] if timeline_out else None,
            "last_summary": timeline_out[-1]["summary"] if timeline_out else None,
        },
        "timeline": timeline_out,
    }


def _render_item(
    workspace: Workspace,
    item: dict,
    users: UserRepo,
    contacts: ContactRepo,
) -> dict:
    out = dict(item)
    # Per pivot-interface.md: every timeline entry carries `expanded: false` and `body`.
    out.setdefault("quote", None)
    out.setdefault("refer", [])
    out.setdefault("comments", [])
    out.setdefault("status_change", None)
    out["expanded"] = False
    out["body"] = _read_item_body(workspace, item.get("file") or "")
    # Name resolution (reuse users→contacts→open_id chain from thread path).
    creator = out.get("creator")
    owner = out.get("owner")
    out["creator_display"] = resolve_id(creator, users, contacts)
    out["creator_avatar_url"] = resolve_avatar_url(creator, users, contacts)
    out["owner_display"] = resolve_id(owner, users, contacts)
    out["owner_avatar_url"] = resolve_avatar_url(owner, users, contacts)
    # Comments: resolve author_display + mentions_display.
    resolved_comments = []
    for c in out.get("comments") or []:
        cc = dict(c)
        author = cc.get("author")
        if author:
            cc["author_display"] = resolve_id(author, users, contacts)
        if cc.get("mentions"):
            cc["mentions_display"] = [
                resolve_id(m, users, contacts) for m in cc["mentions"]
            ]
        # Also resolve @ids inside the comment body text.
        if cc.get("body"):
            cc["body"] = resolve_text(cc["body"], users, contacts)
        resolved_comments.append(cc)
    out["comments"] = resolved_comments
    return out


def _read_item_body(workspace: Workspace, file_rel: str) -> str:
    if not file_rel.startswith("discussions/"):
        return ""
    path = workspace.path / file_rel
    if not path.is_file():
        return ""
    try:
        return read_post(path).body
    except Exception:
        return ""
