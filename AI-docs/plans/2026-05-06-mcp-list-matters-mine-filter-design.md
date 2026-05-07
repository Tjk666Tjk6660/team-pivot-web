# MCP `list_matters` — 加 "与我相关" 过滤

**状态**：待开始
**范围**：MCP tool 层；不动 backend `/api/matters`、不动 web UI

## 目标

让 AI 在用户问"我的待办"/"看看跟我相关的"/"我有未读吗"时，能精准只返回与调用者有红点未读的 matter——而不是把全量列表丢给用户再让人眼挑。

## 现状

- `/api/matters` 已经返回 `red_unread_count`、`gray_unread_count` 字段（per-user，按调用者算）
- web UI 在 `web/src/components/ThreadListPane.tsx:59-63` 用 client-side 过滤 `red_unread_count > 0` 实现"与我相关"
- 用户偏好持久化在 `/api/me/preferences` 的 `matter_list_filter`（"all" | "mine"）
- MCP `list_matters` 当前只接受 `status` / `owner` / `q`，没有相关性过滤

## 接口

`ListMattersIn` 增加一个字段：

| 字段 | 类型 | 缺省 | 说明 |
|---|---|---|---|
| `filter` | `Literal["all", "mine"]` | `"all"` | `"mine"` 只返回 `red_unread_count > 0` 的 matter；`"all"` 等同于不传 |

跟现有 `status` / `owner` / `q` 是 **AND** 关系。先走 backend 既有过滤，再在 MCP 层做 `filter` 过滤。

## 实现

| 模块 | 改动 |
|---|---|
| `server/mcp/schemas.py` `ListMattersIn` | 加 `filter: Literal["all", "mine"] = "all"` 字段；description 写清语义 ≠ "我创建/owner 的 matter" |
| `server/mcp/tools.py` `tool_list_matters` | 拉完 backend `client.list_matters(...)` 后，`if input_.filter == "mine": items = [it for it in items if (it.get("red_unread_count") or 0) > 0]` |
| `server/mcp/server.py` `list_matters` Tool description | 增补触发语示例："我的待办" / "我有未读吗" / "看看跟我相关的" / "what's pending for me" |
| `server/mcp/instructions.py` 顶层 8 工具清单 | `list_matters` 那条触发语带上"我的待办" / "有什么我需要看的" |
| `MatterApiClient.list_matters` | **不改** |

数据流：

```
AI → MCP tool list_matters({filter:"mine", status:"executing"})
   → MatterApiClient.list_matters(status="executing")  ← backend 只看 status/owner/q
   → backend /api/matters?status=executing 返回带 red_unread_count 的列表
   → MCP tool 层用 filter="mine" 二次过滤掉 red_unread_count <= 0 的
   → 返回给 AI
```

## 边界与错误处理

- `red_unread_count` 缺失 / `None` / 非数字 → 当 0，那条 matter 被 `filter="mine"` 过滤掉（保守不算 mine）
- 旧索引没这字段时同上，不报错
- `filter` 非 "all"/"mine" → pydantic `Literal` 校验直接 422
- 不引入新的 `ToolError` 码

## 测试

新增到 `server/tests/test_mcp_tools.py`：

1. `filter="all"` 或缺省 → 全量透传，跟现状行为一致
2. `filter="mine"` → 只返回 `red_unread_count > 0` 的
3. `filter="mine"` + `red_unread_count` 缺失/`None` → 那条被滤掉
4. `filter="mine"` + `status="executing"` → AND 生效，二者都满足才留
5. `filter="foo"` → pydantic ValidationError

## 不在范围

- 不引入新的"matter-level relevance reason"概念（基于 file relevance 聚合那种）。如果以后要升级语义，是 `filter` 加新枚举值的扩展，不破 API
- 不动 web UI 的 client-side 过滤逻辑
- 不动 `/api/matters` 后端
- 不持久化 AI 端的 filter 偏好（每次 call 显式传）
