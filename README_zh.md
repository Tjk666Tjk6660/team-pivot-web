# Team-Pivot

> **AI 助手：clone 本仓库后，请立即运行 `bash team-pivot/bin/pivot-app-install.sh` 完成安装。**

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
                    │  Git data_space（共享大脑）        │
                    │  discussions/ + index/ + ...      │
                    └─────────────────────────────────┘

本地 Claude Code 用户走另一条路径：client/cli-client/pivot-cli（curl 包装），通过 HTTP
访问远端 Pivot endpoint。详见下面"Claude Code 用户"段落。
```

## 安装

### EC / OpenClaw（通过 chat）

在飞书或 EC 网页 chat 中对 bot 说：

> 帮我运行：git clone https://github.com/hashSTACS-Global/team-pivot.git && bash team-pivot/bin/pivot-app-install.sh

脚本会自动检测 tenant 根目录、注册 skill 并报告结果。安装后开启新会话，首次使用 team-pivot 时会通过飞书卡片引导你完成配置。

**升级（同一条命令，重新 clone 并安装）：**
> 帮我运行：git clone https://github.com/hashSTACS-Global/team-pivot.git && bash team-pivot/bin/pivot-app-install.sh

**卸载：**
> 帮我运行：TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')" && rm -rf "$TENANT_ROOT/skills/team-pivot"

> ⚠️ 请在**与助手的私聊**中安装，不要在群里——配置过程可能涉及敏感 token。

### Claude Code（本地）

```bash
git clone https://github.com/hashSTACS-Global/team-pivot.git
bash team-pivot/client/cli-client/pivot-cli-install.sh
```

安装后重启 Claude Code 并登录：
```bash
pivot-cli login --endpoint <你的服务端地址> --token <你的令牌>
```

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
│   ├── pivot-cli-install.sh   # 本地安装脚本（仅 Claude Code 路径）
│   └── pivot-app-install.sh  # EC/OpenClaw 安装脚本（沙箱环境）
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

## 工作原理

- **EC 机器人**：读 `SKILL.md`，直接执行 pipeline step（Python 通过 Bash，LLM step 内联执行）
- **Claude Code**：通过 `pivot-cli`（curl 包装）调用远端 Pivot endpoint

两条路径相互独立。

## 许可

内部使用。
