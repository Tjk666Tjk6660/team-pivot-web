from __future__ import annotations

import logging
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import json as _json

from server.auth.deps import require_profile
from server.drafts import Draft, DraftRepo
from server.external_bindings import ExternalBindingRepo
from server.matter_validator import validate_append
from server.notify import Notifier
from server.pivot_users import PivotUser, PivotUserRepo
from server.publish import (
    MatterAlreadyExistsError,
    MatterNotFoundError,
    PublishError,
    publish_matter_append,
    publish_matter_create,
)
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
    # P4.6: matter 草稿在 type=proposal|reply 的基础上，用这一块 payload 承载
    # matter 专属结构化字段。payload 为 None 即回落到老 thread 路径。
    matter_payload: dict | None = None


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
    matter_payload: dict | None = None


def build_router(
    workspace: Workspace,
    drafts: DraftRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    notifier: Notifier,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/drafts")

    def _require_owner(draft: Draft | None, user: PivotUser) -> Draft:
        if draft is None:
            raise HTTPException(status_code=404, detail="draft not found")
        if draft.pivot_user_id != user.open_id:
            raise HTTPException(status_code=404, detail="draft not found")
        return draft

    @router.get("")
    def list_drafts(user: PivotUser = Depends(current_user)):
        require_profile(user)
        return {"items": [_to_dict(d) for d in drafts.list_for_user(user.open_id)]}

    @router.post("")
    def create_draft(body: CreateDraftBody, user: PivotUser = Depends(current_user)):
        require_profile(user)
        log.debug(
            "draft create user=%s type=%s matter=%s",
            user.open_id, body.type, body.matter_payload is not None,
        )
        d = drafts.create(
            pivot_user_id=user.open_id,
            type_=body.type,
            title=body.title,
            category=body.category,
            body_md=body.body_md,
            thread_key=body.thread_key,
            mentions_json=_json.dumps(body.mentions.model_dump()) if body.mentions else None,
            reply_to=body.reply_to,
            references_json=_json.dumps(body.references),
            matter_payload_json=(
                _json.dumps(body.matter_payload) if body.matter_payload is not None else None
            ),
        )
        return _to_dict(d)

    @router.get("/{draft_id}")
    def get_draft(draft_id: str, user: PivotUser = Depends(current_user)):
        require_profile(user)
        d = _require_owner(drafts.get(draft_id), user)
        return _to_dict(d)

    @router.patch("/{draft_id}")
    def update_draft(
        draft_id: str, body: UpdateDraftBody,
        user: PivotUser = Depends(current_user),
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
            matter_payload_json=(
                _json.dumps(body.matter_payload) if body.matter_payload is not None else None
            ),
        )
        assert d is not None
        return _to_dict(d)

    @router.delete("/{draft_id}")
    def delete_draft(draft_id: str, user: PivotUser = Depends(current_user)):
        require_profile(user)
        _require_owner(drafts.get(draft_id), user)
        drafts.delete(draft_id)
        return {"ok": True}

    @router.post("/{draft_id}/publish")
    def publish_draft(draft_id: str, user: PivotUser = Depends(current_user)):
        require_profile(user)
        d = _require_owner(drafts.get(draft_id), user)
        matter_payload = _parse_matter_payload(d.matter_payload_json)

        # P4.6: matter 迁移完成后，`/api/drafts/{id}/publish` 是 matter 发布的唯一
        # 草稿路径，不再回落到老 `publish_proposal / publish_reply`——那条路径
        # 数据层面已随 index 迁移废弃，历史草稿必须补全 matter 字段后才能发布。
        # （想直发老 thread 的调用方仍可走 `POST /api/threads`，那是 P5 清理范围。）
        if matter_payload is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "matter_payload_required",
                    "message": (
                        "草稿缺少 matter 字段，请补全 matter_payload"
                        "（doc_type / summary / ...）后再发布"
                    ),
                },
            )

        log.info(
            "draft publish start id=%s user=%s type=%s",
            draft_id, user.open_id, d.type,
        )
        try:
            result = _publish_matter_from_draft(
                workspace, user, d, matter_payload,
                pivot_users=pivot_users, bindings=bindings, notifier=notifier,
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
        "matter_payload": _parse_matter_payload(d.matter_payload_json),
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


def _parse_matter_payload(s: str | None) -> dict | None:
    if not s:
        return None
    try:
        data = _json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _publish_matter_from_draft(
    workspace: Workspace,
    user: PivotUser,
    d: Draft,
    payload: dict,
    *,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    notifier: Notifier,
) -> dict:
    """P4.6: matter 草稿分支。

    draft.type 沿用 proposal|reply 语义：
      - proposal: matter 首篇 → publish_matter_create（需 category + title + initial_file）
      - reply: matter 追加 → publish_matter_append（需 thread_key=matter_id 或 category/matter_id）

    matter item 的结构化字段从 payload 里取：doc_type / summary / owner / quote /
    refer / verifications / outcome / status_change。
    """
    doc_type = str(payload.get("doc_type") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    if not doc_type:
        raise HTTPException(
            status_code=400,
            detail={"code": "matter_doc_type_required"},
        )
    if not summary:
        raise HTTPException(
            status_code=400,
            detail={"code": "matter_summary_required"},
        )

    common_fields: dict = {
        "type": doc_type,
        "summary": summary,
        "body": d.body_md,
    }
    if payload.get("owner"):
        common_fields["owner"] = payload["owner"]
    for key in ("quote", "refer", "verifications", "outcome", "status_change"):
        if payload.get(key) is not None:
            common_fields[key] = payload[key]

    if d.type == "proposal":
        if not d.category:
            raise HTTPException(
                status_code=400, detail="matter proposal draft needs category"
            )
        if not d.title:
            raise HTTPException(
                status_code=400, detail="matter proposal draft needs title"
            )
        # Pre-flight validator against a fresh planning matter so we get a
        # precise 422 rather than a generic ValidationError from the writer.
        fake_index = {
            "matter": {"current_status": "planning"},
            "timeline": [],
        }
        r = validate_append(fake_index, common_fields)
        if not r.ok:
            raise HTTPException(
                status_code=422,
                detail={"code": r.code, "field": r.field, "message": r.message},
            )
        try:
            result = publish_matter_create(
                workspace, user,
                category=d.category,
                title=d.title,
                initial_item=common_fields,
                pivot_users=pivot_users,
                bindings=bindings,
                notifier=notifier,
            )
        except MatterAlreadyExistsError as e:
            raise HTTPException(
                status_code=409,
                detail={"code": "matter_already_exists", "message": str(e)},
            ) from e
        return result

    # d.type == "reply": matter 追加
    if not d.thread_key:
        raise HTTPException(
            status_code=400, detail="matter reply draft needs thread_key"
        )
    # thread_key 可以是 "matter_id" 或 "category/matter_id"；取最后一段作 matter_id。
    matter_id = d.thread_key.split("/")[-1]
    if not matter_id:
        raise HTTPException(
            status_code=400, detail="matter reply draft has empty matter_id"
        )
    try:
        result = publish_matter_append(
            workspace, user,
            matter_id=matter_id,
            item_body=common_fields,
            pivot_users=pivot_users,
            bindings=bindings,
            notifier=notifier,
        )
    except MatterNotFoundError as e:
        raise HTTPException(
            status_code=404, detail={"code": "matter_not_found", "message": str(e)}
        ) from e
    return result
