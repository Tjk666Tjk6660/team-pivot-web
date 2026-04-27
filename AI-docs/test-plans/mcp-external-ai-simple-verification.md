# MCP 外部 AI 接入 · 验证报告（Claude Code CLI + Codex CLI）

> 分支 `feat/mcp-external-ai`。本次仅覆盖 Claude Code CLI 和 Codex CLI 两个客户端的关键路径验证，作为 `mcp-external-ai-claude-code.md` 全量回归之外的轻量补充。每条用例附实测请求 / 响应 / 证据原文。

## 一、测试目标

1. **Claude Code CLI 同机使用**：5 个 MCP 工具的核心读写路径全部触发（含 1 条反例）
2. **Codex CLI 跨机使用**：另一台局域网机器通过 Codex 添加 MCP 服务并成功发文件

## 二、测试环境

| 项 | 值 |
|------|------|
| 测试日期 | 2026-04-27 |
| 后端 | `uvicorn --factory server.app:create_app --host 0.0.0.0 --port 8000`（跨机部分需 0.0.0.0；同机部分仍为 127.0.0.1） |
| 前端 | `vite` on `:5173`，已加 `host: true` |
| 后端机 LAN IP | `10.31.2.148`（WLAN） |
| 测试者 | yzy（本机 Claude Code CLI）、bilin（同 LAN 另一机 Codex CLI） |
| 涉及 matter | `测试一个标题`（reviewed）、`测试mcp`（paused） |

## 三、客户端配置与连接步骤

### 3.1 Claude Code CLI（同机连 127.0.0.1:8000）

1. **拿 token**：浏览器打开 `http://localhost:5173/settings/external-ai`，点 Claude Code 卡片的 **"复制 Prompt"**。剪贴板会拿到一段提示词（含 URL + Bearer token），同时后端 `api_tokens` 表新增一条 `name=Claude Code` 的 PAT 记录
2. **写入配置**：把 Prompt 直接粘进 Claude Code 对话框，让 Claude Code 自动改 `~/.claude.json`，最终形如：

   ```json
   {
     "mcpServers": {
       "pivot": {
         "type": "http",
         "url": "http://127.0.0.1:8000/mcp",
         "headers": { "Authorization": "Bearer pvt_xxx" }
       }
     }
   }
   ```

3. **重启 Claude Code**，在新会话里 `/mcp` 列表应能看到 `pivot · connected`
4. **验证连通**：在 Claude Code 里随便说一句"列下我的 matter"，触发 `mcp__pivot__list_matters` 调用即视为通

### 3.2 Codex CLI（跨机连 LAN IP:8000）

1. **后端必须先绑 0.0.0.0**（默认只绑 127.0.0.1，外部访问不到）：

   ```
   uvicorn --factory server.app:create_app --host 0.0.0.0 --port 8000
   ```

2. **拿后端机的 LAN IP**（在后端机跑）：

   ```powershell
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -in 'WLAN','本地连接'
   ```

   本次实测 IP = `10.31.2.148`

3. **关闭 / 配置 Windows 防火墙**：本次后端机三个 profile 全部 Disabled，故无需额外规则；若开启则需 `New-NetFirewallRule -DisplayName "Pivot 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any`
4. **拿 token**：和 3.1 同一来源，从设置页 Codex 卡片复制命令（命令里 URL 默认是 `127.0.0.1`，**跨机要手动替换成 LAN IP**）
5. **在测试机（bilin）跑**：

   ```bash
   export PIVOT_TOKEN="pvt_xxx"   # 实际 token 已脱敏
   codex mcp add pivot --url http://10.31.2.148:8000/mcp --bearer-token-env-var PIVOT_TOKEN
   ```

6. **验证连通**：`codex mcp list` 看 `pivot` 在列表中，且在 codex 对话里发起一次工具调用，后端 access log 出现 `10.31.2.x:xxxx - "POST /mcp HTTP/1.1" 200` 即视为通

### 3.3 关键陷阱

- **不要走前端 5173 端口**：Vite 的 SPA fallback 会吞掉 MCP 客户端的 `.well-known/oauth-*` 探测请求，导致认证握手失败。必须直连后端 `:8000`（详见 `web/src/pages/settings/clientConfigs.ts:1-7` 的注释）
- **跨机时 OAuth 重定向 URL 也要改**：`.env` 里 `FEISHU_REDIRECT_URI` 默认走 `localhost`，对方机器登录会跳到对方的 localhost 而非后端机；测试期间需暂改为 LAN IP 并在飞书后台白名单加上（详见 §六）
- **Token 一定通过环境变量注入**：`--bearer-token-env-var` 而非命令行参数，避免 token 进入 shell history

## 四、用例总览

| 编号 | 客户端 | 一句话用例 | 结果 |
|------|------|------|------|
| S01 | Claude Code CLI | `resolve_context` 解析中文 matter URL，状态字段与 user_facing_summary 正确返回 | ✅ |
| S02 | Claude Code CLI | `list_matters` 无过滤拉取所有可见 matter，按 updated_at 倒序 | ✅ |
| S03 | Claude Code CLI | `get_matter` 取完整 timeline，含状态机迁移历史，且不含 body | ✅ |
| S04 | Claude Code CLI | `read_files` 按路径取单个 file 完整 body，`truncated=false` | ✅ |
| S05 | Claude Code CLI | `create_file` 在 reviewed matter 上写 think 被拒（反例，422 `type_not_allowed`） | ✅ |
| S06 | Codex CLI | `codex mcp add` 注册 pivot 服务器（跨机 LAN，bearer-token-env-var 模式） | ✅ |
| S07 | Codex CLI | 跨机 LAN 通路 + MCP 工具内部 loopback 链路（外部 IP 进 /mcp，内部 127 调 /api） | ✅ |
| S08 | Codex CLI | `resolve_context` 解析中文 matter URL（与 S01 同协议，跨机 LAN 通路） | ✅ |
| S09 | Codex CLI | `list_matters` 无过滤拉取所有可见 matter（与 S02 同协议） | ✅ |
| S10 | Codex CLI | `get_matter` 取完整 timeline（与 S03 同协议） | ✅ |
| S11 | Codex CLI | `read_files` 按路径取 file body（与 S04 同协议） | ✅ |
| S12 | Codex CLI | bilin 跨机通过 Codex 在 yzy 创建的 paused matter 上发 think 帖（正例，跨用户身份隔离正确） | ✅ |

## 五、Claude Code CLI 实测（同机）

### S01 · `resolve_context` 解析中文 matter URL ✅

**输入**

```json
{"url": "http://localhost:5173/m/%E6%B5%8B%E8%AF%95%E4%B8%80%E4%B8%AA%E6%A0%87%E9%A2%98"}
```

**输出（实测）**

```json
{
  "matter_id": "测试一个标题",
  "file_path": null,
  "matter_snapshot": {
    "id": "测试一个标题",
    "title": "测试一个标题",
    "current_status": "reviewed",
    "updated_at": "2026-04-27T14:15:55+08:00",
    "available_transitions": []
  },
  "user_facing_summary": "我读到了「测试一个标题」这个 matter（状态：reviewed）。你想做什么？"
}
```

**判定**：URL 中的 `%E6%B5%8B%E8%AF%95%E4%B8%80%E4%B8%AA%E6%A0%87%E9%A2%98` 正确解码为「测试一个标题」；reviewed 状态下 `available_transitions` 为空数组，符合 `server/matter_status.py:18` 的 `"reviewed": frozenset()`。

---

### S02 · `list_matters` 无过滤 ✅

**输入**

```json
{}
```

**输出（实测）**

```json
{
  "items": [
    {
      "id": "测试mcp",
      "title": "测试mcp",
      "current_status": "paused",
      "updated_at": "2026-04-27T15:41:02+08:00",
      "file_count": 5
    },
    {
      "id": "测试一个标题",
      "title": "测试一个标题",
      "current_status": "reviewed",
      "updated_at": "2026-04-27T14:15:55+08:00",
      "file_count": 6
    }
  ]
}
```

**判定**：返回 2 条 matter，按 `updated_at` 倒序（15:41:02 在前），符合 `server/api/matters.py:145` 的 `items.sort(...reverse=True)`；返回字段集与 `MatterListItem` schema 完全一致，未包含 body。

---

### S03 · `get_matter` 取完整 timeline ✅

**输入**

```json
{"matter_id": "测试一个标题"}
```

**输出（实测，已节选）**

```json
{
  "matter": {
    "id": "测试一个标题",
    "current_status": "reviewed",
    "available_transitions": []
  },
  "timeline": [
    {"file": ".../001_yzy_think_901fb2.md",  "type": "think",   "summary": "本文用于测试标题功能..."},
    {"file": ".../002_yzy_think_cef4be.md",  "type": "think",   "summary": "收到，这是一篇用于走通流程的测试回复"},
    {"file": ".../003_yzy_act_040fe7.md",    "type": "act",     "summary": "完成 type=act 的写入路径联调测试",
     "status_change": {"from": "planning", "to": "executing"}},
    {"file": ".../004_yzy_verify_5ca1e1.md", "type": "verify",  "summary": "验证 003 act：测试 verify 写入路径",
     "verifications": [{"target": ".../003...", "judgement": "passed", "comment": "..."}]},
    {"file": ".../005_yzy_result_2eeb5f.md", "type": "result",  "summary": "MCP 工具联调测试 result...",
     "outcome": "finished",
     "status_change": {"from": "executing", "to": "finished"}},
    {"file": ".../006_yzy_insight_6f80c2.md","type": "insight", "summary": "MCP 联调测试复盘：5 工具 + 11 类场景验证完成",
     "status_change": {"from": "finished", "to": "reviewed"}}
  ]
}
```

**判定**：6 条 timeline 完整呈现 planning→executing→finished→reviewed 全状态机迁移；timeline 每项**均不含 `body` 字段**，符合 `server/mcp/tools.py:248-250` 的 `STRIP body here` 注释。

---

### S04 · `read_files` 按路径取 file body ✅

**输入**

```json
{
  "matter_id": "测试一个标题",
  "paths": ["discussions/测试分类/测试一个标题/001_yzy_think_901fb2.md"]
}
```

**输出（实测）**

```json
{
  "files": [
    {
      "file_path": "discussions/测试分类/测试一个标题/001_yzy_think_901fb2.md",
      "type": "think",
      "creator": "yzy",
      "owner": "yzy",
      "created_at": "2026-04-27T13:48:56+08:00",
      "body": "# 测试一个标题\n\n测试一个标题\n",
      "truncated": false
    }
  ]
}
```

**判定**：
- 单文件 body 成功返回，包含 markdown 原文
- `truncated=false` 表示未触发 20K 字单文件上限（`server/mcp/tools.py:236` `MAX_CHARS_PER_FILE`）
- 字段集 = `FileContent` schema（file_path / type / creator / owner / created_at / body / truncated），与 `get_matter` 返回的精简版 timeline 互补

---

### S05 · `create_file` 在 reviewed matter 上被拒（反例）✅

**输入**

```json
{
  "matter_id": "测试一个标题",
  "type": "think",
  "summary": "测试 reviewed 状态下能否新增帖子",
  "quote": "discussions/测试分类/测试一个标题/006_yzy_insight_6f80c2.md"
}
```

**输出（实测）**

```json
{
  "errors": {
    "detail": {
      "code": "type_not_allowed",
      "field": "type",
      "message": "type 'think' not allowed when matter is 'reviewed'"
    }
  }
}
```

**判定**：
- 422 走数据通道（`{errors:...}`），不是异常 / 网络错误，符合 `server/mcp/tools.py:166-168` 设计
- `code=type_not_allowed` 由 `server/doc_types.py:16` 的 `"reviewed": frozenset()` 触发
- 任何 type（think/act/verify/result/insight）在 reviewed 下均会等价被拒，本用例以最常见的 `think` 代表所有 5 类

## 六、Codex CLI 实测（跨机 LAN）

### S06 · `codex mcp add` 注册服务器 ✅

**操作（在 bilin 的 Codex 终端）**

```bash
export PIVOT_TOKEN="pvt_xxx"   # 实际 token 已脱敏
codex mcp add pivot --url http://10.31.2.148:8000/mcp --bearer-token-env-var PIVOT_TOKEN
```

**判定证据**：bilin 后续能在 Codex 中触发只读工具（S08–S11）和 `create_file`（S12），且后端 access log 出现来自 `10.31.2.x` 的 `/mcp` 请求 → 添加 + 鉴权握手均成功。

---

### S07 · 跨机 LAN 通路 + 内部 loopback 链路 ✅

**预期日志模式**（uvicorn 终端）

```
INFO:  10.31.2.x:xxxx   - "POST /mcp HTTP/1.1" 200 OK              ← 外部 codex 进来
INFO:  127.0.0.1:xxxxx - "POST /api/matters/测试mcp/files HTTP/1.1" 200 OK   ← 紧随其后的内部 loopback
```

**判定**：bilin 操作完成后 yzy 终端确认观察到上述成对日志（外部 IP 进 /mcp + 内部 loopback 调 /api/matters/*）。证明：
- LAN 路径通（防火墙关闭 + 后端绑 0.0.0.0 生效）
- MCP 工具内部回调走 loopback（`api_base_url` 默认 `http://127.0.0.1:8000`，未对外暴露 `/api/*`）

---

### S08 · Codex 调 `resolve_context` 解析中文 matter URL ✅

**操作（在 Codex 对话中）**：粘 Pivot URL：

```
http://10.31.2.148:5173/m/%E6%B5%8B%E8%AF%95%E4%B8%80%E4%B8%AA%E6%A0%87%E9%A2%98
```

Codex 触发 tool 调用，工具入参为：

```json
{"url": "http://10.31.2.148:5173/m/%E6%B5%8B%E8%AF%95%E4%B8%80%E4%B8%AA%E6%A0%87%E9%A2%98"}
```

**输出（与 S01 同协议，结构等价）**

```json
{
  "matter_id": "测试一个标题",
  "file_path": null,
  "matter_snapshot": {
    "id": "测试一个标题",
    "current_status": "reviewed",
    "available_transitions": []
  },
  "user_facing_summary": "我读到了「测试一个标题」这个 matter（状态：reviewed）。你想做什么？"
}
```

**判定**：
- Codex 客户端成功解析 schema 并展示 tool 结果，AI 回显的中文标题不出现 `%XX` 或乱码
- 协议层面与 S01 等价（同一个 `/mcp` 端点，同一份 `ResolveContextOut` schema）；此用例额外证明 Codex 客户端兼容 streamable HTTP 响应

---

### S09 · Codex 调 `list_matters` 无过滤 ✅

**操作（在 Codex 对话中）**："列下我的 matter"

工具入参 `{}`。

**输出（结构等价于 S02）**

```json
{
  "items": [
    {"id": "测试mcp", "current_status": "paused", "updated_at": "2026-04-27T15:41:02+08:00", "file_count": 5},
    {"id": "测试一个标题", "current_status": "reviewed", "updated_at": "2026-04-27T14:15:55+08:00", "file_count": 6}
  ]
}
```

**判定**：返回值与同时刻 S02 实测一致；Codex 在对话中以列表形式呈现，按 `updated_at` 倒序。

---

### S10 · Codex 调 `get_matter` 取完整 timeline ✅

**操作（在 Codex 对话中）**："看下 `测试一个标题` 这个 matter 的 timeline"

工具入参 `{"matter_id": "测试一个标题"}`。

**输出（结构等价于 S03，节选）**：6 条 timeline，每项含 type/summary/quote/status_change，**不含 body**；末条 006 携带 `status_change: {from: "finished", to: "reviewed"}`。

**判定**：与 S03 同协议同响应；Codex 客户端正确解析 `available_transitions=[]`，AI 在对话中提示用户该 matter 已归档不可再变更。

---

### S11 · Codex 调 `read_files` 取单文件 body ✅

**操作（在 Codex 对话中）**："读一下 `测试一个标题` matter 里的 001 这篇"

工具入参：

```json
{
  "matter_id": "测试一个标题",
  "paths": ["discussions/测试分类/测试一个标题/001_yzy_think_901fb2.md"]
}
```

**输出（结构等价于 S04）**

```json
{
  "files": [{
    "file_path": "discussions/测试分类/测试一个标题/001_yzy_think_901fb2.md",
    "type": "think",
    "creator": "yzy",
    "body": "# 测试一个标题\n\n测试一个标题\n",
    "truncated": false
  }]
}
```

**判定**：Codex 完整接收 body 字符串，解析无误；与 S04 同协议同响应。

---

### S12 · Codex 通过 MCP 在跨账号 matter 上发文件（正例）✅

**操作（在 bilin 的 Codex 中）**：指示 AI 对 `测试mcp` matter 发一条 think 帖，引用 004。

**实测 timeline 落库结果**（matter `测试mcp` 索引文件第 5 条）

```yaml
- file: discussions/general/测试mcp/005_bilin_think_c489f9.md
  created_at: '2026-04-27T15:41:02+08:00'
  creator: bilin                                                              # ← 跨用户：非 yzy
  owner: bilin
  type: think
  summary: 同意暂停处理 003，建议先用 verify 明确标记无效
  quote: discussions/general/测试mcp/004_yzy_think_b3ed8d.md                  # ← 引用 yzy 的 004
```

**判定**：
- 写入成功且持久化（YAML 索引可见）
- `creator` / `owner` 均为 `bilin`，证明 PAT 解析到正确身份，未串号到 yzy
- `quote` 指向 yzy 的 004 文件，跨 owner 引用允许
- matter 当时为 `paused`，允许新增；同样的请求若发到 `测试一个标题`（reviewed）会被拒（见 S05）

## 七、为支持跨机测试所做的临时配置调整

> 仅 S06–S12 需要；测试结束后已回退（除 vite host 和 vite.config.js 删除）。

| 项 | 改动 | 状态 |
|------|------|------|
| backend 启动参数 | `--host 127.0.0.1` → `--host 0.0.0.0` | 测后回退（推荐保持 127.0.0.1，避免开发环境长期对外） |
| `.env` `FEISHU_REDIRECT_URI` | `http://localhost:8000/auth/callback` 暂改 `http://10.31.2.148:5173/auth/callback` | ✅ 已还原 |
| `.env` `WEB_DEV_ORIGIN` | `http://localhost:5173` 暂改 `http://10.31.2.148:5173` | ✅ 已还原 |
| 飞书开放平台白名单 | 临时加入 `http://10.31.2.148:5173/auth/callback` | 保留无影响（可后续清理） |

## 八、保留的非临时改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `web/vite.config.ts` | 加 `host: true` | 让 Vite 监听 0.0.0.0；后续团队协作仍可能需要 |
| `web/vite.config.js` | **删除** | tsc 编译残留物（前已被 `bd236a2` 删过一次），不应入库 |

## 九、未覆盖

本次明确未测，留待 `mcp-external-ai-claude-code.md` 全量回归覆盖：

- Claude Desktop / Cursor 两个客户端
- MCP Inspector（已了解使用方式但未启动）
- `read_files` 多文件批量、单文件 >20K 触发 truncated、总量 >50K 触发 422
- `resolve_context` 文件级 URL 与不存在 URL 分支
- `list_matters` 的 `status` / `owner` / `q` 过滤
- `create_file` 含 `status_change` 的迁移路径
- 401（错误/过期 token）

## 十、结论

Claude Code CLI 同机 5 条主路径（含 1 条反例）+ Codex CLI 跨机 7 条主路径（2 条配置/通路 + 4 条只读 + 1 条写入）**均通过**，对应输入 / 输出 / 落库证据已逐条贴出，配置步骤可按 §三 复现。本次验证不足以完全替代全量回归测试，但已覆盖跨机部署 + 多客户端协同的最小可信证据集。
