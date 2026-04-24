# Pivot MCP 外部 AI 接入：实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Pivot 服务里新增一个 `/mcp` endpoint + 5 个 MCP tool，并在 Pivot Web 加"复制给 AI"按钮和"外部 AI 接入"设置页，让 Claude Code / Cursor / Codex / Claude Desktop 等外部 AI 都能经 MCP 协议读写 Pivot matter。

**Architecture:** MCP 服务挂在现有 FastAPI 上（**Streamable HTTP 传输，单 endpoint `/mcp`**），5 个 tool 是对已有 Matter API（`server/api/matters.py`）的薄包装层，MCP 层完全无状态、PAT 认证透传。前端沿用现有 React + shadcn/ui + Tailwind 栈。

**Tech Stack:** Python 3.12 + FastAPI + `mcp` 官方 Python SDK + Pydantic + pytest + React + TypeScript + shadcn/ui + Tailwind

**依据**：`AI-docs/designs/2026-04-23-mcp-external-ai-design.md`（V2，已批准）

---

## 方案变更记录（实施前重要修订）

实施计划初稿写于设计文档 V2 批准之后。在启动实施前，根据对 AI 客户端实际支持情况的进一步调研，本计划做了两处**强制修订**。记录在此供实施者参考。

### 变更 1：MCP 传输协议由 SSE 改为 Streamable HTTP

**之前怎么做**：设计文档 V2 原文和本计划初稿 Phase 1.2 / 1.3 采用 **MCP SSE 传输**——两个 endpoint 模式：`/mcp/sse`（GET，建立 SSE 长连接）+ `/mcp/messages/`（POST，client→server 消息）。Python SDK API 为 `mcp.server.sse.SseServerTransport`。

**为什么不能用了**：
- MCP 协议规范 **2025-03-26 起正式废弃 SSE 传输**（见 https://modelcontextprotocol.io/specification/2025-03-26/basic/transports）
- **2026-04-01 起，协议规范明确要求客户端和服务端都不再接受 SSE 连接**
- 发稿时（2026-04-24）已过 deadline 23 天
- 实调：Claude Code / Cursor / Codex 三家已完整转向 Streamable HTTP；Claude Desktop 的远程服务也只走 Streamable HTTP。**SSE 对我们没有任何现实使用价值**

**改成怎么做**：采用 **MCP Streamable HTTP 传输**——单 endpoint `/mcp`，同时处理 GET（服务端→客户端流）和 POST（客户端→服务端消息）。Python SDK API 为 `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`。

**影响范围**：
- Phase 1.2：`server/mcp/server.py` 用 `StreamableHTTPSessionManager` 而不是 `SseServerTransport`
- Phase 1.3：FastAPI mount 为单路径 `/mcp`，而不是 `/mcp/sse` + `/mcp/messages/`
- Phase 8.1：`clientConfigs.ts` 的 MCP_URL 为 `.../mcp`（不是 `.../mcp/sse`），且客户端配置的 `type` 字段写 `"http"`（Claude Code）或不写（Cursor）

### 变更 2：Claude Desktop 接入方式从 JSON 文件改为 UI

**之前怎么做**：设置页的 Claude Desktop 卡片"复制 JSON 片段 + 显示 `claude_desktop_config.json` 路径"让用户手工粘进去。

**为什么不能用了**：
- Claude Desktop 的桌面应用 **`claude_desktop_config.json` 只支持 stdio 本地进程**，不支持远程 HTTP 服务（见 Anthropic 官方 support 文章 https://support.claude.com/en/articles/11503834）
- 远程服务**只能通过 UI 手工添加**：Settings → Connectors → Add custom connector

**改成怎么做**：设置页"Claude Desktop"卡片**改为"复制 URL + Token"**，提示用户打开 Desktop，走 Settings → Connectors → Add custom connector 的 UI 流程粘贴。

**影响范围**：
- Phase 8.1 `clientConfigs.ts` 的 `claudeDesktopJson` 函数改为 `claudeDesktopConnectionInfo`，输出 "URL: ...\nToken: Bearer ..." 两行
- Phase 8.2 设置页 "Claude Desktop" 卡片按钮文案从 "复制 JSON" 改为 "复制 URL+Token"，附带 UI 导航提示文案

### 另：Cursor 配置 schema 确认

调研中顺带确认 Cursor 的 `~/.cursor/mcp.json` **不使用 `type` 字段**（直接 `{url, headers}` 即可，传输由 Cursor 自动判断）。Phase 8.1 的 `cursorDeepLink` 生成器无需改结构（深链本身就不含 `type`），但需确认生成的 JSON 片段里**不要塞 `"type": "sse"` 之类的字段**。

---

## 文件结构

### 后端新增

| 路径 | 职责 |
|------|------|
| `server/mcp/__init__.py` | 包标识 |
| `server/mcp/server.py` | 构造 MCP Server、注册 5 个 tool、挂到 FastAPI 作为 `/mcp` SSE 路由 |
| `server/mcp/tools.py` | 5 个 tool 的实现（`resolve_context`、`list_matters`、`get_matter`、`read_files`、`create_file`）|
| `server/mcp/context.py` | URL 解析、matter access helper、`user_facing_summary` / `summary_for_ai` 生成 |
| `server/mcp/schemas.py` | tool 参数和返回的 Pydantic 模型 |

### 后端修改

| 路径 | 修改内容 |
|------|----------|
| `server/app.py` | 启动时把 MCP ASGI 路由挂进 FastAPI |
| `pyproject.toml` | 加 `mcp>=1.0` 依赖 |

### 后端测试

| 路径 | 覆盖 |
|------|------|
| `server/tests/test_mcp_context.py` | URL 解析、summary 生成 |
| `server/tests/test_mcp_tools.py` | 5 个 tool 的单测（mock Matter API）|
| `server/tests/test_mcp_server.py` | 真 HTTP 集成测（启动 TestClient 连 /mcp，走完一次 JSON-RPC 交互）|

### 前端新增

| 路径 | 职责 |
|------|------|
| `web/src/components/CopyForAIButton.tsx` | matter / 文件页复用的"复制给 AI"按钮 |
| `web/src/pages/SettingsExternalAI.tsx` | 外部 AI 接入设置页主组件 |
| `web/src/pages/settings/clientConfigs.ts` | 4 家客户端的配置模板生成器（纯函数） |

### 前端修改

| 路径 | 修改内容 |
|------|----------|
| `web/src/pages/MatterDetail.tsx`（或当前 matter 详情页）| 每个文件卡片上 + matter 头部加"复制给 AI"按钮 |
| `web/src/App.tsx`（或路由文件）| 挂载 `/settings/external-ai` 路由 |
| `web/src/pages/SettingsPage.tsx` | 设置页左侧目录加一项入口 |

---

## Phase 0：准备

### Task 0.1：确认工作分支并拉取最新代码

- [ ] **Step 1：确认当前分支**

Run: `git status && git log -1 --oneline`
Expected: 在一个从 `main` 切出的 feature 分支上，例如 `feat/mcp-external-ai`。如不是，先 `git checkout -b feat/mcp-external-ai main` 并 `git pull`.

- [ ] **Step 2：验证 Matter API 可用**

Run: `python -m pytest server/tests/test_matters_api.py -q`
Expected: PASS (说明 `GET /api/matters`、`GET /api/matters/{id}`、`POST /api/matters/{id}/files` 的实现健康)。

- [ ] **Step 3：确认前端能跑**

Run: `cd web && npm run dev` (后台)；`curl http://localhost:5173` 能返回 HTML。

---

## Phase 1：MCP 服务骨架

### Task 1.1：加 `mcp` 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1：在 dependencies 里加 `mcp>=1.0`**

打开 `pyproject.toml`，把 `dependencies` 段改成：

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "lark-oapi>=1.4",
    "itsdangerous>=2.2",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "mcp>=1.0",
]
```

- [ ] **Step 2：安装**

Run: `uv sync`
Expected: 输出 `Resolved N packages, installed mcp-x.y.z`.

- [ ] **Step 3：验证可 import**

Run: `python -c "from mcp.server import Server; print(Server)"`
Expected: 打印 `<class 'mcp.server.Server'>`.

- [ ] **Step 4：Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add mcp python SDK dependency"
```

---

### Task 1.2：建 MCP 包结构

**Files:**
- Create: `server/mcp/__init__.py`
- Create: `server/mcp/server.py`

- [ ] **Step 1：创建包**

写入 `server/mcp/__init__.py`：

```python
"""MCP endpoint exposing Pivot Matter API to external AI clients."""
```

- [ ] **Step 2：创建最小 server.py**

写入 `server/mcp/server.py`：

```python
from __future__ import annotations

import logging

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

log = logging.getLogger(__name__)

_SERVER_NAME = "pivot-mcp"
_SERVER_VERSION = "0.1.0"


def build_mcp_app() -> Starlette:
    """Return an ASGI app that serves MCP over Streamable HTTP at `/`.

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

    async def handle_streamable(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    return Starlette(routes=[
        Mount("/", app=handle_streamable),
    ])
```

**注**：Streamable HTTP 是单 endpoint 模式——同一个 URL 既处理 POST（client→server JSON-RPC 消息）也处理 GET（server→client 流式响应，用 SSE 作为 transport sub-layer 但只在需要流式时才开）。

- [ ] **Step 3：Commit**

```bash
git add server/mcp/
git commit -m "feat(mcp): MCP server skeleton with Streamable HTTP transport"
```

---

### Task 1.3：挂到 FastAPI

**Files:**
- Modify: `server/app.py`

- [ ] **Step 1：读取当前 app.py**

Run: `grep -n "app.mount\|FastAPI" server/app.py | head -20` 找到 `FastAPI()` 实例化和现有 mount 代码的位置。

- [ ] **Step 2：在 app.py 的 create_app 函数里挂 /mcp**

在 FastAPI 实例创建后、return app 之前，加：

```python
from server.mcp.server import build_mcp_app

app.mount("/mcp", build_mcp_app())
```

- [ ] **Step 3：本地起服务确认路由**

Run: `./.venv/Scripts/uvicorn.exe --factory server.app:create_app --host 127.0.0.1 --port 8000` (后台)

```bash
# 不带 Authorization 的 POST 应该返回 401
curl -i -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```
Expected: `HTTP/1.1 401 Unauthorized` + `{"detail":"missing_bearer_token"}`（PAT 鉴权会在 Task 1.4 加上，现在暂时可能是 200 或别的，先确认路径能路由到就行）。

- [ ] **Step 4：Commit**

```bash
git add server/app.py
git commit -m "feat(mcp): mount MCP Streamable HTTP endpoint at /mcp"
```

---

### Task 1.4：PAT 认证中间件

MCP 请求自带 `Authorization: Bearer pvt_xxx` 头，我们要在 SSE handler 里提取并验证。

**Files:**
- Modify: `server/mcp/server.py`
- Create: `server/mcp/auth.py`

- [ ] **Step 1：写 auth.py**

写入 `server/mcp/auth.py`：

```python
from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

from server.api_tokens import ApiTokenRepo, hash_token
from server.users import User, UserRepo


class McpAuthError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def authenticate(
    request: Request,
    tokens: ApiTokenRepo,
    users: UserRepo,
) -> User:
    """Extract Bearer PAT from request headers and return the authenticated User.

    Raises McpAuthError with proper HTTP status on failure.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise McpAuthError(401, "missing_bearer_token")
    token = auth_header.split(" ", 1)[1].strip()
    record = tokens.get(hash_token(token))
    if record is None:
        raise McpAuthError(401, "invalid_token")
    if record.expires_at and record.expires_at < _now():
        raise McpAuthError(401, "expired_token")
    user = users.get(record.user_open_id)
    if user is None:
        raise McpAuthError(401, "user_not_found")
    tokens.touch(hash_token(token))
    return user


def _now() -> float:
    from time import time
    return time()
```

- [ ] **Step 2：写单测**

创建 `server/tests/test_mcp_auth.py`：

```python
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from server.mcp.auth import McpAuthError, authenticate


def _mk_request(headers: dict) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def test_missing_header_rejects():
    with pytest.raises(McpAuthError) as ei:
        authenticate(_mk_request({}), MagicMock(), MagicMock())
    assert ei.value.status == 401
    assert ei.value.detail == "missing_bearer_token"


def test_invalid_token_rejects():
    tokens = MagicMock()
    tokens.get.return_value = None
    with pytest.raises(McpAuthError) as ei:
        authenticate(
            _mk_request({"Authorization": "Bearer pvt_bad"}),
            tokens, MagicMock(),
        )
    assert ei.value.status == 401
    assert ei.value.detail == "invalid_token"


def test_valid_token_returns_user():
    from server.api_tokens import ApiToken
    from server.users import User

    tok = ApiToken(
        token_hash="x"*64, user_open_id="ou_abc", name="Claude Code",
        created_at=0, last_used_at=None, expires_at=9e12,
    )
    tokens = MagicMock()
    tokens.get.return_value = tok
    users = MagicMock()
    users.get.return_value = User(
        open_id="ou_abc", name="Test", avatar_url="", pinyin="test",
        github_username="", needs_setup=False,
    )
    u = authenticate(
        _mk_request({"Authorization": "Bearer pvt_ok"}),
        tokens, users,
    )
    assert u.open_id == "ou_abc"
    tokens.touch.assert_called_once()
```

- [ ] **Step 3：跑单测**

Run: `python -m pytest server/tests/test_mcp_auth.py -q`
Expected: `3 passed`.

- [ ] **Step 4：在 server.py 里把 Streamable HTTP handler 前置一道鉴权**

修改 `server/mcp/server.py`：把 `build_mcp_app` 改为接收依赖，并用一个 ASGI 包装器在 `session_manager.handle_request` 前先鉴权：

```python
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

from server.api_tokens import ApiTokenRepo
from server.mcp.auth import McpAuthError, authenticate
from server.users import UserRepo


def build_mcp_app(tokens: ApiTokenRepo, users: UserRepo) -> Starlette:
    mcp_server = Server(_SERVER_NAME, version=_SERVER_VERSION)

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    async def handle_streamable(scope, receive, send):
        # Wrap in Request so we can read headers uniformly
        if scope.get("type") != "http":
            await session_manager.handle_request(scope, receive, send)
            return
        request = Request(scope, receive)
        try:
            user, token = authenticate(request, tokens, users)
        except McpAuthError as e:
            response = JSONResponse({"detail": e.detail}, status_code=e.status)
            await response(scope, receive, send)
            return
        # stash current user token for tools to use (see runtime.py in Task 2.2 Step 5)
        from server.mcp.runtime import set_user_token
        set_user_token(token)
        await session_manager.handle_request(scope, receive, send)

    return Starlette(routes=[
        Mount("/", app=handle_streamable),
    ])
```

**同时修改 `server/mcp/auth.py` 的 `authenticate` 返回签名**：把返回值从 `User` 改为 `(User, str)` 元组（第二个是原始 token 字符串，供 Task 2.2 的 tool runtime 用）。对应地改单测（把 `assert u.open_id == ...` 改成 `assert u[0].open_id == ...` 或解构 `user, token = authenticate(...)`）。

在 `server/app.py` 里也同步更新 mount 调用：`app.mount("/mcp", build_mcp_app(api_tokens, users))`。

- [ ] **Step 5：起服务验证 401**

Run: `./.venv/Scripts/uvicorn.exe --factory server.app:create_app --host 127.0.0.1 --port 8000` (后台)

```bash
curl -i -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```
Expected: `HTTP/1.1 401 Unauthorized` + `{"detail":"missing_bearer_token"}`.

- [ ] **Step 6：Commit**

```bash
git add server/mcp/auth.py server/mcp/server.py server/app.py server/tests/test_mcp_auth.py
git commit -m "feat(mcp): PAT bearer auth on /mcp endpoint"
```

---

## Phase 2：`resolve_context` tool

### Task 2.1：URL 解析 + schemas

**Files:**
- Create: `server/mcp/context.py`
- Create: `server/mcp/schemas.py`

- [ ] **Step 1：写 schemas.py**

写入 `server/mcp/schemas.py`：

```python
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- resolve_context ----------

class ResolveContextIn(BaseModel):
    url: str = Field(description="A Pivot URL copied from the Web, e.g. https://pivot.enclaws.ai/m/auth-redesign/f/005_xxx.md")


class MatterSnapshot(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str


class ResolveContextOut(BaseModel):
    matter_id: str
    file_path: str | None
    matter_snapshot: MatterSnapshot
    user_facing_summary: str = Field(
        description="A natural-language summary the AI MUST show to the user verbatim, so the user can verify the correct context was loaded."
    )


# ---------- list_matters ----------

class ListMattersIn(BaseModel):
    status: str | None = None
    owner: str | None = None
    q: str | None = None


class MatterListItem(BaseModel):
    id: str
    title: str
    current_status: str
    updated_at: str
    file_count: int | None = None


class ListMattersOut(BaseModel):
    items: list[MatterListItem]


# ---------- get_matter ----------

class GetMatterIn(BaseModel):
    matter_id: str


class TimelineItem(BaseModel):
    file: str
    created_at: str
    creator: str
    owner: str
    type: str
    summary: str
    quote: str | None = None
    refer: list[str] = []
    verifications: list[dict] | None = None
    outcome: str | None = None
    status_change: dict | None = None


class GetMatterOut(BaseModel):
    matter: MatterSnapshot
    timeline: list[TimelineItem]


# ---------- read_files ----------

class ReadFilesIn(BaseModel):
    matter_id: str
    paths: list[str]


class FileContent(BaseModel):
    file_path: str
    type: str
    creator: str
    owner: str
    created_at: str
    body: str
    truncated: bool = False


class ReadFilesOut(BaseModel):
    files: list[FileContent]


# ---------- create_file ----------

class VerificationIn(BaseModel):
    target: str
    judgement: str  # passed | failed | cancelled
    comment: str


class StatusChangeIn(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class CreateFileIn(BaseModel):
    matter_id: str
    type: str  # think | act | verify | result | insight
    summary: str
    body: str = ""
    quote: str | None = None
    refer: list[str] | None = None
    owner: str | None = None
    verifications: list[VerificationIn] | None = None
    outcome: str | None = None  # finished | cancelled (result only)
    status_change: StatusChangeIn | None = None


class CreateFileOut(BaseModel):
    ok: bool
    file_path: str
    view_url: str
    summary_for_ai: str = Field(
        description="A human-friendly confirmation message the AI MUST relay verbatim to the user."
    )
```

- [ ] **Step 2：写 context.py（URL 解析）**

写入 `server/mcp/context.py`：

```python
from __future__ import annotations

from urllib.parse import unquote, urlparse


class ContextUrlError(ValueError):
    pass


def parse_context_url(url: str) -> tuple[str, str | None]:
    """Parse a Pivot context URL.

    Accepted shapes:
      https://<host>/m/<matter_id>
      https://<host>/m/<matter_id>/f/<file_path>

    Returns (matter_id, file_path or None).
    Raises ContextUrlError if the URL does not match.
    """
    if not url:
        raise ContextUrlError("empty url")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ContextUrlError(f"unsupported scheme: {parsed.scheme}")
    path = parsed.path
    parts = [p for p in path.split("/") if p]
    # expected parts: ["m", <matter_id>] or ["m", <matter_id>, "f", <file...>]
    if len(parts) < 2 or parts[0] != "m":
        raise ContextUrlError("URL must be in the form /m/<matter_id> or /m/<matter_id>/f/<path>")
    matter_id = unquote(parts[1])
    if len(parts) == 2:
        return matter_id, None
    if len(parts) < 4 or parts[2] != "f":
        raise ContextUrlError("file part must be /f/<path>")
    file_path = "/".join(unquote(p) for p in parts[3:])
    return matter_id, file_path


def build_user_facing_summary(matter: dict, file_path: str | None, timeline: list[dict]) -> str:
    """Compose a one-liner the AI shows to the user after resolve_context."""
    title = matter.get("title") or matter.get("id")
    status = matter.get("current_status") or "unknown"
    if not file_path:
        return f'我读到了「{title}」这个 matter（状态：{status}）。你想做什么？'
    # find the file's type + summary in timeline
    matched = next((t for t in timeline if t.get("file") == file_path), None)
    if matched:
        ftype = matched.get("type", "file")
        fsummary = matched.get("summary", "")
        return (
            f'我读到了「{title}」matter 的一篇 {ftype} 文件：《{fsummary}》。'
            f'当前 matter 状态：{status}。你想做什么？'
        )
    return f'我读到了「{title}」matter 的一篇文件（{file_path}）。当前状态：{status}。你想做什么？'


def build_view_url(web_base_url: str, matter_id: str, file_path: str) -> str:
    """Compose a Web URL for 'where to view this file'."""
    base = web_base_url.rstrip("/")
    return f"{base}/m/{matter_id}/f/{file_path}"
```

- [ ] **Step 3：写单测**

创建 `server/tests/test_mcp_context.py`：

```python
import pytest

from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    build_view_url,
    parse_context_url,
)


def test_parse_matter_only():
    m, f = parse_context_url("https://pivot.enclaws.ai/m/auth-redesign")
    assert m == "auth-redesign"
    assert f is None


def test_parse_matter_and_file():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/auth-redesign/f/005_dengke_think_xxx.md"
    )
    assert m == "auth-redesign"
    assert f == "005_dengke_think_xxx.md"


def test_parse_nested_file_path():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/foo/f/subdir/bar.md"
    )
    assert m == "foo"
    assert f == "subdir/bar.md"


def test_parse_urlencoded_chinese():
    m, f = parse_context_url(
        "https://pivot.enclaws.ai/m/%E4%BA%A7%E5%93%81/f/005.md"
    )
    assert m == "产品"
    assert f == "005.md"


def test_parse_rejects_wrong_path():
    with pytest.raises(ContextUrlError):
        parse_context_url("https://pivot.enclaws.ai/t/thread/foo")


def test_parse_rejects_non_http():
    with pytest.raises(ContextUrlError):
        parse_context_url("ftp://pivot.enclaws.ai/m/foo")


def test_summary_matter_only():
    s = build_user_facing_summary(
        {"title": "Auth Redesign", "current_status": "executing"},
        None, [],
    )
    assert "Auth Redesign" in s
    assert "executing" in s


def test_summary_with_file():
    s = build_user_facing_summary(
        {"title": "Auth", "current_status": "executing"},
        "005.md",
        [{"file": "005.md", "type": "think", "summary": "梳理问题"}],
    )
    assert "think" in s
    assert "梳理问题" in s


def test_view_url():
    assert (
        build_view_url("https://pivot.enclaws.ai", "auth", "005.md")
        == "https://pivot.enclaws.ai/m/auth/f/005.md"
    )
```

- [ ] **Step 4：跑单测**

Run: `python -m pytest server/tests/test_mcp_context.py -q`
Expected: `9 passed`.

- [ ] **Step 5：Commit**

```bash
git add server/mcp/context.py server/mcp/schemas.py server/tests/test_mcp_context.py
git commit -m "feat(mcp): URL parsing + schemas for 5 tools"
```

---

### Task 2.2：实现 `resolve_context` tool

**Files:**
- Create: `server/mcp/tools.py`
- Modify: `server/mcp/server.py`（注册 tool）

- [ ] **Step 1：写 tools.py 骨架**

写入 `server/mcp/tools.py`：

```python
from __future__ import annotations

import logging
from typing import Any

import httpx

from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    parse_context_url,
)
from server.mcp.schemas import (
    MatterSnapshot,
    ResolveContextIn,
    ResolveContextOut,
)

log = logging.getLogger(__name__)


class ToolError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class MatterApiClient:
    """Thin wrapper around Matter API, using the calling user's PAT."""

    def __init__(self, base_url: str, token: str):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    def get_matter(self, matter_id: str) -> dict:
        resp = httpx.get(
            f"{self._base}/api/matters/{matter_id}",
            headers=self._headers,
            timeout=10.0,
        )
        if resp.status_code == 404:
            raise ToolError(404, "matter_not_found")
        if resp.status_code == 403:
            raise ToolError(403, "forbidden")
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        resp.raise_for_status()
        return resp.json()


def tool_resolve_context(
    payload: dict,
    client: MatterApiClient,
) -> dict:
    """Parse a Pivot URL + verify access + return summary for AI to echo."""
    input_ = ResolveContextIn.model_validate(payload)
    try:
        matter_id, file_path = parse_context_url(input_.url)
    except ContextUrlError as e:
        raise ToolError(400, f"bad_url: {e}")

    data = client.get_matter(matter_id)
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []

    if file_path is not None:
        found = any(t.get("file") == file_path for t in timeline)
        if not found:
            raise ToolError(404, "file_not_in_matter")

    summary_text = build_user_facing_summary(matter, file_path, timeline)

    result = ResolveContextOut(
        matter_id=matter_id,
        file_path=file_path,
        matter_snapshot=MatterSnapshot(
            id=matter.get("id", matter_id),
            title=matter.get("title", ""),
            current_status=matter.get("current_status", "unknown"),
            updated_at=matter.get("updated_at", ""),
        ),
        user_facing_summary=summary_text,
    )
    return result.model_dump(mode="json")
```

- [ ] **Step 2：单测 resolve_context**

创建 `server/tests/test_mcp_tools.py`：

```python
from unittest.mock import MagicMock

import pytest

from server.mcp.tools import MatterApiClient, ToolError, tool_resolve_context


def _make_client(matter: dict, timeline: list[dict]) -> MatterApiClient:
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {"matter": matter, "timeline": timeline}
    return client


def test_resolve_context_matter_only():
    client = _make_client(
        {"id": "auth", "title": "Auth Redesign", "current_status": "executing",
         "updated_at": "2026-04-23T10:00:00+08:00"},
        [],
    )
    out = tool_resolve_context(
        {"url": "https://pivot.enclaws.ai/m/auth"},
        client,
    )
    assert out["matter_id"] == "auth"
    assert out["file_path"] is None
    assert "Auth Redesign" in out["user_facing_summary"]
    assert "executing" in out["user_facing_summary"]


def test_resolve_context_with_file():
    client = _make_client(
        {"id": "auth", "title": "Auth", "current_status": "executing",
         "updated_at": "2026-04-23T10:00:00+08:00"},
        [{"file": "005.md", "type": "think", "summary": "梳理问题",
          "created_at": "", "creator": "a", "owner": "a"}],
    )
    out = tool_resolve_context(
        {"url": "https://pivot.enclaws.ai/m/auth/f/005.md"},
        client,
    )
    assert out["file_path"] == "005.md"
    assert "think" in out["user_facing_summary"]
    assert "梳理问题" in out["user_facing_summary"]


def test_resolve_context_bad_url():
    client = _make_client({}, [])
    with pytest.raises(ToolError) as ei:
        tool_resolve_context({"url": "not a url"}, client)
    assert ei.value.status == 400


def test_resolve_context_file_not_in_matter():
    client = _make_client(
        {"id": "auth", "title": "T", "current_status": "x", "updated_at": ""},
        [{"file": "001.md", "type": "think", "summary": "", "created_at": "",
          "creator": "a", "owner": "a"}],
    )
    with pytest.raises(ToolError) as ei:
        tool_resolve_context(
            {"url": "https://pivot.enclaws.ai/m/auth/f/999.md"},
            client,
        )
    assert ei.value.status == 404
    assert ei.value.detail == "file_not_in_matter"
```

- [ ] **Step 3：跑单测**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`
Expected: `4 passed`.

- [ ] **Step 4：把 tool 注册到 MCP Server**

修改 `server/mcp/server.py`，在 `build_mcp_app` 里增加 tool 注册：

```python
from mcp.types import Tool, TextContent

from server.mcp.tools import (
    MatterApiClient, ToolError,
    tool_resolve_context,
)
from server.mcp.schemas import ResolveContextIn


def _register_tools(mcp_server: Server, api_base_url: str):
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
            # more tools added below in later tasks
        ]

    @mcp_server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        # Per-request user token comes via ContextVar (see Task 1.4).
        # For now, resolve_context uses the caller's request PAT.
        from server.mcp.runtime import current_user_token
        token = current_user_token()
        client = MatterApiClient(api_base_url, token)
        import json
        try:
            if name == "resolve_context":
                out = tool_resolve_context(arguments, client)
            else:
                raise ToolError(404, f"unknown tool: {name}")
        except ToolError as e:
            return [TextContent(type="text", text=json.dumps(
                {"error": {"status": e.status, "detail": e.detail}},
                ensure_ascii=False,
            ))]
        return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False))]
```

然后在 `build_mcp_app(tokens, users, api_base_url)` 里调用 `_register_tools(mcp_server, api_base_url)` 并改签名接受 `api_base_url`。

- [ ] **Step 5：写 runtime.py 管理 per-request token**

创建 `server/mcp/runtime.py`：

```python
from __future__ import annotations

from contextvars import ContextVar

_token: ContextVar[str] = ContextVar("mcp_user_token")


def set_user_token(token: str) -> None:
    _token.set(token)


def current_user_token() -> str:
    try:
        return _token.get()
    except LookupError:
        raise RuntimeError("current_user_token called outside an MCP request")
```

在 `handle_sse` 的 authenticate 成功分支里，用 `set_user_token(...)` 把原始 PAT 注入 ContextVar。需要在 authenticate 返回 token 本身，修改 auth.py 让 authenticate 返回 `(user, token)` 二元组。

- [ ] **Step 6：本地跑通**

Run: `./.venv/Scripts/uvicorn.exe --factory server.app:create_app --host 127.0.0.1 --port 8000` (后台)
用一段 Python 脚本手工发一次 MCP `tools/call` 请求：

```python
# scratch_mcp_call.py
import httpx, json
TOKEN = "pvt_xxx_真实token"
resp = httpx.post(
    "http://127.0.0.1:8000/mcp",
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    json={"jsonrpc":"2.0","id":1,"method":"tools/call",
          "params":{"name":"resolve_context",
                    "arguments":{"url":"http://127.0.0.1:8000/m/<存在的matter>"}}},
)
print(resp.status_code, resp.text)
```
Expected: 返回 JSON-RPC 响应里带 `user_facing_summary` 字段。

- [ ] **Step 7：Commit**

```bash
git add server/mcp/tools.py server/mcp/server.py server/mcp/runtime.py server/mcp/auth.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): resolve_context tool + per-request token plumbing"
```

---

## Phase 3：`list_matters` tool

### Task 3.1：实现 + 注册

**Files:**
- Modify: `server/mcp/tools.py`
- Modify: `server/mcp/server.py`

- [ ] **Step 1：在 MatterApiClient 加 `list_matters` 方法**

在 `server/mcp/tools.py` 的 `MatterApiClient` 类里加：

```python
def list_matters(
    self, status: str | None = None, owner: str | None = None, q: str | None = None,
) -> list[dict]:
    params: dict[str, str] = {}
    if status: params["status"] = status
    if owner: params["owner"] = owner
    if q: params["q"] = q
    resp = httpx.get(
        f"{self._base}/api/matters",
        headers=self._headers, params=params, timeout=10.0,
    )
    if resp.status_code == 401: raise ToolError(401, "invalid_token")
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])
```

- [ ] **Step 2：写 tool_list_matters**

在 tools.py 里加：

```python
from server.mcp.schemas import ListMattersIn, ListMattersOut, MatterListItem


def tool_list_matters(payload: dict, client: MatterApiClient) -> dict:
    input_ = ListMattersIn.model_validate(payload)
    raw_items = client.list_matters(
        status=input_.status, owner=input_.owner, q=input_.q,
    )
    items = [
        MatterListItem(
            id=it.get("id", ""),
            title=it.get("title", ""),
            current_status=it.get("current_status", ""),
            updated_at=it.get("updated_at", ""),
            file_count=it.get("file_count"),
        )
        for it in raw_items
    ]
    return ListMattersOut(items=items).model_dump(mode="json")
```

- [ ] **Step 3：单测**

在 `server/tests/test_mcp_tools.py` 追加：

```python
def test_list_matters_passes_filters():
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = [
        {"id": "a", "title": "A", "current_status": "executing",
         "updated_at": "2026-04-23T10:00:00+08:00", "file_count": 3},
    ]
    out = tool_list_matters(
        {"status": "executing", "q": "auth"},
        client,
    )
    client.list_matters.assert_called_once_with(
        status="executing", owner=None, q="auth",
    )
    assert len(out["items"]) == 1
    assert out["items"][0]["id"] == "a"
```

- [ ] **Step 4：跑测试**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`
Expected: `5 passed`.

- [ ] **Step 5：注册到 MCP Server**

在 `_register_tools` 里的 list_tools 返回值加一项：

```python
Tool(
    name="list_matters",
    description="List matters visible to the current user. Supports status/owner/q filters.",
    inputSchema=ListMattersIn.model_json_schema(),
),
```

在 call_tool 的 dispatch 里加：

```python
elif name == "list_matters":
    out = tool_list_matters(arguments, client)
```

- [ ] **Step 6：手工验证**

用 scratch 脚本调 `list_matters` 方法（替换脚本里的 tool name 和 arguments），确认返回列表结构。

- [ ] **Step 7：Commit**

```bash
git add server/mcp/tools.py server/mcp/server.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): list_matters tool"
```

---

## Phase 4：`get_matter` + `read_files`（共享 Matter API 拉取）

### Task 4.1：实现两个 tool

**Files:**
- Modify: `server/mcp/tools.py`
- Modify: `server/mcp/server.py`

- [ ] **Step 1：写 tool_get_matter**

在 `server/mcp/tools.py` 里加：

```python
from server.mcp.schemas import (
    GetMatterIn, GetMatterOut, TimelineItem, MatterSnapshot,
    ReadFilesIn, ReadFilesOut, FileContent,
)


def tool_get_matter(payload: dict, client: MatterApiClient) -> dict:
    input_ = GetMatterIn.model_validate(payload)
    data = client.get_matter(input_.matter_id)
    matter = data.get("matter") or {}
    timeline_raw = data.get("timeline") or []

    timeline = []
    for item in timeline_raw:
        # STRIP body here — AI only needs index
        clean = {k: v for k, v in item.items() if k != "body"}
        timeline.append(TimelineItem.model_validate(clean).model_dump(mode="json"))

    return GetMatterOut(
        matter=MatterSnapshot(
            id=matter.get("id", input_.matter_id),
            title=matter.get("title", ""),
            current_status=matter.get("current_status", "unknown"),
            updated_at=matter.get("updated_at", ""),
        ),
        timeline=timeline,
    ).model_dump(mode="json")
```

- [ ] **Step 2：写 tool_read_files**

```python
def tool_read_files(payload: dict, client: MatterApiClient) -> dict:
    input_ = ReadFilesIn.model_validate(payload)
    if not input_.paths:
        raise ToolError(400, "paths must not be empty")
    data = client.get_matter(input_.matter_id)
    timeline = data.get("timeline") or []
    by_path = {t.get("file"): t for t in timeline}

    results: list[FileContent] = []
    for p in input_.paths:
        item = by_path.get(p)
        if item is None:
            raise ToolError(404, f"file_not_in_matter: {p}")
        body = item.get("body") or ""
        truncated = False
        if len(body) > 20000:
            body = body[:20000]
            truncated = True
        results.append(FileContent(
            file_path=p,
            type=item.get("type", ""),
            creator=item.get("creator", ""),
            owner=item.get("owner", ""),
            created_at=item.get("created_at", ""),
            body=body,
            truncated=truncated,
        ))
    return ReadFilesOut(files=results).model_dump(mode="json")
```

- [ ] **Step 3：单测**

在 `server/tests/test_mcp_tools.py` 追加：

```python
def test_get_matter_strips_bodies():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "x", "updated_at": ""},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "s1",
             "created_at": "", "creator": "u", "owner": "u",
             "body": "这是正文不应该出现", "refer": []},
        ],
    }
    out = tool_get_matter({"matter_id": "a"}, client)
    assert "body" not in out["timeline"][0]
    assert out["timeline"][0]["file"] == "001.md"


def test_read_files_returns_selected_bodies():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a", "title": "T", "current_status": "x", "updated_at": ""},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "s1",
             "body": "正文1", "created_at": "", "creator": "u", "owner": "u"},
            {"file": "002.md", "type": "act", "summary": "s2",
             "body": "正文2", "created_at": "", "creator": "u", "owner": "u"},
        ],
    }
    out = tool_read_files({"matter_id": "a", "paths": ["002.md"]}, client)
    assert len(out["files"]) == 1
    assert out["files"][0]["body"] == "正文2"
    assert out["files"][0]["truncated"] is False


def test_read_files_rejects_unknown_path():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a"}, "timeline": [],
    }
    with pytest.raises(ToolError) as ei:
        tool_read_files({"matter_id": "a", "paths": ["xxx.md"]}, client)
    assert ei.value.status == 404


def test_read_files_truncates_long_body():
    client = MagicMock(spec=MatterApiClient)
    client.get_matter.return_value = {
        "matter": {"id": "a"},
        "timeline": [
            {"file": "001.md", "type": "think", "summary": "",
             "body": "x" * 30000, "created_at": "", "creator": "u", "owner": "u"},
        ],
    }
    out = tool_read_files({"matter_id": "a", "paths": ["001.md"]}, client)
    assert out["files"][0]["truncated"] is True
    assert len(out["files"][0]["body"]) == 20000
```

- [ ] **Step 4：跑**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`
Expected: `9 passed`.

- [ ] **Step 5：注册 tool**

在 `_register_tools` 里加：

```python
Tool(
    name="get_matter",
    description="Return a matter's header + timeline metadata (no file bodies). Call read_files afterwards to fetch specific file bodies on demand.",
    inputSchema=GetMatterIn.model_json_schema(),
),
Tool(
    name="read_files",
    description="Fetch the full text of one or more files within a matter. Always call get_matter first to see which files exist.",
    inputSchema=ReadFilesIn.model_json_schema(),
),
```

dispatch：

```python
elif name == "get_matter":
    out = tool_get_matter(arguments, client)
elif name == "read_files":
    out = tool_read_files(arguments, client)
```

- [ ] **Step 6：Commit**

```bash
git add server/mcp/tools.py server/mcp/server.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): get_matter + read_files tools (MCP-layer body split)"
```

---

## Phase 5：`create_file` tool

### Task 5.1：实现 + 注册

**Files:**
- Modify: `server/mcp/tools.py`
- Modify: `server/mcp/server.py`

- [ ] **Step 1：在 MatterApiClient 加 post_file**

```python
def post_file(self, matter_id: str, body: dict) -> dict:
    resp = httpx.post(
        f"{self._base}/api/matters/{matter_id}/files",
        headers={**self._headers, "Content-Type": "application/json"},
        json=body, timeout=15.0,
    )
    if resp.status_code == 401: raise ToolError(401, "invalid_token")
    if resp.status_code == 403: raise ToolError(403, "forbidden")
    if resp.status_code == 404: raise ToolError(404, "matter_not_found")
    if resp.status_code == 409: raise ToolError(409, resp.text)
    if resp.status_code == 422:
        # return 200 + errors for AI to iterate on (design §四 约定)
        return {"__validation_errors__": resp.json()}
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 2：写 tool_create_file**

在 `server/mcp/tools.py`：

```python
from server.mcp.schemas import CreateFileIn, CreateFileOut
from server.mcp.context import build_view_url


def tool_create_file(
    payload: dict,
    client: MatterApiClient,
    web_base_url: str,
) -> dict:
    input_ = CreateFileIn.model_validate(payload)
    api_body: dict = {
        "type": input_.type,
        "summary": input_.summary,
        "body": input_.body,
    }
    if input_.quote is not None: api_body["quote"] = input_.quote
    if input_.refer is not None: api_body["refer"] = input_.refer
    if input_.owner is not None: api_body["owner"] = input_.owner
    if input_.verifications is not None:
        api_body["verifications"] = [v.model_dump() for v in input_.verifications]
    if input_.outcome is not None: api_body["outcome"] = input_.outcome
    if input_.status_change is not None:
        api_body["status_change"] = {
            "from": input_.status_change.from_,
            "to": input_.status_change.to,
        }

    resp = client.post_file(input_.matter_id, api_body)

    if "__validation_errors__" in resp:
        # design §四：422 → 200 with errors payload so AI can iterate
        return {"errors": resp["__validation_errors__"]}

    # 成功
    item = resp.get("item") or {}
    matter = resp.get("matter") or {}
    file_path = item.get("file", "")
    view_url = build_view_url(web_base_url, input_.matter_id, file_path)

    title = matter.get("title") or input_.matter_id
    file_count = matter.get("file_count") or "?"
    summary_ai = (
        f"✅ 已提交。这是 matter「{title}」的第 {file_count} 篇。"
        f"点这里查看：{view_url}"
    )

    return CreateFileOut(
        ok=True,
        file_path=file_path,
        view_url=view_url,
        summary_for_ai=summary_ai,
    ).model_dump(mode="json")
```

- [ ] **Step 3：单测**

```python
from server.mcp.tools import tool_create_file


def test_create_file_success_returns_summary():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "item": {"file": "007_x_verify_abc.md", "type": "verify"},
        "matter": {"id": "a", "title": "Auth", "file_count": 7,
                   "current_status": "executing"},
    }
    out = tool_create_file(
        {
            "matter_id": "a",
            "type": "verify",
            "summary": "验证 003/004",
            "body": "# Verify",
            "verifications": [
                {"target": "003.md", "judgement": "passed", "comment": "ok"}
            ],
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert out["ok"] is True
    assert out["file_path"].endswith(".md")
    assert "Auth" in out["summary_for_ai"]
    assert out["view_url"].startswith("https://pivot.enclaws.ai/m/a/f/")


def test_create_file_validation_errors_returned_as_200():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.return_value = {
        "__validation_errors__": {"detail": {"code": "invalid_quote"}},
    }
    out = tool_create_file(
        {"matter_id": "a", "type": "verify", "summary": "x",
         "verifications": [{"target": "x", "judgement": "passed", "comment": "y"}]},
        client,
        "https://pivot.enclaws.ai",
    )
    assert "errors" in out
    assert "ok" not in out


def test_create_file_404_raises():
    client = MagicMock(spec=MatterApiClient)
    client.post_file.side_effect = ToolError(404, "matter_not_found")
    with pytest.raises(ToolError):
        tool_create_file(
            {"matter_id": "missing", "type": "think", "summary": "x"},
            client, "https://pivot.enclaws.ai",
        )
```

- [ ] **Step 4：跑测试**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`
Expected: `12 passed`.

- [ ] **Step 5：注册 tool**

在 `_register_tools` 里加：

```python
Tool(
    name="create_file",
    description=(
        "Create a new timeline item (think/act/verify/result/insight) in a matter. "
        "PROTOCOL: BEFORE calling this tool, you MUST present the draft content to "
        "the user in natural language in the chat and wait for explicit approval "
        "('ok', 'go', etc). The tool approval dialog is the final confirmation. "
        "After success, relay the returned `summary_for_ai` message verbatim."
    ),
    inputSchema=CreateFileIn.model_json_schema(),
),
```

dispatch：

```python
elif name == "create_file":
    out = tool_create_file(arguments, client, web_base_url)
```

注意：`_register_tools` 需要接受 `web_base_url` 参数，`build_mcp_app` 同步改签名。

- [ ] **Step 6：端到端手工测**

用本地真的 PAT 和 matter，在 scratch 脚本里串一遍：resolve → get → create 小 think 文件（可以放"测试数据"随时删）。

- [ ] **Step 7：Commit**

```bash
git add server/mcp/tools.py server/mcp/server.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): create_file tool (with preview-in-chat protocol)"
```

---

## Phase 6：后端端到端集成测试

### Task 6.1：写一个最小的 MCP client 集成测

**Files:**
- Create: `server/tests/test_mcp_e2e.py`

- [ ] **Step 1：写集成测**

这个测试启动一个 TestClient，真实调 `/mcp`（Streamable HTTP 单 endpoint）走一轮 JSON-RPC。使用 Matter API 真实依赖（用 fixture 准备一个最小 matter）。

```python
"""E2E: spin up FastAPI via TestClient, hit /mcp endpoint with a real PAT,
and exercise resolve→get_matter→create_file flow."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Requires the app factory to support a test-mode wiring
# that accepts a temp workspace + in-memory token.
# See server/tests/conftest.py for the fixture.


@pytest.mark.integration
def test_mcp_resolve_get_create_flow(mcp_client_with_token):
    client: TestClient = mcp_client_with_token["client"]
    token: str = mcp_client_with_token["token"]
    matter_id: str = mcp_client_with_token["matter_id"]

    def mcp_call(method: str, params: dict) -> dict:
        resp = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # 1. resolve_context
    out = mcp_call("tools/call", {
        "name": "resolve_context",
        "arguments": {"url": f"http://testserver/m/{matter_id}"},
    })
    body = json.loads(out["result"]["content"][0]["text"])
    assert body["matter_id"] == matter_id

    # 2. get_matter
    out = mcp_call("tools/call", {
        "name": "get_matter",
        "arguments": {"matter_id": matter_id},
    })
    body = json.loads(out["result"]["content"][0]["text"])
    assert "timeline" in body
    for item in body["timeline"]:
        assert "body" not in item  # must be stripped

    # 3. create_file (think, minimal)
    out = mcp_call("tools/call", {
        "name": "create_file",
        "arguments": {
            "matter_id": matter_id,
            "type": "think",
            "summary": "E2E test think",
            "body": "# E2E test",
        },
    })
    body = json.loads(out["result"]["content"][0]["text"])
    assert body["ok"] is True
    assert body["view_url"]
```

- [ ] **Step 2：在 conftest.py 加 fixture**

如果还没有 `mcp_client_with_token` fixture，在 `server/tests/conftest.py` 里创建。参考现有 `server/tests/test_matters_api.py` 的 TestClient 构造方式。

- [ ] **Step 3：跑集成测**

Run: `python -m pytest server/tests/test_mcp_e2e.py -q`
Expected: `1 passed`.

- [ ] **Step 4：Commit**

```bash
git add server/tests/test_mcp_e2e.py server/tests/conftest.py
git commit -m "test(mcp): E2E flow resolve → get_matter → create_file"
```

---

## Phase 7：Web "复制给 AI" 按钮

### Task 7.1：按钮组件

**Files:**
- Create: `web/src/components/CopyForAIButton.tsx`

- [ ] **Step 1：写组件**

```tsx
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Copy, Check } from "lucide-react";

export function CopyForAIButton({
  matterId,
  filePath,
  size = "sm",
}: {
  matterId: string;
  filePath?: string;
  size?: "sm" | "default";
}) {
  const [copied, setCopied] = useState(false);
  const url = filePath
    ? `${window.location.origin}/m/${encodeURIComponent(matterId)}/f/${encodeURIComponent(filePath)}`
    : `${window.location.origin}/m/${encodeURIComponent(matterId)}`;

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("已复制，粘到 Claude Code 或其他 AI 助手即可");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("复制失败，请手动复制：" + url);
    }
  };

  return (
    <Button size={size} variant="outline" onClick={onCopy}>
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      复制给 AI
    </Button>
  );
}
```

- [ ] **Step 2：在 matter 详情页添加**

找到当前 matter 详情页（例如 `web/src/pages/MatterDetail.tsx` 或类似）。在：
- matter 头部（`matter` 级 URL）
- 每个文件卡片上（`file` 级 URL）

各加一个 `<CopyForAIButton />`。具体位置请参考现有"收藏"按钮或"查看原文"按钮摆放逻辑。

- [ ] **Step 3：手工验证**

起前端 `npm run dev`，打开一个 matter，点按钮，确认：
- 剪贴板内容是正确的 URL
- Toast 文案是"已复制，粘到 Claude Code 或其他 AI 助手即可"
- 按钮图标短暂切换为 Check 图标

- [ ] **Step 4：Commit**

```bash
git add web/src/components/CopyForAIButton.tsx web/src/pages/MatterDetail.tsx
git commit -m "feat(web): '复制给 AI' button on matter / file cards"
```

---

## Phase 8：Web 外部 AI 接入设置页

### Task 8.1：4 家客户端配置生成器

**Files:**
- Create: `web/src/pages/settings/clientConfigs.ts`

- [ ] **Step 1：纯函数模块**

```typescript
/**
 * Streamable HTTP MCP endpoint (single URL, both GET + POST).
 * In dev we serve from the same origin; in prod it's behind pivot.enclaws.ai.
 */
const MCP_URL = typeof window !== "undefined"
  ? `${window.location.origin}/mcp`
  : "https://pivot.enclaws.ai/mcp";


/**
 * Claude Code: a prompt the user pastes into Claude Code itself,
 * asking Claude to update ~/.claude.json for them.
 */
export function claudeCodePrompt(token: string): string {
  return [
    `请帮我把下面的 MCP 服务器加到 Claude Code 的配置里。`,
    ``,
    `服务器名: pivot`,
    `传输类型: http (Streamable HTTP)`,
    `URL: ${MCP_URL}`,
    `Authorization 头: Bearer ${token}`,
    ``,
    `请修改 ~/.claude.json 或项目 .mcp.json，对应的 JSON 形如：`,
    `  {"mcpServers":{"pivot":{"type":"http","url":"${MCP_URL}","headers":{"Authorization":"Bearer ${token}"}}}}`,
    `改完后告诉我完成了。`,
  ].join("\n");
}


/**
 * Cursor: deep link that opens Cursor and pre-fills the MCP config.
 * Cursor's mcp.json schema does NOT use a `type` field; transport is auto-detected.
 */
export function cursorDeepLink(token: string): string {
  const config = {
    name: "pivot",
    url: MCP_URL,
    headers: { Authorization: `Bearer ${token}` },
  };
  return `cursor://anysphere.cursor-deeplink/mcp/install?config=${encodeURIComponent(JSON.stringify(config))}`;
}


/**
 * Codex: CLI command the user pastes into their terminal.
 * Codex detects Streamable HTTP from the presence of `url`.
 * Bearer token is passed via env var so it doesn't hit shell history.
 */
export function codexCliCommand(token: string): string {
  // User should first `export PIVOT_TOKEN=pvt_xxx`.
  return [
    `# 1) 先设置 token 到环境变量（避免进 shell 历史）:`,
    `export PIVOT_TOKEN="${token}"`,
    `# 2) 添加 MCP 服务器:`,
    `codex mcp add pivot --url ${MCP_URL} --bearer-token-env-var PIVOT_TOKEN`,
  ].join("\n");
}


/**
 * Claude Desktop: NOT a JSON config paste. Users must add via the UI.
 * We give them copy-pasteable URL + Token, and instructions on where to paste.
 */
export function claudeDesktopConnectionInfo(token: string): string {
  return [
    `URL: ${MCP_URL}`,
    `Authorization: Bearer ${token}`,
  ].join("\n");
}


export const CLAUDE_DESKTOP_UI_HINT =
  '打开 Claude Desktop → Settings → Connectors → "Add custom connector"，' +
  '把上面的 URL 和 Authorization header 粘进去，保存即可。';
```

**关键变化说明**（实施者必读）：

- 所有客户端的 MCP URL 都是**单 endpoint `/mcp`**（Streamable HTTP 不再分 `/sse` 和 `/messages`）
- Claude Code 的 JSON 配置里**显式写 `"type": "http"`**（对应 Streamable HTTP 传输）
- Cursor 的 JSON 配置**不写 `type` 字段**（Cursor schema 不用这个 key）
- Codex 用 `--bearer-token-env-var`（不用 `--header`）把 token 从环境变量取，避免 shell 历史泄露
- Claude Desktop 不生成 JSON 片段，只给 URL + Token，附带一段 UI 导航提示文案

- [ ] **Step 2：写单测（vitest）**

`web/src/pages/settings/clientConfigs.test.ts`：

```typescript
import { describe, it, expect } from "vitest";
import {
  claudeCodePrompt, cursorDeepLink, codexCliCommand,
  claudeDesktopConnectionInfo, CLAUDE_DESKTOP_UI_HINT,
} from "./clientConfigs";

describe("clientConfigs", () => {
  it("claude code prompt embeds token and type:http hint", () => {
    const p = claudeCodePrompt("pvt_xxx");
    expect(p).toContain("Bearer pvt_xxx");
    expect(p).toContain('"type":"http"');
  });

  it("cursor deep link is well-formed and contains no 'type' field", () => {
    const link = cursorDeepLink("pvt_xxx");
    expect(link.startsWith("cursor://")).toBe(true);
    expect(link).toContain("pvt_xxx");
    // Must NOT embed a type:sse or type:http — Cursor schema doesn't use it.
    const payload = decodeURIComponent(link.split("config=")[1]);
    const cfg = JSON.parse(payload);
    expect("type" in cfg).toBe(false);
  });

  it("codex cli command uses bearer-token-env-var", () => {
    const cmd = codexCliCommand("pvt_xxx");
    expect(cmd).toMatch(/codex mcp add pivot/);
    expect(cmd).toContain("--bearer-token-env-var PIVOT_TOKEN");
    // Token goes into env var, not onto the command line.
    expect(cmd).toContain('export PIVOT_TOKEN="pvt_xxx"');
  });

  it("claude desktop info has url+token and hint tells users to use UI", () => {
    const info = claudeDesktopConnectionInfo("pvt_xxx");
    expect(info).toContain("Bearer pvt_xxx");
    expect(info).toContain("/mcp");
    expect(CLAUDE_DESKTOP_UI_HINT).toContain("Settings");
    expect(CLAUDE_DESKTOP_UI_HINT).toContain("Connectors");
  });
});
```

- [ ] **Step 3：跑 vitest**

Run: `cd web && npm run test clientConfigs`
Expected: 4 tests passing.

- [ ] **Step 4：Commit**

```bash
git add web/src/pages/settings/clientConfigs.ts web/src/pages/settings/clientConfigs.test.ts
git commit -m "feat(web): 4-client MCP config generators"
```

---

### Task 8.2：设置页组件

**Files:**
- Create: `web/src/pages/SettingsExternalAI.tsx`
- Modify: 主路由或设置页导航（具体路径由前端负责人确认）

- [ ] **Step 1：写页面主组件**

```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Layout } from "@/components/Layout";
import {
  claudeCodePrompt, cursorDeepLink, codexCliCommand,
  claudeDesktopConnectionInfo, CLAUDE_DESKTOP_UI_HINT,
} from "./settings/clientConfigs";
import { createToken, listTokens } from "@/api";

export function SettingsExternalAI({ me, onLogout }: { me: any; onLogout: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [connected, setConnected] = useState<{name:string; last_used_at:number|null}[]>([]);

  useEffect(() => {
    listTokens().then((items) => {
      setConnected(items.filter(t => ["Claude Code","Cursor","Codex","Claude Desktop"].includes(t.name)));
    });
  }, []);

  const ensureToken = async (clientName: string): Promise<string> => {
    if (token) return token;
    const r = await createToken({ name: clientName, ttl_days: 90 });
    setToken(r.token);
    return r.token;
  };

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast.success("已复制");
  };

  return (
    <Layout me={me} onLogout={onLogout}>
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <h1 className="text-2xl font-semibold">外部 AI 接入</h1>

        <p className="text-muted-foreground">
          选择你的 AI 客户端，点"复制"或"一键安装"，按提示完成连接。
          连接上之后，在 matter / 文件页点"复制给 AI"就能让 AI 读写 Pivot 内容。
        </p>

        <div className="grid grid-cols-2 gap-4">
          <Card className="p-4 space-y-2">
            <h3 className="font-medium">Claude Code</h3>
            <p className="text-sm text-muted-foreground">跨平台，让 Claude 自己改配置</p>
            <Button onClick={async () => copy(claudeCodePrompt(await ensureToken("Claude Code")))}>
              复制 Prompt
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-medium">Cursor</h3>
            <p className="text-sm text-muted-foreground">浏览器一键唤起 Cursor</p>
            <Button onClick={async () => {
              const link = cursorDeepLink(await ensureToken("Cursor"));
              window.location.href = link;
            }}>
              一键安装
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-medium">Codex</h3>
            <p className="text-sm text-muted-foreground">终端粘贴 CLI 命令</p>
            <Button onClick={async () => copy(codexCliCommand(await ensureToken("Codex")))}>
              复制 CLI 命令
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-medium">Claude Desktop</h3>
            <p className="text-sm text-muted-foreground">
              {CLAUDE_DESKTOP_UI_HINT}
            </p>
            <Button onClick={async () => copy(claudeDesktopConnectionInfo(await ensureToken("Claude Desktop")))}>
              复制 URL + Token
            </Button>
          </Card>
        </div>

        <div>
          <h3 className="font-medium mb-2">已接入客户端</h3>
          {connected.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无。完成上面任一客户端的接入后，这里会显示。</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {connected.map(t => (
                <li key={t.name}>✅ {t.name} · 最后使用：{t.last_used_at ? new Date(t.last_used_at*1000).toLocaleString() : "尚未使用"}</li>
              ))}
            </ul>
          )}
        </div>

        <details className="mt-8">
          <summary className="cursor-pointer text-sm text-muted-foreground">▸ 高级设置（访问令牌、撤销连接、手工配置）</summary>
          <div className="mt-3 space-y-2 text-sm">
            {token && <div>当前 token（仅本次显示一次）：<code>{token}</code></div>}
            <p>如果要撤销某个客户端的连接，去"设置 → API Tokens"删除对应 token。</p>
          </div>
        </details>
      </div>
    </Layout>
  );
}
```

- [ ] **Step 2：挂路由**

在前端主路由文件里加 `/settings/external-ai → <SettingsExternalAI />`。

在现有 `SettingsPage.tsx`（如果有）的左侧目录里加一项入口。

- [ ] **Step 3：加 API helpers**

确认 `web/src/api.ts` 里已经有 `createToken` / `listTokens`。如果没有，按现有 PAT API 封装方式加。

- [ ] **Step 4：手工跑一遍**

起前端，打开 `/settings/external-ai`：
- 4 个卡片都显示
- 点 Claude Code 卡片的"复制 Prompt" → 剪贴板有正确 prompt（带真实 token）
- 点 Cursor 一键安装 → 浏览器跳 cursor:// 协议
- "高级设置"默认折叠
- 生成 token 后刷新页面，"已接入客户端"区域显示出来

- [ ] **Step 5：Commit**

```bash
git add web/src/pages/SettingsExternalAI.tsx web/src/App.tsx web/src/api.ts
git commit -m "feat(web): external AI settings page (4 clients)"
```

---

## Phase 9：上线前手工回归

Manual phase（不是代码任务），由 QA / 开发自己跑一遍。

- [ ] **Step 1：起本地服务**

```bash
./.venv/Scripts/uvicorn.exe --factory server.app:create_app --host 127.0.0.1 --port 8000 &
cd web && npm run dev &
```

- [ ] **Step 2：走完李明的 7 步用户旅程**

对照 `AI-docs/designs/2026-04-23-mcp-external-ai-design.md` §七 的用户视角一步步操作：

- 打开 http://localhost:5173 → 设置 → 外部 AI 接入
- 点 Claude Code 复制 Prompt
- 打开 Claude Code，粘贴，让它完成配置
- 重启 Claude Code
- 回 Pivot Web，进入一个已有 matter
- 点"复制给 AI"
- 去 Claude Code 粘贴
- AI 回复 user_facing_summary
- 问 AI "帮我写个 think 总结一下这个 matter"
- AI 起草 → 在对话里展示草稿 → 点头
- AI 调 create_file → approval dialog 确认
- AI 回复带 view_url 的 summary_for_ai
- 点回链，看到新文件

期望：全程顺畅，没有 500 / 401 / 红色报错。

- [ ] **Step 3：在 Codex / Claude Desktop 上各至少跑一次"接入 + 读一个 matter"**

只要"能连上 + 能读成功"就够，不一定全流程。

- [ ] **Step 4：回归后报告**

开一个 issue 或在现有渠道记录："MCP 外部 AI 接入 V1 本地验收通过"，把 Claude Code 主流程的截图和时长记录贴上。

---

## 自检清单

实施完 Phase 1~8 后，检查：

- [ ] `python -m pytest server/tests/test_mcp_*.py -q` 全部 PASS
- [ ] `cd web && npm run test` 全部 PASS
- [ ] `cd web && npm run typecheck` 无错
- [ ] 本地起服务后，`curl -X POST http://127.0.0.1:8000/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'` 返回 401（没带 token 的情况）
- [ ] 带有效 PAT 请求能成功握手 MCP 协议
- [ ] Phase 9 的用户旅程至少在 Claude Code 上跑通

---

## 不做的事（明确范围外）

照 V2 设计 §十一：
- 新建 matter（先去 Web 建）
- 跨 matter 读取
- 搜索 / 评论流 / 编辑已提交文件
- CLI 壳层
- 其他 AI 客户端（手工配置入口兜底）

如有越界需求，单独提 V1.1 设计，不塞进本次实施。
