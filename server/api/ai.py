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
    build_starting_post_block,
    truncate_messages,
)
from server.ai.prompts import build_system_prompt
from server.ai.tools import AITools
from server.ai_conversations import AIConversationRepo
from server.auth.admin import require_admin
from server.matter_index import matter_index_path, read_matter_index
from server.settings import SettingsRepo
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

_MAX_TOOL_TURNS = 8


def _get_int(settings: SettingsRepo, key: str, default: int) -> int:
    v = settings.get(key)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


class ChatMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=50000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    reply_target: str | None = Field(default=None, max_length=300)


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


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


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

    # ── Conversation persistence + chat (SSE) ────────────────────────────────
    # Both conversation key and chat are matter-scoped. Conversation key is
    # `category/matter_id` (derived from the matter index by `_matter_thread_key`);
    # the chat endpoint never validates matter existence — `build_starting_post_block`
    # silently downgrades to an empty starting block on a missing path, so callers
    # like NewMatter can use a placeholder matter_id to generate ad-hoc summaries.

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
        messages, reply_target = conversations.get(user.open_id, key)
        return {
            "messages": messages,
            "reply_target": reply_target,
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
            [m.model_dump() for m in body.messages],
            body.reply_target,
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
        # No existence check: build_starting_post_block silently downgrades to
        # an empty starting block on missing/invalid paths, so callers like
        # NewMatter (matter not yet created) can use a placeholder matter_id
        # to generate ad-hoc summaries without us 404-ing them upfront.

        api_key = settings.get(_KEY_API_KEY)
        if not api_key:
            raise HTTPException(400, "未配置 AI API Key，请在【设置】中配置")

        base_url = settings.get(_KEY_BASE_URL) or DEFAULT_BASE_URL
        model = settings.get(_KEY_MODEL) or DEFAULT_MODEL
        max_context_tokens = _get_int(settings, _KEY_MAX_CONTEXT_TOKENS, _DEFAULT_MAX_CONTEXT_TOKENS)
        min_rounds = _get_int(settings, _KEY_MIN_ROUNDS, _DEFAULT_MIN_ROUNDS)
        max_rounds = _get_int(settings, _KEY_MAX_ROUNDS, _DEFAULT_MAX_ROUNDS)

        if not body.reply_target:
            raise HTTPException(400, "缺少起点帖子（reply_target）")

        try:
            starting_block = build_starting_post_block(
                workspace.discussions_dir, workspace.index_dir, body.reply_target
            )
        except ContextTooLongError as e:
            raise HTTPException(422, str(e))

        system_prompt = build_system_prompt(starting_block)
        user_history = [{"role": m.role, "content": m.content} for m in body.messages]

        tools_handler = AITools(workspace.discussions_dir, workspace.index_dir)
        tool_specs = tools_handler.specs()

        async def generate():
            try:
                selected = truncate_messages(
                    user_history,
                    system_prompt_len=len(system_prompt),
                    max_context_tokens=max_context_tokens,
                    min_rounds=min_rounds,
                    max_rounds=max_rounds,
                )
                messages: list[dict] = [{"role": "system", "content": system_prompt}]
                messages.extend(selected)

                for turn in range(_MAX_TOOL_TURNS):
                    pending_tool_calls: list[dict] = []
                    finish_reason = "stop"
                    assistant_text_parts: list[str] = []

                    async for event in stream_chat(
                        messages, model, api_key, base_url, tools=tool_specs
                    ):
                        etype = event.get("type")
                        if etype == "text":
                            delta = event.get("delta") or ""
                            assistant_text_parts.append(delta)
                            yield _sse({"delta": delta})
                        elif etype == "tool_call":
                            pending_tool_calls.append(
                                {
                                    "id": event.get("id") or "",
                                    "name": event.get("name") or "",
                                    "arguments": event.get("arguments") or "",
                                }
                            )
                        elif etype == "finish":
                            finish_reason = event.get("reason") or "stop"

                    if not pending_tool_calls:
                        break

                    assistant_msg: dict = {
                        "role": "assistant",
                        "content": "".join(assistant_text_parts),
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            }
                            for tc in pending_tool_calls
                        ],
                    }
                    messages.append(assistant_msg)

                    for tc in pending_tool_calls:
                        try:
                            args = json.loads(tc["arguments"] or "{}")
                            if not isinstance(args, dict):
                                args = {}
                        except json.JSONDecodeError:
                            args = {}

                        yield _sse(
                            {
                                "tool_call_start": {
                                    "id": tc["id"],
                                    "name": tc["name"],
                                    "arguments": args,
                                }
                            }
                        )
                        result = tools_handler.dispatch(tc["name"], args)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result,
                            }
                        )
                        yield _sse(
                            {
                                "tool_call_end": {
                                    "id": tc["id"],
                                    "name": tc["name"],
                                    "output_summary": _summarize(result),
                                }
                            }
                        )

                    if finish_reason not in ("tool_calls", "function_call", None):
                        pass
                else:
                    yield _sse(
                        {
                            "error": f"工具调用超过 {_MAX_TOOL_TURNS} 轮，已中止。"
                        }
                    )
            except AIError as e:
                log.warning("ai matter chat error: %s", e)
                yield _sse({"error": str(e)})
            except Exception:
                log.exception("unexpected ai matter chat error")
                yield _sse({"error": "服务异常，请稍后重试"})
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router


def _summarize(tool_result: str) -> dict:
    """Lightweight preview of a tool result for the frontend's 已读 line."""
    head = tool_result.strip().splitlines()[:1]
    return {
        "size": len(tool_result),
        "head": head[0][:160] if head else "",
    }
