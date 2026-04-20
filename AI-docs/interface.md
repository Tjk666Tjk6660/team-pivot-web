# Interface

本文件面向其他客户端与 AI 代理，描述 `team-pivot-web` 当前提供的 HTTP 接口、用途、鉴权方式和基本调用方法。

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

### GET /login
- 作用：发起飞书 OAuth 登录
- 鉴权：无
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
  - 每项含 `category / slug / title / author / author_display / status / last_updated / post_count / unread_count`

### GET /api/threads/{category}/{slug}
- 作用：获取线程详情与帖子内容
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `meta`
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

### POST /api/workspace/refresh
- 作用：从远端仓库拉取最新内容
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `ok`
  - `head`

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

### GET /api/admin/workspace-config
- 作用：读取管理员工作区配置
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

## AI

### GET /api/ai/settings
- 作用：读取 AI 配置
- 鉴权：Cookie 会话 + 管理员口令

### PUT /api/ai/settings
- 作用：更新 AI 配置
- 鉴权：Cookie 会话 + 管理员口令
- 请求体：
  - `api_key?`
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

### DELETE /api/tokens/{short_id}
- 作用：删除一个 PAT
- 鉴权：Cookie 会话

## App Home

### GET /api/app/home
- 作用：获取首页欢迎页所需的版本、欢迎内容和更新信息
- 鉴权：Cookie 或 Bearer PAT
- 返回：
  - `app`
  - `welcome`
  - `latest_release`
  - `recent_releases`

## 维护规则

- 新增、删除、修改对外接口时，必须同步更新本文件。
- 对外客户端应优先以本文件为准，不要从前端实现中反推接口。
