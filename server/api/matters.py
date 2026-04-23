from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth.deps import require_profile
from server.contacts import ContactRepo
from server.matter_index import (
    matter_index_path,
    read_matter_index,
)
from server.matter_validator import validate_append
from server.notify import Notifier
from server.posts import read_post
from server.publish import (
    MatterAlreadyExistsError,
    MatterNotFoundError,
    PublishError,
    publish_matter_append,
    publish_matter_comment,
    publish_matter_create,
)
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


# ---------- Router ----------


def build_router(
    workspace: Workspace,
    users: UserRepo,
    contacts: ContactRepo,
    notifier: Notifier,
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
        items = []
        for path in _list_index_files(workspace.index_dir):
            data = read_matter_index(path)
            if data is None:
                continue
            summary = _summarize_matter(data)
            if status and summary.get("current_status") != status:
                continue
            if owner and not _matter_has_owner(data, owner):
                continue
            if q and q.lower() not in (summary.get("title") or "").lower():
                continue
            items.append(summary)
        items.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
        return {"items": items}

    @router.get("/matters/{matter_id}")
    def get_matter(matter_id: str, user: User = Depends(current_user)):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        return _render_matter_detail(workspace, data)

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
            )
        except MatterAlreadyExistsError as e:
            raise HTTPException(
                status_code=409,
                detail={"code": "matter_already_exists", "message": str(e)},
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
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
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
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
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
            )
        except MatterNotFoundError as e:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"}) from e
        except ValueError as e:
            # matter_index.append_comment raises ValueError on missing target
            raise HTTPException(
                status_code=404,
                detail={"code": "comment_target_not_found", "message": str(e)},
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


def _summarize_matter(data: dict) -> dict:
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []
    last = timeline[-1] if timeline else {}
    return {
        "id": matter.get("id"),
        "title": matter.get("title"),
        "current_status": matter.get("current_status"),
        "created_at": matter.get("created_at"),
        "updated_at": matter.get("updated_at"),
        "file_count": len(timeline),
        "last_file_type": last.get("type"),
        "last_summary": last.get("summary"),
    }


def _matter_has_owner(data: dict, owner: str) -> bool:
    for item in data.get("timeline") or []:
        if item.get("owner") == owner:
            return True
    return False


def _render_matter_detail(workspace: Workspace, data: dict) -> dict:
    matter = data.get("matter") or {}
    timeline_out = []
    for item in data.get("timeline") or []:
        rendered = _render_item(workspace, item)
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


def _render_item(workspace: Workspace, item: dict) -> dict:
    out = dict(item)
    # Per pivot-interface.md: every timeline entry carries `expanded: false` and `body`.
    out.setdefault("quote", None)
    out.setdefault("refer", [])
    out.setdefault("comments", [])
    out.setdefault("status_change", None)
    out["expanded"] = False
    out["body"] = _read_item_body(workspace, item.get("file") or "")
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
