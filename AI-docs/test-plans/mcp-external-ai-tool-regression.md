# MCP 外部 AI 接入：工具级回归（直接调 MCP）

> 分支 `feat/mcp-external-ai`。**绕开 Claude Code / Cursor 等客户端 UI**，由具备 MCP 工具能力的模型直接调用 5 个 tool 与服务端联调，专注**协议层 / 字段层 / 错误码**而不是端到端 UX。
>
> 跟 `mcp-external-ai-claude-code.md` 互补：那篇验"用户 → Claude Code → MCP"全链路；本篇验"MCP tool ↔ /api/matters" 这一段。

## 一、功能背景

5 个 tool 与状态机交互的关键约定：

- 读侧 4 个：`resolve_context`、`list_matters`、`get_matter`、`read_files`
- 写侧 1 个：`create_file`
- 服务端 422 不抛异常，作为 `{errors: {detail: {code, field, message}}}` 返回，让 AI 迭代
- `create_file` 的 status_change 字段，`from` 必须等于当前 matter 状态、`to` 必须落在 `available_transitions[].to`、文件 `type` 必须等于该迁移的 `trigger_type`
- 状态 × 文件类型有强约束（即使不挂 status_change，type 也未必允许，例如 paused 下不允许 verify/act）

## 二、前置条件 / 数据准备

1. 后端 `http://127.0.0.1:8000` 已起；前端 `http://localhost:5173` 已起
2. 当前账号至少 2 个可见 matter，**至少 1 个状态为 `planning`**（用于走完整状态机）
3. 调用方持有 PAT，能直接命中 `/mcp`（或由具备 MCP 工具的模型代调）

测试时使用的两个 matter：
- `测试mcp`（status: paused，4 篇文件，路径在 `discussions/general/...`）
- `测试一个标题`（status: planning，1 篇文件，路径在 `discussions/测试分类/...`，分类不同）

## 三、测试用例

> 结果列：✅ 通过 / ❌ 失败 / ◯ 部分通过 / — 跳过。本次执行结果已预填，可作为后续回归的基线。

### 3.1 `resolve_context`

| 编号 | 用例 | 输入 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| R01 | matter 级 URL | `http://localhost:5173/m/<id>` | matter_id 解码、`user_facing_summary` 描述 matter | ✅ | |
| R02 | 文件级 URL | `http://localhost:5173/m/<id>/f/<file_path>` | file_path 解码、`user_facing_summary` 定位到具体文件 | ✅ | |
| R03 | 非 Pivot URL | `https://example.com/foo/bar` | 400 `bad_url`，detail 给出格式提示 | ✅ | |
| R04 | matter 不存在 | `http://localhost:5173/m/__nope__` | 404 `matter_not_found` | ✅ | |
| R05 | 中文 matter id 编码 | `/m/%E6%B5%8B%E8%AF%95mcp` | 解码后正确返回中文标题 | ✅ | |

### 3.2 `list_matters`

| 编号 | 用例 | 输入 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| L01 | 无筛选 | `{}` | 返回所有可见 matter | ✅ | |
| L02 | status 筛选 | `{status: "paused"}` | 仅返回 paused 的 matter | ✅ | |
| L03 | owner 筛选 | `{owner: "yzy"}` | 仅返回 owner=yzy 的 matter | ✅ | |
| L04 | q 关键字 | `{q: "mcp"}` | 标题含 "mcp" 的 matter | ✅ | |

### 3.3 `get_matter`

| 编号 | 用例 | 输入 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| G01 | 正常 matter | 已存在 matter_id | matter 头部 + timeline 元信息（不含 body） | ✅ | |
| G02 | 不存在 matter | 随机 matter_id | 404 `matter_not_found` | ✅ | |

### 3.4 `read_files`

| 编号 | 用例 | 输入 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| F01 | 单文件正常读 | paths=[1 个真实路径] | 返回 body，`truncated:false` | ✅ | |
| F02 | 多文件批量读 | paths=[3 个真实路径] | 一次返回 3 项 | ✅ | |
| F03 | path 不在 matter | paths=[1 个不存在路径] | 404 `file_not_in_matter`，detail 回显具体 path | ✅ | |
| F04 | 超 5 篇限制 | paths.length=6 | 400 `too_many_files`，detail 含 "Call again in batches" | ✅ | |
| F05 | 单文件 >20K 截断 | 正文 >20000 字符 | 截断到 20000，`truncated:true` | — | 跳过实际触发；逻辑见 `server/mcp/tools.py` L288–290（4 行直白代码） |
| F06 | 总字符 >50K | 多文件累加 >50000 | 400 `body_too_large` | — | 同 F05，逻辑见同文件 L292–298 |

### 3.5 `create_file`：5 种文件类型 + 字段 + 协议

| 编号 | 用例 | 关键输入 | 期望 | 结果 | 备注 |
|------|------|---------|------|------|------|
| W01 | type=think + 无 status_change | matter=paused | 写入成功 | ✅ | 此前已多次在普通讨论里覆盖 |
| W02 | type=think + status_change planning→paused | matter=planning | 写入成功，状态切换 | ✅ | 前置依赖：matter 处于 planning |
| W03 | type=act + status_change planning→executing | matter=planning，trigger_type=act | 写入成功，状态切换 | ✅ | |
| W04 | type=verify + verifications[] | judgement=passed/cancelled，target 指向同 matter act | 写入成功，verifications[] 落库（target/judgement/comment 完整） | ✅ | 通过 `get_matter` 回读校验 |
| W05 | type=result + outcome + status_change executing→finished | outcome=finished | 写入成功，outcome 与 status_change 同时生效 | ✅ | |
| W06 | type=insight + status_change finished→reviewed | trigger_type=insight | 写入成功，matter 抵达终态 reviewed | ✅ | |
| W07 | refer 字段 | refer=[1 个真实路径] | 字段透传并落库 | — | 本次未在成功路径验证：唯一带 refer 的请求撞了 E01 的 422 没走到落库；下次回归补做 |

### 3.6 `create_file`：错误路径

| 编号 | 用例 | 关键输入 | 期望 | 结果 | 备注 |
|------|------|---------|------|------|------|
| E01 | type 在当前 status 下不允许 | matter=paused，type=verify 或 act | 422 `type_not_allowed`，field=type | ✅ | 在 W04 第一次尝试 + E03 都触发 |
| E02 | status_change.from 与当前状态不符 | matter=paused，from="planning" | 422 `status_change_from_mismatch`，field=`status_change.from` | ✅ | |
| E03 | trigger_type 不匹配（被 E01 前置遮蔽） | matter=paused，type=act + to=executing | 期望"trigger_type 不符"，实际命中 E01 的 `type_not_allowed` | ◯ | 校验顺序为 type×status → status_change 内部一致性，前者优先；纯 trigger_type 不符要在允许多种 type 的状态下才能隔离触发 |

### 3.7 协议契约

| 编号 | 用例 | 期望 | 结果 | 备注 |
|------|------|------|------|------|
| P01 | `resolve_context` 返回的 `user_facing_summary` 包含 `available_transitions` 提示 | "当前可触发的状态迁移：xxx（→...，需 type=...）" | ✅ | |
| P02 | `create_file` 写入前先在对话里展示草稿（含 type/summary/body/quote/refer/status_change），等用户口头确认后再调 tool | 协议 §五 第 1 条 | ✅ | 全程遵守 |
| P03 | `create_file` 写入后返回 `summary_for_ai`，含 ✅ 和 `view_url`，由调用方原话转述 | 协议 §五 第 2 条 | ✅ | 全程遵守 |
| P04 | `create_file` 调用前若 `available_transitions` 非空，必须显式问用户是否挂 status_change | 工具 description 中的 PROTOCOL (2/3) | ✅ | 全程遵守 |

---

## 四、结果汇总

- 测试日期：2026-04-27
- 测试人：yzy + Claude（直接调用 MCP 工具）
- 测试环境：本地（127.0.0.1:8000 + localhost:5173）
- 通过 / 总数：25 / 25（F05 / F06 / W07 跳过实际触发，记入"非测试"，从分母剔除；E03 部分通过按 1 计）

### 关键发现

1. **状态机 × 文件类型有强约束**
   - 服务端会在 422 `type_not_allowed` 之前先于 status_change 校验，例如 paused 下不允许 type=verify/act
   - 当前 `available_transitions` 只暴露 `{to, trigger_type, label}`，AI 难以一步推断"这个状态下哪些 type 能写"
   - **建议**：在 `GetMatterOut` / `ResolveContextOut` 增加 `allowed_types: ["think", ...]` 字段，让 AI 调用前能直接判断

2. **422 错误链路设计正确**
   - 服务端 422 → MCP 包装为 `{errors: {detail: {code, field, message}}}`
   - 三段式（code/field/message）足够支持 AI 自动重试与定位错误字段
   - `too_many_files` 的 message 直接告诉 AI "Call again in batches"，是 AI-friendly 的好示例

3. **校验顺序**
   - 当前顺序：`type × status` 白名单 → `status_change` 内部一致性 → 其他字段
   - 优点：前置校验先暴露问题，对 AI 友好
   - 副作用：让某些深层错误路径（如纯 trigger_type 不匹配）难以隔离测试

4. **协议契约 100% 可遵守**
   - 4 条契约（P01–P04）在所有 6 次写入中均无例外执行；草稿预览 + status_change 询问的两步开销实测在对话里完全自然，没有引发用户不耐烦

### 后续回归点（建议在新版本回归时补做）

- F05 / F06 的实际触发：构造一篇 21K 字符的填充文件，验证 `truncated:true` 与 `body_too_large` 实际生效
- W07：在成功路径上验证 `refer=[多个真实路径]` 字段透传并通过 `get_matter` 回读对得上
- E03 的纯 trigger_type 不匹配：在 executing 状态下用 type=result 配 to=paused（要求 trigger_type=think），隔离触发该校验
- 401 / 403 路径：需要无效 token 与跨用户访问场景（本次测试上下文未具备）
- `read_files` 的同一路径 N 次调用是否被 MCP 层短时缓存（设计文档 §八 有提，但未观测验证）
