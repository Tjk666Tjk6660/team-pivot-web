# Interface

本文件面向其他客户端与 AI 代理，描述 `team-pivot-web` 当前提供的 HTTP 接口、用途、鉴权方式和基本调用方法。

说明：

- 本文前半部分描述当前已经存在的接口
- 文末 “Matter API（设计草案）” 描述接下来围绕 `matter` 模型准备新增或重构的最小接口集
- 设计草案不是现状承诺，而是后续实现的目标接口方向

## 全局约定

### Base URL
- 本地开发：`http://localhost:8000`
- 线上部署：由部署环境决定

### 鉴权方式
- 浏览器会话：依赖登录后写入的 `sid` Cookie
- Bearer PAT：`Authorization: Bearer <token>`
- 管理员额外口令：`X-Admin-Password: <password>`

说明：
- 大多数 `/api/*` 业务接口接受 Cookie 或 Bearer PAT。
- `/api/tokens` 只接受 Cookie 会话。
- `/api/admin/*`、`/api/ai/settings`、`/api/contacts/sync` 需要管理员口令，其中部分还要求 Cookie-only。

### 错误格式
- 失败时通常返回：`{"detail":"..."}`
- Bearer token 无效时，返回：`401 {"detail":"invalid_token"}`

## Auth

### GET /auth/entry
- 作用：统一登录入口；如果已有会话则直接跳转目标页面，否则根据环境选择飞书端内免登或普通 OAuth
- 鉴权：无
- 查询参数：
  - `next?`：登录完成后的站内跳转路径，例如 `/t/产品/讨论`
- 备注：
  - 飞书客户端内打开时，会先跳转到飞书登录预授权码入口
  - 普通浏览器中会回退到 `/login`

### GET /login
- 作用：发起飞书 OAuth 登录
- 鉴权：无
- 查询参数：
  - `next?`：登录完成后的站内跳转路径
- 使用：浏览器跳转到该地址

### GET /auth/callback
- 作用：飞书 OAuth 回调
- 鉴权：无
- 使用：由飞书回调，不应由客户端主动构造调用

### GET /me
- 作用：获取当前登录用户
- 鉴权：Cookie 会话
- 返回：
  - `open_id`
  - `name`
  - `avatar_url`
  - `pinyin`
  - `github_username`
  - `needs_setup`

### POST /me/profile
- 作用：更新当前用户资料
- 鉴权：Cookie 会话
- 请求体：
  - `pinyin?`
  - `github_username?`

### POST /logout
- 作用：退出登录
- 鉴权：Cookie 会话

## Threads

### GET /api/threads
- 作用：获取线程列表
- 鉴权：Cookie 或 Bearer PAT
- 查询参数：
  - `category?`
- 返回：
  - `items[]`
  - 每项含 `category / slug / title / author / author_display / status / last_updated / post_count / unread_count / favorite`

### GET /api/threads/{category}/{slug}
- 作用：获取线程详情与帖子内容
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `meta`：与线程列表同结构，包含 `favorite`
  - `posts[]`
  - 每个 post 含 `filename / frontmatter / body / author_display / mentions`

### POST /api/threads
- 作用：发布新的 proposal 线程
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `category`
  - `title`
  - `body`
  - `mentions?`
- 备注：
  - `category` 支持中文，最长 20 个字符
  - `category` 不能包含 `/ \\ : * ? " < > |` 或换行 / 制表符

### POST /api/threads/{category}/{slug}/posts
- 作用：在线程内发布 reply
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `body`
  - `mentions?`
  - `reply_to?`
  - `references?`

### POST /api/threads/{category}/{slug}/mentions
- 作用：对指定帖子追加独立提及
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `target_filename`
  - `mentions`

### POST /api/threads/{category}/{slug}/status
- 作用：变更线程状态
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `to`
  - `reason?`

### POST /api/threads/{category}/{slug}/favorite
- 作用：设置或取消当前用户对某个 thread 的个人收藏状态
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `favorite`: `true | false`
- 返回：
  - `ok`
  - `thread_key`
  - `favorite`

## Drafts

### GET /api/drafts
- 作用：列出当前用户草稿
- 鉴权：Cookie 或 Bearer PAT

### POST /api/drafts
- 作用：创建草稿
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `type`: `proposal | reply`
  - `title?`
  - `category?`
  - `body_md?`
  - `thread_key?`
  - `mentions?`
  - `reply_to?`
  - `references?`
- 备注：
  - proposal 草稿的 `category` 与正式发帖共用同一规则：支持中文，最长 20 个字符，禁止路径危险字符

### GET /api/drafts/{draft_id}
- 作用：读取草稿
- 鉴权：Cookie 或 Bearer PAT

### PATCH /api/drafts/{draft_id}
- 作用：更新草稿
- 鉴权：Cookie 或 Bearer PAT

### DELETE /api/drafts/{draft_id}
- 作用：删除草稿
- 鉴权：Cookie 或 Bearer PAT

### POST /api/drafts/{draft_id}/publish
- 作用：发布草稿为正式 proposal 或 reply
- 鉴权：Cookie 或 Bearer PAT

## Inbox / Read State

### GET /api/inbox
- 作用：获取当前用户的收件箱与未读信息
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `items[]`
  - 每项含 `meta / unread_count / last_post_filename / last_post_author_display`

### POST /api/threads/{category}/{slug}/read
- 作用：将线程标记为已读到最新帖子
- 鉴权：Cookie 或 Bearer PAT

## Contacts

### GET /api/contacts
- 作用：搜索联系人
- 鉴权：Cookie 或 Bearer PAT
- 查询参数：
  - `q?`
  - `limit?`

### POST /api/contacts/sync
- 作用：从飞书同步联系人
- 鉴权：Cookie 会话 + 管理员口令
- 备注：
  - 当前会话必须带飞书 `user_access_token`
  - Bearer PAT 不能调用此接口

## Workspace

### GET /api/workspace/status
- 作用：返回服务器工作区状态
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `ready`
  - `path`
  - `head`
- 可能错误：
  - `503 {"detail":"workspace_not_configured"}`：管理员尚未完成工作区配置

### POST /api/workspace/refresh
- 作用：从远端仓库拉取最新内容
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `ok`
  - `head`
- 可能错误：
  - `503 {"detail":"workspace_not_configured"}`

### GET /api/workspace/mirror
- 作用：返回客户端 clone / pull 用的只读镜像配置
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `repo_url`
  - `visibility`
  - `branch`
  - `repo_name`
  - `provider`
  - `readonly`
  - `git_username`
  - `git_token`
  - `head`
- 备注：
  - `branch` 固定为 `main`
  - `visibility=public` 时，`git_username` 和 `git_token` 为 `null`
  - `visibility=private` 时，返回只读凭据，不返回服务器写入 token

### GET /api/admin/workspace-config
- 作用：读取管理员工作区配置

## Matter API（设计草案）

这一组接口服务于新的 `matter` 模型。第一版目标不是替换所有 thread 接口，而是在现有 discussion 基础上，逐步补出 `matter timeline + 文件创建 + 状态迁移` 的最小闭环。

### GET /api/matters
- 作用：获取 `matter` 列表
- 鉴权：Cookie 或 Bearer PAT
- 查询参数：
  - `status?`
  - `owner?`
  - `q?`
- 返回：
  - `items[]`
  - 每项建议包含：
    - `id`
    - `title`
    - `current_status`
    - `created_at`
    - `updated_at`
    - `file_count`
    - `last_file_type`
    - `last_summary`

### GET /api/matters/{matter_id}
- 作用：获取单个 `matter` 的详情页数据
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `matter`
    - `id`
    - `title`
    - `current_status`
    - `created_at`
    - `updated_at`
    - `file_count`
    - `last_file_type?`
    - `last_summary?`
  - `timeline[]`
    - 按时间顺序返回全部文件节点
    - 每项建议包含三层信息：
      - 卡片首屏字段
      - 类型专属结构化字段
      - 可选正文字段
    - `timeline[]` 每项基础字段：
      - `file`
      - `created_at`
      - `creator`
      - `owner`
      - `type`
      - `summary`
      - `quote?`
      - `refer?`
      - `comments`
      - `status_change?`
      - `expanded`: `true | false`
    - 类型专属字段：
      - `think`
        - 无额外必需字段
      - `act`
        - 无额外必需字段
      - `verify`
        - `verifications[]`
          - `target`
          - `judgement`
          - `comment`
      - `result`
        - `outcome`
      - `insight`
        - 无额外必需字段
    - 正文字段：
      - `body?`
        - 第一版可直接返回完整 Markdown 正文
        - 如果后续列表首屏性能有压力，再改成按需加载
  - 说明：
    - 第一版建议 `GET /api/matters/{matter_id}` 直接返回完整 timeline 和文件正文，优先换取实现简单
    - 前端时间轴和文件卡片首屏主要使用基础字段
    - 文件展开后直接读取同一条 timeline item 里的 `body`
    - `verify` 的被验证对象只通过 `verifications[]` 返回，不再通过 `refer` 表达
    - `result` 的最终状态只通过 `outcome` 返回

### GET /api/matters/{matter_id} 返回示例

```json
{
  "matter": {
    "id": "auth-redesign",
    "title": "Authentication Redesign",
    "current_status": "executing",
    "created_at": "2026-04-23T10:00:00+08:00",
    "updated_at": "2026-04-23T18:00:00+08:00",
    "file_count": 6,
    "last_file_type": "verify",
    "last_summary": "003 行动通过；004 行动未通过"
  },
  "timeline": [
    {
      "file": "discussions/auth-redesign/001_dengke_think_f9e2.md",
      "created_at": "2026-04-23T10:00:00+08:00",
      "creator": "dengke",
      "owner": "dengke",
      "type": "think",
      "summary": "梳理当前登录链路的问题和目标边界",
      "quote": null,
      "refer": [],
      "comments": [],
      "status_change": null,
      "expanded": false,
      "body": "# Summary\\n\\n梳理当前登录链路的问题和目标边界。"
    },
    {
      "file": "discussions/auth-redesign/006_liuyu_verify_f6g7.md",
      "created_at": "2026-04-23T15:30:00+08:00",
      "creator": "liuyu",
      "owner": "dengke",
      "type": "verify",
      "summary": "003 行动通过；004 行动未通过",
      "quote": "discussions/auth-redesign/004_liuyu_act_b2c3.md",
      "refer": [],
      "verifications": [
        {
          "target": "discussions/auth-redesign/003_dengke_act_a1b2.md",
          "judgement": "passed",
          "comment": "主链路完成，质量一般，但结果可接受"
        },
        {
          "target": "discussions/auth-redesign/004_liuyu_act_b2c3.md",
          "judgement": "failed",
          "comment": "关键边界遗漏，当前结果不可接受"
        }
      ],
      "comments": [],
      "status_change": null,
      "expanded": false,
      "body": "# Verifications\\n\\n- 003_dengke_act_a1b2.md\\n  - judgement: passed\\n  - comment: 主链路完成，质量一般，但结果可接受"
    }
  ]
}
```

### POST /api/matters
- 作用：创建新的 `matter`
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `category`
  - `title`
  - `initial_file`
    - `type`: `think | act`
    - `owner?`
    - `summary`
    - `body`
    - `comments?`
- 说明：
  - `category` 与 `POST /api/threads` 同规则：支持中文，最长 20 字符，禁止 `/ \\ : * ? " < > |` 及换行 / 制表符
  - `category` 仅作为磁盘分组标签（`discussions/<category>/<slug>/`），不参与 matter 模型语义
  - 第一篇文件允许没有 `quote`
  - 第一篇文件通常是 `think`，但也允许直接是 `act`
- 返回：
  - `matter`
  - `initial_timeline_item`
  - `matter_id`：等同 `matter.id`，前端便利字段
  - `file`：首个 timeline item 的完整路径（`discussions/<category>/<slug>/<filename>`）

### POST /api/matters/{matter_id}/files
- 作用：在指定 `matter` 下新增文件
- 鉴权：Cookie 或 Bearer PAT
- 请求体通用字段：
  - `type`: `think | act | verify | result | insight`
  - `summary`
  - `body?`
  - `quote?`
  - `refer?`
  - `owner?`
  - `comments?`
    - `[]`
    - 每项：
      - `body`
      - `mentions?`
- 通用字段说明：
  - `summary`
    - 必填
    - 用于写入 frontmatter 和 timeline item 摘要
  - `body`
    - 可选
    - 用于写入 Markdown 正文
  - `quote`
    - 可选
    - 表示新文件主要基于哪篇已有文件继续长出来
  - `refer`
    - 可选
    - 仅表示补充参考对象，不承担 `verify` 的验证目标语义
  - `owner`
    - 可选
    - 不传时默认等于当前用户
  - `comments`
    - 可选
    - 轻量评论流和圈人，不是正文主内容
- 类型专属请求体：
  - `think`
    - 允许字段：
      - 通用字段
      - `status_change?`
    - 说明：
      - `think` 可用于 `planning/executing -> paused`
      - 也可用于 `paused -> planning/executing`
  - `act`
    - 允许字段：
      - 通用字段
      - `status_change?`
    - 说明：
      - `act` 的 `owner` 表示执行责任人
      - 如果用于从 `planning` 正式进入 `executing`，可带：
        - `status_change.from = planning`
        - `status_change.to = executing`
  - `verify`
    - 允许字段：
      - 通用字段
      - `verifications[]`
    - `verifications[]`
      - 至少 1 项
      - 每项：
        - `target`
        - `judgement`: `passed | failed | cancelled`
        - `comment`
    - 说明：
      - `verify` 不再使用 `refer` 表达被验证对象
      - 被验证对象只写在 `verifications[].target`
  - `result`
    - 允许字段：
      - 通用字段
      - `outcome`: `finished | cancelled`
      - `status_change`
    - 说明：
      - `result` 可以没有 `quote`
      - `result` 可以没有 `refer`
      - `result` 不要求必须建立在 `verify` 之上
      - `result` 是唯一允许把 `matter` 从 `executing` 推到终态的文件
  - `insight`
    - 允许字段：
      - 通用字段
    - 说明：
      - `insight` 用于 `finished/cancelled` 之后的复盘沉淀
- `status_change?`
  - 可选
  - 建议结构：
    - `from`
    - `to`
  - 说明：
    - 只有在本次创建同时触发事项状态变化时才传
- 返回：
  - `item`
  - `matter`

### POST /api/matters/{matter_id}/files 请求体示例

#### 新增 think

```json
{
  "type": "think",
  "summary": "说明当前事项需要暂停，等待外部依赖确认",
  "body": "# Summary\n\n当前事项需要暂停。\n",
  "quote": "discussions/auth-redesign/004_liuyu_act_b2c3.md",
  "owner": "liuyu",
  "status_change": {
    "from": "executing",
    "to": "paused"
  }
}
```

#### 新增 act

```json
{
  "type": "act",
  "summary": "按修正后的登录链路继续推进实现",
  "body": "# Summary\n\n按修正后的登录链路继续推进实现。\n",
  "quote": "discussions/auth-redesign/002_liuyu_think_c3d4.md",
  "owner": "liuyu",
  "comments": [
    {
      "body": "请先覆盖主链路。",
      "mentions": ["dengke"]
    }
  ]
}
```

#### 新增 verify

```json
{
  "type": "verify",
  "summary": "003 行动通过；004 行动未通过",
  "body": "# Verifications\n",
  "quote": "discussions/auth-redesign/004_liuyu_act_b2c3.md",
  "owner": "dengke",
  "verifications": [
    {
      "target": "discussions/auth-redesign/003_dengke_act_a1b2.md",
      "judgement": "passed",
      "comment": "主链路完成，质量一般，但结果可接受"
    },
    {
      "target": "discussions/auth-redesign/004_liuyu_act_b2c3.md",
      "judgement": "failed",
      "comment": "关键边界遗漏，当前结果不可接受"
    }
  ]
}
```

#### 新增 result

```json
{
  "type": "result",
  "summary": "事项正式完成，整体结果可接受",
  "body": "这个事项已经完成。整体结果可接受。",
  "owner": "dengke",
  "outcome": "finished",
  "status_change": {
    "from": "executing",
    "to": "finished"
  }
}
```

#### 新增 insight

```json
{
  "type": "insight",
  "summary": "这次执行暴露出需求澄清和验收节奏的几个问题",
  "body": "# Summary\n\n这次执行暴露出需求澄清和验收节奏的几个问题。\n",
  "owner": "dengke"
}
```

### POST /api/matters/{matter_id}/result
- 作用：创建该 `matter` 的最终 `result`
- 鉴权：Cookie 或 Bearer PAT
- 说明：
  - 这是 `POST /api/matters/{matter_id}/files` 的特化便捷入口
  - 主要服务右侧详情页顶部的 “生成 Result” 动作
- 请求体：
  - `summary`
  - `body?`
  - `outcome`: `finished | cancelled`
  - `comments?`
- 返回：
  - `item`
  - `matter`

### POST /api/matters/{matter_id}/comments
- 作用：向指定 timeline item 追加一条评论
- 鉴权：Cookie 或 Bearer PAT
- 请求体：
  - `target_file`：目标 timeline item 的 `file` 字段值
  - `body`：评论正文，必填
  - `mentions?`：@人列表（open_id 或 pinyin），可选
- 说明：
  - 评论挂在 timeline item 的 `comments[]` 下，与该文件同生命周期
  - 评论追加**不会**刷新 `matter.updated_at`（评论不计入事项推进）
  - `target_file` 不存在于本 matter 的 timeline 时返回 `404 comment_target_not_found`
- 返回：
  - `matter_id`
  - `target_file`
  - `at`：本次评论的时间戳

### 最小服务端校验建议

第一版建议只做最小必要校验：

- `planning`
  - 允许创建：`think / act / verify`
- `executing`
  - 允许创建：`think / act / verify / result`
- `paused`
  - 只允许创建：`think`
- `finished`
  - 只允许创建：`insight`
- `cancelled`
  - 只允许创建：`insight`
- `reviewed`
  - 原则上不再新增文件

补充规则：

- `verify` 使用 `verifications[]`，不再使用 `refer` 表达被验证对象
- `result` 必须带 `outcome`
- `result` 是唯一允许把 `matter` 从 `executing` 推到 `finished` 或 `cancelled` 的文件
- `paused` 的进入与恢复都应由 `think` 触发
- 鉴权：Cookie 会话 + 管理员口令
- 返回：
  - `repo_url`
  - `visibility`
  - `write_token`
  - `readonly_token`
  - `branch`

### PUT /api/admin/workspace-config
- 作用：更新管理员工作区配置
- 鉴权：Cookie 会话 + 管理员口令
- 请求体：
  - `repo_url`
  - `visibility`
  - `write_token`
  - `readonly_token`
- 校验规则：
  - `write_token` 必填
  - `visibility=private` 时，`readonly_token` 必填

## AI

### GET /api/ai/settings
- 作用：读取 AI 配置
- 鉴权：Cookie 会话 + 管理员口令
- 返回：
  - `base_url`
  - `model`
  - `has_key`
  - `max_context_tokens`
  - `min_rounds`
  - `max_rounds`

### PUT /api/ai/settings
- 作用：更新 AI 配置
- 鉴权：Cookie 会话 + 管理员口令
- 请求体：
  - `api_key?`
  - `base_url?`
  - `model?`
  - `max_context_tokens?`
  - `min_rounds?`
  - `max_rounds?`

### GET /api/ai/files
- 作用：列出 AI 可引用的 thread 文件树
- 鉴权：Cookie 或 Bearer PAT

### GET /api/ai/threads/{category}/{slug}/conversation
- 作用：读取用户在线程内保存的 AI 会话
- 鉴权：Cookie 或 Bearer PAT

### PUT /api/ai/threads/{category}/{slug}/conversation
- 作用：保存用户在线程内的 AI 会话
- 鉴权：Cookie 或 Bearer PAT

### DELETE /api/ai/threads/{category}/{slug}/conversation
- 作用：清除用户在线程内的 AI 会话
- 鉴权：Cookie 或 Bearer PAT

### POST /api/ai/threads/{category}/{slug}/chat
- 作用：发起 AI 流式聊天
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `text/event-stream`
- 请求体：
  - `messages[]`
  - `reply_target`
  - `reference_files[]`

## Tokens

### POST /api/tokens
- 作用：为当前用户创建新的 PAT
- 鉴权：Cookie 会话
- 请求体：
  - `name`
  - `ttl_days`
- 返回：
  - `id`
  - `name`
  - `token`
  - `created_at`
  - `expires_at`

### GET /api/tokens
- 作用：列出当前用户已有 PAT
- 鉴权：Cookie 会话
- 返回：
  - `items[]`
  - 每项含 `id / name / created_at / last_used_at / expires_at`

### DELETE /api/tokens/{short_id}
- 作用：删除一个 PAT
- 鉴权：Cookie 会话

## App Home

### GET /api/app/home
- 作用：获取首页欢迎页所需的版本、欢迎内容和更新信息
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `app`：`name / version / head`
  - `welcome`：`title / body_md`
  - `latest_release`
  - `recent_releases`

## 维护规则

- 新增、删除、修改对外接口时，必须同步更新本文件。
- 对外客户端应优先以本文件为准，不要从前端实现中反推接口。
