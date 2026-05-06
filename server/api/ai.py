from __future__ import annotations

import json
import logging

from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.ai.client import AIError, DEFAULT_BASE_URL, DEFAULT_MODEL, stream_chat
from server.ai.context import (
    ContextTooLongError,
    build_starting_post_block,
    truncate_messages,
)
from server.ai.prompts import build_new_matter_system_prompt, build_system_prompt
from server.ai.runner import spec_for
from server.ai.tools import AITools
from server.ai_conversations import AIConversationRepo
from server.db import Database
from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUser
from server.settings import SettingsRepo
from server.visibility_scopes import VisibilityScope
from server.visibility_store import read_category_visibility
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
    mode: Literal["reply", "new-matter"] = "reply"


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
    admin_user_cookie_only: Callable,
    db: Database | None = None,
) -> APIRouter:
    router = APIRouter()

    # ── Settings ──────────────────────────────────────────────────────────────
    # Admin-gated AND cookie-only — PATs cannot read/write the AI API key.

    @router.get("/api/ai/settings")
    def get_ai_settings(_: PivotUser = Depends(admin_user_cookie_only)):
        return {
            "base_url": settings.get(_KEY_BASE_URL) or DEFAULT_BASE_URL,
            "model": settings.get(_KEY_MODEL) or DEFAULT_MODEL,
            "has_key": bool(settings.get(_KEY_API_KEY)),
            "max_context_tokens": _get_int(settings, _KEY_MAX_CONTEXT_TOKENS, _DEFAULT_MAX_CONTEXT_TOKENS),
            "min_rounds": _get_int(settings, _KEY_MIN_ROUNDS, _DEFAULT_MIN_ROUNDS),
            "max_rounds": _get_int(settings, _KEY_MAX_ROUNDS, _DEFAULT_MAX_ROUNDS),
        }

    @router.put("/api/ai/settings")
    def update_ai_settings(
        body: AISettingsUpdate,
        _: PivotUser = Depends(admin_user_cookie_only),
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

    def _matter_thread_key(matter_id: str, user: PivotUser) -> str:
        data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
        if data is None or not _can_read_matter(data, user, db, workspace):
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
        user: PivotUser = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id, user)
        messages, reply_target = conversations.get(user.open_id, key)
        return {
            "messages": messages,
            "reply_target": reply_target,
        }

    @router.put("/api/ai/matters/{matter_id}/conversation")
    def save_matter_conversation(
        matter_id: str,
        body: ConversationSave,
        user: PivotUser = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id, user)
        conversations.save(
            user.open_id, key,
            [m.model_dump() for m in body.messages],
            body.reply_target,
        )
        return {"ok": True}

    @router.delete("/api/ai/matters/{matter_id}/conversation")
    def clear_matter_conversation(
        matter_id: str,
        user: PivotUser = Depends(current_user),
    ):
        key = _matter_thread_key(matter_id, user)
        conversations.delete(user.open_id, key)
        return {"ok": True}

    @router.post("/api/ai/matters/{matter_id}/chat")
    async def chat_matter(
        matter_id: str,
        body: ChatRequest,
        user: PivotUser = Depends(current_user),
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

        if body.mode == "new-matter":
            # NewMatter mode: no matter context yet; AI helps draft the first
            # document. reply_target is irrelevant and ignored if present.
            system_prompt = build_new_matter_system_prompt()
        else:
            data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
            if data is None or not _can_read_matter(data, user, db, workspace):
                raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
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

        tools_handler = AITools(
            workspace.discussions_dir,
            workspace.index_dir,
            visible_matter_ids=_visible_matter_ids(workspace, user, db),
        )
        tool_specs = tools_handler.specs()

        # 方案 B：所有 chat 调用走统一 spec — 心跳/超时/错误归一从这里集中。
        # NewMatter 模式下走 "summary" 桶（更短的 soft/hard 超时，匹配生成草稿
        # 的实际语义），其他对话走 "chat" 桶。
        ai_spec = spec_for("summary" if body.mode == "new-matter" else "chat")

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
                        messages, model, api_key, base_url,
                        tools=tool_specs, spec=ai_spec,
                    ):
                        etype = event.get("type")
                        if etype == "text":
                            delta = event.get("delta") or ""
                            assistant_text_parts.append(delta)
                            yield _sse({"delta": delta})
                        elif etype == "heartbeat":
                            # Forward upstream-silent signals to the frontend so
                            # AIPane can show "AI 响应较慢…". Field name kept
                            # explicit so the wire format is self-describing.
                            yield _sse({
                                "heartbeat": {
                                    "since_last_token_ms": int(
                                        event.get("since_last_token_ms") or 0
                                    ),
                                }
                            })
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
                log.warning(
                    "ai matter chat error code=%s retryable=%s: %s",
                    e.code, e.retryable, e,
                )
                # 方案 B：error 事件升级为结构化 payload {code, retryable, message,
                # status}，同时保留旧 `error: <string>` 字段供旧前端兜底。
                yield _sse({
                    "error": e.user_message_zh,
                    "error_detail": e.to_event_payload(),
                })
            except Exception:
                log.exception("unexpected ai matter chat error")
                yield _sse({
                    "error": "服务异常，请稍后重试",
                    "error_detail": {
                        "code": "unknown",
                        "retryable": True,
                        "message": "服务异常，请稍后重试",
                        "status": None,
                    },
                })
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router


def _visible_matter_ids(
    workspace: Workspace,
    user: PivotUser,
    db: Database | None,
) -> set[str]:
    out: set[str] = set()
    if not workspace.index_dir.is_dir():
        return out
    for path in workspace.index_dir.glob("*.index.yaml"):
        data = read_matter_index(path)
        if data is None:
            continue
        matter_id = str((data.get("matter") or {}).get("id") or path.name.removesuffix(".index.yaml"))
        if _can_read_matter(data, user, db, workspace):
            out.add(matter_id)
    return out


def _can_read_matter(
    data: dict,
    user: PivotUser,
    db: Database | None,
    workspace: Workspace,
) -> bool:
    roles = _roles_for_user(user, db)
    category = _matter_category(data)
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
    return bool(set(_identifiers_for_user(user)) & set(visibility.user_ids))


def _matter_category(data: dict) -> str | None:
    timeline = data.get("timeline") or []
    if not timeline:
        return None
    parts = str(timeline[0].get("file") or "").split("/")
    if len(parts) >= 4 and parts[0] == "discussions":
        return parts[1]
    return None


def _identifiers_for_user(user: PivotUser) -> list[str]:
    values = [
        getattr(user, "id", None),
        getattr(user, "open_id", None),
        getattr(user, "pinyin", None),
        getattr(user, "email", None),
    ]
    return [str(v) for v in values if v]


def _roles_for_user(user: PivotUser, db: Database | None) -> list[str]:
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


def _decode_role_list(raw: str) -> list[str]:
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


def _summarize(tool_result: str) -> dict:
    """Lightweight preview of a tool result for the frontend's 已读 line."""
    head = tool_result.strip().splitlines()[:1]
    return {
        "size": len(tool_result),
        "head": head[0][:160] if head else "",
    }
