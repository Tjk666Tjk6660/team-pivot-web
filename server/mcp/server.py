from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

log = logging.getLogger(__name__)

_SERVER_NAME = "pivot-mcp"
_SERVER_VERSION = "0.1.0"


def build_mcp_app() -> Starlette:
    """Return an ASGI app that serves MCP over Streamable HTTP at `/`.

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
        await session_manager.handle_request(scope, receive, send)

    return Starlette(
        routes=[Mount("/", app=handle_streamable)],
        lifespan=lifespan,
    )
