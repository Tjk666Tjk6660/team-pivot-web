from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

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
from server.mcp.schemas import GetMatterIn, ListMattersIn, ReadFilesIn, ResolveContextIn
from server.mcp.tools import (
    MatterApiClient,
    ToolError,
    tool_get_matter,
    tool_list_matters,
    tool_read_files,
    tool_resolve_context,
)
from server.users import UserRepo

log = logging.getLogger(__name__)

_SERVER_NAME = "pivot-mcp"
_SERVER_VERSION = "0.1.0"


def _register_tools(mcp_server: Server, api_base_url: str) -> None:
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
                    "Resolve a Pivot URL (e.g. copied from the Web) into "
                    "matter + file info. ALWAYS display the returned "
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
        ]

    @mcp_server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        token = current_user_token()
        client = MatterApiClient(api_base_url, token)
        try:
            if name == "resolve_context":
                out = tool_resolve_context(arguments, client)
            elif name == "list_matters":
                out = tool_list_matters(arguments, client)
            elif name == "get_matter":
                out = tool_get_matter(arguments, client)
            elif name == "read_files":
                out = tool_read_files(arguments, client)
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
    _register_tools(mcp_server, api_base_url)

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
