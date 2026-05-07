# MCP 发布 matter 接入可见范围 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MCP 的 `create_matter` 能传可见范围（含新分类的可见范围），并提供一个 `list_visibility_options` 工具供 AI 在用户表达受限意图时拉候选名单。

**Architecture:** 新增两个 pydantic 子模型镜像后端 wire format，挂到 `CreateMatterIn` 上；`tool_create_matter` 把字段透传到 `POST /api/matters`；新增 `MatterApiClient.get_visibility_options` 方法和 `tool_list_visibility_options` 工具，包一层 `GET /api/visibility-options`；在 MCP server 注册新工具并更新 `create_matter` 工具描述 + 顶层 INSTRUCTIONS。后端校验逻辑（缺新分类范围、超出分类范围、把 owner 排除）已经存在，错误码通过现有 `__validation_errors__` → `errors` 通道透传，不需要 MCP 端再查一遍。

**Tech Stack:** Python 3.11、pydantic v2、FastAPI（被调方）、MCP Python SDK、pytest + unittest.mock。

---

## File Structure

| 文件 | 用途 | 改动 |
|---|---|---|
| `server/mcp/schemas.py` | MCP 工具入参/出参的 pydantic 模型 | 增加 `VisibilityScopeIn` / `CategoryVisibilityIn` / `ListVisibilityOptionsIn` / `ListVisibilityOptionsOut`；扩 `CreateMatterIn` |
| `server/mcp/tools.py` | 工具实现 + Matter API 客户端 | `MatterApiClient.get_visibility_options`；扩 `tool_create_matter`；新增 `tool_list_visibility_options` |
| `server/mcp/server.py` | MCP 工具注册和分发 | 在 `_list_tools` 注册新工具；在 `_call_tool` 加分发分支；扩 `create_matter` 工具的 description（PROTOCOL 新增 visibility 段） |
| `server/mcp/instructions.py` | 顶层 INSTRUCTIONS | 在能力清单加 `list_visibility_options` 一行 |
| `server/tests/test_mcp_tools.py` | 单测 | 加 visibility 透传、422 透出、`list_visibility_options` 各场景 |

---

## Task 1: 加 visibility 子模型并挂到 CreateMatterIn

**Files:**
- Modify: `server/mcp/schemas.py`
- Test: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: 在 `server/tests/test_mcp_tools.py` 顶部 import 区下面追加新的测试**

```python
from server.mcp.schemas import (
    CategoryVisibilityIn,
    CreateMatterIn,
    VisibilityScopeIn,
)


def test_visibility_scope_in_defaults_public():
    v = VisibilityScopeIn()
    assert v.mode == "public"
    assert v.roles == []
    assert v.user_ids == []


def test_visibility_scope_in_restricted_roundtrip():
    v = VisibilityScopeIn(mode="restricted", roles=["dev"], user_ids=["u1"])
    assert v.model_dump() == {
        "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
    }


def test_visibility_scope_in_rejects_unknown_mode():
    with pytest.raises(Exception):
        VisibilityScopeIn(mode="weird")


def test_category_visibility_in_defaults_public():
    c = CategoryVisibilityIn()
    assert c.mode == "public"
    assert c.authorized_roles == []


def test_category_visibility_in_restricted():
    c = CategoryVisibilityIn(mode="restricted", authorized_roles=["dev"])
    assert c.model_dump() == {
        "mode": "restricted", "authorized_roles": ["dev"],
    }


def test_create_matter_in_accepts_visibility_fields():
    payload = {
        "category": "Pivot", "title": "T", "type": "think",
        "summary": "s", "body": "b",
        "visibility": {"mode": "restricted", "roles": ["dev"], "user_ids": []},
        "new_category_visibility": {"mode": "public", "authorized_roles": []},
    }
    m = CreateMatterIn.model_validate(payload)
    assert m.visibility is not None
    assert m.visibility.mode == "restricted"
    assert m.visibility.roles == ["dev"]
    assert m.new_category_visibility is not None
    assert m.new_category_visibility.mode == "public"


def test_create_matter_in_visibility_default_is_none():
    m = CreateMatterIn.model_validate({
        "category": "Pivot", "title": "T", "type": "think",
        "summary": "s", "body": "b",
    })
    assert m.visibility is None
    assert m.new_category_visibility is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "visibility_scope_in or category_visibility_in or visibility_fields or visibility_default_is_none" -v`

Expected: ImportError / 7 个测试 FAIL（schemas.py 还没定义这些模型）。

- [ ] **Step 3: 在 `server/mcp/schemas.py` 加子模型**

在文件顶部把 `Literal` 已经 import 过了，确认 `Literal` 在 import 里；如果没有就加上。

在 `# ---------- list_matters ----------` 区段**之前**追加（也就是 `MatterListItem` 之前）：

```python
# ---------- visibility (shared) ----------


class VisibilityScopeIn(BaseModel):
    """Matter-level visibility scope, mirroring the backend's wire format.

    Empty restricted scope (no roles, no user_ids) is allowed at this layer —
    the backend rejects it implicitly via `visibility_excludes_required_user`
    when the creator/owner can't be admitted, and we surface that 422 verbatim.
    """

    mode: Literal["public", "restricted"] = "public"
    roles: list[str] = Field(
        default_factory=list,
        description="Role names allowed to see the matter when mode='restricted'.",
    )
    user_ids: list[str] = Field(
        default_factory=list,
        description="User open_ids individually allowed when mode='restricted'.",
    )


class CategoryVisibilityIn(BaseModel):
    """Category-level visibility, only used at category creation time."""

    mode: Literal["public", "restricted"] = "public"
    authorized_roles: list[str] = Field(
        default_factory=list,
        description="Role names allowed to see this category when mode='restricted'.",
    )
```

- [ ] **Step 4: 在 `CreateMatterIn` 末尾加 `visibility` / `new_category_visibility` 字段**

定位 `CreateMatterIn` 类（约在 `mentions` 字段后），在 `mentions` 字段定义之后追加：

```python
    visibility: VisibilityScopeIn | None = Field(
        default=None,
        description=(
            "OPTIONAL matter-level visibility. PROTOCOL: only set when the "
            "user EXPLICITLY says to limit access (e.g. '只给 dev 看', "
            "'限制可见范围', '不要让 X 看到'); otherwise leave null and the "
            "backend defaults to public. Do NOT infer from the body text. "
            "Before setting `mode='restricted'`, call `list_visibility_options` "
            "to fetch the candidate roles/users for the target category, then "
            "echo the resolved scope back to the user for confirmation."
        ),
    )
    new_category_visibility: CategoryVisibilityIn | None = Field(
        default=None,
        description=(
            "OPTIONAL category-level visibility, ONLY needed when (a) the "
            "`category` does not yet exist AND (b) the matter `visibility` is "
            "restricted. Backend returns 422 `missing_category_visibility` "
            "if absent in that scenario. Leave null in every other case."
        ),
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "visibility_scope_in or category_visibility_in or visibility_fields or visibility_default_is_none" -v`

Expected: 7 PASS。

- [ ] **Step 6: 跑全文件测试，确保旧用例没破**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`

Expected: 全部 PASS（应该是 35 + 7 = 42 个测试或类似）。

- [ ] **Step 7: 提交**

```bash
git add server/mcp/schemas.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): add visibility schemas to CreateMatterIn"
```

---

## Task 2: tool_create_matter 把 visibility / new_category_visibility 透传到后端

**Files:**
- Modify: `server/mcp/tools.py:441-497` (`tool_create_matter`)
- Test: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: 写"受限可见范围被透传"的失败测试**

在 `server/tests/test_mcp_tools.py` 现有 `test_create_matter_*` 测试旁追加：

```python
def test_create_matter_visibility_passthrough():
    """Restricted visibility object lands in the api body verbatim."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    out = tool_create_matter(
        {
            "category": "Pivot", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["visibility"] == {
        "mode": "restricted", "roles": ["dev"], "user_ids": ["u1"],
    }
    assert "new_category_visibility" not in sent_body
    assert out["ok"] is True


def test_create_matter_new_category_visibility_passthrough():
    """Both visibility and new_category_visibility ride along when both set."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    tool_create_matter(
        {
            "category": "NewCat", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": [],
            },
            "new_category_visibility": {
                "mode": "restricted", "authorized_roles": ["dev"],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert sent_body["new_category_visibility"] == {
        "mode": "restricted", "authorized_roles": ["dev"],
    }


def test_create_matter_omits_visibility_keys_when_unset():
    """No visibility key is sent when caller doesn't set it — backend defaults to public."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "matter": {"id": "m1", "title": "T"},
        "matter_id": "m1",
        "initial_timeline_item": {"file": "001.md"},
        "file": "001.md",
    }
    tool_create_matter(
        {
            "category": "Pivot", "title": "T", "type": "think",
            "summary": "s", "body": "b",
        },
        client,
        "https://pivot.enclaws.ai",
    )
    sent_body = client.post_matter.call_args[0][0]
    assert "visibility" not in sent_body
    assert "new_category_visibility" not in sent_body


def test_create_matter_surfaces_missing_category_visibility_422():
    """Backend's missing_category_visibility flows through as `errors` payload."""
    client = MagicMock(spec=MatterApiClient)
    client.post_matter.return_value = {
        "__validation_errors__": {
            "detail": {"code": "missing_category_visibility"},
        },
    }
    out = tool_create_matter(
        {
            "category": "NewCat", "title": "T", "type": "think",
            "summary": "s", "body": "b",
            "visibility": {
                "mode": "restricted", "roles": ["dev"], "user_ids": [],
            },
        },
        client,
        "https://pivot.enclaws.ai",
    )
    assert "errors" in out
    assert out["errors"]["detail"]["code"] == "missing_category_visibility"
```

- [ ] **Step 2: 跑测试确认前 3 个测试失败、第 4 个已经过（422 通道现成）**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "visibility_passthrough or new_category_visibility_passthrough or omits_visibility_keys or missing_category_visibility_422" -v`

Expected:
- `test_create_matter_visibility_passthrough` FAIL（visibility 还没写到 api_body）
- `test_create_matter_new_category_visibility_passthrough` FAIL
- `test_create_matter_omits_visibility_keys_when_unset` 可能 PASS（默认就没有这俩 key）
- `test_create_matter_surfaces_missing_category_visibility_422` PASS（`__validation_errors__` 通道现成）

- [ ] **Step 3: 在 `tool_create_matter` 里把字段透传**

打开 `server/mcp/tools.py`，找到 `tool_create_matter` 函数（约 441 行）。在已有的 `if input_.owner is not None` / `if input_.mentions is not None` 块之后，在 `resp = client.post_matter(api_body)` **之前**，追加：

```python
    if input_.visibility is not None:
        api_body["visibility"] = input_.visibility.model_dump()
    if input_.new_category_visibility is not None:
        api_body["new_category_visibility"] = input_.new_category_visibility.model_dump()
```

注意：`api_body` 当前的结构是 `{category, title, initial_file: {...}}` —— `visibility` 和 `new_category_visibility` 是顶级字段（与 `category` 并列），不是塞到 `initial_file` 里。

- [ ] **Step 4: 跑测试全过**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "visibility" -v`

Expected: 全部 PASS。

- [ ] **Step 5: 跑全文件测试，确保 mentions / owner 等老路径没破**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add server/mcp/tools.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): pass visibility through tool_create_matter"
```

---

## Task 3: MatterApiClient + tool_list_visibility_options

**Files:**
- Modify: `server/mcp/schemas.py` (新增 In/Out)
- Modify: `server/mcp/tools.py` (新增 client method + tool 函数)
- Test: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: 写 `tool_list_visibility_options` 的失败测试**

在 `server/tests/test_mcp_tools.py` 末尾追加：

```python
from server.mcp.tools import tool_list_visibility_options


def test_list_visibility_options_passes_category_to_client():
    client = MagicMock(spec=MatterApiClient)
    client.get_visibility_options.return_value = {
        "all": {"label": "全部用户", "value": "public"},
        "roles": [
            {"role": "dev", "name": "Dev", "label": "Dev",
             "users": [{"id": "u1", "display_name": "Alice",
                        "pinyin": "alice", "avatar_url": ""}]},
        ],
        "users": [
            {"id": "u1", "display_name": "Alice",
             "pinyin": "alice", "avatar_url": ""},
        ],
    }
    out = tool_list_visibility_options({"category": "Pivot"}, client)
    client.get_visibility_options.assert_called_once_with(category="Pivot")
    assert out["roles"][0]["role"] == "dev"
    assert out["users"][0]["pinyin"] == "alice"


def test_list_visibility_options_no_category():
    client = MagicMock(spec=MatterApiClient)
    client.get_visibility_options.return_value = {
        "all": {"label": "全部用户", "value": "public"},
        "roles": [], "users": [],
    }
    tool_list_visibility_options({}, client)
    client.get_visibility_options.assert_called_once_with(category=None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "list_visibility_options" -v`

Expected: ImportError 或 AttributeError（`tool_list_visibility_options` / `client.get_visibility_options` 都没定义）。

- [ ] **Step 3: 在 `server/mcp/schemas.py` 末尾加 In/Out 模型**

```python
# ---------- list_visibility_options ----------


class ListVisibilityOptionsIn(BaseModel):
    category: str | None = Field(
        default=None,
        description=(
            "OPTIONAL category id. When provided AND the category is "
            "restricted, the returned roles/users list is filtered to only "
            "what's compatible with that category's authorized_roles. Leave "
            "null to list everything visible to the calling user."
        ),
    )


class ListVisibilityOptionsOut(BaseModel):
    """Mirrors backend `/api/visibility-options` response."""

    all: dict
    roles: list[dict]
    users: list[dict]
```

- [ ] **Step 4: 在 `server/mcp/tools.py` 的 `MatterApiClient` 类里加 `get_visibility_options` 方法**

定位到 `MatterApiClient.post_comment` 之后（类的末尾），追加：

```python
    def get_visibility_options(self, category: str | None = None) -> dict:
        """GET /api/visibility-options?category=... — candidate roles + users.

        Wraps the same endpoint Web's VisibilityScopePicker uses. Returns the
        full payload (`all`, `roles`, `users`) verbatim so the MCP tool can
        relay it without reshaping.
        """
        params: dict[str, str] = {}
        if category:
            params["category"] = category
        resp = self._client.get(
            f"{self._base}/api/visibility-options",
            headers=self._headers,
            params=params,
        )
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        if resp.status_code == 403:
            raise ToolError(403, "forbidden")
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 5: 在 `server/mcp/tools.py` 顶部 import 区追加新 schema**

把现有 import 改成（找 `from server.mcp.schemas import (...)` 那块）：

```python
from server.mcp.schemas import (
    AddCommentIn,
    AddCommentOut,
    AvailableTransition,
    CategoryVisibilityIn,
    CreateFileIn,
    CreateFileOut,
    CreateMatterIn,
    CreateMatterOut,
    FileContent,
    GetMatterIn,
    GetMatterOut,
    ListMattersIn,
    ListMattersOut,
    ListVisibilityOptionsIn,
    ListVisibilityOptionsOut,
    MatterListItem,
    MatterSnapshot,
    ReadFilesIn,
    ReadFilesOut,
    ResolveContextIn,
    ResolveContextOut,
    TimelineItem,
    VisibilityScopeIn,
)
```

注：`CategoryVisibilityIn` / `VisibilityScopeIn` 在 Task 2 已经被 tool_create_matter 间接用上（通过 model_dump），import 这里加上是为了显式可读。

- [ ] **Step 6: 在 `server/mcp/tools.py` 末尾添加 `tool_list_visibility_options`**

```python
def tool_list_visibility_options(payload: dict, client: MatterApiClient) -> dict:
    """List candidate roles/users for the visibility picker, optionally
    scoped to a category. Wraps GET /api/visibility-options."""
    input_ = ListVisibilityOptionsIn.model_validate(payload)
    raw = client.get_visibility_options(category=input_.category)
    return ListVisibilityOptionsOut(
        all=raw.get("all") or {},
        roles=raw.get("roles") or [],
        users=raw.get("users") or [],
    ).model_dump(mode="json")
```

- [ ] **Step 7: 跑测试通过**

Run: `python -m pytest server/tests/test_mcp_tools.py -k "list_visibility_options" -v`

Expected: 2 PASS。

- [ ] **Step 8: 跑全文件测试**

Run: `python -m pytest server/tests/test_mcp_tools.py -q`

Expected: 全部 PASS。

- [ ] **Step 9: 提交**

```bash
git add server/mcp/schemas.py server/mcp/tools.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): add list_visibility_options tool"
```

---

## Task 4: 在 MCP server 注册 list_visibility_options

**Files:**
- Modify: `server/mcp/server.py:21-40` (imports)
- Modify: `server/mcp/server.py:60-210` (`_list_tools`)
- Modify: `server/mcp/server.py:212-253` (`_call_tool` dispatch)

- [ ] **Step 1: 在 server.py 的 imports 里加新符号**

把 `from server.mcp.schemas import (...)` 块改成：

```python
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
```

把 `from server.mcp.tools import (...)` 块改成：

```python
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
```

- [ ] **Step 2: 在 `_list_tools` 里追加新 Tool**

在 `_list_tools` 返回的 list 末尾、`add_comment` Tool 之后追加：

```python
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
```

- [ ] **Step 3: 在 `_call_tool` 分发里加分支**

在 `elif name == "add_comment":` 之后、`else:` 之前追加：

```python
            elif name == "list_visibility_options":
                out = await anyio.to_thread.run_sync(
                    partial(tool_list_visibility_options, arguments, client)
                )
```

- [ ] **Step 4: 跑现有 e2e / server 注册相关测试**

Run: `python -m pytest server/tests/test_mcp_e2e.py -q`

Expected: 该测试列举工具时已有断言（`assert {"resolve_context", "list_matters", ...}`）会发现新工具，需要修改测试 —— 见 Step 5。

- [ ] **Step 5: 修 `test_mcp_e2e.py` 的工具清单断言**

打开 `server/tests/test_mcp_e2e.py`，找到 `assert {"resolve_context", "list_matters", "get_matter", "read_files",` 那段（约 585-589 行），把 `list_visibility_options` 加进集合。同样找类似的 sorted/list 断言一并加上。

- [ ] **Step 6: 跑 e2e 测试通过**

Run: `python -m pytest server/tests/test_mcp_e2e.py -q`

Expected: 全部 PASS。

- [ ] **Step 7: 跑全 server 测试套兜底**

Run: `python -m pytest server/tests/ -q`

Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
git add server/mcp/server.py server/tests/test_mcp_e2e.py
git commit -m "feat(mcp): register list_visibility_options tool"
```

---

## Task 5: 更新 create_matter 工具描述 + 顶层 INSTRUCTIONS

**Files:**
- Modify: `server/mcp/server.py:158-186` (`create_matter` Tool description)
- Modify: `server/mcp/instructions.py:31-46` (能力清单)

- [ ] **Step 1: 在 `create_matter` Tool 的 description 里加 PROTOCOL (visibility) 段**

定位 `Tool(name="create_matter", ...)`，在 description 字符串内 `PROTOCOL (mentions): ...` 段**之后**追加新段（注意保持字符串拼接的反斜杠/续行风格一致）：

```python
                    "PROTOCOL (visibility): The `visibility` and "
                    "`new_category_visibility` fields are OPTIONAL. Default to "
                    "leaving them null — the matter goes public, matching the "
                    "current behavior. Set them ONLY when the user EXPLICITLY "
                    "asks to restrict access ('只给 dev 看', 'limit to ops', "
                    "'不要让 X 看到'). When the user does ask for restriction, "
                    "first call `list_visibility_options` with the same "
                    "`category` to fetch valid role / user candidates, then "
                    "echo the resolved scope (with display names) back to the "
                    "user for confirmation, then call create_matter. If the "
                    "category does not yet exist AND the matter is restricted, "
                    "you MUST also include `new_category_visibility`; the "
                    "backend rejects with 422 `missing_category_visibility` "
                    "otherwise. Never infer restriction from the body text."
```

- [ ] **Step 2: 在 `server/mcp/instructions.py` 的能力清单里加一行**

定位 `INSTRUCTIONS = """\` 内的能力清单（`- create_matter — 新建 matter ...` 那段附近），在 `- add_comment` 行之后追加：

```python
- list_visibility_options — 列可见范围候选角色 / 成员（"哪些角色能选" / \
"看下这个分类能限制给谁"）
```

同时把上头【7 个能力 + 用户该说什么】的"7"改成"8"：

```python
【8 个能力 + 用户该说什么】
```

- [ ] **Step 3: 跑全 server 测试套兜底（确认描述变化没破任何 snapshot 类断言）**

Run: `python -m pytest server/tests/ -q`

Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add server/mcp/server.py server/mcp/instructions.py
git commit -m "docs(mcp): create_matter visibility protocol + INSTRUCTIONS"
```

---

## Self-Review

**1. Spec coverage:**

需求文档章节 → 任务对应：
- 需求 1（`create_matter` 加 visibility 参数）→ Task 1 + Task 2
- 需求 2（`create_matter` 加 new_category_visibility 参数）→ Task 1 + Task 2
- 需求 3（新增 `list_visibility_options` 工具）→ Task 3 + Task 4
- 需求 4（三个 422 错误码透传）→ Task 2 Step 1 第 4 个测试覆盖（其余两个 `visibility_scope_exceeds_category` / `visibility_excludes_required_user` 走完全相同的 `__validation_errors__` 通道，不需要额外代码；如需也加测试可在 Task 2 末尾扩展）
- AI 协议补充 → Task 5
- 完成判据"实测落到 index.yaml" → 不在自动化测试范畴，作为人工验收项保留（实施完后由 PR 描述指引验证）

无 spec 缺口。

**2. Placeholder scan:**

通读：所有 step 都给了具体代码块或具体命令；没有 "TBD" / "implement later" / "similar to Task N" 这类占位。命令、import 路径、文件位置都是确定的。✅

**3. Type / 命名一致性:**

- `VisibilityScopeIn` / `CategoryVisibilityIn` / `ListVisibilityOptionsIn` / `ListVisibilityOptionsOut` 在 Task 1 / 3 定义；Task 4 在 server.py 引用一致。
- `tool_list_visibility_options` 在 Task 3 定义、Task 4 引用；签名 `(payload, client)` 一致。
- `MatterApiClient.get_visibility_options(category=...)` 在 Task 3 定义并按 keyword 参数被 `tool_list_visibility_options` 调用，测试也按 keyword 断言。
- 后端 wire format 字段名（`mode` / `roles` / `user_ids` / `authorized_roles`）和后端 `VisibilityScope.from_dict` / `CategoryVisibilityScope.from_dict` 一致。

无不一致。

---

## 验收（人工）

实施完成后：

1. 重启 MCP server。
2. 在 AI 客户端发"在 Pivot 分类下新开一个 matter，标题 X，**只给 dev 看**"。
3. AI 应：先调 `list_visibility_options(category="Pivot")` 拿候选 → 在对话里念出受限范围 → 用户确认 → 调 `create_matter` 带 `visibility={mode:"restricted",roles:["dev"],...}` → 成功。
4. 在 Web 详情页打开新 matter → 详情接口返回的 `matter.visibility` 应是 `{mode:"restricted",roles:["dev"],...}`，对应 `index/<id>.index.yaml` 已落盘。
5. 反向验证：让 AI"只给某个不属于该分类授权角色的 role 看" → 应收到 `visibility_scope_exceeds_category` 422，AI 把错误转给用户。
