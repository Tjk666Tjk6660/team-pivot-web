# Team-Pivot 架构设计

## 1. 总体理念

Team-Pivot 是一个团队讨论管理系统，作为 EnClaws（EC）平台上的 APP/Skill 运行。核心设计原则：

- **业务逻辑与展示逻辑严格分离**
- **数据仓库作为单一事实源**（通过 Git 管理）
- **Pipeline 是唯一的业务执行单元**，LLM 不能绕过 pipeline 直接操作数据
- **多渠道适配**：当前支持飞书，未来支持 WebView、CLI、Slack 等

## 2. 分层架构

```
┌──────────────────────────────────────────────┐
│ 渠道层 (EC Gateway)                           │
│ 飞书 / 企微 / Slack / WebView / ...           │
└────────┬─────────────────────────────────────┘
         │ 用户意图（自然语言）
         ▼
┌──────────────────────────────────────────────┐
│ EC Agent (LLM 编排)                           │
│ 读取 SKILL.md，理解意图，调用对应 pipeline      │
└────────┬─────────────────────────────────────┘
         │ pipeline 命令（bash exec）
         ▼
┌──────────────────────────────────────────────┐
│ App Runner (app-runner.py)                   │
│ 读 pipeline.yaml，编排 code/llm step          │
└────────┬─────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────┐
    ▼                                    ▼
┌───────────────────────┐     ┌─────────────────────────┐
│ Pipeline 业务层         │     │ LLM Backend              │
│ pipelines/*/steps/*.py │     │ 通过 EC Gateway API      │
│ tools/ 共享工具         │     │ 调用 LLM 完成 llm step   │
└────────┬──────────────┘     └─────────────────────────┘
         │ Pipeline 输出（canonical 数据）
         ▼
┌──────────────────────────────────────────────┐
│ Adapter 展示层 (adapters/*)                   │
│ 把 pipeline 输出适配成特定 channel 的格式      │
│ feishu/card_formatter.py                     │
│ webview/html_renderer.py（未来）              │
└──────────────────────────────────────────────┘
```

## 3. 业务逻辑 vs 展示逻辑的边界

这是架构中最关键的分界线。

### 3.1 Pipeline 层（业务逻辑，channel-agnostic）

**归属**：
- 所有数据 CRUD 操作（草稿、讨论、索引、状态）
- 业务规则（如"草稿最多 5 条"、"回复必须关联 thread"）
- 数据格式转换（文件转 Markdown、索引构建）
- Git 仓库操作

**特征**：
- 不关心谁调用、在哪里显示
- 输出**完整的、canonical 的数据结构**
- 不做任何针对 UI 的截断、分页、格式化

### 3.2 Adapter 层（展示逻辑）

**归属**：
- channel 特有的格式化（飞书卡片 JSON、HTML、终端 ANSI）
- channel 特有的物理限制处理（飞书卡片 30KB、终端行宽）
- channel 特有的交互元素（按钮、链接、表单）

**特征**：
- 每个 channel 一个独立的 adapter
- 接受相同的 pipeline 输出
- 针对本 channel 做合适的渲染

### 3.3 典型场景

| 需求 | 归属 | 理由 |
|------|------|------|
| 草稿 CRUD | Pipeline | 纯业务 |
| 草稿最多 5 条 | Pipeline | 业务规则（任何 UI 都生效） |
| draft_id 命名规则 | Pipeline | 数据标识 |
| 文件转 Markdown | Pipeline | 数据转换 |
| 飞书卡片 30KB 限制下的截断 | Adapter（飞书） | channel 物理约束 |
| 列表显示时每条分配多少字符 | Adapter（飞书） | 展示策略 |
| "回复 xxx 查看全文"的提示 | Adapter（飞书） | 交互引导 |
| WebView 完整渲染不截断 | Adapter（WebView） | WebView 没有大小限制 |
| 终端按屏宽换行 | Adapter（CLI） | 终端特有约束 |

## 4. 目录结构

```
team-pivot/
├── SKILL.md                          # skill 定义（EC agent 读取）
├── pivot.yaml                        # 版本号、升级配置
├── pivot-config.yaml                 # 用户配置模板
├── README.md / README_zh.md
├── CLAUDE.md                         # 开发者指南
│
├── docs/                             # 设计文档
│   └── architecture.md               # 本文档
│
├── bin/                              # 运行时入口
│   ├── app-runner.py                 # pipeline 编排器
│   ├── llm_gateway.py                # EC Gateway LLM Backend
│   ├── pivot-app-install.sh          # 在 EC 沙箱中安装
│   └── pivot-check-config.sh         # 配置完整性检查
│
├── pipelines/                        # 业务逻辑层（channel-agnostic）
│   ├── _constructor/                 # 全局前置（config 校验）
│   ├── _destructor/                  # 全局后置
│   ├── check-env/                    # 环境依赖检查
│   ├── upgrade/                      # 自升级
│   │
│   ├── draft-new/                    # 草稿管理
│   ├── draft-list/                   #   — 返回所有草稿完整数据
│   ├── draft-read/                   #   — 读单条草稿
│   ├── draft-edit/
│   ├── draft-delete/
│   ├── draft-new-from-file/          #   — 文件转草稿（PDF/Word/MD/TXT）
│   │
│   ├── discuss-new/                  # 讨论发布（依赖草稿）
│   ├── discuss-reply/                # 回复（依赖草稿）
│   ├── discuss-list/
│   ├── discuss-read/
│   ├── discuss-inbox/
│   ├── discuss-status/
│   ├── discuss-summarize/
│   ├── discuss-result/
│   ├── file-fetch/
│   └── monitor-scan/
│
├── tools/                            # 共享业务工具
│   ├── atomicity.py                  # 原子文件写入
│   ├── config.py                     # PipelineContext 构造
│   ├── drafts.py                     # 草稿 CRUD 核心
│   ├── git_ops.py                    # Git 操作封装
│   ├── index.py                      # 讨论索引
│   ├── threads.py                    # 讨论目录遍历
│   └── notify/                       # 通知模块
│
├── adapters/                         # 展示适配层
│   └── feishu/
│       ├── __init__.py
│       └── card_formatter.py         # 飞书卡片格式化
│   # 未来扩展：
│   # ├── webview/
│   # │   └── html_renderer.py
│   # ├── slack/
│   # │   └── block_kit.py
│   # └── cli/
│   #     └── terminal.py
│
├── client/cli-client/                # 本地 Claude Code CLI 客户端
│   ├── pivot-cli                     # bash 版
│   ├── pivot-cli.cmd                 # Windows 版
│   ├── pivot-cli.ps1                 # PowerShell 版
│   ├── pivot-cli-install.sh
│   └── SKILL.md                      # Claude Code skill 定义
│
├── tests/
│   ├── ec_simulator/                 # EC 环境模拟
│   ├── integration_test/
│   └── pipeline_test/
│
├── conftest.py                       # pytest 共享 fixture（必须根目录）
├── pyproject.toml                    # Python 项目配置（必须根目录）
└── .gitignore
```

## 5. 运行时数据布局

### 5.1 EC 租户级（多用户共享）

```
$TENANT_ROOT/                         # /home/enclaws/.enclaws/tenants/{tid}/
├── skills/team-pivot/                # 应用代码（只读，升级时覆盖）
│   ├── SKILL.md
│   ├── pivot.yaml
│   ├── bin/
│   ├── pipelines/
│   ├── tools/
│   └── adapters/
│
└── workspace/skill-team-pivot/       # 租户级共享数据（持久，升级不动）
    ├── pivot-config.yaml             # 数据仓库配置 + token
    ├── data_space/                   # Git 仓库镜像
    │   ├── discussions/
    │   ├── index/
    │   └── .git/
    └── install.log                   # 安装日志
```

### 5.2 EC 用户级（每个飞书用户独立）

```
$ENCLAWS_USER_WORKSPACE/              # tenants/{tid}/users/{uid}/workspace/
└── skill-team-pivot-drafts/          # 用户私有草稿
    ├── draft-20260417-0238-1.md
    ├── draft-20260417-0245-1.md
    └── ...
```

**设计考量**：草稿是个人的、未公开的内容，按用户隔离；讨论数据是团队共享的，按租户隔离。

## 6. Pipeline 执行模型

### 6.1 执行流程

```
1. EC LLM 读 SKILL.md，理解用户意图
2. LLM 调用 bash: python3 app-runner.py run <pipeline> --params '...' --data-dir <...>
3. app-runner.py:
   a. 执行 _constructor pipeline（config 校验）
   b. 执行目标 pipeline 的 steps
      - type: code  → subprocess 执行 Python 脚本
      - type: llm   → 通过 GatewayLLMBackend 调用 LLM API
   c. 执行 _destructor pipeline（清理）
   d. 调用 adapter 格式化输出
4. stdout 返回 JSON（包含 channelData 供飞书直接渲染）
5. EC 读取 channelData 发送飞书卡片，或转交 LLM 自然语言响应
```

### 6.2 Pipeline 输出契约

Pipeline 输出统一格式：

```json
{
  "status": "completed" | "error",
  "output": {
    // 业务数据（完整、canonical）
    "drafts": [...],
    "count": 5,
    "channelData": {
      "feishu": {
        "card": { ... }      // adapter 生成的飞书卡片
      }
    }
  },
  "error": null
}
```

**关键约定**：
- `output` 里的业务字段是 channel-agnostic 的完整数据
- `channelData` 是 adapter 加进去的展示数据
- EC LLM 看到 `channelData` 时不转述，直接让飞书渲染；没有时才用自然语言描述

## 7. LLM 调用机制

### 7.1 当前：GatewayLLMBackend

Pipeline 中的 `llm` step 通过本地 EC Gateway 的 OpenAI 兼容 API 调用：

```
POST http://127.0.0.1:18888/v1/chat/completions
Authorization: Bearer <gateway_token>
x-enclaws-session-key: <current session>
x-enclaws-tenant-id: <tenant>
```

### 7.2 Token 归因

当前 EC 的 `/v1/chat/completions` 不从请求头提取 tenant，导致子进程调用的 LLM token 消耗未归因到原飞书会话。已提交 feature request（EnClaws#29）。

EC 修复后 usage 自动归因，runner 代码不用改。

### 7.3 临时方案

在 EC 注入 `ENCLAWS_GATEWAY_TOKEN` 之前，`llm_gateway.py` 从 SQLite 数据库读取 token。EnClaws#29 合入后删除此 fallback。

## 8. 草稿机制

### 8.1 数据模型

每份草稿是一个带 YAML frontmatter 的 Markdown 文件：

```markdown
---
draft_id: draft-YYYYMMDD-HHMM-{n}
type: proposal | reply
category: general
title: "..."
thread: "..."             # 仅 reply
source: text | file:filename.ext
created_at: ISO8601
---

<正文>
```

### 8.2 生命周期

```
创建：draft-new 或 draft-new-from-file（文件转换）
      ↓
查看：draft-list（概览） / draft-read（详情）
      ↓
编辑：draft-edit
      ↓
发布：discuss-new 或 discuss-reply（以 draft_id 为输入）
      ↓
      publish 成功后 cleanup step 自动删除
      
手动删除：draft-delete（不发布的废弃草稿）
```

### 8.3 业务规则

- 每个用户最多 5 份草稿
- 超过上限时创建失败，提示用户先删除
- `discuss-new` / `discuss-reply` 必须传 `draft_id`，不接受直接传 content
- 发布成功后草稿自动删除

### 8.4 文件转草稿支持格式

| 扩展名 | 转换方式 | 依赖 |
|--------|---------|------|
| `.md` / `.markdown` / `.txt` | 直接读 | 无 |
| `.docx` / `.doc` | pandoc | pandoc |
| `.pdf` | pdftotext | poppler |
| 其他 | 报错 | — |

依赖不在安装时检查，运行到需要时才检查，缺了给出具体安装命令。`check-env` pipeline 可提前检查所有依赖。

## 9. 错误处理原则

SKILL.md 中明确：**LLM 是 pipeline 的调用者，不是调试者**。

- Pipeline 出错 → 直接把错误报告给用户
- 不允许 LLM 自行修改配置、重试、或用 fallback 方案替代 pipeline
- 不允许绕过 pipeline 直接 git 操作数据仓库
- 未命中任何 pipeline 时才允许 LLM 自由组合 `pipelines/` 下的 steps，但仍不能直接操作数据仓库

## 10. 未来演化方向

### 10.1 WebView 集成

长期看，所有需要复杂交互的功能（编辑草稿、浏览讨论、可视化）应该迁移到 WebView。

**演化路径**：
1. **Phase 1**：新增 `adapters/webview/` + skill 内置轻量 HTTP server，渲染草稿只读页面
2. **Phase 2**：WebView 支持编辑、回复、状态变更，bot 退化为通知器
3. **Phase 3**：WebView 独立部署，支持多租户 SaaS，bot 成为可选入口之一

### 10.2 多渠道支持

`adapters/` 按 channel 横向扩展：
- `adapters/slack/block_kit.py`
- `adapters/wecom/card.py`
- `adapters/cli/terminal.py`

每个 adapter 独立开发，不影响业务层和其他 channel。

### 10.3 交互卡片（飞书）

当前 EC 只支持有限的卡片 action（`ACTION_SUBMIT`、`app_auth_done`）。未来如果 EC 支持通用的"卡片 action → pipeline 调用"，就可以做：

- `draft-list` 卡片每条加"查看详情"按钮，点击触发 `draft-read`
- 回复卡片加"同意/反对"投票
- 列表加分页按钮

这需要给 EC 提 feature request。

## 11. 版本与升级

- `pivot.yaml` 中的 `version` 字段跟随每次发布递增
- `upgrade` pipeline 检查远端版本并调用 `pivot-app-install.sh` 完成升级
- 升级只覆盖 skill 目录下的代码，不触碰 `workspace/skill-team-pivot/` 下的用户数据
- 老数据位置的自动迁移在 install 脚本中处理（第一次从旧路径迁移到新路径后删除旧路径）
