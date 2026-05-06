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
from server.mcp.instructions import INSTRUCTIONS
from server.mcp.runtime import current_user_token, set_user_token
from server.mcp.schemas import (
    AddCommentIn,
    CreateFileIn,
    CreateMatterIn,
    GetMatterIn,
    ListMattersIn,
    ListVisibilityOptionsIn,
    ReadFilesIn,
    ResolveContextIn,
)
from server.mcp.tools import (
    MatterApiClient,
    ToolError,
    tool_add_comment,
    tool_create_file,
    tool_create_matter,
    tool_get_matter,
    tool_list_matters,
    tool_list_visibility_options,
    tool_read_files,
    tool_resolve_context,
)
from server.pivot_users import PivotUserRepo

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
                    "optionally with `/f/<file-path>`). "
                    "Common user phrasings (usually triggered by a pasted URL): "
                    "\"看一下这个帖子 <url>\", \"对这个 matter 评论 <url>\", "
                    "\"summarize <url>\", \"打开这个链接\". "
                    "Pivot is a SPA, so WebFetch only returns an empty HTML "
                    "shell; this tool resolves the URL into matter + file info "
                    "via the authenticated backend. ALWAYS display the returned "
                    "`user_facing_summary` to the user verbatim so they can "
                    "confirm the correct context was loaded."
                ),
                inputSchema=ResolveContextIn.model_json_schema(),
            ),
            Tool(
                name="list_matters",
                description=(
                    "List matters visible to the current user. Supports "
                    "status/owner/q filters. "
                    "Common user phrasings: \"看一下所有 matter\", \"列一下 "
                    "matter 列表\", \"看看 pivot 下面有哪些帖子\", \"最近有什么 "
                    "matter\", \"谁在做什么\", \"有哪些进行中的 matter\", "
                    "\"show me all matters\". "
                    "Use this for OVERVIEW questions where the user does NOT "
                    "name a specific matter; if they DO name one (or paste a "
                    "URL), use `get_matter` / `resolve_context` instead. "
                    "Filters: `status` accepts planning/executing/paused/"
                    "finished/reviewed/cancelled; `owner` accepts pinyin "
                    "(e.g. 'dengke'); `q` does fuzzy title search."
                ),
                inputSchema=ListMattersIn.model_json_schema(),
            ),
            Tool(
                name="get_matter",
                description=(
                    "Return a matter's header + timeline metadata (no file "
                    "bodies). "
                    "Common user phrasings: \"看下 X matter\", \"X 帖子里都有"
                    "什么\", \"X matter 的 timeline\", \"X 的进度\", "
                    "\"summarize matter X\". "
                    "Use this when the user names a SPECIFIC matter (by id or "
                    "title); for overview lists use `list_matters`; if the "
                    "user pasted a Pivot URL, call `resolve_context` first to "
                    "extract the matter_id. "
                    "Call `read_files` afterwards to fetch specific file "
                    "bodies on demand."
                ),
                inputSchema=GetMatterIn.model_json_schema(),
            ),
            Tool(
                name="read_files",
                description=(
                    "Fetch the full text of one or more files within a matter. "
                    "Common user phrasings: \"看一下这条 think 的具体内容\", "
                    "\"展开这篇 act\", \"X 文件里写了啥\", \"summarize this "
                    "file\", \"读一下这条\". "
                    "Always call get_matter first to see which files exist, "
                    "then pick paths from its timeline. "
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
                    "not silently retry with guessed pinyin. "
                    "PROTOCOL (visibility): The `visibility` and "
                    "`new_category_visibility` fields are OPTIONAL. Default to "
                    "leaving them null — the matter goes public, matching the "
                    "current behavior. Set them ONLY when the user EXPLICITLY "
                    "asks to restrict access ('只给 dev 看', 'limit to ops', "
                    "'不要让 X 看到'). When the user does ask for restriction, "
                    "first call `list_visibility_options` with the same "
                    "`category` to fetch valid role / user candidates, then "
                    "echo the resolved scope (with display names) back to the "
                    "user for confirmation, then call `create_matter`. If the "
                    "category does not yet exist AND the matter is restricted, "
                    "you MUST also include `new_category_visibility`; the "
                    "backend rejects with 422 `missing_category_visibility` "
                    "otherwise. Never infer restriction from the body text."
                ),
                inputSchema=CreateMatterIn.model_json_schema(),
            ),
            Tool(
                name="add_comment",
                description=(
                    "Append a comment (with optional @-mention) to an EXISTING file "
                    "inside a matter. This is the equivalent of the Web's '@ 提及' "
                    "button — it adds a comment under a file, not a new timeline item. "
                    "Common user phrasings: \"@ X\", \"圈下 X 看一下这条\", "
                    "\"对 <file> 留言\", \"通知 X review 这条 think\". "
                    "Use `create_file` instead when the user wants to add a new "
                    "timeline item (think/act/verify/result/insight); use `create_matter` "
                    "when they want a brand-new matter. "
                    "PROTOCOL (1/3): BEFORE calling, present the draft (target_file, "
                    "body, mentions) to the user in chat and wait for explicit approval. "
                    "If you don't know the target_file path yet, call get_matter first "
                    "and ask the user which file. "
                    "PROTOCOL (2/3): If the backend rejects with 422 (`{errors: ...}`), "
                    "surface the field-level errors to the user — do NOT silently retry "
                    "with guessed pinyin. "
                    "PROTOCOL (3/3): After success, relay the returned `summary_for_ai` "
                    "message verbatim to the user, including the view_url."
                ),
                inputSchema=AddCommentIn.model_json_schema(),
            ),
            Tool(
                name="list_visibility_options",
                description=(
                    "List the role + user candidates eligible for a matter's "
                    "visibility scope, optionally filtered by category. "
                    "Common user phrasings (any language): \"哪些角色能选\", "
                    "\"列一下能限制可见的人和组\", \"who can I share this with\". "
                    "PRIMARY USE: call this BEFORE `create_matter` whenever the "
                    "user expresses a restricted-visibility intent (\"只给 dev "
                    "看\", \"limit to ops\", \"不要让 X 看到\") — the response "
                    "tells you what `roles` / `user_ids` are valid for that "
                    "category, so you can echo the resolved scope back to the "
                    "user for confirmation, then submit `create_matter` with "
                    "the right visibility object. "
                    "When no category is given, returns the global candidates "
                    "the calling user can see."
                ),
                inputSchema=ListVisibilityOptionsIn.model_json_schema(),
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
            elif name == "add_comment":
                out = await anyio.to_thread.run_sync(
                    partial(tool_add_comment, arguments, client, web_base_url)
                )
            elif name == "list_visibility_options":
                out = await anyio.to_thread.run_sync(
                    partial(tool_list_visibility_options, arguments, client)
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
    users: PivotUserRepo,
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
    mcp_server = Server(
        _SERVER_NAME,
        version=_SERVER_VERSION,
        instructions=INSTRUCTIONS,
    )
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
