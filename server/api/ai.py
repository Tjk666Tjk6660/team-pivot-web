from __future__ import annotations

import json
import logging

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.ai.client import AIError, DEFAULT_BASE_URL, DEFAULT_MODEL, stream_chat
from server.ai.context import (
    ContextTooLongError,
    build_context_from_files,
    truncate_messages,
)
from server.ai.prompts import build_system_prompt
from server.ai_conversations import AIConversationRepo
from server.auth.admin import require_admin
from server.matter_index import matter_index_path, read_matter_index
from server.posts import read_post
from server.settings import SettingsRepo
from server.threads import list_threads, get_thread
from server.users import User
from server.workspace import Workspace

log = logging.getLogger("server.api.ai")

_KEY_API_KEY = "ai.openrouter_api_key"
_KEY_BASE_URL = "ai.base_url"
_KEY_MODEL = "ai.model"
_KEY_MAX_CONTEXT_TOKENS = "ai.max_context_tokens"
_KEY_MIN_ROUNDS = "ai.min_rounds"
_KEY_MAX_ROUNDS = "ai.max_rounds"

_DEFAULT_MAX_CONTEXT_TOKENS = 5000
_DEFAULT_MIN_ROUNDS = 3
_DEFAULT_MAX_ROUNDS = 20


def _get_int(settings: SettingsRepo, key: str, default: int) -> int:
    v = settings.get(key)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


class ChatMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=50000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    reply_target: str | None = Field(default=None, max_length=300)
    reference_files: list[str] = Field(default_factory=list, max_length=4)


class AISettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=100)
    max_context_tokens: int | None = Field(default=None, ge=1000, le=200000)
    min_rounds: int | None = Field(default=None, ge=1, le=50)
    max_rounds: int | None = Field(default=None, ge=1, le=200)


class ConversationSave(BaseModel):
    messages: list[ChatMessage] = Field(max_length=500)
    reply_target: str | None = Field(default=None, max_length=300)
    reference_files: list[str] = Field(default_factory=list, max_length=4)


def build_router(
    workspace: Workspace,
    settings: SettingsRepo,
    conversations: AIConversationRepo,
    current_user: Callable,
    current_user_cookie_only: Callable,
) -> APIRouter:
    router = APIRouter()

    # ── Settings ──────────────────────────────────────────────────────────────
    # Admin-gated AND cookie-only — PATs cannot read/write the AI API key.

    @router.get("/api/ai/settings", dependencies=[Depends(require_admin)])
    def get_ai_settings(_: User = Depends(current_user_cookie_only)):
        return {
            "base_url": settings.get(_KEY_BASE_URL) or DEFAULT_BASE_URL,
            "model": settings.get(_KEY_MODEL) or DEFAULT_MODEL,
            "has_key": bool(settings.get(_KEY_API_KEY)),
            "max_context_tokens": _get_int(settings, _KEY_MAX_CONTEXT_TOKENS, _DEFAULT_MAX_CONTEXT_TOKENS),
            "min_rounds": _get_int(settings, _KEY_MIN_ROUNDS, _DEFAULT_MIN_ROUNDS),
            "max_rounds": _get_int(settings, _KEY_MAX_ROUNDS, _DEFAULT_MAX_ROUNDS),
        }

    @router.put("/api/ai/settings", dependencies=[Depends(require_admin)])
    def update_ai_settings(
        body: AISettingsUpdate,
        _: User = Depends(current_user_cookie_only),
    ):
        if body.api_key is not None:
            settings.set(_KEY_API_KEY, body.api_key)
        if body.base_url is not None:
            normalized = body.base_url.strip().rstrip("/") if body.base_url.strip() else DEFAULT_BASE_URL
            settings.set(_KEY_BASE_URL, normalized)
        if body.model is not None:
            settings.set(_KEY_MODEL, body.model)
        if body.max_context_tokens is not None:
            settings.set(_KEY_MAX_CONTEXT_TOKENS, str(body.max_context_tokens))
        if body.min_rounds is not None:
            settings.set(_KEY_MIN_ROUNDS, str(body.min_rounds))
        if body.max_rounds is not None:
            settings.set(_KEY_MAX_ROUNDS, str(body.max_rounds))
        return {"ok": True}

    # ── File tree ─────────────────────────────────────────────────────────────

    @router.get("/api/ai/files")
    def list_ai_files(_: User = Depends(current_user)):
        metas = list_threads(workspace.discussions_dir, workspace.index_dir)
        items = []
        for meta in metas[:200]:
            detail = get_thread(
                workspace.discussions_dir, workspace.index_dir, meta.category, meta.slug
            )
            if detail is None:
                continue
            files = []
            for post in detail.posts:
                fm = post.frontmatter
                files.append({
                    "path": f"{meta.category}/{meta.slug}/{post.filename}",
                    "filename": post.filename,
                    "type": str(fm.get("type", "")),
                    "author": str(fm.get("author", "")),
                    "created": str(fm.get("created", "")),
                })
            if files:
                items.append({
                    "category": meta.category,
                    "slug": meta.slug,
                    "title": meta.title,
                    "files": files,
                })
        return {"items": items}

    # ── Conversation persistence ───────────────────────────────────────────────

    @router.get("/api/ai/threads/{category}/{slug}/conversation")
    def get_conversation(
        category: str,
        slug: str,
        user: User = Depends(current_user),
    ):
        messages, reply_target, reference_files = conversations.get(
            user.open_id, f"{category}/{slug}"
        )
        return {
            "messages": messages,
            "reply_target": reply_target,
            "reference_files": reference_files,
        }

    @router.put("/api/ai/threads/{category}/{slug}/conversation")
    def save_conversation(
        category: str,
        slug: str,
        body: ConversationSave,
        user: User = Depends(current_user),
    ):
        conversations.save(
            user.open_id,
            f"{category}/{slug}",
            [{"role": m.role, "content": m.content} for m in body.messages],
            body.reply_target,
            body.reference_files,
        )
        return {"ok": True}

    @router.delete("/api/ai/threads/{category}/{slug}/conversation")
    def clear_conversation(
        category: str,
        slug: str,
        user: User = Depends(current_user),
    ):
        conversations.delete(user.open_id, f"{category}/{slug}")
        return {"ok": True}

    # ── Chat (SSE) ─────────────────────────────────────────────────────────────

    @router.post("/api/ai/threads/{category}/{slug}/chat")
    async def chat(
        category: str,
        slug: str,
        body: ChatRequest,
        _: User = Depends(current_user),
    ):
        api_key = settings.get(_KEY_API_KEY)
        if not api_key:
            raise HTTPException(400, "未配置 AI API Key，请在【设置】中配置")

        base_url = settings.get(_KEY_BASE_URL) or DEFAULT_BASE_URL
        model = settings.get(_KEY_MODEL) or DEFAULT_MODEL
        max_context_tokens = _get_int(settings, _KEY_MAX_CONTEXT_TOKENS, _DEFAULT_MAX_CONTEXT_TOKENS)
        min_rounds = _get_int(settings, _KEY_MIN_ROUNDS, _DEFAULT_MIN_ROUNDS)
        max_rounds = _get_int(settings, _KEY_MAX_ROUNDS, _DEFAULT_MAX_ROUNDS)

        if not body.reply_target:
            raise HTTPException(400, "请先选择「回复对象」文件")

        try:
            file_context = build_context_from_files(
                workspace.discussions_dir,
                body.reply_target,
                body.reference_files,
            )
        except ContextTooLongError as e:
            raise HTTPException(422, str(e))

        system_prompt = build_system_prompt(file_context)
        all_messages = [{"role": m.role, "content": m.content} for m in body.messages]
        selected = truncate_messages(
            all_messages,
            system_prompt_len=len(system_prompt),
            max_context_tokens=max_context_tokens,
            min_rounds=min_rounds,
            max_rounds=max_rounds,
        )
        llm_messages = [{"role": "system", "content": system_prompt}] + selected

        async def generate():
            try:
                async for delta in stream_chat(llm_messages, model, api_key, base_url):
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
            except AIError as e:
                log.warning("ai chat error: %s", e)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            except Exception:
                log.exception("unexpected ai error")
                yield f"data: {json.dumps({'error': '服务异常，请稍后重试'})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # ── Matter AI routes (P4.5) ────────────────────────────────────────────────
    # Mirror the thread routes above, but key conversations on
    # `category/matter_id` (derived from the matter index). matter_id equals
    # slug, so the existing ai_conversations schema is reused unchanged.

    def _matter_thread_key(matter_id: str) -> str:
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None:
            raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
        timeline = data.get("timeline") or []
        if timeline:
            first = (timeline[0].get("file") or "").split("/")
            if len(first) >= 4 and first[0] == "discussions":
                return f"{first[1]}/{matter_id}"
        return matter_id

    @router.get("/api/ai/matters/{matter_id}/conversation")
    def get_matter_conversation(
        matter_id: str,
        user: User = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id)
        messages, reply_target, reference_files = conversations.get(
            user.open_id, key
        )
        return {
            "messages": messages,
            "reply_target": reply_target,
            "reference_files": reference_files,
        }

    @router.put("/api/ai/matters/{matter_id}/conversation")
    def save_matter_conversation(
        matter_id: str,
        body: ConversationSave,
        user: User = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id)
        conversations.save(
            user.open_id, key,
            [{"role": m.role, "content": m.content} for m in body.messages],
            body.reply_target,
            body.reference_files,
        )
        return {"ok": True}

    @router.delete("/api/ai/matters/{matter_id}/conversation")
    def clear_matter_conversation(
        matter_id: str,
        user: User = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id)
        conversations.delete(user.open_id, key)
        return {"ok": True}

    @router.post("/api/ai/matters/{matter_id}/chat")
    async def chat_matter(
        matter_id: str,
        body: ChatRequest,
        _: User = Depends(current_user),
    ):
        # Existence check — produces 404 before we burn an API call.
        _matter_thread_key(matter_id)

        api_key = settings.get(_KEY_API_KEY)
        if not api_key:
            raise HTTPException(400, "未配置 AI API Key，请在【设置】中配置")

        base_url = settings.get(_KEY_BASE_URL) or DEFAULT_BASE_URL
        model = settings.get(_KEY_MODEL) or DEFAULT_MODEL
        max_context_tokens = _get_int(settings, _KEY_MAX_CONTEXT_TOKENS, _DEFAULT_MAX_CONTEXT_TOKENS)
        min_rounds = _get_int(settings, _KEY_MIN_ROUNDS, _DEFAULT_MIN_ROUNDS)
        max_rounds = _get_int(settings, _KEY_MAX_ROUNDS, _DEFAULT_MAX_ROUNDS)

        if not body.reply_target:
            raise HTTPException(400, "请先选择「回复对象」文件")

        try:
            file_context = build_context_from_files(
                workspace.discussions_dir,
                body.reply_target,
                body.reference_files,
            )
        except ContextTooLongError as e:
            raise HTTPException(422, str(e))

        system_prompt = build_system_prompt(file_context)
        all_messages = [{"role": m.role, "content": m.content} for m in body.messages]
        selected = truncate_messages(
            all_messages,
            system_prompt_len=len(system_prompt),
            max_context_tokens=max_context_tokens,
            min_rounds=min_rounds,
            max_rounds=max_rounds,
        )
        llm_messages = [{"role": "system", "content": system_prompt}] + selected

        async def generate():
            try:
                async for delta in stream_chat(llm_messages, model, api_key, base_url):
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
            except AIError as e:
                log.warning("ai matter chat error: %s", e)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            except Exception:
                log.exception("unexpected ai matter chat error")
                yield f"data: {json.dumps({'error': '服务异常，请稍后重试'})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router
