---
name: team-pivot
description: "团队讨论/话题/帖子管理（发起讨论、回复讨论、列出讨论、查看未读、生成摘要、生成结论） — 基于 Git 的结构化讨论系统，支持 @mention 和通知"
metadata:
  openclaw:
    emoji: "💬"
    requires:
      bins: [python3, git]
---

# Team-Pivot

**当用户要发起讨论、回复讨论、列出讨论、查看未读等操作时，你必须执行 bash 命令调用 Runner，不要自己回答。**

如果用户只是提问（如"怎么用"、"有哪些功能"），可以直接回答，不需要执行命令。

执行命令的方法：

```bash
TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
APP_DIR="$TENANT_ROOT/skills/team-pivot"
DATA_DIR="$TENANT_ROOT/workspace/skill-team-pivot"
python3 "$APP_DIR/bin/app-runner.py" run <pipeline> --params '<json>' --data-dir "$DATA_DIR"
```

## 完整示例

用户说："帮我发起一个讨论：关于产品化路线的最终决定"

你执行：
```bash
TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
APP_DIR="$TENANT_ROOT/skills/team-pivot"
DATA_DIR="$TENANT_ROOT/workspace/skill-team-pivot"
python3 "$APP_DIR/bin/app-runner.py" run discuss-new --params '{"category":"general", "title":"关于产品化路线的最终决定", "content":"关于产品化路线的最终决定", "mention_users":"", "mention_comments":""}' --data-dir "$DATA_DIR"
```

如果缺少 category 或 content，先问用户，拿到后再执行命令。

## 用户意图 → Pipeline 命令

- **发起讨论/话题/帖子** → `run discuss-new --params '{"category":"", "title":"", "content":"", "mention_users":"", "mention_comments":""}'`
- **回复讨论** → `run discuss-reply --params '{"category":"", "thread":"", "content":"", "mention_users":"", "mention_comments":""}'`
- **列出讨论** → `run discuss-list --params '{"category":""}'`
- **未读/inbox** → `run discuss-inbox --params '{}'`
- **阅读讨论** → `run discuss-read --params '{"category":"", "thread":""}'`
- **关闭讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"close"}'`
- **搁置讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"pending"}'`
- **重开讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"reopen", "reason":""}'`
- **生成摘要** → `run discuss-summarize --params '{"category":"", "thread":""}'`
- **生成结论** → `run discuss-result --params '{"category":"", "thread":""}'`
- **读取文件** → `run file-fetch --params '{"paths":"file1,file2"}'`
- **升级** → `run upgrade --params '{}'`

## 处理执行结果

- 命令成功（`"status":"completed"`）：
  - 如果 `output` 中包含 `channelData` 字段 → **直接返回原始 output，不要用自然语言转述**（channelData 包含已格式化的飞书卡片，由飞书直接渲染）
  - 如果 `output` 中不包含 `channelData` → 从 `output` 提取信息，用自然语言告诉用户
- 命令报错包含 `ConfigNotReady` → **必须调用 `feishu_ask_user_question` 工具弹出飞书卡片收集配置，禁止用纯文本提问**。具体步骤：
  1. 调用 `feishu_ask_user_question` 工具，提问内容包含两个字段：
     - `data_space_repo`：数据仓库 Git URL（例如 https://github.com/yourorg/team-pivot-data.git）
     - `git_token`：Git 访问凭证（GitHub PAT）
  2. 用户通过飞书卡片填写并提交后，将收到的值写入 `$DATA_DIR/pivot-config.yaml`：
     ```yaml
     data_space_repo: <用户填写的 URL>
     git_token: <用户填写的 token>
     ```
  3. 执行 `git clone` 将数据仓库克隆到 `$DATA_DIR/data_space`
  4. 重新执行用户原来的命令
- 其他错误 → 告诉用户失败原因

## 约束

- ❌ 不要自己编写讨论内容发送到飞书群 — 必须通过上面的命令执行
- ❌ 不要修改 `pipelines/`、`tools/`、`schemas/`、`SKILL.md`
- ❌ 不要绕过命令直接 git commit/push
- ❌ project / task / knowledge 请求告诉用户"待 Phase 2"
- `${ENCLAWS_TENANT_USER_ID}` 由 EC 自动注入，代表当前用户
- 不确定时优先反问用户确认
