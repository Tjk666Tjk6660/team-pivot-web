# 外部 AI 接入 Pivot：MCP 方案设计（V2）

**作者**：yezaiyong
**日期**：2026-04-23（V2 更新于 2026-04-24，2026-04-24 经领导认可定版）
**状态**：**已批准**，准备进入实施
**依据**：Pivot 新需求《支持 MCP 接入外部 AI》、`pivot-product.md`、`pivot-interface.md`
**前置依赖**：新 Matter API 落地（见 `2026-04-23-index-refactor-design.md`）

---

## 本次（V2）主要变更

> **一句话：简化接入步骤，补齐产品使用方案（3 分钟上手该 MCP：2 分钟接入 + 1 分钟用完一次）。**

详细调整点如下：

| # | 项 | V1 怎么做 | V2 改成 | 动因 |
|---|----|----------|---------|------|
| 1 | 读取正文 | `get_matter` 工具一次把所有文件正文给 AI | `get_matter` 工具只返回 index；新增 `read_files(paths[])` 工具按需拉正文（**MCP 层切分，不改后端接口**） | 避免大 matter 灌满 AI 上下文；让 AI 基于 index 做判断再读 |
| 2 | 写入流程 | 两步走：`prepare_draft` + `submit_draft`，服务端存草稿 12h | 一步写入：`create_file`，MCP 层**完全无状态** | 防"API 膨胀"（否则还要补 get/update/list draft）；Gate 交给 AI 客户端的 approval 对话框做 |
| 3 | 工具命名 | `prepare_draft / submit_draft`（需解释） | `create_file`（自解释） | API 命名规范 |
| 4 | 接入体验 | 只说"配 URL + PAT 就能用" | 新增 §六：Pivot Web"外部 AI 接入"设置页，按 Claude Code / Cursor / Codex / Claude Desktop 四家客户端分别给接入方案 | 避免非技术用户第一次接入就卡住 |
| 5 | 日常使用的 UX | "让 AI 读就行"这类模糊表述 | §五 给关键工具加了三条协议约定：`resolve_context` 返回 `user_facing_summary`、`create_file` 调用前必须在对话里先出人话草稿、`create_file` 返回 `view_url` + `summary_for_ai` 让 AI 给用户人话确认 | 把"非技术同事用起来的体感"做成硬协议而不是口头约定 |
| 6 | 用户流程叙述 | V1 只给工具列表和时序图 | §七 重写为"真实使用场景与复杂度账本"：走一遍李明的一次完整使用，附复杂度量化、对比"没有 MCP 会怎么样"、"好产品标准"达成情况 | 看文档的人一眼能判断这东西用起来到底简不简单 |
| 7 | 传输协议 | SSE（两 endpoint：`/sse` + `/messages`） | **Streamable HTTP**（单 endpoint `/mcp`） | MCP spec 2025-03-26 起 SSE 被废弃，**2026-04-01 起 spec 拒绝接受 SSE 连接**（发稿时已过 deadline）。Claude Code / Cursor / Codex 均已切到 Streamable HTTP，我们直接按终态实现 |
| 8 | Claude Desktop 接入 | 复制 JSON 片段 → 贴到 `claude_desktop_config.json` | 复制 URL + Token → 走 Desktop UI "Settings → Connectors → Add custom connector" | Claude Desktop 的 JSON 配置文件不再支持远程 HTTP 服务，只能通过桌面应用 UI 添加 |

最终工具总数不变（5 个），但职责和约定更清晰。详细理由见正文对应章节。完整变更历史见文末**附：本文档变更历史**。

---

## 一、为什么要做这件事

Pivot 正在从旧的 `thread / reply` 模型切到新的 `matter / timeline` 模型。老 API 和建立在它上面的客户端（例如 vscode-team-pivot）后续会失效或需要重构。

与此同时，公司同事越来越多地在 Claude Code、Codex、ChatGPT 这些外部 AI 终端里工作。如果我们只做新 Web 和 Pivot 内置 AI，**不定义一套统一的外部 AI 接入方式**，各家客户端很可能各接一套，形成新的碎片化。

一句话：

> 我们需要一条**不绑定某家 AI 产品、基于新 Matter API、正式对外开放**的外部 AI 接入通道。

---

## 二、第一版目标

让任何支持 MCP 的 AI 客户端（Claude Code、Codex、ChatGPT 等）都能接入 Pivot，跑完**最小闭环**：

```
用户在 Pivot Web 复制上下文 URL
        ↓
粘到外部 AI
        ↓
AI 读上下文 → 与用户讨论 → 起草新文件
        ↓
用户审稿 → 用户点头
        ↓
AI 提交，文件出现在 Pivot matter timeline 上
```

**明确不做**：创建新 matter、跨 matter 读取、搜索、评论流、草稿列表等。等第一版跑通再看。

---

## 三、技术选型：为什么是 MCP，而不是 skill 或 CLI

结论：**MCP 为主，CLI 为辅，skill 不作为主方案**。

| 方案 | 适合 | 不适合作为主线的原因 |
|------|------|--------------------|
| **MCP** | AI 终端 | — |
| skill | 某个客户端内部 | 跟客户端强耦合，跨产品难复用，升级成本高 |
| CLI | 调试 / 脚本 / fallback | 面向人类命令行用户，不直接服务 AI 终端 |

MCP 的核心优势：**工具名、描述、参数、返回结构一定义清楚，AI 在运行时就能直接理解并调用**，不用用户另装 skill 来"教"它。这正好符合"跨 AI 客户端通用"的目标。

CLI 作为辅助壳层保留（未来需要时再做），skill 作为极少数客户端的增强层保留（需要时再做）。

---

## 四、整体架构

```
┌──────────────────────────────────────────────────────┐
│   外部 AI 客户端                                      │
│   （Claude Code / Codex / ChatGPT / ...）             │
└──────────────┬───────────────────────────────────────┘
               │
               │  MCP 协议（Streamable HTTP 传输，单 endpoint）
               │  认证：Authorization: Bearer pvt_xxxxxxxx
               ▼
┌──────────────────────────────────────────────────────┐
│   pivot.enclaws.ai  （FastAPI 服务）                   │
│                                                      │
│   ┌────────────────────┐      ┌──────────────────┐   │
│   │  /mcp endpoint     │ ───▶ │  Matter API      │   │
│   │  （本次新增）        │      │  （已有设计草案）  │   │
│   │                    │ ◀─── │  /api/matters    │   │
│   │  - PAT 认证转发     │      │  /api/matters/.. │   │
│   │  - URL 解析         │      │  /files          │   │
│   │  - 草稿状态存储      │      └──────────────────┘   │
│   │  - 字段校验         │                ↓            │
│   └────────────────────┘      ┌──────────────────┐   │
│                               │ Git + index YAML │   │
│                               └──────────────────┘   │
└──────────────────────────────────────────────────────┘
```

### 上下文 URL 长这样

用户从 Web 复制出来、粘给外部 AI 的那串东西：

```
https://pivot.enclaws.ai/m/{matter_id}               ← 仅到 matter 级
https://pivot.enclaws.ai/m/{matter_id}/f/{file_path}  ← 精确到某文件
```

好处是**就是一条普通网址**：用户点开能直接看到 Web 页面；粘给任何 AI，AI 也能认出这是 Pivot 链接并主动调 `resolve_context` 工具，不需要用户教。

### 三个关键决定

1. **远程部署**：MCP 服务挂在 pivot.enclaws.ai 现有服务里，不起独立进程。用户只要配一个 URL + PAT 就能用，无需本地安装。
2. **现有 PAT 认证**：沿用 Pivot 已有的 PAT（`pvt_` 前缀、90 天过期、Bearer 头认证），不引入新机制。
3. **纯协议包装层**：MCP 自己不碰文件、不碰 index YAML，一切写入都走 Matter API。

---

## 五、MCP 对外提供的 5 个工具

### 读（4 个）

| 工具 | 作用 |
|------|------|
| `resolve_context` | 把用户粘的 Pivot URL 解析成 matter + 文件定位。**返回里包含 `user_facing_summary`，AI 需原话展示给用户**，让用户一眼核对 AI 是否抓到了对的 matter / 文件 |
| `list_matters` | 列出当前用户可见的 matter，可按状态、负责人、关键字筛选 |
| `get_matter` | 返回某个 matter 的头部 + timeline 元信息（摘要 / 类型 / 引用关系），**不带文件正文** |
| `read_files` | 按路径数组批量拉取文件正文（单文件就是数组长度为 1） |

### 写（1 个）

| 工具 | 作用 |
|------|------|
| `create_file` | 一次性写入：AI 带齐类型、摘要、正文、结构化字段（quote / refer / verifications / outcome / status_change），服务端校验后直接写进 matter timeline。**两条协议约定**见下 |

**`create_file` 的两条协议约定**：

1. **调用前必须先在对话里用人话展示草稿**。AI 要在对话里（不是 approval 对话框里）先告诉用户"我准备写以下内容"，等用户自然语言确认（"可以"、"发"）之后再调用。approval 对话框只是最后橡皮图章。
2. **返回值包含 `view_url` 和 `summary_for_ai`**。`summary_for_ai` 是一句人话确认（形如"✅ 已提交，这是 matter「xxx」的第 N 篇，点这里查看：<view_url>"），AI 需原话转发给用户，让用户立即知道写成了 + 有直接可点的回链。

### 为什么读是"先拿 index，再拿正文"

如果 `get_matter` 一次把所有文件正文都返回，**大 matter 会把 AI 的 context 灌满**（timeline 几十篇文件是常见的）。合理做法：

1. AI 先调 `get_matter` 拿 timeline 的**元信息**（每项摘要、类型、引用关系）
2. AI 基于这份 index **自己判断**要读哪几篇全文
3. 再调 `read_files(paths)` 按需拉

这让 AI 的 context 用量可控，也让"AI 阅读 Pivot"变成它真正在做判断，而不是粗暴把所有内容灌进去。

### 为什么写是一步到位（不走两步草稿）

最初考虑过"prepare + submit"两步走防 AI 在审稿和写入之间偷改内容。但进一步分析：

- 外部 AI 客户端（Claude Code / Codex 等）在 AI 每次调用工具时都**弹 approval 对话框**，里面**完整展示工具参数**
- 所以 AI 调 `create_file(matter_id, type, summary, body, ...)` 时，**用户在对话框里看到的参数 = 真正写进去的参数**
- Gate 由 AI 客户端的 approval 对话框天然提供，不需要服务端多存一份草稿

一步写入的好处：
- 服务端不需要草稿表、TTL、清理任务
- 不会被迫再补 `get_draft / update_draft / list_drafts` 等 API
- 命名自然（`create_file` 一眼看懂）

代价：AI 要在**自己的 context 里**起草和打磨。这正好符合外部 AI 的工作方式（AI 本来就用 context 做写作），没有额外负担。

---

## 六、接入引导：Pivot Web 外部 AI 接入设置页

### 为什么单独说这件事

§四 的架构只讲了"配一个 URL + PAT 就能用"。这对开发者成立，但对**非技术用户**隐藏了三件事：

1. 不同操作系统（Mac / Win / Linux）下 AI 客户端的配置文件路径不一样
2. 配置文件是 JSON 或 TOML，手改改错一个逗号客户端就打不开
3. 不同 AI 客户端的配置格式不同，**不能复用同一份 JSON**

如果 V1 只上线 MCP 端点、让用户"自己查各家文档配置"，非技术用户会在**第一次接入**就卡住。MCP 服务端实施时**同步做一个接入设置页**，能把"踩坑 + 问人"变成"2 分钟自助搞定"。

### 客户端能力对比

| 能力 / 客户端 | Claude Code | Cursor | Codex | Claude Desktop |
|---------------|-------------|--------|-------|----------------|
| Streamable HTTP 支持 | ✅ | ✅ | ✅ | ✅（仅走 UI） |
| 远程服务接入方式 | JSON（`~/.claude.json` / 项目 `.mcp.json`）或 `claude mcp add` CLI | JSON（`~/.cursor/mcp.json`，**无 `type` 字段**）或 `cursor://` 深链 | TOML（`~/.codex/config.toml`）或 `codex mcp add` CLI | **只能走 UI**：Settings → Connectors → Add custom connector |
| 认证方式 | 自定义 HTTP 头（Bearer PAT） | 自定义 HTTP 头 | Bearer token（TOML 里 `bearer_token_env_var`）| UI 里粘 token，支持 OAuth |

**关键变化**：MCP spec 2025-03-26 起废弃 SSE 传输，**SSE 连接从 2026-04-01 起被 spec 拒绝**。所有四家都已转向 **Streamable HTTP**，这是**唯一**现行远程传输。我们的 `/mcp` endpoint 直接按 Streamable HTTP 实现，不做 SSE 兼容。

此外，**Claude Desktop 的桌面 app 不再支持从 `claude_desktop_config.json` 加载远程 HTTP 服务**（该文件只支持 stdio 本地进程），必须通过 UI 手工添加 custom connector。所以我们的设置页 Claude Desktop 卡片产出的不是 JSON，而是"URL + Token + UI 导航提示"。

此外有一条关键的 UX 原则：**PAT / 访问令牌对普通用户永远不可见**。各家客户端点"复制"时，PAT 已经嵌在复制出来的内容里（JSON / prompt / CLI 命令都带上），用户从头到尾不需要理解什么是 token。只有想手工配置或撤销连接的开发者，才展开"高级设置"看得到。

### 设置页长这样

```
┌──────────────────────────────────────────────────────────┐
│  Pivot Web > 设置 > 外部 AI 接入                           │
├──────────────────────────────────────────────────────────┤
│  ▸  高级设置（访问令牌、撤销连接、手工配置）  [展开]         │
├──────────────────────────────────────────────────────────┤
│  选择你的 AI 客户端：                                       │
│                                                           │
│    ┌──────────────────┐    ┌──────────────────┐          │
│    │ Claude Code      │    │ Cursor           │          │
│    │ [ 复制 Prompt ]   │    │ [ 一键安装 ]      │          │
│    └──────────────────┘    └──────────────────┘          │
│    ┌──────────────────┐    ┌──────────────────┐          │
│    │ Claude Desktop   │    │ Codex            │          │
│    │ [ 复制 URL+Token ]│    │ [ 复制 CLI 命令 ] │          │
│    └──────────────────┘    └──────────────────┘          │
│                                                           │
│    [ 其他 / 手动配置... ]                                  │
├──────────────────────────────────────────────────────────┤
│  已接入客户端：Claude Code（3 分钟前连上）                   │
└──────────────────────────────────────────────────────────┘
```

### 每家客户端的推荐方式

按客户端能力挑最稳方案，让用户**复制一下就能用**：

| 客户端 | 推荐方式 | 理由 |
|--------|---------|------|
| Claude Code | 复制一段 prompt，粘给 Claude，让它自己改配置 | Claude Code 自带文件读写，跨平台容错最强 |
| Cursor | `cursor://` 深链一键安装（浏览器唤起 Cursor 并自动填入 URL+Token） | Cursor 原生支持深链，零手工 |
| Codex | 复制 CLI 命令：`codex mcp add pivot --url ... --bearer-token-env-var PIVOT_TOKEN`（token 以环境变量注入） | Codex 有 CLI，避免手改 TOML |
| Claude Desktop | **复制 URL + Token** + 提示用户 "打开 Claude Desktop → Settings → Connectors → Add custom connector，粘贴即可" | Claude Desktop 不再从 JSON 文件加载远程服务，只能走 UI |

### 用户接入流程（按客户端分路）

```
                        Pivot Web 设置页
                               │
           ┌─────────────────┬─┴──────────────┬──────────────┐
           ▼                 ▼                ▼              ▼
   ┌──────────────┐  ┌──────────────┐ ┌──────────┐ ┌──────────────────┐
   │ Claude Code  │  │   Cursor     │ │  Codex   │ │ Claude Desktop   │
   ├──────────────┤  ├──────────────┤ ├──────────┤ ├──────────────────┤
   │ 复制 Prompt  │  │  点一键安装   │ │ 复制 CLI │ │ 复制 URL+Token    │
   │      ↓       │  │      ↓       │ │    ↓     │ │      ↓           │
   │ 粘到 Claude  │  │ 浏览器唤起    │ │ 终端粘贴 │ │ 打开 Desktop      │
   │      ↓       │  │    Cursor    │ │    ↓     │ │  Settings→       │
   │ Claude 自改  │  │      ↓       │ │ Codex    │ │  Connectors→     │
   │  配置        │  │  Cursor 确认 │ │ 添加     │ │  Add custom...   │
   │      ↓       │  │      ↓       │ │    ↓     │ │      ↓           │
   │  重启 → ✓    │  │      ✓       │ │ 重启→✓   │ │ 粘 URL+Token→✓    │
   │   ~2 min     │  │    ~30 秒    │ │ ~1 min   │ │     ~1 min        │
   └──────────────┘  └──────────────┘ └──────────┘ └──────────────────┘
```

### 小结

**MCP 服务端实施时必须同步做这个设置页。** 否则"一次配置、全员可用"只对开发者成立，对非技术同事就是"又一个踩坑入口"。

---

## 七、真实使用场景与复杂度账本

**这一节回答一个问题：让非技术同事用起来，到底有多难。**

### 场景：李明为 matter 写一篇 verify

李明是产品经理，平时不写代码，但会在 Claude Code 里改文档和跟 AI 讨论。今天他要给 matter「认证重构」验证前端同事提交的 003 / 004 两篇 act 文件。

#### 第一阶段 · 首次接入（只做一次，~2 分钟）

```
① Pivot Web 右上角 "设置" → "外部 AI 接入"
② 看到 4 个卡片，点 "Claude Code"
③ 点 "复制" 按钮（复制出的内容里已经包含连接所需的一切）
④ 切到 Claude Code，粘
⑤ Claude Code 按指示自动完成配置
⑥ 回 Pivot，看到 "已连接 Claude Code（刚才）"
```

**李明全程没看到过 "MCP"、"PAT"、"JSON" 这些词**。他的心智模型就是"复制一段→粘到 Claude Code→连上了"。

#### 第二阶段 · 日常使用（每次，~1 分钟）

```
⑦ 在 matter 页面找到 004 这篇 act，点卡片上的 "复制给 AI" 按钮
   → toast 提示 "已复制，粘到 AI 助手即可"

⑧ 切到 Claude Code，粘

⑨ Claude Code 自动回复：
   我读到了 「认证重构」matter（执行中）。你粘的是其中一篇
   act 文件《按修正后的登录链路推进实现》。要做什么？

⑩ 李明用自然语言说：
   帮我写个 verify，003 通过，004 边界没覆盖

⑪ Claude Code 在对话里展示完整草稿（人话格式），问 "要发吗？"

⑫ 李明看完，说 "发"

⑬ Claude Code 弹 approval 对话框 → 李明点 OK

⑭ Claude Code 回复：
   ✅ 已提交。这是 matter「认证重构」的第 7 篇。
      点这里查看：https://pivot.enclaws.ai/m/auth-redesign/f/007_...
```

### 复杂度账本

| 维度 | 数量 |
|------|------|
| 要学的技术概念 | **0 个**（MCP / PAT / JSON / TOML 一个都不用懂） |
| 要记的操作 | **1 个**："复制给 AI" → 粘到 Claude Code |
| 首次接入耗时 | ~2 分钟 |
| 日常使用耗时 | ~1 分钟 / 次 |
| 可能出错时的体感 | AI 用人话告诉用户出什么问题、怎么办（不是 401/403/409 码） |

### 对比：如果没有这个 MCP，李明要怎么做？

李明只能在 Pivot Web 里手工操作：

1. 打开 matter 详情页
2. 点 "新建文件" → 选类型 "verify"
3. 想：quote 选哪个？—— 去翻 timeline 找 004 的路径复制进来
4. 填结构化字段表格：`verifications[0].target` 填 003 路径、`judgement` 选 passed、`comment` 写几句；再加一项填 004……
5. 写正文
6. 发布

中间随时得查 "verify 跟 act 是什么关系"、"quote 和 refer 有什么区别"、"judgement 的 cancelled 啥时候用"。

**预计 15~30 分钟**。新手很容易填错（漏 verifications、quote 指向错文件、忘了设 owner 等），发出去之后返工。

### 用户怎么看正文？MCP 何时读正文？

常被问到的问题。不同用户意图对应不同姿势：

| 用户想做什么 | 发生的事 | Token 消耗 |
|------------|---------|-----------|
| **让 AI 总结或回答** —— "这文件讲了啥？" | AI 自动调 `read_files` 拉正文 → 用人话总结给用户看（原文进 AI context 但不贴出） | ~5-10K |
| **看完整原文** —— "把原文贴给我" | AI 调 `read_files` → 把 markdown 正文原样贴进对话里 | ~5-10K |
| **在 Pivot Web 上看** —— "我直接网页看" | AI 不读正文，只给 `view_url`，用户点开看格式化页面 | ~0 |
| **一次看多篇** | AI 一次 `read_files(paths=[A, B, C])` 批量拉 | 按篇累加 |

### AI 什么时候主动读？

AI 自主判断：
1. `resolve_context` 给了一句 summary —— 够回答"是什么"级别的问题
2. 用户继续问细节 —— AI 判断信息不够，**自动**调 `get_matter` 看 timeline 元信息（只要目录不要正文）
3. 判断需要哪几篇正文 —— **自动**调 `read_files(paths=[...])` 精准拉
4. **用户不用明说"请读 004"**，AI 自己知道

### 兜底场景

| 情况 | 兜底 |
|------|------|
| 单篇超 20K 字符 | `read_files` 自动截断前 20K 字 + 标记 `truncated: true`，AI 告知用户"超出部分看不到"+给 view_url 让用户去 Web 看全的 |
| 文件 refer 到别的 matter | V1 不支持跨 matter 读，AI 退回给 view_url |
| 用户想要比对两篇不同 matter 的文件 | V1 要在两次对话里分别处理，V1.1 可加跨 matter 支持 |

一句话：**AI 自主判断何时读、读哪几篇；用户要原文还是要总结靠对话自然决定；大文件 / 跨 matter 的兜底是 Pivot Web 的 view_url**。

### 这就是"好产品"的意思

| 轴 | 标准 | 我们达成没有 |
|----|------|-------------|
| 首次接入学习曲线 | ≤ 5 分钟，不需要看文档 | ✅ 2 分钟，0 概念 |
| 日常使用门槛 | 只要会用自然语言描述需求 | ✅ 粘 URL + 说一句话 |
| 出错时的挫败感 | 错误信息是人话、告诉用户怎么办 | ✅ AI 做了翻译层 |
| 对用户技术水平的要求 | 会用浏览器和 AI 聊天即可 | ✅ 无编程 / 无命令行 |

### 附：工具调用时序（技术参考）

这张图展示上面场景里 ⑧~⑭ 步，AI 客户端和 Pivot 之间到底发生了什么。**普通用户完全不需要看**，留给实现和评审的同事理解内部机制。

```
 用户         外部 AI        MCP 服务      Matter API
  │             │              │              │
  │  粘 URL ──▶ │              │              │
  │             │─ resolve ──▶ │              │
  │             │              │─ 校验存在 ──▶ │
  │             │◀── matter + ─│◀── OK ────── │
  │             │   人话摘要                    │
  │             │                             │
  │◀─ AI 回复  ─│                             │
  │   (转述人话摘要)                             │
  │             │                             │
  │  讨论… ──▶  │─ get_matter▶ │─ 拉 timeline▶│
  │             │◀── index ─── │◀── 元信息 ── │
  │             │  （无正文）                   │
  │             │                             │
  │             │─read_files ▶ │─ 拉正文 ────▶│
  │             │  [路径...]                   │
  │             │◀── 文件正文 ─│◀──────────── │
  │             │                             │
  │◀─讨论… ────│                             │
  │             │                             │
  │ 帮我起草 ──▶│                             │
  │             │ (AI 在自己的 context 里起草)  │
  │ 看草稿 ◀────│ (对话里出人话预览，等用户确认) │
  │             │                             │
  │ 发 ───────▶ │─create_file▶ │─ 校验 ──────▶│
  │             │  (完整字段)   │─ POST files▶│
  │             │              │              │─ 写入 Git
  │             │              │◀── 成功 + ── │
  │             │◀ summary_for_│  view_url    │
  │             │   ai + url                  │
  │◀── ✅+链接 ── │                             │
```

---

## 八、实施分工

这件事分成两条线，**本次我们只做其中一条**。

| 事项 | 谁做 | 状态 |
|------|------|------|
| 新 Matter API（`GET /api/matters`、`GET /api/matters/{id}`、`POST /api/matters/{id}/files`）| Index 重构线 | 设计已完成，待实现 |
| MCP 端点 `/mcp` + 5 个工具 | **本次** | 待设计确认、实现 |
| Pivot Web "复制给 AI" 按钮（matter / 文件页可见，toast 提示"已复制，粘到 AI 助手即可"） | **本次** | 待实现 |
| Pivot Web "外部 AI 接入"设置页（见 §六，4 家客户端配置生成） | **本次** | 待实现 |

**不需要 Index 重构线为本项目做任何额外调整**。我们完全复用 `pivot-interface.md` 末尾"Matter API（设计草案）"里已定义的接口：

- `GET /api/matters` —— 支撑 `list_matters` 工具
- `GET /api/matters/{matter_id}` —— 一次返回 header + 完整 timeline（含 `file` 路径、`type`、`summary`、`body` 等全量元信息和正文）
- `POST /api/matters/{matter_id}/files` —— 支撑 `create_file` 工具

**读侧的实现策略**：MCP 层在**自己这一侧**对 `GET /api/matters/{id}` 的响应做切分——

- `get_matter(id)` 工具：调接口拿到完整响应，**在 MCP 层把 `timeline[].body` 字段剥掉**再返回给 AI（只保留元信息，省 AI 上下文）
- `read_files(id, paths)` 工具：调同一个接口（配合短时内存缓存避免重复拉取），**在 MCP 层按 paths 过滤出对应的 body** 返回

这样做的代价是：后端每次都返回全量 body，带宽略浪费。但 V1 的 matter 体量小（每个 matter 十几篇文件量级），可接受。**等将来真的出现性能瓶颈**（超大 matter、上百篇文件），再让 Index 重构线按需补一个 `GET /api/matters/{id}/files?paths=...` 接口，MCP 层切换调用即可，对外工具签名不变。

**关键结论**：本项目 V1 **不阻塞于任何 Index 重构线的额外工作**，只要 Matter API 设计草案里的三个接口按现有设计落地，我们就能独立跑通。

---

## 九、访问控制

一句话：**MCP 不做任何自己的权限判断，全部透传给 Matter API**。

- 用户的 PAT 能读某个 matter → MCP 就能让 AI 读
- PAT 不行 → MCP 返回 401/403 给 AI，AI 告知用户

MCP 层只做"认证头转发"，不在 MCP 这一层重新实现权限模型。

---

## 十、MCP 层完全无状态

本次设计**不在 MCP 服务端保留任何草稿 / 会话 / 缓存**：

- 没有草稿表、没有 TTL、没有清理任务
- 没有 session 概念，每次请求独立
- AI 在自己的 context 里起草、打磨、改稿
- 用户点头 → AI 一次性调 `create_file`（approval 对话框里完整展示字段）→ 服务端校验并写入

**这样做的好处**：

1. 服务端简单——只做 HTTP 路由、字段校验、透传 Matter API
2. 不会被迫补一整套草稿管理 API（get_draft / update_draft / list_drafts...）
3. 命名自然（`create_file` 即创建文件，语义清晰）

**潜在代价**：AI 如果在跨天会话里"明天再改"，要么把上下文带回来，要么从头开始。实测下来这代价可接受——外部 AI 本来就是一次会话完成一篇的节奏。

---

## 十一、V1 的边界

| 在 V1 里 | 不在 V1 里 |
|----------|-----------|
| 读 matter 列表 / matter index / 按需读文件正文 | 跨 matter 读取（refer 到别的 matter 的文件） |
| 起草并一次性写入 think / act / verify / result / insight | 新建 matter（暂时先到 Web 建） |
| PAT 认证 | CLI 壳层 |
| 单 matter 作用域 | 搜索、评论流 |
| MCP 层无状态 | 编辑已提交的文件 |
| Pivot Web 设置页生成 4 家客户端接入方案 | 其他客户端（手动配置入口兜底） |

第一版优先跑通最小闭环。上述"不在 V1"的能力等真实使用中有明确需求再补。

---

## 十二、风险

1. **Matter API 未落地，MCP 无 upstream 可调**
   - 对策：设计并行、实现错峰。本文档就是并行设计的产物。

2. **不同 AI 客户端对 MCP 的实现成熟度不一**
   - Claude Code 最佳，Codex / ChatGPT 待验证
   - 对策：V1 联调优先在 Claude Code 上跑通；其他客户端发现不兼容再逐家适配

3. **AI 起草期间 matter 被别人改了（例如状态被迁移、相关文件被更新）**
   - 对策：`create_file` 时服务端会校验 matter 当前状态和前置条件；不一致返回 409 + 明确错误信息；AI 基于新状态重新起草再调用

---

## 十三、成功标准

以下流程能在**任何支持 MCP 的 AI 客户端**里跑通，不依赖该客户端的任何插件 / skill：

1. 用户在 Pivot Web 复制 URL
2. 粘到 AI 客户端，AI 自动识别出是 Pivot 上的某 matter
3. 用户和 AI 讨论后让它起草一篇 think/act/verify/result/insight
4. 用户审稿后点头
5. 该文件出现在 Pivot matter timeline 上

若以 Claude Code 为首要验证对象，上述链路跑通 = V1 达标。

---

## 十四、待评审关注点

1. **部署形态**选远程 HTTP 而不是本地命令行 MCP server，符合"一次配置、全员可用"的原则。但离线 / 企业内网场景 V1 不覆盖——是否接受？
2. **跨 matter 读取 V1 不做**——对当前实际使用场景影响有多大？
3. **CLI 完全延后**——是否接受，还是至少要在 V1 里放一个最简 `pivot cat matter/X` 用于调试？

---

## 附：本文档变更历史

- **2026-04-23**：初稿
- **2026-04-24**：根据评审意见调整
  - 读侧拆分：`get_matter` 不再返回文件正文，新增 `read_files` 按需读取
  - 写侧简化：移除服务端草稿，改为一步 `create_file` 写入（用户 gate 由 AI 客户端 approval 对话框天然提供）
  - 命名更自解释：`prepare_draft / submit_draft` → `create_file`
  - 新增 §六：Pivot Web "外部 AI 接入"设置页，覆盖 4 家客户端（Claude Code / Cursor / Codex / Claude Desktop）的接入引导
  - §五 给 `resolve_context` / `create_file` 补上三条协议约定（`user_facing_summary` / 调用前对话预览 / `summary_for_ai` + `view_url`）
  - §六 mockup 里"访问令牌"行默认折叠到"高级设置"，普通用户看不到 PAT
  - §六 追加 UX 原则："PAT 对普通用户永远不可见"
  - §八 分工表"复制上下文 URL 按钮" → "复制给 AI 按钮"
  - §七 整节重写为"真实使用场景与复杂度账本"，把李明的一次使用走完整，附复杂度量化、对比旧做法、对照好产品标准
  - §八 确认**不需要 Index 重构线为本项目做任何额外 API 调整**：读侧的 `get_matter` / `read_files` 切分改在 MCP 层做，后端完全复用 `pivot-interface.md` 设计草案里已有的三个 Matter 接口；对应删除 §十四 原先关于"Index 重构线新要求"的评审点
- **2026-04-24（晚）**：根据 AI 客户端实际支持情况调整传输协议与 Claude Desktop 接入路径
  - **传输**：由 SSE 改为 **Streamable HTTP**。MCP spec 2025-03-26 起废弃 SSE，2026-04-01 起 spec 已拒绝 SSE 连接；Claude Code / Cursor / Codex 三家都已完整支持 Streamable HTTP，本项目直接按终态实现，不做 SSE 兼容层
  - **Claude Desktop 接入**：由"复制 JSON 贴到配置文件"改为"复制 URL+Token → 桌面应用 Settings → Connectors → Add custom connector"。Claude Desktop 的 JSON 配置文件不再支持远程 HTTP 服务
  - **Cursor 配置格式**：确认 Cursor 的 `mcp.json` **不使用 `type` 字段**（直接 `url + headers`），设置页生成器需要按 Cursor 实际 schema 输出
  - §四 架构图、§六 客户端能力对比表/推荐方式/用户流程图都相应调整
  - 实施计划同步修订（见 `AI-docs/plans/2026-04-24-mcp-external-ai-plan.md` 的"方案变更记录"节）
  - §七 新增"用户怎么看正文？MCP 何时读正文？"子节：答复评审关心的"读正文"问题，列出 3 种常见姿势（AI 总结 / AI 贴原文 / Pivot Web 直接看）、AI 自主判断何时读正文的逻辑、超长文件和跨 matter 的兜底
