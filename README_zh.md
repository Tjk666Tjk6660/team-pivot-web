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

### EC 用户（通过 chat 安装）

在 EC 控制台 chat 或飞书中对 bot 说：

- **安装：** `请安装 team-pivot：git clone https://github.com/hashSTACS-Global/team-pivot.git ~/.enclaws/skills/team-pivot`
- **更新：** `请更新 team-pivot：cd ~/.enclaws/skills/team-pivot && git pull`
- **卸载：** `请卸载 team-pivot：rm -rf ~/.enclaws/skills/team-pivot`

安装后新开一个会话即可使用，EC 会自动发现该技能。

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

### 手动 CLI 安装

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
├── SKILL.md              # EC 技能定义（EC agent 自动发现）
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

**EC agent（飞书 / 网页 chat）：**
EC 自动发现 `SKILL.md` 并加载该技能。agent 通过 `pivot-cli` 命令管理讨论。

**Claude Code / Cursor（本地）：**
1. AI 读 `CLAUDE.md` 了解项目和自己的角色
2. AI 检查 `pivot-cli` 是否已安装，没有就从 `bin/` 安装
3. AI 用 `pivot-cli` 命令和 Pivot Agent 交互
4. AI 解析 JSON 返回，加上分析和格式化展示给用户

## 许可

内部使用。
