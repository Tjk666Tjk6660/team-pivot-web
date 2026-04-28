from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from functools import partial

import anyio
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from server.api_tokens import ApiTokenRepo
from server.mcp.auth import McpAuthError, authenticate
from server.mcp.runtime import current_user_token, set_user_token
from server.mcp.schemas import (
    CreateFileIn,
    CreateMatterIn,
    GetMatterIn,
    ListMattersIn,
    ReadFilesIn,
    ResolveContextIn,
)
from server.mcp.tools import (
    MatterApiClient,
    ToolError,
    tool_create_file,
    tool_create_matter,
    tool_get_matter,
    tool_list_matters,
    tool_read_files,
    tool_resolve_context,
)
from server.users import UserRepo

log = logging.getLogger(__name__)

_SERVER_NAME = "pivot-mcp"
_SERVER_VERSION = "0.1.0"


def _register_tools(mcp_server: Server, api_base_url: str, web_base_url: str) -> None:
    """Wire MCP list_tools / call_tool handlers onto the low-level server.

    The call_tool dispatch uses `current_user_token()` to build a
    per-request `MatterApiClient`, so each tool call acts on behalf of
    the calling user (their PAT was validated by the auth middleware and
    stashed in a ContextVar just before this coroutine runs).
    """

    @mcp_server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="resolve_context",
                description=(
                    "Use this tool — NOT WebFetch — for any URL on a Pivot "
                    "host (e.g. `https://pivot.enclaws.*/m/<matter-id>`, "
                    "optionally with `/f/<file-path>`). Pivot is a SPA, so "
                    "WebFetch only returns an empty HTML shell; this tool "
                    "resolves the URL into matter + file info via the "
                    "authenticated backend. ALWAYS display the returned "
                    "`user_facing_summary` to the user verbatim so they "
                    "can confirm the correct context was loaded."
                ),
                inputSchema=ResolveContextIn.model_json_schema(),
            ),
            Tool(
                name="list_matters",
                description="List matters visible to the current user. Supports status/owner/q filters.",
                inputSchema=ListMattersIn.model_json_schema(),
            ),
            Tool(
                name="get_matter",
                description=(
                    "Return a matter's header + timeline metadata (no file bodies). "
                    "Call read_files afterwards to fetch specific file bodies on demand."
                ),
                inputSchema=GetMatterIn.model_json_schema(),
            ),
            Tool(
                name="read_files",
                description=(
                    "Fetch the full text of one or more files within a matter. "
                    "Always call get_matter first to see which files exist. "
                    "Hard limits: at most 5 files and 50,000 total chars per call."
                ),
                inputSchema=ReadFilesIn.model_json_schema(),
            ),
            Tool(
                name="create_file",
                description=(
                    "Create a new timeline item (think/act/verify/result/insight) in "
                    "a matter. "
                    "Common user phrasings: \"在 X matter 里加一条 think/act\", "
                    "\"给 matter 加个想法/方案/验证/结果\", \"在 matter 下补一条 timeline\". "
                    "Requires an EXISTING matter in context — if no matter is loaded or "
                    "named, ask which one (or use `create_matter` to start a new one). "
                    "PROTOCOL (1/3): BEFORE calling this tool, you MUST present the draft "
                    "content to the user in natural language in the chat and wait for "
                    "explicit approval ('ok', 'go', etc). The tool approval dialog is "
                    "the final confirmation. "
                    "PROTOCOL (2/3): If matter_snapshot.available_transitions (returned by "
                    "resolve_context / get_matter) is non-empty, you MUST also ask the user "
                    "whether to attach a status transition this time — show each option's "
                    "label + target status, and let the user pick one or skip. Set the "
                    "`status_change` field ONLY after the user explicitly opts in; otherwise "
                    "leave it null. Never silently attach, never silently skip. "
                    "PROTOCOL (3/3): After success, relay the returned `summary_for_ai` "
                    "message verbatim to the user. "
                    "PROTOCOL (mentions): The `mentions` field is OPTIONAL. Only set it "
                    "when the user explicitly says to notify/圈/@ someone. Names that "
                    "merely appear in the body are NOT a signal to auto-mention. "
                    "When the user does ask for it, present the resolved targets + the "
                    "`say` line in chat first, get confirmation, then call. If the "
                    "backend can't resolve a name (422), surface it to the user — do "
                    "not silently retry with guessed pinyin."
                ),
                inputSchema=CreateFileIn.model_json_schema(),
            ),
            Tool(
                name="create_matter",
                description=(
                    "Create a new Matter (with its first timeline file) in the given "
                    "category. The new Matter starts in `planning` status; to advance "
                    "status, use `create_file` with `status_change` afterwards. "
                    "Common user phrasings (any language): \"新建/创建/发起一个 matter\", "
                    "\"开一个帖子讨论 X\", \"起一个 matter 跟踪 X\", "
                    "\"create/start/open a matter for X\". "
                    "If the user wants to \"create something\" but no existing matter is "
                    "in context, this tool — not `create_file` — is usually the right choice. "
                    "PROTOCOL (1/3): BEFORE calling this tool, you MUST present the draft "
                    "to the user in natural language in chat — title, category, summary, "
                    "and body — and wait for explicit approval ('ok', 'go', '发吧', etc). "
                    "The tool approval dialog is the FINAL confirmation, not the first. "
                    "PROTOCOL (2/3): If the backend rejects with 422 (`{errors: ...}` in "
                    "the response), surface the field-level errors to the user and ask "
                    "them to revise — do NOT silently retry with guessed fixes. "
                    "PROTOCOL (3/3): After success, relay the returned `summary_for_ai` "
                    "message verbatim to the user, including the view_url. "
                    "PROTOCOL (mentions): The `mentions` field is OPTIONAL. Only set it "
                    "when the user explicitly says to notify/圈/@ someone. Names that "
                    "merely appear in the body are NOT a signal to auto-mention. "
                    "When the user does ask for it, present the resolved targets + the "
                    "`say` line in chat first, get confirmation, then call. If the "
                    "backend can't resolve a name (422), surface it to the user — do "
                    "not silently retry with guessed pinyin."
                ),
                inputSchema=CreateMatterIn.model_json_schema(),
            ),
        ]

    @mcp_server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        # MatterApiClient uses SYNC httpx.get/post. If we ran it directly from
        # this coroutine, the blocking call would freeze the event loop — and
        # when api_base_url loops back to the SAME uvicorn worker serving /mcp
        # (e.g. single-worker dev), the inbound /mcp request waits on an
        # outbound request that cannot be scheduled → deadlock.
        # Off-load the sync tool body to a worker thread so the event loop
        # stays responsive and the nested HTTP call can actually be served.
        token = current_user_token()
        client = MatterApiClient(api_base_url, token)
        try:
            if name == "resolve_context":
                out = await anyio.to_thread.run_sync(
                    partial(tool_resolve_context, arguments, client)
                )
            elif name == "list_matters":
                out = await anyio.to_thread.run_sync(
                    partial(tool_list_matters, arguments, client)
                )
            elif name == "get_matter":
                out = await anyio.to_thread.run_sync(
                    partial(tool_get_matter, arguments, client)
                )
            elif name == "read_files":
                out = await anyio.to_thread.run_sync(
                    partial(tool_read_files, arguments, client)
                )
            elif name == "create_file":
                out = await anyio.to_thread.run_sync(
                    partial(tool_create_file, arguments, client, web_base_url)
                )
            elif name == "create_matter":
                out = await anyio.to_thread.run_sync(
                    partial(tool_create_matter, arguments, client, web_base_url)
                )
            else:
                raise ToolError(404, f"unknown_tool: {name}")
        except ToolError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": {"status": e.status, "detail": e.detail}},
                        ensure_ascii=False,
                    ),
                )
            ]
        return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False))]


def build_mcp_app(
    tokens: ApiTokenRepo,
    users: UserRepo,
    api_base_url: str,
    web_base_url: str,
) -> Starlette:
    """Return an ASGI app that serves MCP over Streamable HTTP at `/`.

    Every HTTP request must carry `Authorization: Bearer pvt_...`; we verify
    the PAT against `tokens`, resolve the user via `users`, stash the
    plaintext token in a ContextVar (so tool callbacks can forward it to
    Matter API calls), and only then hand off to the session manager.

    `api_base_url` is the origin of the Matter REST API the tool handlers
    call (e.g. "http://127.0.0.1:8000" in dev). The same PAT authenticates
    there, so MCP tools act as the user.

    The returned app has a lifespan that drives `session_manager.run()`.
    The parent FastAPI app must propagate this sub-app's lifespan — see
    server/app.py.

    (When mounted at `/mcp`, external clients reach it as POST/GET `/mcp`.)
    """
    mcp_server = Server(_SERVER_NAME, version=_SERVER_VERSION)
    _register_tools(mcp_server, api_base_url, web_base_url)

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    @asynccontextmanager
    async def lifespan(starlette_app):
        async with session_manager.run():
            log.info("MCP session manager started")
            yield
            log.info("MCP session manager stopped")

    async def handle_streamable(scope, receive, send):
        # Non-HTTP scopes (e.g. lifespan) just pass through.
        if scope.get("type") != "http":
            await session_manager.handle_request(scope, receive, send)
            return

        request = Request(scope, receive)
        try:
            _user, token = authenticate(request, tokens, users)
        except McpAuthError as e:
            log.info("mcp auth rejected detail=%s", e.detail)
            response = JSONResponse({"detail": e.detail}, status_code=e.status)
            await response(scope, receive, send)
            return

        # Stash token so tool callbacks can forward it to Matter API calls.
        set_user_token(token)
        await session_manager.handle_request(scope, receive, send)

    return Starlette(
        routes=[Mount("/", app=handle_streamable)],
        lifespan=lifespan,
    )
