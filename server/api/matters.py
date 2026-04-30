from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.acl_cache import rebuild_acl_cache
from server.auth.deps import require_profile
from server.contacts import ContactRepo
from server.db import Database
from server.events import TOPIC_MATTER_VISIBILITY_CHANGED, emit
from server.external_bindings import ExternalBindingRepo
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo, ReaderEntry
from server.inbox import (
    compute_matter_unread_breakdown,
    compute_matter_unread_counts,
    latest_matter_post_filename,
)
from server.relevance_events import RelevanceEventsRepo
from server.matter_index import (
    ValidationError as MatterIndexValidationError,
    matter_index_path,
    read_matter_index,
)
from server.matter_validator import validate_append
from server.mentions import (
    DisplayResolver,
    author_view,
    resolve_avatar_url,
    resolve_id,
    resolve_text,
)
from server.notify import Notifier
from server.pivot_users import PivotUserRepo
from server.posts import read_post
from server.publish import (
    AmbiguousMentionError,
    MatterAlreadyExistsError,
    MatterNotFoundError,
    PublishError,
    publish_matter_append,
    publish_matter_comment,
    publish_matter_create,
    publish_matter_owner_change,
)
from server.read_state import ReadStateRepo
from server.users import User, UserRepo
from server.workspace import Workspace
from server.visibility_scopes import CategoryVisibilityScope, VisibilityScope
from server.visibility_store import read_category_visibility, write_matter_visibility


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
    body_source: Literal["ai", "manual"] | None = None


class NewMatterBody(BaseModel):
    # `category` is not in pivot-interface.md §POST /api/matters, but is required
    # to place the MD files on disk under discussions/<category>/<slug>/.
    # Recorded as a non-core deviation in deviations.md.
    category: str = Field(
        min_length=1, max_length=20,
        pattern=r'^[^/\\:*?"<>|\t\n\r]{1,20}$',
    )
    title: str = Field(min_length=1, max_length=200)
    # Optional matter-level owner (distinct from initial_file.owner which is
    # the file-level owner of the first think/act). Defaults to the creator
    # when absent / equal to the creator's open_id.
    owner_open_id: str | None = Field(default=None, max_length=50)
    visibility: dict | None = None
    new_category_visibility: dict | None = None
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
    body_source: Literal["ai", "manual"] | None = None


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


class StatusChangeIn(BaseModel):
    """Status change carried by an owner_change event. Aliases `from` to
    `from_` for Python compatibility; populate_by_name lets us accept both."""
    from_: str = Field(alias="from", min_length=1, max_length=20)
    to: str = Field(min_length=1, max_length=20)

    model_config = {"populate_by_name": True}


class OwnerChangeBody(BaseModel):
    to_owner: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=200)
    status_change: StatusChangeIn | None = None


class MatterVisibilityBody(BaseModel):
    mode: str = "public"
    roles: list[str] | None = None
    user_ids: list[str] | None = None


# ---------- Router ----------


def build_router(
    workspace: Workspace,
    users: UserRepo,
    contacts: ContactRepo,
    notifier: Notifier,
    read_states: ReadStateRepo,
    favorites: FavoriteRepo,
    file_reads: FileReadRepo,
    relevance_repo: RelevanceEventsRepo,
    resolver: DisplayResolver,
    current_user: Callable,
    db: Database | None = None,
    pivot_users: PivotUserRepo | None = None,
    bindings: ExternalBindingRepo | None = None,
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
        breakdown = compute_matter_unread_breakdown(
            workspace.discussions_dir, workspace.index_dir,
            user.open_id, read_states, relevance_repo,
        )
        favorite_keys = favorites.all_for_user(user.open_id)

        items = []
        for path in _list_index_files(workspace.index_dir):
            data = read_matter_index(path)
            if data is None:
                continue
            if not _can_read_matter(data, user, db, workspace):
                continue
            summary = _summarize_matter(data, resolver)
            if status and summary.get("current_status") != status:
                continue
            if owner and not _matter_has_owner(data, owner):
                continue
            if q and q.lower() not in (summary.get("title") or "").lower():
                continue
            category = _matter_category(data)
            key = f"{category}/{summary['id']}" if category else summary["id"]
            red, gray = breakdown.get(key, (0, 0))
            summary["red_unread_count"] = red
            summary["gray_unread_count"] = gray
            # unread_count keeps the "total unread" semantic (red + gray) so
            # older frontends that read only this field stay correct.
            summary["unread_count"] = red + gray
            summary["favorite"] = key in favorite_keys
            summary["category"] = category
            # Derived "any activity" timestamp: matter.updated_at only moves
            # on file appends; comments do not bump it (per pivot-product.md
            # design — comments are discussion, not progress). For list
            # sorting we want comments to count too so that a newly @-ed
            # matter floats to the top, hence this max() over both sources.
            summary["last_activity_at"] = _matter_last_activity_at(data)
            items.append(summary)
        items.sort(key=lambda m: m.get("last_activity_at") or "", reverse=True)
        return {"items": items}

    @router.get("/matters/{matter_id}")
    def get_matter(matter_id: str, user: User = Depends(current_user)):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        rendered = _render_matter_detail(workspace, data, resolver)
        category = _matter_category(data)
        key = f"{category}/{matter_id}" if category else matter_id
        rendered["matter"]["category"] = category
        rendered["matter"]["favorite"] = favorites.has(user.open_id, key)
        _inject_readers(rendered["timeline"], matter_id, file_reads, resolver)
        _inject_relevance(
            rendered["timeline"], matter_id, user.open_id, relevance_repo,
        )
        return rendered

    @router.post("/matters/{matter_id}/files/{filename}/read")
    def mark_file_read(
        matter_id: str,
        filename: str,
        user: User = Depends(current_user),
    ):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _timeline_has_file(data, filename):
            raise HTTPException(
                status_code=404,
                detail={"code": "file_not_in_matter"},
            )
        entry = file_reads.mark(user.open_id, matter_id, filename)
        # Side effect: clear file-level + mention rows on this file. Aligns
        # mention "已读" with the card-level read trigger; matter-level
        # POST /matters/{id}/read is intentionally NOT changed, see v3.1 §3.4.
        relevance_repo.mark_all_read_for_file(user.open_id, matter_id, filename)
        return {
            "matter_id": matter_id,
            "filename": filename,
            "first_read_at": _ts_to_iso(entry.first_read_at),
        }

    @router.post("/matters/{matter_id}/read")
    def mark_read(matter_id: str, user: User = Depends(current_user)):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
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
        if data is None or not _can_read_matter(data, user, db, workspace):
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

    @router.get("/matters/{matter_id}/visibility")
    def get_matter_visibility(
        matter_id: str,
        user: User = Depends(current_user),
    ):
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        matter = data.get("matter") or {}
        visibility = VisibilityScope.from_dict(matter.get("visibility"))
        return {"visibility": visibility.to_dict()}

    @router.put("/matters/{matter_id}/visibility")
    def update_matter_visibility(
        matter_id: str,
        body: MatterVisibilityBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _can_write_matter(data, user, db, workspace):
            raise HTTPException(status_code=403, detail={"code": "matter_write_forbidden"})
        if not _can_edit_matter_visibility(data, user):
            raise HTTPException(
                status_code=403,
                detail={"code": "matter_visibility_forbidden"},
            )

        try:
            visibility = VisibilityScope.from_dict(body.model_dump())
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_visibility", "message": str(e)},
            ) from e
        category = _matter_category(data)
        if category:
            category_visibility = read_category_visibility(
                workspace.path / "categories",
                category,
            )
            if (
                category_visibility.mode == "restricted"
                and visibility.mode == "restricted"
            ):
                extra = set(visibility.roles) - set(category_visibility.authorized_roles)
                if extra:
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "visibility_scope_exceeds_category"},
                    )
        required = [_matter_creator(data), _effective_matter_owner(data)]
        for principal in {value for value in required if value}:
            if not _scope_allows_principal(principal, visibility, db):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "visibility_excludes_required_user"},
                )

        with workspace.write_session(
            message=f"chore: update matter visibility {matter_id}",
            author_name=user.name,
            author_email=f"{user.pinyin}@pivot.local",
        ):
            write_matter_visibility(workspace.index_dir, matter_id, visibility)

        _refresh_acl_cache(db, workspace)
        emit(
            TOPIC_MATTER_VISIBILITY_CHANGED,
            matter_id=matter_id,
            actor=user.pinyin or user.open_id,
            payload={"visibility": visibility.to_dict()},
        )
        return {"visibility": visibility.to_dict()}

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
        if body.initial_file.body_source is not None:
            initial["body_source"] = body.initial_file.body_source
        _preflight_initial(initial)
        try:
            visibility = VisibilityScope.from_dict(body.visibility)
            new_category_visibility = (
                CategoryVisibilityScope.from_dict(body.new_category_visibility)
                if body.new_category_visibility is not None
                else None
            )
            category_visibility_path = workspace.path / "categories" / f"{body.category}.yaml"
            if (
                not category_visibility_path.is_file()
                and visibility.mode == "restricted"
                and new_category_visibility is None
            ):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "missing_category_visibility"},
                )
            if (
                new_category_visibility is not None
                and new_category_visibility.mode == "restricted"
                and visibility.mode == "restricted"
            ):
                extra = set(visibility.roles) - set(new_category_visibility.authorized_roles)
                if extra:
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "visibility_scope_exceeds_category"},
                    )
            result = publish_matter_create(
                workspace, user,
                category=body.category,
                title=body.title,
                initial_item=initial,
                matter_owner_open_id=body.owner_open_id,
                contacts=contacts,
                notifier=notifier,
                users=users,
                pivot_users=pivot_users,
                bindings=bindings,
                file_reads=file_reads,
                visibility=visibility,
                new_category_visibility=new_category_visibility,
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
            # publish_matter_create raises "matter owner not found: …" when the
            # supplied owner_open_id can't be resolved. Translate to 422 with
            # the canonical owner_unknown code.
            msg = str(e)
            if msg.startswith("matter owner not found"):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "owner_unknown",
                        "field": "owner_open_id",
                        "message": msg,
                    },
                ) from e
            raise HTTPException(status_code=400, detail=msg) from e
        _refresh_acl_cache(db, workspace)
        return {
            "matter": result["matter"],
            "initial_timeline_item": result["item"],
            "matter_id": result["matter_id"],
            "file": result["file"],
        }

    @router.post("/matters/{matter_id}/owner")
    def transfer_owner(
        matter_id: str,
        body: OwnerChangeBody,
        user: User = Depends(current_user),
    ):
        require_profile(user)
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _can_write_matter(data, user, db, workspace):
            raise HTTPException(status_code=403, detail={"code": "matter_write_forbidden"})
        sc_dict = (
            {"from": body.status_change.from_, "to": body.status_change.to}
            if body.status_change
            else None
        )
        try:
            result = publish_matter_owner_change(
                workspace, user,
                matter_id=matter_id,
                to_owner_open_id=body.to_owner,
                reason=body.reason,
                status_change=sc_dict,
                contacts=contacts,
                notifier=notifier,
                users=users,
                pivot_users=pivot_users,
                bindings=bindings,
            )
        except MatterNotFoundError as e:
            raise HTTPException(
                status_code=404, detail={"code": "matter_not_found"}
            ) from e
        except MatterIndexValidationError as e:
            # Owner_stale / status_stale → conflict (409) so clients can retry
            # after a refresh; everything else (reason / shape) → 422.
            code = e.result.code or "validation_error"
            status = 409 if code in ("owner_stale", "status_stale") else 422
            raise HTTPException(
                status_code=status,
                detail={
                    "code": code,
                    "field": e.result.field,
                    "message": e.result.message,
                },
            ) from e
        except PublishError as e:
            msg = str(e)
            if msg.startswith("owner_unknown:"):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "owner_unknown",
                        "field": "to_owner",
                        "message": f"owner not found: {msg.split(':', 1)[1]}",
                    },
                ) from e
            raise HTTPException(status_code=400, detail=msg) from e
        rendered_detail = _render_matter_detail(
            workspace,
            {
                "matter": result["matter"],
                "timeline": [result["item"]],
            },
            resolver,
        )
        return {
            "matter": rendered_detail["matter"],
            "item": rendered_detail["timeline"][0],
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
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _can_write_matter(data, user, db, workspace):
            raise HTTPException(status_code=403, detail={"code": "matter_write_forbidden"})

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
                pivot_users=pivot_users,
                bindings=bindings,
                file_reads=file_reads,
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
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _can_write_matter(data, user, db, workspace):
            raise HTTPException(status_code=403, detail={"code": "matter_write_forbidden"})

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
                pivot_users=pivot_users,
                bindings=bindings,
                file_reads=file_reads,
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
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        if not _can_write_matter(data, user, db, workspace):
            raise HTTPException(status_code=403, detail={"code": "matter_write_forbidden"})
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
    if body.body_source is not None:
        out["body_source"] = body.body_source
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
    resolver: DisplayResolver | None = None,
) -> dict:
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []
    # file_count / last_file_type / last_summary are file-only. Skip event-type
    # entries (owner_change) so a recent transfer doesn't mask the actual last
    # file in the list.
    file_items = [t for t in timeline if t.get("type") not in {"owner_change"}]
    last_file = file_items[-1] if file_items else {}
    out: dict = {
        "id": matter.get("id"),
        "title": matter.get("title"),
        "current_status": matter.get("current_status"),
        "created_at": matter.get("created_at"),
        "updated_at": matter.get("updated_at"),
        "file_count": len(file_items),
        "last_file_type": last_file.get("type"),
        "last_summary": last_file.get("summary"),
    }
    if resolver is not None:
        # creator = original first file's creator (matter.creator equivalent).
        first_file = file_items[0] if file_items else {}
        creator = first_file.get("creator")
        out["creator"] = creator
        out["creator_display"] = resolve_id(creator, resolver)
        out["creator_avatar_url"] = resolve_avatar_url(creator, resolver)
        out["creator_view"] = author_view(creator, resolver)
        # matter-level owner: prefer matter.owner; for legacy indexes where
        # the key is missing, fall back to first timeline file owner/creator.
        # Explicit owner: null still means unassigned.
        owner = _effective_matter_owner(data)
        out["owner"] = owner
        out["owner_display"] = resolve_id(owner, resolver) if owner else None
        out["owner_avatar_url"] = (
            resolve_avatar_url(owner, resolver) if owner else None
        )
        out["owner_view"] = author_view(owner, resolver) if owner else None
    return out


def _matter_has_owner(data: dict, owner: str) -> bool:
    matter_owner = _effective_matter_owner(data)
    if matter_owner == owner:
        return True
    for item in data.get("timeline") or []:
        if item.get("owner") == owner:
            return True
    return False


def _matter_creator(data: dict) -> str | None:
    for item in data.get("timeline") or []:
        if item.get("type") == "owner_change":
            continue
        return item.get("creator")
    return None


def _can_edit_matter_visibility(data: dict, user: User) -> bool:
    user_id = user.pinyin or user.open_id
    return user_id in {_matter_creator(data), _effective_matter_owner(data)}


def _can_read_matter(
    data: dict,
    user: User,
    db: Database | None,
    workspace: Workspace,
) -> bool:
    category = _matter_category(data)
    roles = _roles_for_user(user, db)
    identifiers = _identifiers_for_user(user)
    if category:
        category_visibility = read_category_visibility(
            workspace.path / "categories",
            category,
        )
        if category_visibility.mode == "restricted" and not (
            set(roles) & set(category_visibility.authorized_roles)
        ):
            return False

    visibility = VisibilityScope.from_dict((data.get("matter") or {}).get("visibility"))
    if visibility.mode == "public":
        return True
    if set(roles) & set(visibility.roles):
        return True
    return bool(set(identifiers) & set(visibility.user_ids))


def _can_write_matter(
    data: dict,
    user: User,
    db: Database | None,
    workspace: Workspace,
) -> bool:
    return _can_read_matter(data, user, db, workspace)


def _identifiers_for_user(user: User) -> list[str]:
    values = [
        getattr(user, "id", None),
        getattr(user, "open_id", None),
        getattr(user, "pinyin", None),
        getattr(user, "email", None),
    ]
    return [str(v) for v in values if v]


def _roles_for_user(user: User, db: Database | None) -> list[str]:
    roles = getattr(user, "roles", None)
    if isinstance(roles, list):
        return [str(role) for role in roles]
    if db is None:
        return []
    identifiers = _identifiers_for_user(user)
    if not identifiers:
        return []
    placeholders = ",".join("?" for _ in identifiers)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT role FROM pivot_user"
            f" WHERE status='active' AND (id IN ({placeholders})"
            f" OR pinyin IN ({placeholders}) OR email IN ({placeholders}))"
            " LIMIT 1",
            (*identifiers, *identifiers, *identifiers),
        ).fetchone()
    if row is None:
        return []
    return _decode_role_list(row["role"])


def _roles_for_principal(principal_id: str | None, db: Database | None) -> list[str]:
    if not principal_id or db is None:
        return []
    with db.connect() as conn:
        row = conn.execute(
            "SELECT role FROM pivot_user"
            " WHERE status='active' AND (id=? OR pinyin=? OR email=?)"
            " LIMIT 1",
            (principal_id, principal_id, principal_id),
        ).fetchone()
    if row is None:
        return []
    return _decode_role_list(row["role"])


def _scope_allows_principal(
    principal_id: str,
    visibility: VisibilityScope,
    db: Database | None,
) -> bool:
    if visibility.mode == "public":
        return True
    if principal_id in visibility.user_ids:
        return True
    roles = _roles_for_principal(principal_id, db)
    return bool(set(roles) & set(visibility.roles))


def _decode_role_list(raw: str) -> list[str]:
    import json

    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return [value]


def _refresh_acl_cache(db: Database | None, workspace: Workspace) -> None:
    if db is None:
        return
    rebuild_acl_cache(
        db,
        index_dir=workspace.index_dir,
        categories_dir=workspace.path / "categories",
    )


def _matter_category(data: dict) -> str | None:
    timeline = data.get("timeline") or []
    if not timeline:
        return None
    first = timeline[0].get("file") or ""
    parts = first.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]


def _matter_last_activity_at(data: dict) -> str:
    """Latest ISO timestamp across matter.updated_at + every comment.created_at.

    matter.updated_at only moves on file appends; comments deliberately do
    not bump it (pivot-product.md treats comments as discussion, not
    matter progress). Using this derived field for list sort lets a matter
    that just got a new comment / @-mention float to the top, while
    leaving the on-disk index schema untouched.
    """
    matter = data.get("matter") or {}
    latest = str(matter.get("updated_at") or "")
    for item in data.get("timeline") or []:
        for c in item.get("comments") or []:
            ca = str(c.get("created_at") or "")
            if ca > latest:
                latest = ca
    return latest


def _render_matter_detail(
    workspace: Workspace,
    data: dict,
    resolver: DisplayResolver,
) -> dict:
    matter = data.get("matter") or {}
    timeline_out = []
    for item in data.get("timeline") or []:
        rendered = _render_item(workspace, item, resolver)
        timeline_out.append(rendered)
    # last_file_type / last_summary skip owner_change events (no summary).
    file_items = [t for t in timeline_out if t.get("type") not in {"owner_change"}]
    last_file = file_items[-1] if file_items else None
    # Resolve matter-level owner display + avatar via the same fallback as
    # _summarize_matter (matter.owner → first file owner/creator → null).
    owner = _effective_matter_owner({"matter": matter, "timeline": file_items})
    matter_out = {
        **matter,
        "file_count": len(file_items),
        "last_file_type": last_file["type"] if last_file else None,
        "last_summary": last_file.get("summary") if last_file else None,
        "owner": owner,
        "owner_display": resolve_id(owner, resolver) if owner else None,
        "owner_avatar_url": (
            resolve_avatar_url(owner, resolver) if owner else None
        ),
        "owner_view": author_view(owner, resolver) if owner else None,
    }
    return {"matter": matter_out, "timeline": timeline_out}


def _effective_matter_owner(data: dict) -> str | None:
    matter = data.get("matter") or {}
    if "owner" in matter:
        return matter.get("owner")
    for item in data.get("timeline") or []:
        if item.get("type") == "owner_change":
            continue
        return item.get("owner") or item.get("creator")
    return None


def _render_item(
    workspace: Workspace,
    item: dict,
    resolver: DisplayResolver,
) -> dict:
    # Owner_change events have a different shape — no file / body / creator /
    # comments / readers. Branch early so the file-type defaults below don't
    # pollute event entries.
    if item.get("type") == "owner_change":
        return _render_owner_change_item(item, resolver)
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
    out["creator_display"] = resolve_id(creator, resolver)
    out["creator_avatar_url"] = resolve_avatar_url(creator, resolver)
    out["creator_view"] = author_view(creator, resolver)
    out["owner_display"] = resolve_id(owner, resolver)
    out["owner_avatar_url"] = resolve_avatar_url(owner, resolver)
    out["owner_view"] = author_view(owner, resolver)
    # Comments: resolve author_display + mentions_display.
    resolved_comments = []
    for c in out.get("comments") or []:
        cc = dict(c)
        author = cc.get("author")
        if author:
            cc["author_display"] = resolve_id(author, resolver)
            cc["author_view"] = author_view(author, resolver)
        if cc.get("mentions"):
            cc["mentions_display"] = [
                resolve_id(m, resolver) for m in cc["mentions"]
            ]
            cc["mentions_view"] = [
                author_view(m, resolver) for m in cc["mentions"]
            ]
        # Also resolve @ids inside the comment body text.
        if cc.get("body"):
            cc["body"] = resolve_text(cc["body"], resolver)
        resolved_comments.append(cc)
    out["comments"] = resolved_comments
    return out


def _render_owner_change_item(
    item: dict,
    resolver: DisplayResolver,
) -> dict:
    """Render an owner_change timeline event with display + avatar resolution.

    Distinct shape from file-type entries: no file / body / quote / refer /
    comments / readers, but adds actor / from_owner / to_owner display +
    avatar fields. status_change is preserved as-is.
    """
    out = dict(item)
    actor = out.get("actor")
    out["actor_display"] = resolve_id(actor, resolver) if actor else None
    out["actor_avatar_url"] = (
        resolve_avatar_url(actor, resolver) if actor else None
    )
    out["actor_view"] = author_view(actor, resolver) if actor else None
    from_owner = out.get("from_owner")
    out["from_owner_display"] = (
        resolve_id(from_owner, resolver) if from_owner else None
    )
    out["from_owner_avatar_url"] = (
        resolve_avatar_url(from_owner, resolver) if from_owner else None
    )
    out["from_owner_view"] = (
        author_view(from_owner, resolver) if from_owner else None
    )
    to_owner = out.get("to_owner")
    out["to_owner_display"] = (
        resolve_id(to_owner, resolver) if to_owner else None
    )
    out["to_owner_avatar_url"] = (
        resolve_avatar_url(to_owner, resolver) if to_owner else None
    )
    out["to_owner_view"] = (
        author_view(to_owner, resolver) if to_owner else None
    )
    # Frontend timeline iterates over a heterogeneous list — keep readers_count
    # at 0 (consistent with FileCard's empty state) so consumers don't have to
    # special-case missing keys.
    out.setdefault("status_change", None)
    out["readers_count"] = 0
    out["readers"] = []
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


def _timeline_has_file(data: dict, filename: str) -> bool:
    """Match by basename so the API accepts `01-decision.md` against
    `discussions/<cat>/<matter>/01-decision.md`."""
    for item in data.get("timeline") or []:
        rel = item.get("file") or ""
        if rel.endswith("/" + filename) or rel == filename:
            return True
    return False


def _ts_to_iso(ts: float) -> str:
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def _inject_readers(
    timeline: list[dict],
    matter_id: str,
    file_reads: FileReadRepo,
    resolver: DisplayResolver,
) -> None:
    by_file = file_reads.list_for_matter(matter_id)
    for item in timeline:
        rel = item.get("file") or ""
        basename = rel.rsplit("/", 1)[-1]
        readers_raw = by_file.get(basename, [])
        item["readers_count"] = len(readers_raw)
        item["readers"] = [
            _reader_to_dict(r, resolver) for r in readers_raw
        ]


def _reader_to_dict(
    entry: ReaderEntry,
    resolver: DisplayResolver,
) -> dict:
    return {
        "open_id": entry.open_id,
        "name": resolve_id(entry.open_id, resolver),
        "avatar_url": resolve_avatar_url(entry.open_id, resolver),
        "view": author_view(entry.open_id, resolver),
        "first_read_at": _ts_to_iso(entry.first_read_at),
    }


def _inject_relevance(
    timeline: list[dict],
    matter_id: str,
    pivot_user_id: str,
    relevance_repo: RelevanceEventsRepo,
) -> None:
    """Attach `relevance_reason` to each timeline item and
    `mention_unread_for_me` to each comment, based on the current user's
    relevance_events rows for this matter. Two SQL reads regardless of
    timeline length: one for file reasons, one for unread mention keys.
    """
    file_reasons = relevance_repo.file_reasons_for_matter(pivot_user_id, matter_id)
    unread_mention_keys = relevance_repo.unread_mention_keys_for_matter(
        pivot_user_id, matter_id,
    )

    for item in timeline:
        rel = item.get("file") or ""
        basename = rel.rsplit("/", 1)[-1]
        item["relevance_reason"] = file_reasons.get(basename)

        for comment in item.get("comments") or []:
            key = (
                basename,
                str(comment.get("created_at") or ""),
                str(comment.get("author") or ""),
            )
            comment["mention_unread_for_me"] = key in unread_mention_keys
