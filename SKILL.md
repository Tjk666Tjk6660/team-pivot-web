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

## 草稿机制（重要）

**发起讨论 / 回复讨论都必须先有草稿**。用户说"发起讨论"或"回复"时，按这个流程：

1. 运行 `draft-list` 查看当前草稿
2. 如果没有草稿 → 引导用户先创建（用 `draft-new`，或让用户上传文件用 `draft-new-from-file`）
3. 如果有一个草稿 → 与用户确认后，用 `discuss-new` 或 `discuss-reply` 发布
4. 如果有多个草稿 → 列出来让用户选择，拿到 `draft_id` 后发布
5. 发布成功后草稿会自动删除

**如果用户上传了文件**：用 `draft-new-from-file` 把文件转为草稿，支持 `.md` `.txt` `.docx` `.doc` `.pdf`。其他格式直接报错。

## 完整示例

用户说："帮我发起一个讨论：关于产品化路线的最终决定"

**第一步**：先创建草稿（如果用户还没有准备好内容，询问用户；准备好了再调用）
```bash
TENANT_ROOT="$(pwd | sed -E 's|(.*/\.enclaws/tenants/[^/]+).*|\1|')"
APP_DIR="$TENANT_ROOT/skills/team-pivot"
DATA_DIR="$TENANT_ROOT/workspace/skill-team-pivot"
python3 "$APP_DIR/bin/app-runner.py" run draft-new --params '{"type":"proposal","category":"general","title":"关于产品化路线的最终决定","content":"..."}' --data-dir "$DATA_DIR"
```

**第二步**：用返回的 `draft_id` 发布
```bash
python3 "$APP_DIR/bin/app-runner.py" run discuss-new --params '{"draft_id":"<上一步返回的 id>","mention_users":"","mention_comments":""}' --data-dir "$DATA_DIR"
```

## 意图识别原则

**凡是涉及"草稿 / draft"的任何操作，都必须走 team-pivot 的 draft-* pipeline**。
**凡是涉及"讨论 / 话题 / 帖子 / thread"的任何操作，都必须走 team-pivot 的 discuss-* pipeline**。

**不允许擅自把"草稿"理解为"通用文档"或"文字创作"**，team-pivot 里的草稿**只有两种**：
- `proposal`：发起新讨论用的草稿
- `reply`：回复某个讨论用的草稿

**不允许编造"文档草稿""文字草稿""文案草稿"等不存在的类型**。如果用户只说"写草稿/编写草稿"，默认按 `proposal` 处理；或者反问一下是新讨论还是回复。

## 用户意图 → Pipeline 命令

### 草稿管理（任何涉及"草稿"的请求）

**创建草稿** — 触发词举例：
> "新建草稿" / "创建草稿" / "起草" / "编写草稿" / "写草稿" / "写个草稿" / "起个草稿" / "我想写草稿" / "draft" / "new draft" / "create draft" / "草稿"（孤词也算）

→ `run draft-new --params '{"type":"proposal","category":"<分类>","title":"<标题>","content":"<内容>","thread":""}'`
  - `type`：`proposal`（新讨论草稿，默认） 或 `reply`（回复草稿）
  - `category`：仅 `proposal` 时必填；`reply` 时可留空（从 thread 推导）
  - `thread`：仅 `reply` 时必填

**上传文件为草稿** — 用户发送 `.md/.txt/.docx/.doc/.pdf` 文件时：
→ `run draft-new-from-file --params '{"file_path":"<EC 保存的路径>","type":"proposal","category":"<分类>","title":"","thread":""}'`

**列出我的草稿** — 触发词举例：
> "我的草稿" / "草稿列表" / "查看草稿" / "列出草稿" / "有哪些草稿" / "list drafts" / "draft list"

→ `run draft-list --params '{}'`

**查看某个草稿的完整内容** — 触发词举例：
> "读取草稿 xxx" / "查看草稿 xxx" / "打开 xxx" / "显示 xxx"（xxx 是 draft_id 或列表里的序号）

→ `run draft-read --params '{"draft_id":"<draft_id>"}'`

**编辑草稿** — 触发词举例：
> "编辑草稿 xxx" / "修改草稿 xxx" / "改草稿"

→ `run draft-edit --params '{"draft_id":"","title":"","content":""}'`

**删除草稿** — 触发词举例：
> "删除草稿 xxx" / "删草稿"

→ `run draft-delete --params '{"draft_id":""}'`

### 发布讨论（必须基于已有草稿）

**发起新讨论** — 触发词举例：
> "发起讨论" / "创建讨论" / "发布讨论" / "发起话题" / "发帖" / "new discussion"

→ 步骤：
1. 先 `run draft-list` 看用户有什么草稿
2. 如果没有 `proposal` 草稿，引导用户先 `draft-new` 或上传文件
3. 有一个 proposal 草稿 → 与用户确认后发布
4. 有多个 proposal 草稿 → 列出让用户选
5. 发布命令：`run discuss-new --params '{"draft_id":"<id>","mention_users":"","mention_comments":""}'`

**回复讨论** — 触发词举例：
> "回复 xxx" / "回复讨论" / "跟帖" / "reply"

→ 同上，但草稿类型必须是 `reply`，然后 `run discuss-reply --params '{"draft_id":"<id>","mention_users":"","mention_comments":""}'`

### 查询与管理讨论

- **列出讨论** → `run discuss-list --params '{"category":""}'`
  - 触发词：`列出讨论` / `讨论列表` / `有什么讨论` / `list discussions`
- **未读/inbox** → `run discuss-inbox --params '{}'`
  - 触发词：`未读` / `新消息` / `inbox` / `我的通知`
- **阅读讨论** → `run discuss-read --params '{"category":"", "thread":""}'`
- **关闭讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"close"}'`
- **搁置讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"pending"}'`
- **重开讨论** → `run discuss-status --params '{"category":"", "thread":"", "action":"reopen", "reason":""}'`
- **生成摘要** → `run discuss-summarize --params '{"category":"", "thread":""}'`
- **生成结论** → `run discuss-result --params '{"category":"", "thread":""}'`
- **读取文件** → `run file-fetch --params '{"paths":"file1,file2"}'`

### 系统
- **检查环境** → `run check-env --params '{}'`
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
- 其他错误 → **直接告诉用户错误信息，不要尝试修复**

## 错误处理原则

**你是 pipeline 的调用者，不是调试者。pipeline 出错时报告给用户，不要自己修。**

- ❌ 不要自行修改配置文件、环境变量或代码来绕过错误
- ❌ 不要换一种方式重试（如换命令、改参数、手动执行 pipeline 的单个步骤）
- ❌ 不要用 fallback 方案替代 pipeline（如自己写 git 命令、自己生成内容）
- ❌ 不要创建脚本或临时文件来"修复"问题
- ✅ 唯一的例外：用户意图未匹配到任何 pipeline 时，可以自由组合 `pipelines/` 目录下的各个脚本（steps/*.py）来完成用户请求。阅读对应目录下的 `pipeline.yaml` 了解每个脚本的用途和参数。但仍然**不允许直接操作数据仓库**（不能直接 git commit/push、手动写文件到 data_space 等）
- ✅ `ConfigNotReady` 错误按上面的流程处理（弹飞书卡片收集配置）

## 约束

- ❌ 不要自己编写讨论内容发送到飞书群 — 必须通过上面的命令执行
- ❌ 不要修改 `pipelines/`、`tools/`、`schemas/`、`SKILL.md`
- ❌ 不要绕过命令直接 git commit/push
- ❌ project / task / knowledge 请求告诉用户"待 Phase 2"
- `${ENCLAWS_TENANT_USER_ID}` 由 EC 自动注入，代表当前用户
- 不确定时优先反问用户确认
