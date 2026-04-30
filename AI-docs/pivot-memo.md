# team-pivot-web · 构建备忘

新 Claude Code session 先读这个。**这是项目现状的权威文档**，memo 和代码有出入时以代码为准，但请立刻更新 memo。

## 1. 项目目标

把原 `team-pivot`（飞书 IM bot）改造为**独立 Web 应用**，交互形态从最初的"邮件式讨论"演进为以**事项（matter）**为顶层视角的工作系统：每件事是一条沿时间线推进的 matter，文件类型（think/act/verify/result/insight）和 6 状态机（planning/executing/paused/finished/cancelled/reviewed）共同描述事项推进位置。原 thread/discussion 模型已被替换，老索引已通过一次性迁移转为 matter 索引（详见 `coding-test-plan/index-migration-plan.md`）。

数据仓库继续用 Git（`teamDocs` 模式），只通过**飞书 OAuth2 鉴权**登录，不开放自主注册。EC bot 保留做"通知推送 + 快速发帖"的轻交互。

## 2. 技术栈

| 层 | 选型 |
|---|---|
| 前端 | React 18 + Vite + TypeScript + React Router 7 + react-markdown + remark-gfm |
| UI | shadcn/ui + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + Uvicorn（sync handlers in threadpool） |
| 包管理 | **uv** |
| Git | 纯 subprocess 封装（`server/git_ops.py`，不用 GitPython） |
| SQLite | 标准库 `sqlite3`（per-user 状态） |
| Session | SQLite 持久化 + 签名 cookie（itsdangerous） |
| 飞书 | `lark-oapi`（OAuth）；`httpx` 直调（IM 通知） |
| MCP | 自建 MCP server（外部 AI 通过它读 / 写 matter） |
| 实时 | Server-Sent Events（matter 列表 / 详情订阅） |
| 日志 | 标准库 `logging`，`LOG_LEVEL` env 切换，`var/log/pivot.log` |

**Git 是内容权威源**。SQLite 只存 per-user 私有状态，不做内容索引。

## 3. 目录结构

```
team-pivot-web/
├── server/
│   ├── app.py                  # create_app() 工厂
│   ├── config.py               # .env 读配置
│   ├── db.py                   # SQLite schema + 一次性迁移(注意 ai_conversations DELETE)
│   ├── events.py               # in-process pub/sub: matter.created / .updated / .file_appended / .comment_appended
│   ├── auth/
│   │   ├── feishu_oauth.py     # lark-oapi: code → token → user_info
│   │   ├── session.py          # SessionStore（SQLite 持久化）
│   │   ├── deps.py             # make_current_user (cookie 或 Bearer) + cookie_only + require_profile
│   │   ├── admin.py            # ADMIN_PASSWORD="000123" + require_admin (X-Admin-Password 头)
│   │   └── routes.py           # /auth/entry /login /auth/callback /me /logout /me/profile
│   ├── api/
│   │   ├── matters.py          # ★ POST/GET /api/matters, /api/matters/{id}/files, /comments, /reviewed
│   │   ├── matters_events.py   # SSE: /api/events/matters (订阅 events.py 主题转客户端事件)
│   │   ├── discussions.py      # 老 thread 接口，仅供 PAT/VS Code 客户端读侧兼容
│   │   ├── drafts.py           # CRUD + matter_payload_json 字段(P4.6)
│   │   ├── inbox.py            # GET /inbox + POST .../read
│   │   ├── contacts.py         # GET /contacts, POST /contacts/sync (cookie-only + 管理员密码)
│   │   ├── ai.py               # AI 助手: /api/ai/{settings,threads/*/conversation,/chat}
│   │   ├── tokens.py           # PAT 管理: /api/tokens (cookie-only)
│   │   ├── workspace.py        # /api/workspace/{status,refresh,mirror} + /api/admin/workspace-config
│   │   └── app_home.py         # /api/app/home (版本号 + HOME.md + CHANGELOG.md 聚合)
│   ├── matter_index.py         # ★ <matter_id>.index.yaml 读写, create/append_file_item/append_comment
│   │                           #   _normalize_item 维护 canonical key order
│   │                           #   _reverse_write_verifications 反写 verifications_received[] 到 act
│   ├── matter_status.py        # ★ 6 状态机: VALID_STATES / can_transition / can_file_type_trigger
│   ├── matter_validator.py     # ★ validate_append(index_data, item) 纯函数,API 层 + writer 层都跑
│   ├── doc_types.py            # ★ VALID_DOC_TYPES + ALLOWED_TYPES_BY_STATUS 矩阵 + JUDGEMENTS / OUTCOMES
│   ├── publish.py              # ★ publish_matter_create / _append / _comment + _resolve_owner_for_index
│   │                           #   保留 publish_proposal / _reply 给 PAT 客户端兼容,新功能不进
│   ├── ai/
│   │   ├── client.py           # OpenAI-compatible SSE 流式（默认 OpenRouter，可配 base_url）
│   │   ├── context.py          # build_context_from_files
│   │   ├── tools.py            # ★ 工具函数: list_matters / read_matter_index / search_indexes 等(tool-use)
│   │   └── prompts.py          # 系统提示词（[[GENERATE_REPLY_DRAFT]] 强约束）
│   ├── ai_conversations.py     # 每用户×matter 对话持久化 (列名仍叫 thread_key,值是 matter_id)
│   ├── api_tokens.py           # PAT repo（pvt_<urlsafe44>，DB 只存 sha256）
│   ├── favorites.py            # per-user 收藏状态
│   ├── read_state.py           # per-user × matter 已读位置
│   ├── settings.py             # SQLite key-value（AI 配置 + workspace 配置）
│   ├── workspace.py            # Workspace: clone/pull/write_session/recover
│   ├── workspace_config.py     # workspace settings keys + 校验
│   ├── workspace_runtime.py    # 从 SQLite settings 读取配置并初始化/重载 Workspace
│   ├── git_ops.py              # subprocess 封装（clone/pull/commit/push）
│   ├── posts.py                # markdown+frontmatter 读写 + 两阶段 pending/indexed
│   ├── threads.py              # 老 thread 目录扫描，只读侧兼容
│   ├── index_files.py          # 老 <slug>-discuss.index.yaml 读写,只读侧兼容
│   ├── status_machine.py       # 老 5 状态机,只读侧兼容
│   ├── recovery.py             # 启动时扫 un-indexed 文件修复(同时处理 matter + 老 thread)
│   ├── notify.py               # FeishuNotifier / NoOpNotifier 卡片通知
│   │                           #   _matter_url() 走 /m/<matter_id>; _thread_url 仅老兼容路径残留
│   ├── inbox.py                # compute_inbox（未读计算,按 matter 文件类型）
│   ├── mentions.py             # open_id → 用户名解析
│   ├── mcp/                    # ★ MCP server: 外部 AI 通过 PAT 读写 matter (含 available_transitions)
│   ├── contacts.py / feishu_contacts.py / feishu_token.py
│   └── tests/                  # pytest, 覆盖主要模块 (含 test_matters_api / test_matter_index / test_migrate_index_schema 等)
├── scripts/
│   ├── migrate_index_schema.py # ★ 一次性迁移老 thread 索引→matter 索引(_ReadOnlyUserView 守护读 prod db)
│   ├── migration-test/         # Linux 测试服务器执行手册脚本(01-check..08-cleanup)
│   └── migration-prod/         # 生产上线手册脚本(01-preflight..99-rollback)
└── web/src/
    ├── main.tsx / App.tsx      # 路由: / → MatterDetailEmpty; /m/:matter_id → MatterDetailPane;
    │                           #       /new /settings /admin; * → Navigate("/")
    ├── api.ts                  # 所有 fetch 封装
    ├── hooks/useDraftAutosave.ts  # 2s debounce 自动存草稿
    ├── lib/time.ts / utils.ts
    ├── events/                 # ★ MatterEventsProvider (SSE) + scheduleRefresh + types
    ├── components/
    │   ├── Layout.tsx          # 通用 header
    │   ├── ThreadListPane.tsx  # 左栏: 收藏 / 草稿 / matter (按 category 分组)
    │   ├── StatusBadge.tsx     # 6 色状态徽章 (planning/executing/paused/finished/cancelled/reviewed)
    │   ├── MentionField.tsx    # @mention 输入
    │   ├── AIPane.tsx          # 右栏 AI 助手(tool-use,不再手选文件)
    │   ├── CopyForAIButton.tsx # 把 matter 上下文复制到剪贴板供外部 AI
    │   ├── UserBar.tsx
    │   └── matter/             # ★ matter 专属组件
    │       ├── CreateFileDialog.tsx   # 创建 think/act/verify/result/insight 入口
    │       ├── FileCard.tsx           # timeline 上每条文件卡片
    │       ├── TimelineStrip.tsx      # 顶部时间轴
    │       ├── OwnerPicker.tsx        # 联系人下拉(value 存 open_id,后端转 pinyin)
    │       ├── ResultConfirmDialog.tsx
    │       ├── MermaidBlock.tsx
    │       └── timeline-config.ts
    └── pages/
        ├── Login.tsx
        ├── ProfileSetup.tsx           # 首登 pinyin 收集
        ├── Dashboard.tsx              # 主布局(左栏 + 右栏 Outlet),双栏/单栏自适应
        ├── MatterDetailPane.tsx       # ★ matter 详情(timeline + 文件卡片 + AIPane)
        ├── NewMatter.tsx              # ★ 创建 matter(autosave 草稿)
        ├── HomeWelcomePane.tsx        # 主页欢迎
        ├── SettingsPage.tsx           # /settings: PAT 管理
        ├── SettingsExternalAI.tsx     # /settings/external-ai: 外部 AI MCP 接入说明
        └── AdminPage.tsx              # /admin: 数据仓库 + AI + 联系人同步

var/
  data.db                       # SQLite
  git/<repo-name>/              # 数据仓库工作副本
  log/pivot.log                 # tee 日志（手动开启）
  backup/                       # 迁移用 bundle + db 副本(生产)
```

## 4. 鉴权与会话

| 功能 | 状态 |
|---|---|
| 飞书 OAuth2 登录（`/login` → 飞书 → `/auth/callback`） | ✅ |
| 邮箱 + 密码登录（邀请码用户） | ✅ |
| 首部署初始化 `/init/status` + `/init/complete` 创建首个 admin | ✅ |
| 加入申请审批：扫码未绑用户 → `join_application` → admin 审批 / 合并 / 拒绝 | ✅ |
| 邀请码：admin 生成一次性 token → 被邀请人 `/invite/<token>/accept` 落账号 | ✅ |
| 用户治理：暂停 / 恢复 / 标停用 / 撤销停用 / 角色升降级 / 重置密码 | ✅ |
| 最后一名 active admin 不能被暂停 / 标停用 / 降级（self-refuse + last-admin guard） | ✅ |
| 状态变更强制登出：suspended / deleted 用户下次请求 401 + `detail=<status>` | ✅ |
| SQLite 持久化 session（重启不丢登录） | ✅ |
| **PAT（Personal Access Token）—— `Authorization: Bearer pvt_…`** | ✅（供 VS Code 插件 / MCP 客户端等） |
| **基于 `pivot_user.role` 的管理员守卫**（替代 X-Admin-Password 旧硬编码门） | ✅（保护 `/api/admin/*`、`/api/ai/settings`、workspace 配置、`/api/contacts/sync`） |
| 飞书客户端内统一登录入口（`/auth/entry`，端内走登录预授权码） | ✅ |
| 飞书真实 email 收集（commit author 现在用 `<pinyin>@pivot.local`） | ❌ 未做 |

**鉴权层级**（统一在 `auth/deps.py`）：
- `current_user` — 普通业务接口，cookie 或 Bearer 都行；返回 `PivotUser`
- `current_user_cookie_only` — 仅 cookie（`/api/tokens`、AI 设置、workspace 管理设置）
- `require_admin_user` — 在已解析的 `PivotUser` 上加 `role=='admin'` 检查
- `require_admin_user_cookie` — cookie + role='admin' 一站式（PATs 显式不被接受，admin 端点强制 browser-only）
- 失败统一返回 `401 {"detail":"invalid_token"|"not logged in"|"suspended"|"deleted"}`
  或 `403 {"detail":"admin_required"}`

身份模型（design §7）：
- `pivot_user` 表是身份主表（ULID），与外部 IdP 通过 `external_binding` 解耦（feishu open_id / invite email）
- 一个 `pivot_user` 可同时绑多个 provider（飞书 + 邀请码各一条 binding）
- session.pivot_user_id 不再是 open_id；status≠'active' 的 session 在解析时自动删除并 401

所有 `api/*.py` 路由统一用 `Depends(current_user)`，不再每个文件手写 `_current_user(sid)`。

补充：
- 飞书 IM / 工作台里的站内跳转链接，发 `/auth/entry?next=/m/<matter_id>`（**不是**老的 `/t/<cat>/<slug>`，前端已经没有那个路由）
- `/auth/entry` 会先判断现有 `sid`；未登录时，飞书客户端内走登录预授权码入口，外部浏览器回退到普通 `/login`
- `/auth/callback` 会从签名 `state` 中恢复 `next`，登录完成后回跳原 matter，而不是固定回首页
- 飞书扫码用户若没有 `external_binding`，`/auth/callback` 创建 `join_application` 并通知所有 admin（`notify_application_created`），跳 `/login?reason=submitted` 让申请人等待审批

飞书后台须配置：App ID/Secret、回调白名单、`contact:user.base:readonly` 权限、机器人能力 + IM 权限。

## 5. 数据模型

身份层（design §7，user-management 期落地）：

```sql
pivot_user(id PK, display_name, pinyin, email UNIQUE, avatar_url, github_username,
           role CHECK admin|member, status CHECK active|suspended|deleted,
           status_note, created_at, updated_at, last_login_at,
           status_changed_at, status_changed_by)
external_binding(id PK, pivot_user_id FK, provider, external_id, external_union_id,
                 raw_profile, password_hash, bound_at,
                 UNIQUE(provider, external_id))
join_application(id PK, provider, external_id, external_union_id,
                 raw_profile, suggested_match_user_id,
                 status pending|approved|rejected, applied_at, reviewed_at,
                 reviewed_by, reject_reason,
                 UNIQUE pending(provider, external_id))
invite(id PK, token_hash UNIQUE, email, display_name, created_by,
       created_at, expires_at, used_at, used_by_user_id)
```

业务层（其它表保持不变，但 `user_open_id` 字段已改为 `pivot_user_id`）：

```sql
drafts(id PK, pivot_user_id, type, title, category, body_md, thread_key,
       mentions_json, reply_to, references_json, matter_payload_json, created_at, updated_at)
read_state(pivot_user_id, thread_key, last_read_post_filename, updated_at, PK(user, thread_key))
favorites(pivot_user_id, thread_key, created_at, PK(user, thread_key))
sessions(id PK, pivot_user_id, expires_at, created_at, user_access_token)
contacts(open_id PK, union_id, name, en_name, avatar_url, synced_at)
settings(key PK, value, updated_at)                                      -- AI 配置 + workspace 配置
ai_conversations(pivot_user_id, thread_key, messages_json,
                 reply_target, reference_files_json, context_files_json,
                 schema_ver, updated_at, PK(user, thread_key))
api_tokens(token_hash PK, pivot_user_id, name, created_at, last_used_at, expires_at)
```

补充说明：
- `drafts.type` 是**操作模式**这条轴,语义在 matter 时代仍然有效:
  - `proposal` = "新建一个 matter"(对应 `publish_matter_create` → 飞书 `notify_new_thread` 卡)
  - `reply`    = "在已有 matter 上追加文件"(对应 `publish_matter_append` → 飞书 `notify_new_reply` 卡)
  - 飞书通知靠这条来区分推哪种卡片(新讨论 vs 回复)
- `drafts.matter_payload_json`(P4.6)保存的是另一条轴 —— **文档类型 + matter 专属结构化字段**(`doc_type / summary / owner / quote / refer / verifications / outcome / status_change`)。`doc_type ∈ {think, act, verify, result, insight}` 才是 pivot-product.md §四 定义的"文档类型"。
- `read_state.thread_key` / `favorites.thread_key` / `ai_conversations.thread_key` —— **列名保留为 `thread_key` 仅出于兼容**，存的值现在是 `matter_id`。改名是破坏性迁移，单独评审。
- `ai_conversations.schema_ver` 是 tool-use 重构的迁移标记，首次升级时 `_migrate(conn)` 会清空老对话（已在生产触发过，不会再触发）。
- `contacts` 是飞书通讯录镜像（per-source-of-truth：飞书后台），`pivot_user` 是真正登录过 Pivot 的身份记录。两者解耦：被邀请的同事 `pivot_user` 存在但 `contacts` 没他；飞书新员工 `contacts` 有但 `pivot_user` 还没创建。
- 名称解析回退链（design §7.1，实现见 `server/mentions.py:DisplayResolver`）：
  1. 直查 `pivot_user.id`（新内容存 ULID 的稳态路径，不经 binding）
  2. `external_binding` 反查（历史 frontmatter 存 feishu open_id 的兼容路径）
  3. `contacts` 兜底（外部联系人未登录过、无 `pivot_user`）
  4. 原值 + status='unknown'（老 frontmatter 的 pinyin 等）
- 新内容的 frontmatter / matter index 字段（`creator` / `owner` / `mentions` / `readers`）按 design §7.1.1 应持久化为 `pivot_user.id` 的 ULID；historic 内容不回填，由解析器兼容。`scripts/audit_new_content_uses_ulid.py` 用来在迁移上线后扫 leak。
- `favorites` / `read_state` 是 per-user 私有状态，不会进 Git 内容仓库。

## 6. Git 写流程

### Workspace 配置来源

工作区相关配置统一存 SQLite `settings`（不走 `.env`）：

- `workspace.repo_url`
- `workspace.visibility`
- `workspace.write_token`
- `workspace.readonly_token`

应用启动顺序：
1. 先读基础 `.env`（飞书、session、日志等部署级配置）
2. 初始化 SQLite / `SettingsRepo`（**注意** `Database.__init__` 会跑 schema 初始化 + 一次性 migration，包括首次 tool-use 启动时清空 `ai_conversations`——见 `db.py::_migrate`）
3. 从 `settings` 读取 workspace 配置
4. 用 `workspace_runtime.py` 初始化真实 `Workspace`

如果管理员尚未完成 workspace 配置，应用仍可启动，但所有依赖 Git 工作区的接口会返回 `503 workspace_not_configured`。

### 写路径

```python
with workspace.write_session(message, author_name, author_email):
    # pull --rebase                  ← 获取远端最新
    # caller 写文件
    # git commit --author="pinyin <pinyin@pivot.local>"
    # git push（失败 → rebase + 重试 3 次）
```

**两阶段原子写**（抗崩溃）—— matter 路径：
1. `write_post_pending`：MD frontmatter 标 `index_state: un-indexed`
2. `create_matter_index` / `append_file_item` / `append_comment`：原子 tmp+rename 写 `<matter_id>.index.yaml`
3. `mark_indexed`：翻 frontmatter 到 `indexed`

**身份字段写入规约**（matter 落盘形态）：
- `creator` 永远是 `user.pinyin`（必填）
- `owner` 由前端 `OwnerPicker` 提交 `open_id`，`publish._resolve_owner_for_index` 转换：注册用户落 pinyin，未注册兜底保留 open_id
- `comments[].mentions[]` 同语义，复用 `_resolve_mentions_for_index`
- `verifications_received[].verified_by` 派生自 verify 文件的 `owner`（`matter_index._reverse_write_verifications`），自动遵循上述规约

### 启动恢复

`workspace.recover()`（顺序重要，别改）：
1. `repair_partial_writes`：扫 `un-indexed` 文件，补 index + 翻标志（**同时处理 matter + 老 thread 两类未索引文件**）
2. 工作树脏 → commit + push（必须先清本地再 pull）
3. `pull --rebase origin`（最后执行）

`git_ops.pull()` 兜底：若 pull 遇 "unstaged changes"，自动 `add -A + commit + push` 再重试。

## 7. 前端交互规则

### MatterDetailPane

- **顶部时间轴 (`TimelineStrip`)**：横向时间轴显示该 matter 的所有 file item，可点击跳转
- **文件卡片流 (`FileCard`)**：按 created_at 升序，每张卡片包含正文 + comments[] + verifications/verifications_received（如有）
- **每张卡片可发起新文件**：基于此新增 think / act / verify（默认把当前文件写进新文件 `quote`）
- **正文折叠**：默认截断，过长时显示展开/收起
- **草稿状态**：matter 草稿持久化到 `/api/drafts`（`matter_payload_json` 字段），刷新不丢；URL 带 `?draft=<id>` 可定向恢复

### 未读计数规则

- timeline 文件按 type 计入未读：`{think, act, verify, result}` 计入；`insight` 与 `comments[]` 不计
- `append_comment` 不更新 `matter.updated_at`（评论不影响 matter 推进）
- 未读数附在 matter 列表响应里，不需单独调 `/api/inbox`
- 收藏不改变分组；只是对当前用户额外出现在左栏顶级 `收藏` 分组

### 左栏导航结构

- 顶级顺序：`收藏 → 草稿 → matter (按 category 聚合)`
- 每个 category 下展开具体 matter，按 `matter.updated_at` 排序
- 当前正在浏览的 matter 所属 category 会自动展开
- category 未读数 = 该分类下所有 matter 的未读总和

### 实时刷新（SSE）

- `MatterEventsProvider` 在挂载时建立 `/api/events/matters` SSE 连接
- 服务端 `events.py` 的 `matter.created / .updated / .file_appended / .comment_appended` 转成 client 事件
- 客户端按事件 schedule 一次 list 或 detail 重新拉取（`scheduleRefresh.ts`），多个事件 coalesce 不轰炸 API

### Category 规则

- 支持中文，最长 20 个字符
- 不能包含 `/ \\ : * ? " < > |` 以及制表 / 换行
- 前后端校验统一

### Post frontmatter 约定

- AI 摘要字段名：`auto-summary`，写在 YAML frontmatter，不写进 body
- 旧 `summary` 键和 body 内嵌 `---summary---` 块在 `posts.py` 中向后兼容并自动迁移

### AI 助手（AIPane） · tool-use 模式

- **默认关闭**；点 file 卡片上的 "AI 回复" 或底部 "AI 写回复" 才打开
- **不再手选文件作为引用**——AI 通过 tool-use 自主调用 `list_matters` / `read_matter_index` / `search_indexes` 等工具拉取上下文（`server/ai/tools.py`）
- 聊天默认不会生成草稿——AI 受 prompt 严格约束（见 `ai/prompts.py`），只输出普通文本
- 点击 "生成回复草稿" 按钮 → 注入 `[[GENERATE_REPLY_DRAFT]]` 前缀消息 → AI 必须返回 `<draft>` 包裹的完整正文 → 自动填入右侧 ReplyForm（已有内容会弹 confirm 询问覆盖）
- 对话持久化到 `ai_conversations`，切 matter / 刷新不丢
- **历史代价**：tool-use 重构首次启动会清空所有 AI 对话历史（`db.py:_migrate` 检测 `schema_ver` 列缺失即清；已在生产触发过，不会再触发）

### MCP（外部 AI 接入）

- `server/mcp/` 提供 MCP server，外部 AI（Claude Desktop / Cursor 等）通过 PAT 鉴权访问
- 暴露的能力：列 matter、读 index、按规则发 file / comment、查询 `available_transitions`
- 状态变更必须显式声明 `status_change`，AI 不能隐式跃迁

## 8. 功能完成情况

**0.2 已完成（matter 模型上线）：**
- 飞书 OAuth + 首登 / `/auth/entry` 统一登录入口
- **matter 列表 + matter 详情（timeline 视图 + 文件卡片）**
- **创建 matter（think/act 起步）/ 追加 think/act/verify/result/insight**
- **6 状态机 + 文件触发的 status_change（含 result→finished/cancelled、reviewed 收口）**
- **comments + @mention（含飞书 DM 通知）**
- **verify 反向写入 verifications_received 到 act**
- 飞书卡片通知（new thread / new reply / standalone mention / status change，链接走 `/m/<matter_id>`）
- 草稿 autosave（含 matter 专属字段 `matter_payload_json`）
- **SSE 实时刷新（matter 列表 + 详情）**
- **AI 助手 tool-use 重构（list_matters / search_indexes / read_matter_index 等）**
- **MCP server 上线**（外部 AI 接入）
- 一次性老索引迁移到 matter 格式（生产已切，老 `*-discuss.index.yaml` 全部转为 `*.index.yaml`）
- PAT + 管理员密码门 + 设置页
- workspace 配置迁移到 DB + `/api/workspace/mirror`
- 欢迎首页（`HOME.md` + `CHANGELOG.md` + 版本号聚合）
- 左栏分类树导航 + per-user 收藏

**暂缓（有意为之）：**
附件上传 / 多 tenant / 权限分级（PAT 当前 = 全权限）/ 全文搜索 / 键盘快捷键 / 飞书真实 email 收集

## 9. 当前状态

这份文档只记录当前实现事实，不记录产品方向和历史讨论。

- 产品设计结论文档：[`pivot-product.md`](./pivot-product.md)（matter 模型权威定义）
- 愿景和方向文档：[`pivot-vision.md`](./pivot-vision.md)
- 远期形态设想：[`pivot-long-term.md`](./pivot-long-term.md)
- 部署与初始化：[`pivot-deploy.md`](./pivot-deploy.md)
- HTTP 接口（外部客户端）：[`pivot-interface.md`](./pivot-interface.md)
- 矩阵迁移、SSE、matter 实施等近期设计 / runbook：`coding-test-plan/` 子目录

当前实现状态可概括为：

- **matter 模型已成产品主线**：列表、详情、创建、推进、验证、收口、复盘整套链路上线
- **AI 助手是 matter-aware 的**（tool-use 自主拉上下文，非 thread 内回复助手）
- 鉴权、PAT、管理员密码门、workspace 配置、AI 配置、联系人同步都已接入
- 工作区配置和 AI 配置已迁移到 SQLite `settings`
- 老 thread 接口（`/api/threads/*` 等）只读侧保留作 PAT 客户端兼容；写侧不再使用，新功能不进入老路径
- 前端 `/t/<cat>/<slug>` 路由不再存在；卡片链接必须落到 `/m/<matter_id>`

## 11. 约束与边界

- **不要主动 push**——`git commit` 在用户明确说"提交/commit"后可做；`git push` 必须每次单独显式授权（`push/推送`）
- **不要在 commit message / PR body 末尾追加 `Co-Authored-By: Claude` 或"Generated with"之类的痕迹**
- **不要主动做服务器部署或线上配置修改**——除非用户明确要求
- **不要主动改版本号**，等用户指示
- **不要动 `old/` 里的文件**——参考资料；要复用就拷贝到 server/ 再改
- **写代码前先问方向**——尤其是动 matter 状态机、status × type 矩阵、Git 写路径、原子写不变量、身份归一化、鉴权分层
- **不加无关注释**；只写非显然的 why
- **关键路径要有单测**（OAuth、session、recovery、publish、matter validator、迁移脚本、git commit/push）
- **commit 风格**：`feat:` / `fix:` / `chore:` 前缀，简洁一句话；不主动 amend
- **改 HTTP endpoint** → 同 commit 更新 `pivot-interface.md`
- **改 matter index schema 或 status × type 规则** → 同 commit 更新 `pivot-product.md`
- **迁移 / 数据修复脚本读生产 SQLite 必须用只读路径**（SQLite URI `mode=ro`，参考 `migrate_index_schema.py::_ReadOnlyUserView`），**绝不**用 `Database(path)`——后者会跑 schema 同步并可能 `DELETE FROM ai_conversations`

## 12. 相关资源

- 本 repo：`hashSTACS-Global/team-pivot-web`
- 数据仓库：由管理员在 `/admin` 的「数据仓库配置」里维护；服务器工作副本自动 clone 到 `var/git/<repo-name>/`
- 老 APP 参考：原 `team-pivot`（飞书 IM bot），只读
- 测试 / 生产迁移脚本：`scripts/migration-test/` 与 `scripts/migration-prod/`

## 13. 本地快速开发

```bash
# 一次性
cd team-pivot-web
cp .env.example .env         # 填 FEISHU_APP_ID / SECRET / SESSION_SECRET
uv sync
cd web && npm install

# 每次开发（两个终端）
uv run uvicorn --factory server.app:create_app --reload --port 8000 2>&1 | tee -a var/log/pivot.log
cd web && npm run dev

# 浏览器
http://localhost:5173

# 测试
uv run pytest -q
```

调试日志：`.env` 改 `LOG_LEVEL=DEBUG` 重启。

## 14. 新 session 起手式

1. **先读这份 memo**——掌握当前实现细节、目录结构、关键配置与运行约束
2. **再读 [`pivot-product.md`](./pivot-product.md)**——理解 matter 模型的权威定义（状态机、文档类型、index schema）
3. **需要理解长期方向时，再读 [`pivot-vision.md`](./pivot-vision.md)**
4. **改外部接口时再读 [`pivot-interface.md`](./pivot-interface.md)** 并保持同步
5. 改代码前看对应模块现有实现
6. 跑 `uv run pytest -q` 验证 baseline 是否为绿色
7. 写代码前确认当前任务属于实现事实修改、产品设计修改，还是愿景方向修改
