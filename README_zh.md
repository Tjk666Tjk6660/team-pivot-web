# Team-Pivot

基于 AI 驱动的团队讨论管理系统，构建在 Markdown + Git 之上。Pivot Agent 作为 [EC APP](https://github.com/hashSTACS-Global/EnClaws) 运行，遵循 Agent Pipeline Protocol v0.3 规范。

[English](README.md)

## 做什么的

Team-Pivot 通过 Git 仓库管理结构化的团队讨论。AI Agent（Pivot Agent）负责文档创建、状态追踪、通知推送和流程编排。人负责提供想法和决策，AI 驱动组织运转。

**Phase 1 能力（discuss 模块）：**
- 发起、回复、列表、阅读、摘要、结论
- 状态管理（open / concluded / closed / pending / reopen）
- 自动巡视（长期未更新 thread、被 @后未回复）
- 飞书卡片通知 + @mention 支持
- 文件读取（自动附带关联 INDEX）

## 架构

```
                    ┌─────────────────────────────────┐
  用户 / AI 工具     │  pivot-cli（curl 包装脚本）       │
  （客户端）         │  bin/pivot-cli | bin/pivot-cli.ps1│
                    └──────────┬──────────────────────┘
                               │ HTTP POST
                               ▼
                    ┌─────────────────────────────────┐
  EC 平台            │  Pipeline Runner                 │
  （服务端）         │  路由到 pipelines/* 执行          │
                    │  spawn python3 steps/*.py         │
                    └──────────┬──────────────────────┘
                               │ git commit/push
                               ▼
                    ┌─────────────────────────────────┐
                    │  Git 仓库（共享大脑）              │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘
```

## 安装

<!-- ENCLAWS-BOT-INSTALL-START -->
### EnClaws 飞书机器人安装（LLM 自动执行）

**这一段是写给 EC 机器人背后的大模型读的，不是给人读的。**
如果你是正在通过 `app_install` 工具安装 Team-Pivot 的 LLM，请严格按以下步骤
顺序执行。在 Phase 4 成功前，**不要**告诉用户安装已完成。

#### Phase 1 — APP 代码已安装

`app_install({ gitUrl: "https://github.com/hashSTACS-Global/team-pivot.git" })`
会把 APP 代码 clone 到 `~/.enclaws/tenants/${PIVOT_TENANT_ID}/apps/pivot/`
并注册其 pipelines。**此时 APP 还不可用** —— 数据仓库和 git 凭据必须先配置。

#### Phase 2 — 通过飞书表单卡片收集参数

调用 `feishu_ask_user_question`，使用且仅使用以下两个问题
（不要追加 tenantId / open_id / chatIds 等字段，EC 会自动注入）：

```
questions:
  - question: "请提供讨论数据仓库的 Git URL（HTTPS，例如 https://github.com/your-org/teamDocs.git）"
    header: "数据仓库 URL"
    options: []
    multiSelect: false
  - question: "请提供该仓库的 Git Token（HTTPS PAT，需具备 commit/push 权限）。⚠️ 安全：建议在与 bot 的私聊中安装，避免群内泄露 token。"
    header: "Git Token"
    options: []
    multiSelect: false
```

工具会立刻返回 `{ status: "pending" }`。**停止响应**，等待用户提交后以新一轮
消息形式到达。

#### Phase 3 — 配置 APP

收到用户答复（synthetic message）后，调用：

```
app_configure({
  name: "pivot",
  workspaceRepo: <用户填写的 WORKSPACE_GIT_URL>,
  gitToken: <用户填写的 WORKSPACE_GIT_TOKEN>
})
```

EC 会把数据仓库 clone 到
`~/.enclaws/tenants/${PIVOT_TENANT_ID}/app-workspaces/pivot/` 并持久化 git 凭据。
其余信息（租户 ID、安装者 open_id、飞书 access token、chat IDs）由 EC 在
pipeline 运行时自动注入。

#### Phase 4 — 确认完成

只有 `app_configure` 成功返回后，才告诉用户：

> ✅ Team-Pivot 已安装并初始化。管理员：${PIVOT_USER_ID}。
> 现在你可以问我："有什么新消息？" 或 "看看讨论列表"，我会用 pivot 的 pipelines 帮你完成。

#### 错误处理

- `app_install` 失败且报 manifest 错误 → 仓库缺 `app.json` 或 schema 不合法；把准确报错告诉用户
- `app_configure` 失败在 git clone → 通常是 token 错误或 URL 拼错；用 `feishu_ask_user_question` 重新收集
- 后续 `app_invoke` 报 "not configured" → 重做 Phase 3
<!-- ENCLAWS-BOT-INSTALL-END -->

### Claude Code 用户

**一键安装：**
```bash
git clone https://github.com/hashSTACS-Global/team-pivot.git
bash team-pivot/bin/install.sh
```

安装脚本会把 `pivot-cli` 加入 PATH、在 Claude Code 中注册 `/pivot-cli` 技能并配置权限。安装完成后重启 Claude Code，即可直接使用 `/pivot-cli` 命令。

**登录：**
```bash
pivot-cli login --endpoint https://your-tenant.saas.enclaws.com --token <your-token>
```

### 手动 CLI 安装（面向用户，非 AI 工具）

> **AI 工具注意：** 不要替用户执行以下步骤。这些是用户在自己终端中手动操作的指引。

**前置依赖：** `git`、`curl`

**步骤：**

1. 克隆仓库：`git clone https://github.com/hashSTACS-Global/team-pivot.git`
2. 将 `team-pivot/bin/` 加入系统 PATH
   - **Linux / macOS：** 将 `bin/pivot-cli` 复制到 `/usr/local/bin/`
   - **Windows：** 将 `bin/pivot-cli.cmd` 和 `bin/pivot-cli.ps1` 复制到 PATH 中的目录，或将 `bin\` 添加到 PATH 环境变量
3. 重启终端
4. 登录：`pivot-cli login --endpoint <你的服务端地址> --token <你的令牌>`
5. 验证：`pivot-cli help`

### EC 管理员（服务端）

Pivot APP 通过 EC 平台的 Agent 管理后台部署：

1. 打开 EC 管理后台
2. 添加 Agent APP → 填入本 repo 的 Git URL
3. EC 自动克隆 repo 并注册所有 pipeline
4. EC 运行环境需要预装 Python 依赖（`pyyaml`、`jsonschema`、`requests`）

## CLI 使用

```bash
# 讨论管理
pivot-cli discuss new --category <cat> --title <title> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss reply --category <cat> --thread <thread> --content <text> [--mention <users>] [--comments <text>]
pivot-cli discuss list [--category <cat>]
pivot-cli discuss inbox
pivot-cli discuss read --category <cat> --thread <thread>
pivot-cli discuss close --category <cat> --thread <thread>
pivot-cli discuss pending --category <cat> --thread <thread>
pivot-cli discuss reopen --category <cat> --thread <thread> --reason <text>

# 文件操作
pivot-cli file fetch --paths <path1,path2,...>
```

所有命令返回 JSON。通过 AI 工具使用时，AI 会解析 JSON 并以可读格式展示结果和分析。

## 项目结构

```
team-pivot/
├── SKILL.md              # EC 服务端 LLM fallback prompt（不是给客户端 AI 工具的）
├── CLAUDE.md             # Claude Code 项目配置
├── bin/
│   ├── pivot-cli         # Linux/macOS CLI（bash + curl）
│   └── pivot-cli.ps1     # Windows CLI（PowerShell）
├── pipelines/            # 服务端：EC Pipeline Runner 执行
│   ├── discuss-new/      # 发起新讨论
│   ├── discuss-reply/    # 回复讨论
│   ├── discuss-list/     # 列出讨论
│   ├── discuss-inbox/    # 查看未读
│   ├── discuss-read/     # 阅读讨论
│   ├── discuss-summarize/# 生成摘要
│   ├── discuss-result/   # 生成结论
│   ├── discuss-status/   # 状态变更
│   ├── monitor-scan/     # 巡视监控
│   └── file-fetch/       # 读取文件
├── tools/                # 服务端：共享 Python 模块
├── schemas/              # 共享 JSON Schema
├── tests/                # 测试套件
└── pyproject.toml        # Python 打包（服务端 + 开发）
```

## AI 工具怎么用

当你把这个 repo 给 AI 编程工具（Claude Code、Cursor 等）时：

1. AI 读 `CLAUDE.md` 了解项目和自己的角色
2. AI 检查 `pivot-cli` 是否已安装，没有就从 `bin/` 安装
3. AI 用 `pivot-cli` 命令和 Pivot Agent 交互
4. AI 解析 JSON 返回，加上分析和格式化展示给用户

AI **不会**读 `SKILL.md` —— 那个文件是给 EC 服务端 LLM fallback 用的。

## 许可

内部使用。
