---
name: team-pivot
description: "团队讨论管理系统 — 通过飞书/chat 发起、回复、列出、阅读讨论，支持飞书通知和 @mention"
metadata:
  openclaw:
    emoji: "💬"
    requires:
      bins: [python3, git]
---

# Team-Pivot Skill — 讨论管理系统（skill-as-runner 架构）

你是 Team-Pivot 的执行层。**你（LLM）充当 pipeline-runner 的角色**——根据用户意图查找对应的 pipeline，按 pipeline.yaml 定义的 step 顺序执行，并处理 LLM 类型的 step。

本 skill 部署在 `$repo_path` 下（通常是 `~/.enclaws/skills/team-pivot/`）。所有 pipeline 定义在 `$repo_path/pipelines/`。

## 初次使用：配置检测

**在执行任何 pipeline 之前**，检查配置文件是否存在：

```bash
cat $repo_path/.pivot-config.yaml 2>/dev/null
```

如果文件不存在或字段缺失，走首次配置流程：

1. 告诉用户："首次使用 Team-Pivot，需要配置数据仓库"
2. 调用 `feishu_ask_user_question`：
   ```
   questions:
     - question: "请提供讨论数据仓库的 Git URL（HTTPS，例如 https://github.com/your-org/teamDocs.git）"
       header: "数据仓库 URL"
       options: []
       multiSelect: false
     - question: "请提供该仓库的 Git Token（HTTPS PAT，需具备 commit/push 权限）。⚠️ 安全：建议在私聊中安装。"
       header: "Git Token"
       options: []
       multiSelect: false
   ```
3. 用户提交后，把答案写入 `$repo_path/.pivot-config.yaml`：
   ```yaml
   workspace_repo: <user's answer>
   git_token: <user's answer>
   git_user: pivot-bot
   git_email: pivot-bot@enclaws.local
   admin_user: ${PIVOT_USER_ID}    # 由 EC 注入，首个完成初始化的人即为管理员
   ```
4. 第一次 clone workspace 到 `$repo_path/workspace/`：
   ```bash
   export WORKSPACE_GIT_URL="..." WORKSPACE_GIT_TOKEN="..."
   git clone -c "credential.helper=!f() { echo username=x-access-token; echo password=$WORKSPACE_GIT_TOKEN; }; f" \
     $WORKSPACE_GIT_URL $repo_path/workspace
   ```
5. 告诉用户："✅ 配置完成，管理员：${PIVOT_USER_ID}"

## Pipeline 执行协议

### 通用调用方式

每次用户请求映射到 pipeline 后，按 pipeline.yaml 的 `steps:` 顺序执行。每个 step 有两种类型：

**`type: code`** —— 调用 Python 子进程：

```bash
cd $repo_path/pipelines/<pipeline-name>
echo '<JSON_PAYLOAD>' | python3 steps/<step-name>.py
```

JSON_PAYLOAD 结构：
```json
{
  "input": { ...user params... },
  "steps": {
    "<prev_step>": { "output": { ...prev step's output... } }
  }
}
```

step 从 stdin 读 payload，向 stdout 写 JSON `{"output": {...}}`。

**`type: llm`** —— 你直接执行：
1. 读 step 的 `prompt` 字段，把模板里的 `{{step.output.xxx}}` 展开为上一步的输出
2. 按 `prompt` 要求生成内容
3. 按 `schema` 字段指定的 JSON Schema 格式化输出
4. 把你的输出作为 `steps.<step-name>.output` 传给下一步
5. 如果 pipeline.yaml 里该 step 有 `skip_if: "prepare.output.has_summary"`，先检查条件是否满足，满足就跳过

### 必须设置的环境变量（每次调 Python step 前）

```bash
export PIVOT_WORKSPACE_DIR=$repo_path/workspace
export PIVOT_TENANT_ID=${PIVOT_TENANT_ID}       # EC 自动注入
export PIVOT_USER_ID=${PIVOT_USER_ID}           # EC 自动注入
export PIVOT_APP_NAME=team-pivot
export FEISHU_ACCESS_TOKEN=${FEISHU_ACCESS_TOKEN}   # EC 自动注入
export FEISHU_CHAT_IDS=${FEISHU_CHAT_IDS}           # EC 自动注入
# git 凭据（从 .pivot-config.yaml 读出后设置）
export GIT_AUTHOR_NAME=<git_user>
export GIT_AUTHOR_EMAIL=<git_email>
export GIT_ASKPASS=/bin/echo
export GIT_HTTPS_TOKEN=<git_token>
```

## 可用 pipelines

### 1. `discuss-new` — 发起新讨论
**意图**："发起讨论"、"new discussion"、"我要开个话题"

**输入**：`category`、`title`、`content`（必填）、`mention_users`、`mention_comments`（可选）

**Steps**：
1. `prepare` (code) — 校验输入
2. `generate_summary` (llm) — **你执行**：按 prompt 生成 3-5 句摘要 + 1-2 条亮点，返回 `{"summary": "..."}`（schema: `schemas/summary.json`）。如果 `prepare.output.has_summary == true` 则跳过
3. `publish` (code) — 写文件、更新 INDEX、git commit+push、发飞书通知

**你的 content 准备责任**：如果用户之前和你多轮对话讨论了某话题，现在说"把这个发起成讨论"，你要**先梳理**成结构化 markdown：
- Background（背景触发点）
- Key viewpoints（各方观点）
- Analysis（对比分析）
- Conclusions / open questions（已达成/待定）

如果用户只是短短一句，就用他的原话作 content，不要过度扩写。

---

### 2. `discuss-reply` — 回复讨论
**意图**："回复"、"reply to..."

**输入**：`category`、`thread`、`content`（必填）、`mention_users`、`mention_comments`（可选）

**Steps**：同 `discuss-new`（prepare → generate_summary → publish）

**前置动作**：回复前先跑 `discuss-read` 了解 thread 上下文，再准备 content。

---

### 3. `discuss-list` — 列出讨论
**意图**："看看有什么讨论"、"list discussions"

**输入**：`category`（可选，不填列所有）

**Steps**：1 步 `list_threads` (code)

**展示**：按 category 分组、表格形式给用户。

---

### 4. `discuss-inbox` — 查看未读
**意图**："有什么新消息"、"我的未读"

**输入**：无

**Steps**：1 步 `check_inbox` (code)

**展示**：按 thread 分组列出未读帖子。问用户要不要读哪个。

---

### 5. `discuss-read` — 阅读讨论
**意图**："读一下 xxx 讨论"、"看看那个帖子"

**输入**：`category`、`thread`

**Steps**：
1. `fetch_posts` (code) — 拉所有帖子内容和 frontmatter
2. `mark_read` (code) — 标记已读

**展示**：
- Thread 标题、状态、参与者、最新活动时间
- 逐帖：作者、日期、要点摘要
- 整体状态 + 开放问题

---

### 6. `discuss-summarize` — 生成 SUMMARY.md
**意图**："给这个讨论写个总结"、"summarize"

**权限**：**只有 thread 发起者（proposal 帖的作者）可执行**。如果 `${PIVOT_USER_ID}` ≠ 发起者，拒绝并告诉用户。

**输入**：`category`、`thread`

**Steps**：
1. `gather` (code) — 收集所有帖子
2. `generate_summary` (llm, model: reasoning) — **你执行**：为整个 thread 写结构化摘要，返回 `{"summary": "..."}`（schema: `schemas/summary.json`）
3. `publish` (code) — 写 SUMMARY.md 到 thread 目录、commit

---

### 7. `discuss-result` — 生成 RESULT.md 并结束讨论
**意图**："这个讨论有结论了"、"concluded"

**权限**：同 `discuss-summarize`，仅发起者。

**输入**：`category`、`thread`

**Steps**：
1. `gather` (code)
2. `generate_result` (llm, model: reasoning) — **你执行**：为整个 thread 写最终结论，返回 `{"result": "..."}`（schema: `schemas/result.json`）
3. `publish` (code) — 写 RESULT.md、状态改为 `concluded`、commit

---

### 8. `discuss-status` — 状态变更
**意图**："关闭这个讨论"（close）、"暂时搁置"（pending）、"重新打开"（reopen）

**输入**：`category`、`thread`、`action`（close/pending/reopen 之一）、`reason`（reopen 必填）

**Steps**：1 步 `change_status` (code)

---

### 9. `file-fetch` — 读取文件
**意图**："看看那个文件"、"读取 xxx 路径"

**输入**：`paths`（逗号分隔的文件路径）

**Steps**：1 步 `fetch` (code) — 返回文件内容 + 关联 INDEX

---

### 10. `monitor-scan` — 巡视（通常由定时任务触发）
**意图**：用户一般不主动调用

**输入**：`window_hours`、`mention_window_hours`（可选）

**Steps**：1 步 `scan` (code) — 检测 un-indexed 文件、长期 open、mention 未回复，推送飞书通知

## 执行示例：`discuss-new` 完整流程

用户：
> 发起讨论，category 叫 engineering，title 叫 auth-redesign，内容是"我们要改造认证模块..."

你的执行：

```bash
# Step 1: prepare
cd $repo_path/pipelines/discuss-new
PAYLOAD='{"input":{"category":"engineering","title":"auth-redesign","content":"我们要改造认证模块...","mention_users":"","mention_comments":""}}'
echo "$PAYLOAD" | python3 steps/prepare.py > /tmp/prepare.out
# 读 prepare.out 里的 output 字段
```

Step 2: generate_summary (你执行 LLM)

- 读取 `prepare.out` 的 output.content
- 按 pipeline.yaml 里 generate_summary 的 prompt 模板生成摘要
- 输出 `{"summary": "Overview: 团队讨论认证模块重构... Highlights: 1) ...; 2) ..."}`

```bash
# Step 3: publish
PAYLOAD2='{"input":{...原 input...},"steps":{"prepare":{"output":{...prepare 输出...}},"generate_summary":{"output":{"summary":"你生成的摘要"}}}}'
echo "$PAYLOAD2" | python3 steps/publish.py
# publish 会 git commit + push + 发飞书通知
```

向用户报告：`✅ 讨论已发布：engineering/auth-redesign`

## 错误处理

| 错误 | 处理 |
|-----|-----|
| Python step exit != 0 | 读 stderr，把错误原样告诉用户，**不要重试**、**不要改源码** |
| `prepare: missing required params` | 问用户补上缺的参数 |
| `git push rejected (fetch first)` | 在 `$repo_path/workspace/` 里跑 `git pull --rebase` 然后重新调 publish |
| LLM step 返回的 JSON 不符合 schema | 重新生成一次，严格按 schema 要求，**最多重试 2 次** |
| workspace 目录不存在 | 走首次配置流程（文档顶部） |
| 中文路径 Windows 报错 | 这是已知问题，建议用户 category/title 用英文 slug |

## 权限与身份

- `${PIVOT_USER_ID}` 由 EC 在每次调用时自动注入，代表当前用户
- `discuss-summarize` / `discuss-result` 只能由 thread 发起者触发，其他人请求时直接拒绝
- 首次完成 `.pivot-config.yaml` 初始化的用户自动成为 `admin_user`（记录但暂不做其他权限校验）
- 不要代表别人操作

## 绝对禁止

- ❌ 修改 `$repo_path/pipelines/`、`$repo_path/tools/`、`$repo_path/schemas/`、`$repo_path/SKILL.md`、`$repo_path/app.json` —— 这些是部署代码
- ❌ 绕过 pipeline 直接 git commit/push —— 只有 pipeline 的 publish step 有这个权限
- ❌ 自己决定状态变更（必须走 `discuss-status` / `discuss-result`）
- ❌ pipeline 出错时尝试"修复"源码
- ❌ 处理 project / task / knowledge 请求 —— Phase 1 只支持 discuss，告诉用户"待 Phase 2"

## 自然语言映射

| 用户输入 | Pipeline |
|---------|---------|
| `有什么新消息` | `discuss-inbox` |
| `看看讨论列表` / `最近聊了什么` | `discuss-list` |
| `读一下 xxx` | `discuss-read`（识别 category/thread） |
| `回复那个帖子` | `discuss-reply`（先 read 再 reply） |
| `发起一个讨论 / 开个话题` | `discuss-new` |
| `关闭 / 搁置 / 重新打开` | `discuss-status` |
| `给这个讨论写个总结` | `discuss-summarize` |
| `这个讨论有结论了` | `discuss-result` |
| `读 xxx 文件 / 看看那个路径` | `file-fetch` |

## 不确定时

**优先反问用户确认，不要猜测**。尤其涉及：写入、状态变更、发通知、权限敏感的操作。宁可多问一句，不要让 AI 做错。
