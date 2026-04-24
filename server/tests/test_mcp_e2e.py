"""End-to-end integration test for the full MCP flow.

This exercises the complete pipeline against two real uvicorn servers:

    test --[MCP Streamable HTTP]--> /mcp server  (auth + tool dispatch)
                                         |
                                         v
    test <---------/api/matters/--- api server   (Matter REST API)

Why two servers, not one? The MCP tool handlers call `httpx.get/post`
SYNCHRONOUSLY from inside an async `call_tool` coroutine. If that request
looped back to the same uvicorn worker serving /mcp, the event loop would
be blocked waiting on itself, and the nested call would deadlock. Splitting
/api and /mcp onto two separate uvicorn threads (and thus two separate
event loops) lets the inbound /mcp handler make outbound sync HTTP calls
to the api server and get a response.

This test picks Option C (run uvicorn in a thread, use the MCP SDK client)
because the tool layer uses module-level `httpx.get` / `httpx.post`. A
TestClient / ASGI transport approach would require patching httpx deep
inside `server.mcp.tools`, which is fragile.

What this test verifies:
- `initialize` + `tools/list` handshake succeeds with a valid PAT.
- `resolve_context` on a matter URL returns matter_id + user_facing_summary.
- `get_matter` returns a timeline WITHOUT `body` fields per item.
- `create_file` (type=think) succeeds and returns ok=True + plausible view_url.
- After create_file, the matter's timeline has one more item (timeline grew).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from server.api.matters import build_router as build_matters_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user
from server.auth.session import SessionStore
from server.contacts import ContactRepo
from server.db import Database
from server.events import clear_subscribers
from server.favorites import FavoriteRepo
from server.mcp.server import build_mcp_app
from server.notify import NoOpNotifier
from server.read_state import ReadStateRepo
from server.users import UserRepo


# ---- helpers shared with test_matters_api.py --------------------------------


class _WorkspaceStub:
    def __init__(self, root: Path) -> None:
        self.path = root
        self.discussions_dir = root / "discussions"
        self.index_dir = root / "index"

    @contextmanager
    def write_session(self, **_: object):
        self.discussions_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        yield


def _pick_free_port() -> int:
    """Bind to port 0 to let the OS pick a free port, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_api_only_app(db: Database, users: UserRepo,
                        api_tokens: ApiTokenRepo,
                        workspace: _WorkspaceStub) -> FastAPI:
    """FastAPI app with ONLY the matters router — this is the "Matter API"
    that MCP tool handlers call into via httpx.

    We run this on its own uvicorn (so sync httpx inside tool handlers does
    NOT block the same event loop that's serving /mcp)."""
    sessions = SessionStore(db)
    current_user = make_current_user(sessions, users, api_tokens)
    app = FastAPI()
    app.include_router(
        build_matters_router(
            workspace, users, ContactRepo(db), NoOpNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), current_user,
        )
    )
    return app


def _build_mcp_only_app(users: UserRepo, api_tokens: ApiTokenRepo,
                        api_base_url: str) -> FastAPI:
    """FastAPI app with ONLY the MCP mount, pointing at the separate API.

    Two-server topology avoids a deadlock: the MCP tool handlers call httpx
    synchronously, and the outgoing request would otherwise block the same
    asyncio loop that's trying to answer the inbound /mcp call."""
    mcp_app = build_mcp_app(api_tokens, users, api_base_url, api_base_url)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", mcp_app)
    return app


class _ServerInThread:
    """Run uvicorn in a daemon thread; wait for readiness, stop on exit."""

    def __init__(self, app: FastAPI, port: int, *, probe_path: str) -> None:
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.port = port
        self.probe_path = probe_path
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        # Poll until uvicorn answers — any HTTP status (even 4xx/5xx) proves
        # the server is live; ConnectError/timeout means not yet.
        deadline = time.monotonic() + 15.0
        url = f"http://127.0.0.1:{self.port}{self.probe_path}"
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with httpx.Client(trust_env=False, timeout=1.0) as c:
                    r = c.get(url)
                    if r.status_code < 600:
                        return
            except Exception as e:
                last_err = e
            time.sleep(0.1)
        raise RuntimeError(f"uvicorn did not come up on {url}: {last_err}")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5.0)


@pytest.fixture(autouse=True)
def _clear_events():
    clear_subscribers()
    yield
    clear_subscribers()


@pytest.fixture(autouse=True)
def _bypass_system_proxy(monkeypatch):
    """Force httpx to ignore system proxies for the duration of this test.

    On Windows, httpx honours the registry's proxy setting via urllib's
    `getproxies()` whenever `trust_env=True` (the default). That routes
    our loopback requests through a local proxy which doesn't know the
    ephemeral test port, yielding spurious 502s. We patch the module-level
    `httpx.get` / `httpx.post` used by `MatterApiClient` to always pass
    `trust_env=False`, and also clear the env vars for good measure.
    """
    # Belt-and-suspenders: clear env so even code that reads os.environ
    # directly (httpx's default AsyncClient) sees no proxy.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)

    orig_get = httpx.get
    orig_post = httpx.post

    def _get(url, **kw):
        kw["trust_env"] = False
        return orig_get(url, **kw)

    def _post(url, **kw):
        kw["trust_env"] = False
        return orig_post(url, **kw)

    # Patch where MatterApiClient does its lookups (module-level `httpx.get`).
    # server.mcp.tools imports the `httpx` module then calls `httpx.get(...)`,
    # so patching the attribute on its imported module is the surest route.
    import server.mcp.tools as tools_mod
    monkeypatch.setattr(tools_mod.httpx, "get", _get)
    monkeypatch.setattr(tools_mod.httpx, "post", _post)
    yield


@pytest.fixture
def live_server(tmp_path) -> Iterator[dict]:
    """Boot api-only + mcp-only uvicorn servers; mint a PAT and seed a matter.

    Yields a dict with:
        api_base_url (str): Matter REST API base, e.g. "http://127.0.0.1:12345"
        mcp_base_url (str): MCP Streamable HTTP base (same shape, different port)
        token (str): plaintext PAT authorised for both above
        matter_id (str): id of a freshly-seeded matter
        initial_file (str): file path of its first timeline item
    """
    db = Database(tmp_path / "test.db")
    users = UserRepo(db)
    api_tokens = ApiTokenRepo(db)

    # Seed one user and mint a PAT for them.
    users.upsert_from_feishu(
        open_id="ou_1", union_id=None, name="邓柯", avatar_url="",
    )
    users.update_profile("ou_1", pinyin="dengke")
    plaintext, _ = api_tokens.create(user_open_id="ou_1", name="Test PAT")

    workspace = _WorkspaceStub(tmp_path)

    # Run two servers in separate threads:
    #   api_server — serves /api/matters (Matter REST API)
    #   mcp_server — serves /mcp (MCP Streamable HTTP)
    # The MCP server's tool handlers do sync httpx.get against api_base_url,
    # which MUST resolve to the api_server — if it resolved to the mcp_server,
    # the blocking call would deadlock that server's own event loop.
    api_port = _pick_free_port()
    mcp_port = _pick_free_port()
    api_base_url = f"http://127.0.0.1:{api_port}"
    mcp_base_url = f"http://127.0.0.1:{mcp_port}"

    api_app = _build_api_only_app(db, users, api_tokens, workspace)
    mcp_app = _build_mcp_only_app(users, api_tokens, api_base_url=api_base_url)

    api_server = _ServerInThread(api_app, api_port, probe_path="/api/matters")
    mcp_server = _ServerInThread(mcp_app, mcp_port, probe_path="/mcp")
    api_server.start()
    mcp_server.start()
    try:
        # Seed a matter via the REAL Matter API using the PAT.
        with httpx.Client(
            base_url=api_base_url,
            headers={"Authorization": f"Bearer {plaintext}"},
            timeout=5.0,
            trust_env=False,
        ) as http:
            r = http.post("/api/matters", json={
                "category": "Pivot",
                # No spaces — the slug becomes the matter_id and flows through
                # a user-facing URL where spaces would need encoding.
                "title": "E2EAuth",
                "initial_file": {
                    "type": "think",
                    "summary": "初步思考",
                    "body": "# Summary\n\n初步思考\n",
                },
            })
            assert r.status_code == 200, r.text
            data = r.json()
            matter_id = data["matter_id"]
            initial_file = data["initial_timeline_item"]["file"]

        yield {
            "api_base_url": api_base_url,
            "mcp_base_url": mcp_base_url,
            "token": plaintext,
            "matter_id": matter_id,
            "initial_file": initial_file,
        }
    finally:
        mcp_server.stop()
        api_server.stop()


# ---- the actual E2E test ----------------------------------------------------


def _parse_tool_result(result) -> dict:
    """MCP tool results arrive as a list of TextContent; tool JSON is in the
    first block's .text. Raise if the tool returned an MCP protocol error."""
    if getattr(result, "isError", False):
        raise AssertionError(f"tool returned isError: {result}")
    content = result.content
    assert content, f"empty content: {result}"
    first = content[0]
    text = getattr(first, "text", None)
    assert text is not None, f"first content block has no .text: {first}"
    return json.loads(text)


async def _run_mcp_flow(base_url: str, token: str, matter_id: str) -> dict:
    """Drive the handshake + three tool calls; return observations for asserts."""
    # Build a client manually (not via create_mcp_http_client) so we can force
    # trust_env=False — the SDK's default honours system proxies, which on
    # Windows would route our loopback requests through a local proxy.
    client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(10.0, read=30.0),
        follow_redirects=True,
        trust_env=False,
    )
    url = f"{base_url}/mcp"
    async with client:
        async with streamable_http_client(url, http_client=client) as (r, w, _):
            async with ClientSession(r, w) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}

                # resolve_context
                resolve_res = await session.call_tool(
                    "resolve_context",
                    {"url": f"https://pivot.enclaws.ai/m/{matter_id}"},
                )
                resolved = _parse_tool_result(resolve_res)

                # get_matter (baseline timeline length)
                gm_before = await session.call_tool(
                    "get_matter", {"matter_id": matter_id},
                )
                before = _parse_tool_result(gm_before)

                # create_file (type=think, minimal)
                cf_res = await session.call_tool(
                    "create_file",
                    {
                        "matter_id": matter_id,
                        "type": "think",
                        "summary": "E2E thought",
                        "body": "thought body",
                    },
                )
                created = _parse_tool_result(cf_res)

                # get_matter again to confirm timeline grew
                gm_after = await session.call_tool(
                    "get_matter", {"matter_id": matter_id},
                )
                after = _parse_tool_result(gm_after)

                return {
                    "server_name": init.serverInfo.name,
                    "tool_names": tool_names,
                    "resolved": resolved,
                    "before_timeline": before["timeline"],
                    "created": created,
                    "after_timeline": after["timeline"],
                }


def test_mcp_e2e_full_flow(live_server):
    """End-to-end: resolve_context -> get_matter -> create_file -> get_matter.

    Proves the MCP protocol, PAT auth, tool dispatch, Matter API client, and
    git-backed file creation all work together.
    """
    info = live_server
    result = asyncio.run(_run_mcp_flow(
        info["mcp_base_url"], info["token"], info["matter_id"],
    ))

    # Handshake + tool discovery
    assert result["server_name"] == "pivot-mcp"
    assert {"resolve_context", "list_matters", "get_matter", "read_files",
            "create_file"} <= result["tool_names"]

    # resolve_context
    resolved = result["resolved"]
    assert resolved["matter_id"] == info["matter_id"]
    assert resolved["file_path"] is None
    assert "E2EAuth" in resolved["user_facing_summary"]
    assert "planning" in resolved["user_facing_summary"]

    # get_matter -- body field stripped from each timeline item
    before = result["before_timeline"]
    assert len(before) == 1
    assert all("body" not in item for item in before), before
    assert before[0]["file"] == info["initial_file"]

    # create_file success
    created = result["created"]
    assert created.get("ok") is True, created
    assert created["file_path"].endswith(".md")
    # view_url uses the api_base_url (which we passed as web_base_url too).
    assert created["view_url"].startswith(info["api_base_url"] + "/m/")
    assert info["matter_id"] in created["view_url"]

    # Timeline grew by exactly one after create_file
    after = result["after_timeline"]
    assert len(after) == len(before) + 1, (before, after)
    new_file_paths = {it["file"] for it in after} - {it["file"] for it in before}
    assert created["file_path"] in new_file_paths
