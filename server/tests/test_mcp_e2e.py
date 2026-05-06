"""End-to-end integration test for the full MCP flow.

This exercises the complete pipeline against a single real uvicorn server
hosting both /api/matters (Matter REST API) and /mcp (MCP Streamable HTTP):

    test --[MCP Streamable HTTP]--> /mcp  (auth + tool dispatch)
                                     |
                                     v  sync httpx loopback
    test <---------/api/matters/--- /api   (Matter REST API)

Why one server now? The MCP tool handlers call `httpx.get/post`
SYNCHRONOUSLY, but `server._call_tool` off-loads them to a worker thread
via `anyio.to_thread.run_sync`. The event loop stays free to service the
nested loopback request, so a single uvicorn worker is enough. (Before
that fix, a loopback call on the same worker would deadlock — which is why
this test previously spun up two uvicorn threads.)

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
from server.db import Database
from server.events import clear_subscribers
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo
from server.mcp.server import build_mcp_app
from server.notify import NoOpNotifier
from server.read_state import ReadStateRepo
from server.external_bindings import ExternalBindingRepo
from server.mentions import DisplayResolver
from server.pivot_users import PivotUserRepo
from server.relevance_events import RelevanceEventsRepo
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


def _build_combined_app(db: Database, pivot_users: PivotUserRepo,
                        api_tokens: ApiTokenRepo,
                        workspace: _WorkspaceStub,
                        base_url: str) -> FastAPI:
    """FastAPI app that serves BOTH /api/matters and /mcp on the same uvicorn.

    With the thread-pool off-load in `server._call_tool`, sync httpx calls
    inside tool handlers no longer block the event loop, so it's safe to
    loop back to the same worker that answered the inbound /mcp request.
    """
    sessions = SessionStore(db)
    current_user = make_current_user(sessions, pivot_users, api_tokens)
    mcp_app = build_mcp_app(api_tokens, pivot_users, base_url, base_url)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    bindings = ExternalBindingRepo(db)
    app = FastAPI(lifespan=lifespan)
    app.include_router(
        build_matters_router(
            workspace, pivot_users, bindings, NoOpNotifier(),
            ReadStateRepo(db), FavoriteRepo(db), FileReadRepo(db),
            RelevanceEventsRepo(db), DisplayResolver(pivot_users, bindings), current_user,
        )
    )
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
    """Boot a single uvicorn server that hosts both /api and /mcp; mint a
    PAT and seed a matter.

    Yields a dict with:
        api_base_url (str): Matter REST API base, e.g. "http://127.0.0.1:12345"
        mcp_base_url (str): MCP Streamable HTTP base (same origin as api)
        token (str): plaintext PAT authorised for both
        matter_id (str): id of a freshly-seeded matter
        initial_file (str): file path of its first timeline item
    """
    db = Database(tmp_path / "test.db")
    users = UserRepo(db)
    api_tokens = ApiTokenRepo(db)

    # Seed one user and mint a PAT for them. Mirrors the auth flow.
    users.upsert_from_feishu(
        open_id="ou_1", union_id=None, name="邓柯", avatar_url="",
    )
    users.update_profile("ou_1", pinyin="dengke")
    # Seed pivot_user + feishu binding so @-mention resolution by
    # name/pinyin works (replaces the old contacts table seeding).
    pivot_users_seed = PivotUserRepo(db)
    bindings_seed = ExternalBindingRepo(db)
    pu = pivot_users_seed.create(
        display_name="邓柯", pinyin="dengke", email=None, avatar_url="",
    )
    bindings_seed.bind(
        pivot_user_id=pu.id, provider="feishu",
        external_id="ou_1", external_union_id=None, raw_profile_json=None,
    )
    plaintext, _ = api_tokens.create(pivot_user_id=pu.id, name="Test PAT")

    workspace = _WorkspaceStub(tmp_path)

    # One uvicorn worker serves both /api and /mcp. This is the production
    # single-worker dev topology, which used to deadlock when MCP tool
    # handlers made sync httpx calls back to /api on the same event loop.
    # Now that `_call_tool` off-loads to a thread via anyio.to_thread.run_sync,
    # one server is sufficient — and this test proves it.
    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    app = _build_combined_app(db, pivot_users_seed, api_tokens, workspace, base_url)
    server = _ServerInThread(app, port, probe_path="/api/matters")
    server.start()
    try:
        # Seed a matter via the REAL Matter API using the PAT.
        with httpx.Client(
            base_url=base_url,
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
            "api_base_url": base_url,
            "mcp_base_url": base_url,
            "token": plaintext,
            "matter_id": matter_id,
            "initial_file": initial_file,
        }
    finally:
        server.stop()


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
                    "instructions": init.instructions,
                    "tool_names": tool_names,
                    "resolved": resolved,
                    "before_timeline": before["timeline"],
                    "created": created,
                    "after_timeline": after["timeline"],
                }


async def _run_mcp_create_matter(base_url: str, token: str) -> dict:
    """Create a brand-new Matter through MCP, then verify it via list/get."""
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
                await session.initialize()

                cm_res = await session.call_tool(
                    "create_matter",
                    {
                        "category": "Pivot",
                        "title": "E2ECreatedByMcp",
                        "type": "think",
                        "summary": "通过 MCP 创建的新 Matter",
                        "body": "# E2E\n\n正文",
                    },
                )
                created = _parse_tool_result(cm_res)

                # Verify via get_matter on the returned matter_id.
                gm_res = await session.call_tool(
                    "get_matter", {"matter_id": created["matter_id"]},
                )
                got = _parse_tool_result(gm_res)

                return {"created": created, "got": got}


def test_mcp_e2e_create_matter(live_server):
    """End-to-end create_matter: through MCP → backend writes to disk → readable.

    Proves the new tool routes to the backend, parses flat → nested input,
    composes a sensible view_url, and the resulting Matter is queryable.
    """
    info = live_server
    result = asyncio.run(_run_mcp_create_matter(
        info["mcp_base_url"], info["token"],
    ))

    created = result["created"]
    assert created.get("ok") is True, created
    assert created["category"] == "Pivot"
    assert created["title"] == "E2ECreatedByMcp"
    assert created["matter_id"]
    assert created["view_url"] == f"{info['api_base_url']}/m/{created['matter_id']}"
    assert created["first_file"].endswith(".md")
    assert "E2ECreatedByMcp" in created["summary_for_ai"]
    assert created["view_url"] in created["summary_for_ai"]

    # Newly created matter is in `planning` and has exactly one file.
    got = result["got"]
    assert got["matter"]["current_status"] == "planning"
    assert got["matter"]["title"] == "E2ECreatedByMcp"
    assert len(got["timeline"]) == 1
    assert got["timeline"][0]["type"] == "think"
    assert got["timeline"][0]["summary"] == "通过 MCP 创建的新 Matter"


async def _run_mcp_create_matter_with_mention(
    base_url: str, token: str,
) -> dict:
    """Create a Matter via MCP with a mentions block; return raw tool result."""
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
                await session.initialize()
                cm_res = await session.call_tool(
                    "create_matter",
                    {
                        "category": "Pivot",
                        "title": "E2EMentionMcp",
                        "type": "think",
                        "summary": "带 @ 的 matter",
                        "body": "正文",
                        "mentions": {
                            "targets": ["dengke"],
                            "say": "请帮我 review",
                        },
                    },
                )
                return _parse_tool_result(cm_res)


async def _run_mcp_add_comment(
    base_url: str, token: str, matter_id: str, target_file: str,
) -> dict:
    """Append a @-mention comment to an existing file via MCP."""
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
                await session.initialize()
                ac_res = await session.call_tool(
                    "add_comment",
                    {
                        "matter_id": matter_id,
                        "target_file": target_file,
                        "body": "请帮我 review 这条",
                        "mentions": ["dengke"],
                    },
                )
                return _parse_tool_result(ac_res)


def test_mcp_e2e_add_comment_with_mention(live_server):
    """add_comment with mentions persists onto an existing file's comments[].

    Reuses the seeded matter from the fixture so we exercise the
    "@ 提及 on an already-existing file" path that the Web's @ 提及 button
    targets.
    """
    info = live_server
    result = asyncio.run(_run_mcp_add_comment(
        info["mcp_base_url"], info["token"],
        info["matter_id"], info["initial_file"],
    ))
    assert result.get("ok") is True, result
    assert result["matter_id"] == info["matter_id"]
    assert result["target_file"] == info["initial_file"]
    assert "@ 提及" in result["summary_for_ai"]

    with httpx.Client(
        base_url=info["api_base_url"],
        headers={"Authorization": f"Bearer {info['token']}"},
        timeout=5.0,
        trust_env=False,
    ) as http:
        r = http.get(f"/api/matters/{info['matter_id']}")
        assert r.status_code == 200, r.text
        data = r.json()

    timeline = data.get("timeline") or []
    initial = next((t for t in timeline if t.get("file") == info["initial_file"]), None)
    assert initial is not None, "seeded initial file missing from timeline"
    comments = initial.get("comments") or []
    # The mention round-trips on the file as a new comment with body + mentions.
    assert any(
        c.get("body") == "请帮我 review 这条"
        and "dengke" in (c.get("mentions") or [])
        for c in comments
    ), comments


def test_mcp_e2e_create_matter_with_mention(live_server):
    """create_matter with mentions persists the comment + @ on the initial file.

    The seed user (邓柯, pinyin=dengke) is the only resolvable target in the
    fixture, so we @ that user. Proves flat mentions block reaches the backend
    as a nested `comments[]` and the backend records it on the file.
    """
    info = live_server
    created = asyncio.run(_run_mcp_create_matter_with_mention(
        info["mcp_base_url"], info["token"],
    ))
    assert created.get("ok") is True, created

    # Pull the created file and verify the @ + say message round-tripped.
    with httpx.Client(
        base_url=info["api_base_url"],
        headers={"Authorization": f"Bearer {info['token']}"},
        timeout=5.0,
        trust_env=False,
    ) as http:
        r = http.get(f"/api/matters/{created['matter_id']}")
        assert r.status_code == 200, r.text
        data = r.json()

    timeline = data.get("timeline") or []
    assert len(timeline) == 1
    initial = timeline[0]
    comments = initial.get("comments") or []
    assert len(comments) == 1
    assert comments[0]["body"] == "请帮我 review"
    # Mention round-trips as whatever the AI sent (pinyin/name/open_id),
    # backend stores it as-is and resolves at read-time for display.
    assert "dengke" in (comments[0].get("mentions") or [])


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
    # Instructions are delivered at handshake so the LLM can introduce
    # capabilities on the user's first message of the session.
    instructions = result["instructions"] or ""
    assert "Pivot MCP" in instructions, instructions
    # Each tool name should appear in the instructions so the LLM has a
    # concrete list to walk through during the introduction.
    for tool in [
        "resolve_context", "list_matters", "get_matter", "read_files",
        "create_matter", "create_file", "add_comment",
    ]:
        assert tool in instructions, (tool, instructions)
    assert {"resolve_context", "list_matters", "get_matter", "read_files",
            "create_file", "create_matter", "add_comment"} <= result["tool_names"]

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
