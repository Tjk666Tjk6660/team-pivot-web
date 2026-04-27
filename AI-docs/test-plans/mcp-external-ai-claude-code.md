# MCP 外部 AI 接入测试用例（Claude Code）

> 分支 `feat/mcp-external-ai`。仅覆盖 Claude Code 客户端。

## 一、功能背景

让 Claude Code 通过 MCP 协议读写 Pivot 的 matter：用户在 Pivot Web 点"复制给 AI"拿到一个 URL，粘到 Claude Code，AI 就能读 matter / 写 think、act、verify、result、insight。

**5 个 tool**

| tool | 干嘛用 |
|------|------|
| `resolve_context` | 把 Pivot URL 解析成 matter / 文件，并返回一段 `user_facing_summary`（AI 必须**原样复读**给用户校验上下文） |
| `list_matters` | 列出当前用户可见 matter，支持 status/owner/q 过滤 |
| `get_matter` | matter 头部 + timeline 索引（**不含** file body） |
| `read_files` | 按路径取 file body（限额：≤5 文件 / 单文件 ≤20K 字 / 总 ≤50K 字） |
| `create_file` | 写一篇时间线项，返回 `summary_for_ai`（AI 必须**原样转述**，含 view_url） |

**协议契约**
- 所有 `/mcp` 请求带 `Authorization: Bearer pvt_xxx`；缺/错/过期 → 401
- `create_file` 必须**先在对话里展示草稿征求用户口头同意**，再调 tool
- 422 不抛错，作为 `{errors:...}` 返回让 AI 迭代

---

## 二、前置条件

1. 后端 `http://127.0.0.1:8000` 已起
2. 前端 `http://localhost:5173` 已起
3. 当前账号已登录、有至少 1 个可见 matter（记作 `<MATTER_ID>`，含 1 篇文件 `<FILE_PATH>`）
4. Claude Code 已安装、能编辑 `~/.claude.json`

---

## 三、测试用例

> 结果列填：✅ 通过 / ❌ 失败 / — 跳过；失败的把现象写在"备注"列。

### 1. 开发点（自动化测试）

| 编号 | 用例 | 操作 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| D01 | 后端单测 | `python -m pytest server/tests/test_mcp_*.py -q` | 全部 PASS | ✅ | 2026-04-27：32 passed (test_mcp_auth/context/tools/e2e) |
| D02 | 前端单测 | `cd web && npm run test` | clientConfigs 测试 PASS | ✅ | 2026-04-27：1 file / 4 tests passed |
| D03 | 前端类型检查 | `cd web && npm run typecheck` | 无错 | ✅ | 2026-04-27：① package.json 无 `typecheck` 脚本，实际命令为 `npx tsc -b`。② 首跑发现 FileCard.tsx:11 `Input` 未使用（TS6133，d9cbf81 引入），按 yzy 决定本 PR 顺手删除该 import；二次运行无错。 |
| D04 | 无 token 直接打 /mcp | `curl -X POST http://127.0.0.1:8000/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'` | 401 + `{"detail":"missing_bearer_token"}` | ✅ | 2026-04-27：先 307 到 `/mcp/`，再 401 `{"detail":"missing_bearer_token"}` |

### 2. 配置点（设置页 → 接入 Claude Code）

| 编号 | 用例 | 操作 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| C01 | 进入设置页 | 浏览器打开 `/settings/external-ai` | 4 张客户端卡片 + "已接入客户端"区域显示"暂无" | ◯ | 2026-04-27：4 卡片 OK；"暂无"未达成——已有 2 条历史 Claude Code token，故显示 2 行 `✅ Claude Code · 最后使用：2026/4/27 14:16:49` 与 `2026/4/24 18:39:11`，与 DB 时间戳吻合。**非阻塞观察**：UI 不去重，每次刷新页 + 点"复制 Prompt"会新增 token；同名多实例本身是产品取舍。 |
| C02 | 复制 Claude Code Prompt | 点 Claude Code 卡片"复制 Prompt" | Toast 已复制；剪贴板含 `URL: http://127.0.0.1:8000/mcp` 和 `Bearer pvt_xxx`；后端新增一条 name=Claude Code 的 token | ✅ | 2026-04-27：首次点击因 React `token` state 已 cache，未触发新建；F5 后重点击成功。剪贴板 token 的 sha256 与 DB 新行 token_hash 完全吻合（`15a80343…`，name=`Claude Code`，created_at≈14:53:47，last_used_at=NULL）。**非阻塞观察**：UI 不去重也不撤销旧同名 token，多次"复制 Prompt"会累积多条；首次点击短路依赖刷新页才会重建 state。 |
| C03 | 已接入客户端列表更新 | 刷新设置页 | 出现 `✅ Claude Code · 最后使用：尚未使用` | ✅ | 2026-04-27：用户复测确认。本轮中由于 curl C05 已 bump 新 token 的 `last_used_at`，最新一行不再是"尚未使用"而是 14:56:57，但用户既往复测路径在重启 Claude Code 之前能看到"尚未使用"，故按用户口径标 ✅。 |
| C04 | Claude Code 写入配置 | 把 Prompt 粘到 Claude Code，让它改 `~/.claude.json` | Claude 改完报告完成；`~/.claude.json` 的 `mcpServers.pivot` 形如 `{"type":"http","url":"http://127.0.0.1:8000/mcp","headers":{"Authorization":"Bearer pvt_..."}}` | ✅ | 2026-04-27：本会话中将 Prompt 粘给 Claude Code（即本 CLI），先备份 `~/.claude.json.bak.2026-04-27` 再写入。已存在的 `pivot` 条目（旧 token `pvt__sINq…0-bs`）被覆盖为新 token；其余 33 个顶层 key 完整保留，文件可正常解析。 |
| C05 | 重启后连上 | 重启 Claude Code，看 `/mcp` 列表 | `pivot` 状态 connected | ✅ | 2026-04-27：① 本会话以 curl 拿新 token 调 `initialize`（带 `Accept: application/json, text/event-stream`）→ 200 + SSE，server 回 `protocolVersion=2025-03-26 / serverInfo=pivot-mcp v0.1.0`，证明后端握手通路 OK；② 用户既往实测中重启 Claude Code 后 `/mcp` 显示 `pivot` connected，本次以用户口述 attest 通过。 |
| C06 | last_used_at 刷新 | Claude Code 连上后回 Pivot Web 设置页刷新 | "Claude Code 最后使用"从"尚未使用"变为最近时间 | ✅ | 2026-04-27：① curl initialize 后 DB 中新 token 的 `last_used_at` 即从 NULL → 1777273017.40（≈14:56:57），证明刷新逻辑生效；② 用户既往实测中设置页"最后使用"对应文案能从"尚未使用"刷成最近时间，按 attest 标 ✅。 |
| C07 | 错误 token 被拒 | 改 `~/.claude.json` 的 token 为 `pvt_invalid` 重启 | Claude Code `/mcp` 显示 disconnected / 401 | ✅ | 2026-04-27：用户既往复测确认；HTTP 层等价证据见 D04（无 token → 401）。 |

### 3. 使用点 · 复制给 AI 按钮

| 编号 | 用例 | 操作 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| U01 | matter 头部按钮 | 在 matter 页点"复制给 AI" | 剪贴板 = `${origin}/m/<MATTER_ID>`；Toast `已复制，粘到 Claude Code 或其他 AI 助手即可`；图标 2s 内 Copy→Check→Copy | | |
| U02 | 文件卡片按钮 | 在某文件卡片点"复制给 AI" | 剪贴板 = `${origin}/m/<MATTER_ID>/f/<FILE_PATH>`（中文部分应是 `%XX` 编码） | | |

### 4. 使用点 · 5 个 tool 实战

> 操作模式：把上一步复制的 URL 粘到 Claude Code，或直接对 Claude 提需求让它选工具。

| 编号 | 用例 | 操作（在 Claude Code 里） | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| U03 | resolve_context (matter) | 粘 matter 级 URL | Claude 调 `resolve_context`，**原样复读** `我读到了「<title>」这个 matter（状态：<status>）。你想做什么？` | | |
| U04 | resolve_context (file) | 粘文件级 URL | Claude 复读 `我读到了「<title>」matter 的一篇 <type> 文件：《<summary>》。当前 matter 状态：<status>。你想做什么？` | | |
| U05 | resolve_context 中文 matter | 粘 URL 含 `%XX` 编码的中文 matter id | Claude 复读的标题是中文，不出现 `%` 或乱码 | | |
| U06 | resolve_context 不存在 | 让 Claude 调 `resolve_context({"url":"http://localhost:5173/m/__nope__"})` | 返回 404 `matter_not_found`，Claude 转告"找不到" | | |
| U07 | list_matters | "列一下我能看到的 matter" | Claude 调 `list_matters({})`；以列表形式展示；不含 file body | | |
| U08 | list_matters 过滤 | "列状态 executing 关键词 auth 的 matter" | tool args `{status:"executing", q:"auth"}`；返回项均符合条件 | | |
| U09 | get_matter | "看看 matter `<MATTER_ID>` 都有哪些文件" | timeline 每项**不含 body**，Claude 给出文件清单 | | |
| U10 | read_files 单文件 | "读一下 `<FILE_PATH>`" | 返回 body，`truncated:false` | | |
| U11 | read_files 批量 | "读这 3 个文件 ..." | 一次返回 3 项 | | |
| U12 | read_files 超过 5 个 | "读这 6 个文件 ..." | 400 `too_many_files`，Claude 改成两次调用 | | |
| U13 | read_files 不存在的 path | "读 `__nope__.md`" | 404 `file_not_in_matter` | | |
| U14 | **create_file 协议** | "帮我写一个 think，总结 `<MATTER_ID>` 的进展" | Claude **不立即调 tool**，先在对话里贴 type/summary/body 草稿问 OK 吗 | | |
| U15 | create_file 提交 | 上一步草稿，用户回 "OK 提交" | approval dialog 弹出参数；用户确认后 tool 返回 `{ok:true, view_url, summary_for_ai}`；Claude **逐字转述** `summary_for_ai`（含 ✅ 和 view_url） | | |
| U16 | view_url 可跳 | 点 U15 转述里的 view_url | Pivot Web 打开新文件页，作者 = 当前用户 | | |
| U17 | create_file verify | "verify 那篇 think，标记 passed，备注 ok" | 草稿含 `verifications:[{target,judgement,comment}]`；提交成功 | | |
| U18 | create_file 校验失败 | 让 Claude 提交 `type:"verify"` 但不带 verifications | 返回 `{errors:...}`（不抛异常）；Claude 改稿重提 | | |
| U19 | create_file 无权限 | 用 A 用户 token 写 B 私有 matter | 403 `forbidden` | | |

### 5. 鉴权回归

| 编号 | 用例 | 操作 | 期望 | 结果 | 备注 |
|------|------|------|------|------|------|
| A01 | token 撤销 | 在 Web "API Tokens" 删除 Claude Code token，再让 Claude 调 tool | 401 `invalid_token`；设置页"已接入客户端"刷新后 Claude Code 消失 | | |
| A02 | 多用户隔离 | A 用户 token 调 `list_matters` | 不出现 B 的私有 matter | | |

---

## 四、测试结果汇总

> 测完填写。

- 测试日期：____
- 测试人：____
- 测试环境：本地 / 测试 / 生产 ____
- 通过 / 总数：__ / __

**主要发现**
- 阻塞性问题：____
- 非阻塞问题（可后续修）：____
- 是否可放行 Claude Code 接入：☐ 是 ☐ 否
