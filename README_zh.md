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

Team-Pivot 以 **EC skill** 形式发布。EC 机器人的 LLM 充当 pipeline runner —— 读 `SKILL.md`，根据用户意图找到对应 pipeline，逐 step 执行（Python step 通过 `python3 steps/<name>.py`，LLM step 由 LLM 自己生成输出）。

```
                    ┌─────────────────────────────────┐
  EC 机器人用户       │  飞书 / EC 网页 chat              │
                    └──────────┬──────────────────────┘
                               │ 自然语言
                               ▼
                    ┌─────────────────────────────────┐
                    │  EC 机器人（LLM）                 │
                    │  读 SKILL.md → 匹配 pipeline →   │
                    │  通过 Bash 执行 pipelines/<name>/│
                    │  steps/*.py                      │
                    └──────────┬──────────────────────┘
                               │ git commit/push
                               ▼
                    ┌─────────────────────────────────┐
                    │  Git workspace（共享大脑）         │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘

本地 Claude Code 用户走另一条路径：bin/pivot-cli（curl 包装），通过 HTTP
访问远端 Pivot endpoint。详见下面"Claude Code 用户"段落。
```

## 安装

<!-- ENCLAWS-BOT-INSTALL-START -->
### EnClaws 飞书机器人用户（chat 安装）

EC 机器人在每用户独立的沙箱中运行，其 cwd 为 `<tenant_dir>/users/<openId>/workspace/`。所有安装命令都通过相对路径 `../../` 定位到 tenant 根。

在 EC 机器人的对话（飞书或网页）中告诉它：

- **安装：**
  ```
  请安装 team-pivot：git clone https://github.com/hashSTACS-Global/team-pivot.git ../../team-pivot && mkdir -p ../../skills/pivot && cp ../../team-pivot/SKILL.md ../../skills/pivot/SKILL.md
  ```
- **更新：**
  ```
  请更新 team-pivot：cd ../../team-pivot && git pull && cp SKILL.md ../skills/pivot/SKILL.md
  ```
- **卸载：**
  ```
  请卸载 team-pivot：rm -rf ../../team-pivot ../../skills/pivot
  ```

**安装后的目录布局：**
```
<tenant_dir>/
├── skills/pivot/SKILL.md    ← EC 扫描的 skill 入口（拷贝）
└── team-pivot/              ← 真正的代码（pipelines/、tools/ 等）
```

安装后**开启新会话**，让 EC 重新发现 skill。

第一次实际使用 Team-Pivot（如"发起一个讨论"、"看看讨论列表"）时，机器人会通过飞书表单卡片向你收集：

1. **数据仓库 URL** —— 团队的讨论数据仓库（如 `https://github.com/your-org/teamDocs.git`）
2. **Git Token** —— 具备 commit/push 权限的 HTTPS PAT

收集后存到 `<tenant_dir>/team-pivot/.pivot-config.yaml`。第一个完成初始化的用户即为管理员。

> ⚠️ 建议在**与机器人的私聊**中完成首次配置，避免在群里暴露 token。

机器人读取 `SKILL.md`（从 `skills/pivot/SKILL.md` 加载，但所有操作都解析到 `team-pivot/`）完成执行，你不需要记任何命令。
<!-- ENCLAWS-BOT-INSTALL-END -->

### Claude Code 用户（本地 pivot-cli，独立路径）

> **说明：** 这是 **本地** Claude Code 工作流，与上面的 EC 机器人路径**完全独立**。EC 机器人用户**不需要** pivot-cli，直接和机器人对话即可。本节仅适用于：你想在自己电脑的 Claude Code 中通过 HTTP RPC 操作远端的 Pivot endpoint。

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
├── SKILL.md              # EC 技能定义 —— EC 机器人 LLM 作为 runner 读取
├── CLAUDE.md             # Claude Code 项目配置（仅本地 Claude Code）
├── bin/                  # 本地 pivot-cli（Claude Code 路径；EC 机器人不用）
│   ├── pivot-cli         # Bash CLI（Linux/macOS/Git Bash）
│   ├── pivot-cli.ps1     # PowerShell CLI（Windows）
│   ├── pivot-cli.cmd     # PATH 包装，从 CMD/PowerShell 调用 .ps1
│   ├── SKILL.md          # Claude Code 的 /pivot-cli 命令清单
│   └── install.sh        # 本地安装脚本（仅 Claude Code 路径）
├── pipelines/            # Pipeline 定义 —— 由 EC 机器人 LLM 执行（skill-as-runner）
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
├── tools/                # 共享 Python 模块（被 pipeline step 调用）
├── schemas/              # LLM step 输出的 JSON Schema
├── tests/                # 测试套件
└── pyproject.toml        # Python 打包
```

## AI 工具怎么用

**EC 机器人（飞书 / 网页 chat）—— 主要路径：**
执行 `git clone ... ~/.enclaws/skills/team-pivot` 后，EC 自动发现 `SKILL.md`。机器人 LLM 读 SKILL.md，把每条用户请求当作意图 → 找到对应 pipeline → 通过 Bash 执行 `pipelines/<name>/steps/*.py`（Python step）或自己生成输出（LLM step）。机器人**不调用** `pivot-cli`，直接和 pipeline 脚本对话。

**Claude Code / Cursor（本地）—— 独立路径：**
1. AI 读 `CLAUDE.md` 了解自己的角色
2. AI 检查 `pivot-cli` 是否已安装，没有就从 `bin/` 安装
3. AI 用 `pivot-cli` 命令（curl 包装）通过 HTTP 访问远端 Pivot endpoint
4. AI 解析 JSON 响应展示给用户

两条路径相互独立 —— 选适合你客户端的那条即可。

## 许可

内部使用。
