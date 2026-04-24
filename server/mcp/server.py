from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from server.api_tokens import ApiTokenRepo
from server.mcp.auth import McpAuthError, authenticate
from server.mcp.runtime import set_user_token
from server.users import UserRepo

log = logging.getLogger(__name__)

_SERVER_NAME = "pivot-mcp"
_SERVER_VERSION = "0.1.0"


def build_mcp_app(tokens: ApiTokenRepo, users: UserRepo) -> Starlette:
    """Return an ASGI app that serves MCP over Streamable HTTP at `/`.

    Every HTTP request must carry `Authorization: Bearer pvt_...`; we verify
    the PAT against `tokens`, resolve the user via `users`, stash the
    plaintext token in a ContextVar (so tool callbacks can forward it to
    Matter API calls), and only then hand off to the session manager.

    The returned app has a lifespan that drives `session_manager.run()`.
    The parent FastAPI app must propagate this sub-app's lifespan — see
    server/app.py.

    (When mounted at `/mcp`, external clients reach it as POST/GET `/mcp`.)
    """
    mcp_server = Server(_SERVER_NAME, version=_SERVER_VERSION)
    # tools are registered elsewhere; see server/mcp/tools.py

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
