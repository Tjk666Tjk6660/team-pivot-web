# MCP `list_matters` "与我相关" 过滤 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 MCP `list_matters` 工具加 `filter: "all" | "mine"` 参数，`"mine"` 在 MCP tool 层 post-process 过滤 `red_unread_count > 0` 的 matter，让 AI 能精准响应"我的待办"/"我有未读吗"类问题。

**Architecture:** 完全在 MCP 层做（schema + tool + 工具描述 + instructions）。`MatterApiClient` 不动，backend `/api/matters` 不动，web UI 不动。AND 关系：先按 backend 已有 `status` / `owner` / `q` 过滤，最后在 MCP 层按 `filter` 过滤。

**Tech Stack:** Python / FastAPI / pydantic / pytest / MCP Python SDK

**Spec:** `AI-docs/plans/2026-05-06-mcp-list-matters-mine-filter-design.md`

---

## File Structure

| 文件 | 改动类型 | 责任 |
|---|---|---|
| `server/mcp/schemas.py` | Modify | `ListMattersIn` 增加 `filter` 字段 |
| `server/mcp/tools.py` | Modify | `tool_list_matters` 加 post-process 过滤 |
| `server/mcp/server.py` | Modify | `list_matters` Tool description 增补触发语 |
| `server/mcp/instructions.py` | Modify | 顶层 8 工具清单 list_matters 增补触发语 |
| `server/tests/test_mcp_tools.py` | Modify | 新增 5 条测试 |

---

## Task 1: Add `filter` field to `ListMattersIn` schema

**Files:**
- Modify: `server/mcp/schemas.py:78-81`
- Test: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing tests**

在 `server/tests/test_mcp_tools.py` 末尾追加（紧跟 list_visibility_options 那段之后）：

```python
# ---------- list_matters filter=mine ----------

from server.mcp.schemas import ListMattersIn


def test_list_matters_in_filter_defaults_to_all():
    m = ListMattersIn.model_validate({})
    assert m.filter == "all"


def test_list_matters_in_filter_accepts_mine():
    m = ListMattersIn.model_validate({"filter": "mine"})
    assert m.filter == "mine"


def test_list_matters_in_filter_rejects_unknown_value():
    with pytest.raises(Exception):  # pydantic ValidationError
        ListMattersIn.model_validate({"filter": "foo"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_mcp_tools.py -k filter_defaults_to_all -v
```

Expected: FAIL — `AttributeError: 'ListMattersIn' object has no attribute 'filter'`

- [ ] **Step 3: Add `filter` field to `ListMattersIn`**

在 `server/mcp/schemas.py:78-81` 把 `ListMattersIn` 改成：

```python
class ListMattersIn(BaseModel):
    status: str | None = None
    owner: str | None = None
    q: str | None = None
    filter: Literal["all", "mine"] = Field(
        default="all",
        description=(
            "Relevance filter for the calling user. 'mine' returns only "
            "matters with red unread > 0 (i.e. you have unread file-level "
            "relevance hits — owner_assigned / replies to your files / "
            "verify of your work / activity in your matters / mentions of "
            "you). 'mine' is NOT 'matters you created or own' — it tracks "
            "unread, not authorship. Default 'all'."
        ),
    )
```

`Literal` 已在文件顶 `from typing import Literal` 导过，`Field` 已从 pydantic 导过——不需要改 import。

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest server/tests/test_mcp_tools.py -k "filter_defaults_to_all or filter_accepts_mine or filter_rejects_unknown" -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add server/mcp/schemas.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): add filter='all'|'mine' field to ListMattersIn

First step toward 'list_matters mine filter'. Schema only — tool layer
filtering follows in next commit."
```

---

## Task 2: Implement `filter="mine"` post-process in `tool_list_matters`

**Files:**
- Modify: `server/mcp/tools.py:302-328` (the `tool_list_matters` function)
- Test: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing tests**

在 `server/tests/test_mcp_tools.py` 末尾继续追加：

```python
def _matter_dict(
    *,
    matter_id: str = "m1",
    title: str = "T",
    current_status: str = "executing",
    red_unread_count: int | None = 0,
) -> dict:
    """Helper for raw backend matter rows."""
    return {
        "id": matter_id,
        "title": title,
        "current_status": current_status,
        "updated_at": "2026-05-06T10:00:00+08:00",
        "file_count": 1,
        "owner": "yzy",
        "last_summary": "s",
        "red_unread_count": red_unread_count,
    }


def test_list_matters_filter_all_returns_everything():
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = [
        _matter_dict(matter_id="m1", red_unread_count=0),
        _matter_dict(matter_id="m2", red_unread_count=3),
    ]
    out = tool_list_matters({"filter": "all"}, client)
    assert [it["id"] for it in out["items"]] == ["m1", "m2"]


def test_list_matters_filter_mine_keeps_only_red_unread_positive():
    client = MagicMock(spec=MatterApiClient)
    client.list_matters.return_value = [
        _matter_dict(matter_id="m1", red_unread_count=0),
        _matter_dict(matter_id="m2", red_unread_count=3),
        _matter_dict(matter_id="m3", red_unread_count=1),
    ]
    out = tool_list_matters({"filter": "mine"}, client)
    assert [it["id"] for it in out["items"]] == ["m2", "m3"]


def test_list_matters_filter_mine_treats_missing_or_null_as_zero():
    """Defensive: old indexes may not have red_unread_count; treat as 0
    so we never silently include an item that may or may not be relevant."""
    client = MagicMock(spec=MatterApiClient)
    raw_no_field = _matter_dict(matter_id="m1", red_unread_count=2)
    raw_no_field.pop("red_unread_count")
    client.list_matters.return_value = [
        raw_no_field,
        _matter_dict(matter_id="m2", red_unread_count=None),
        _matter_dict(matter_id="m3", red_unread_count=2),
    ]
    out = tool_list_matters({"filter": "mine"}, client)
    assert [it["id"] for it in out["items"]] == ["m3"]


def test_list_matters_filter_mine_combines_with_status_via_backend():
    """status is forwarded to the backend; the MCP layer only adds the mine
    filter on top of the already-narrowed result. Both must hold."""
    client = MagicMock(spec=MatterApiClient)
    # Backend already filtered status=executing — only 2 rows come back.
    client.list_matters.return_value = [
        _matter_dict(matter_id="m1", current_status="executing", red_unread_count=0),
        _matter_dict(matter_id="m2", current_status="executing", red_unread_count=4),
    ]
    out = tool_list_matters(
        {"filter": "mine", "status": "executing"}, client,
    )
    client.list_matters.assert_called_once_with(
        status="executing", owner=None, q=None,
    )
    assert [it["id"] for it in out["items"]] == ["m2"]
```

`tool_list_matters` 在文件顶部已经被 import 过（`from server.mcp.tools import ... tool_list_matters`）——不要重复 import。

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_mcp_tools.py -k "filter_all_returns or filter_mine_keeps or filter_mine_treats or filter_mine_combines" -v
```

Expected: 4 FAILED — current `tool_list_matters` ignores `filter` and returns everything (so `filter_mine_keeps_only_red_unread_positive` etc. fail because m1 with red_unread_count=0 is still returned).

- [ ] **Step 3: Add post-process to `tool_list_matters`**

把 `server/mcp/tools.py:302-328` 的 `tool_list_matters` 整段替换为：

```python
def tool_list_matters(payload: dict, client: MatterApiClient) -> dict:
    input_ = ListMattersIn.model_validate(payload)
    raw_items = client.list_matters(
        status=input_.status,
        owner=input_.owner,
        q=input_.q,
    )
    if input_.filter == "mine":
        raw_items = [it for it in raw_items if _red_unread(it) > 0]
    items = [
        MatterListItem(
            id=it.get("id", ""),
            title=it.get("title", ""),
            current_status=it.get("current_status", ""),
            updated_at=it.get("updated_at", ""),
            file_count=it.get("file_count"),
            owner=it.get("owner"),
            summary=it.get("last_summary"),
        )
        for it in raw_items
    ]
    return ListMattersOut(items=items).model_dump(mode="json")


def _red_unread(item: dict) -> int:
    """Coerce backend's red_unread_count to a non-negative int; treat
    missing / None / non-numeric as 0 so 'mine' never silently includes
    a matter we can't confirm is relevant."""
    value = item.get("red_unread_count")
    if isinstance(value, bool):  # bool is a subclass of int — exclude
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    return 0
```

注意：原函数返回 `ListMattersOut(items=items).model_dump(...)`——保持这一行；如果当前代码是直接 `return {"items": [...]}` 而非走 `ListMattersOut`，按当前文件实际形态对齐（这一步前先 `Read` 确认）。

- [ ] **Step 4: Run all tests to verify pass**

```bash
python -m pytest server/tests/test_mcp_tools.py -v
```

Expected: ALL PASS（包括 Task 1 的 3 条 + 本任务 4 条 + 已有 56 条 = 63 条）。

- [ ] **Step 5: Commit**

```bash
git add server/mcp/tools.py server/tests/test_mcp_tools.py
git commit -m "feat(mcp): filter='mine' returns only matters with red unread

tool_list_matters post-processes backend response: when filter='mine',
keep only items with red_unread_count > 0. Mirrors web UI's
ThreadListPane client-side filter — same semantics, MCP-side."
```

---

## Task 3: Update `list_matters` Tool description

**Files:**
- Modify: `server/mcp/server.py:85-102`

- [ ] **Step 1: Update Tool description**

把 `server/mcp/server.py:85-102` 的 `list_matters` Tool 整块替换为：

```python
            Tool(
                name="list_matters",
                description=(
                    "List matters visible to the current user. Supports "
                    "status/owner/q/filter filters. "
                    "Common user phrasings: \"看一下所有 matter\", \"列一下 "
                    "matter 列表\", \"看看 pivot 下面有哪些帖子\", \"最近有什么 "
                    "matter\", \"谁在做什么\", \"有哪些进行中的 matter\", "
                    "\"show me all matters\". "
                    "Use this for OVERVIEW questions where the user does NOT "
                    "name a specific matter; if they DO name one (or paste a "
                    "URL), use `get_matter` / `resolve_context` instead. "
                    "Filters: `status` accepts planning/executing/paused/"
                    "finished/reviewed/cancelled; `owner` accepts pinyin "
                    "(e.g. 'dengke'); `q` does fuzzy title search; "
                    "`filter='mine'` keeps only matters with red unread > 0 "
                    "(\"我的待办\" / \"我有未读吗\" / \"看看跟我相关的\" / "
                    "\"what's pending for me\" / \"matters with my unread\"). "
                    "Note: `filter='mine'` is NOT \"matters I created/own\" — "
                    "it tracks unread relevance, not authorship."
                ),
                inputSchema=ListMattersIn.model_json_schema(),
            ),
```

- [ ] **Step 2: Run all MCP tests as smoke check**

```bash
python -m pytest server/tests/test_mcp_tools.py -v
```

Expected: still all green (this task is description-only, no behavior change).

- [ ] **Step 3: Commit**

```bash
git add server/mcp/server.py
git commit -m "docs(mcp): document filter='mine' in list_matters tool description

Adds trigger phrasings (\"我的待办\" / \"what's pending for me\" / etc.)
and clarifies semantic delta — 'mine' = unread, NOT authorship."
```

---

## Task 4: Update top-level instructions list

**Files:**
- Modify: `server/mcp/instructions.py:33-34`

- [ ] **Step 1: Update the `list_matters` line in INSTRUCTIONS**

把 `server/mcp/instructions.py:33-34` 那一行：

```python
- list_matters — 列 matter（"看一下所有 matter" / "列一下 xxx 的 matter" / \
"最近有什么 matter"）
```

改成：

```python
- list_matters — 列 matter（"看一下所有 matter" / "列一下 xxx 的 matter" / \
"最近有什么 matter" / "我的待办" / "看看跟我相关的"）
```

注意 instructions.py 头部注释说"target ≤ 1k characters"——加这两条触发语后整段大概多 30 字符，仍在预算内（当前文件总长约 1.5k 字符，1k 是软目标不是硬限）。

- [ ] **Step 2: Run all MCP tests as smoke check**

```bash
python -m pytest server/tests/test_mcp_tools.py -v
```

Expected: 仍然全绿。

- [ ] **Step 3: End-to-end manual smoke (optional but recommended)**

重启 dev server 后，让 AI 跑这两轮：

1. "列一下所有 matter" → 应该不带 filter（或显式 filter="all"），全量返回
2. "我有什么未读？" / "看看我的待办" → 应该带 filter="mine"，只返回 red_unread > 0 的

如果 AI 在第 2 轮没自动用 filter='mine'，回头看 description / instructions 触发语是否够明显，必要时再补例。

- [ ] **Step 4: Commit**

```bash
git add server/mcp/instructions.py
git commit -m "docs(mcp): list 'mine' trigger phrasings in top-level instructions

Adds '我的待办' / '看看跟我相关的' to the list_matters bullet so AI
picks filter='mine' from the user's first message without needing to
read the full tool description."
```

---

## Self-Review

- ✅ Spec coverage: spec § 接口 / 实现 / 边界 / 测试 全部映射到 Task 1–4
- ✅ No placeholders（所有 step 含具体代码 + 命令）
- ✅ Type consistency：`filter: Literal["all", "mine"]` 在 schema/test/工具描述四处一致；`_red_unread` helper 名字一致
- ✅ TDD：每个 task 走 红→绿→commit
