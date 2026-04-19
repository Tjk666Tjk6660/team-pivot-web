# team-pivot-web · 构建备忘

新 Claude Code session 先读这个。**这是项目现状的权威文档**，memo 和代码有出入时以代码为准，但请立刻更新 memo。

## 1. 项目目标

把原 `team-pivot`（飞书 IM bot）改造为**独立 Web 应用**，交互形态类似邮件客户端，数据仓库继续用 Git（`teamDocs` 模式），只通过**飞书 OAuth2 鉴权**登录，不开放自主注册。EC bot 保留做"通知推送 + 快速发帖"的轻交互，和 Web 并行互补。

## 2. 技术栈

| 层 | 选型 |
|---|---|
| 前端 | React 18 + Vite + TypeScript + React Router 7 + react-markdown + remark-gfm |
| UI | shadcn/ui + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + Uvicorn（sync handlers in threadpool） |
| 包管理 | **uv** |
| Git | 纯 subprocess 封装（`server/git_ops.py`，不用 GitPython） |
| SQLite | 标准库 `sqlite3`（per-user 状态：users/drafts/read_state） |
| Session | SQLite 持久化 + 签名 cookie（itsdangerous） |
| 飞书 | `lark-oapi`（OAuth）；`httpx` 直调（IM 通知） |
| 日志 | 标准库 `logging`，`LOG_LEVEL` env 切换，`var/log/pivot.log` |

**Git 是内容权威源**。SQLite 只存 per-user 私有状态（drafts/read_state/users），不做内容索引。

## 3. 目录结构

```
team-pivot-web/
├── server/
│   ├── app.py                  # create_app() 工厂
│   ├── config.py               # .env 读配置
│   ├── db.py                   # SQLite schema 初始化
│   ├── auth/
│   │   ├── feishu_oauth.py     # lark-oapi: code → token → user_info
│   │   ├── session.py          # SessionStore（SQLite 持久化）
│   │   └── routes.py           # /login /auth/callback /me /logout /me/profile
│   ├── api/
│   │   ├── discussions.py      # GET/POST threads, thread detail, status transitions
│   │   ├── drafts.py           # CRUD + /publish（带 reply_to + references）
│   │   ├── inbox.py            # GET /inbox + POST .../read
│   │   ├── contacts.py         # GET /contacts, POST /contacts/sync (cookie-only)
│   │   ├── ai.py               # AI 助手：/api/ai/{settings,files,threads/*/conversation,/chat}
│   │   └── tokens.py           # PAT 管理：/api/tokens（cookie-only，无需管理员密码）
│   ├── ai/
│   │   ├── client.py           # OpenRouter SSE 流式
│   │   ├── context.py          # build_context_from_files(reply_target, references)
│   │   └── prompts.py          # 系统提示词（[[GENERATE_REPLY_DRAFT]] 强约束）
│   ├── ai_conversations.py     # 每用户×thread 对话持久化
│   ├── api_tokens.py           # PAT repo（pvt_<urlsafe44>，DB 只存 sha256）
│   ├── settings.py             # SQLite key-value（AI key/model/截断参数）
│   ├── auth/
│   │   ├── deps.py             # make_current_user (cookie 或 Bearer) + cookie_only + require_profile
│   │   ├── admin.py            # ADMIN_PASSWORD="000123" + require_admin (X-Admin-Password 头)
│   ├── workspace.py            # Workspace: clone/pull/write_session/recover
│   ├── git_ops.py              # subprocess 封装（clone/pull/commit/push）
│   ├── posts.py                # markdown+frontmatter 读写 + 两阶段 pending
│   ├── threads.py              # 目录扫描 → ThreadMeta/ThreadDetail
│   ├── index_files.py          # index/<slug>-discuss.index.yaml 读写
│   ├── publish.py              # publish_proposal/publish_reply（写路径共享入口）
│   ├── recovery.py             # 启动时扫 un-indexed 文件修复
│   ├── notify.py               # FeishuNotifier / NoOpNotifier 卡片通知
│   ├── inbox.py                # compute_inbox（未读计算）
│   ├── mentions.py             # open_id → 用户名解析
│   ├── status_machine.py       # ALLOWED_TRANSITIONS 状态机
│   ├── contacts.py / feishu_contacts.py / feishu_token.py
│   └── tests/                  # pytest，覆盖主要模块
└── web/src/
    ├── main.tsx / App.tsx      # BrowserRouter + 根路由
    ├── api.ts                  # 所有 fetch 封装
    ├── hooks/useDraftAutosave.ts  # 2s debounce 自动存草稿
    ├── lib/time.ts / utils.ts
    ├── components/
    │   ├── Layout.tsx          # 通用 header（NewThread/ProfileSetup 用）
    │   ├── ThreadListPane.tsx  # 左栏：thread 列表 + 未读红点 + 草稿列表
    │   ├── StatusControl.tsx   # 状态选择下拉（含外部点击关闭）
    │   ├── MentionField.tsx    # @mention 输入（含联系人高亮）
    │   ├── StatusBadge.tsx     # 5 色状态徽章
    │   └── UserBar.tsx         # 头像 + 名 + 登出
    ├── components/
    │   ├── AIPane.tsx          # 右栏 AI 助手（回复对象 + 引用文件 + "生成回复草稿"按钮）
    │   └── FileTreeBrowser.tsx # 文件树选择器（reply_target=单选 / reference=多选 max 4）
    └── pages/
        ├── Login.tsx
        ├── ProfileSetup.tsx    # 首登 pinyin 收集
        ├── Dashboard.tsx       # 主布局（左栏列表 + 右栏 Outlet），有**独立 header**；含 UserMenu 下拉
        ├── NewThread.tsx       # 发讨论表单（autosave）
        ├── SettingsPage.tsx    # /settings：个人设置，无密码，只有 PAT 管理
        ├── AdminPage.tsx       # /admin：管理员密码门 + AI 配置 + 联系人同步
        └── ThreadDetailPane.tsx  # 右栏：posts 列表 + 内联 ReplyForm + AIPane

var/
  data.db                       # SQLite
  git/test-team-pivot/          # 数据仓库工作副本
  log/pivot.log                 # tee 日志（手动开启）
```

**⚠️ 陷阱：`Dashboard.tsx` 有自己的独立 header，不使用 `Layout.tsx`。** 改顶栏按钮时两处都要改。

**⚠️ 陷阱：前端改动不生效** 先查 `find web/src -name "*.js" -not -path "*/node_modules/*"`——Vite 优先解析 `.js`，曾有过时 `.js` 文件遮蔽 `.tsx` 的问题。

## 4. 鉴权与会话

| 功能 | 状态 |
|---|---|
| 外部浏览器 OAuth 流程（`/login` → 飞书 → `/auth/callback`） | ✅ |
| 首登 pinyin + github_username 收集 | ✅ |
| SQLite 持久化 session（重启不丢登录） | ✅ |
| **PAT（Personal Access Token）—— `Authorization: Bearer pvt_…`** | ✅（供 VS Code 插件等外部客户端） |
| **管理员密码门（X-Admin-Password，MVP 硬编码 `000123`）** | ✅（保护 `/api/ai/settings` 和 `/api/tokens`） |
| **JSAPI 免登（飞书 WebView 内嵌路径）** | ❌ 未实现 |
| 飞书真实 email 收集（commit author 现在用 `<pinyin>@pivot.local`） | ❌ 未做 |

**鉴权层级**（统一在 `auth/deps.py`）：
- `current_user` — 普通业务接口，cookie 或 Bearer 都行
- `current_user_cookie_only` — 仅 cookie（`/api/tokens`、`/api/contacts/sync`、AI 设置）
- `+ require_admin` — 加管理员密码（**AI 设置、`/api/contacts/sync`**）
- 失败统一返回 `401 {"detail":"invalid_token"}`（PAT 失效）或 `401 {"detail":"admin_required"}`

**权限分配原则（已调整）：**
- `/api/tokens`（PAT 增删查）：cookie-only，**不需要**管理员密码——每个用户都要自己生成 PAT 才能用 VS Code 客户端
- `/api/contacts/sync`：cookie-only **+ 管理员密码**——操作重，只需管理员偶尔执行
- `/api/ai/settings`：管理员密码（不变）

所有 `api/*.py` 路由统一用 `Depends(current_user)`，不再每个文件手写 `_current_user(sid)`。

飞书后台须配置：App ID/Secret、回调白名单、`contact:user.base:readonly` 权限、机器人能力 + IM 权限。

## 5. 数据模型

```sql
users(open_id PK, union_id, name, avatar_url, pinyin, github_username, created_at)
drafts(id PK, user_open_id, type, title, category, body_md, thread_key,
       mentions_json, reply_to, references_json, created_at, updated_at)
read_state(user_open_id, thread_key, last_read_post_filename, updated_at, PK(user, thread_key))
sessions(id PK, user_open_id, expires_at, created_at, user_access_token)
contacts(open_id PK, union_id, name, en_name, avatar_url, synced_at)
settings(key PK, value, updated_at)                                      -- AI 配置
ai_conversations(user_open_id, thread_key, messages_json, reply_target,
                 reference_files_json, updated_at, PK(user, thread_key))
api_tokens(token_hash PK, user_open_id, name, created_at, last_used_at, expires_at)
```

## 6. Git 写流程

```python
with workspace.write_session(message, author_name, author_email):
    # pull --rebase                  ← 获取远端最新
    # caller 写文件
    # git commit --author="pinyin <pinyin@pivot.local>"
    # git push（失败 → rebase + 重试 3 次）
```

**两阶段原子写**（抗崩溃）：
1. `write_post_pending`：frontmatter 标 `index_state: un-indexed`
2. 更新 index yaml（原子 tmp+rename）
3. `mark_indexed`：翻标志到 `indexed`

**启动恢复 `workspace.recover()`**（顺序重要，别改）：
1. `repair_partial_writes`：扫 `un-indexed` 文件，补 index + 翻标志
2. 工作树脏 → commit + push（**必须先清本地再 pull**）
3. `pull --rebase origin`（最后执行）

`git_ops.pull()` 兜底：若 pull 遇 "unstaged changes"，自动 `add -A + commit + push` 再重试。

## 7. 前端交互规则（重要，别回退）

### ThreadDetailPane

- **正文折叠**：每条 post 默认截断到 208px，`scrollHeight > clientHeight` 时显示展开/收起
- **Reply 按钮**：在每条 post 标题栏；点击后 ReplyForm **内联插入在该 post 正下方**；再次点击收起但内容保留；底部"写回复"按钮的表单显示在所有 post 之后
- **草稿状态**：`replyBody`/`replyMentions` 提升到 `ThreadDetailPane`；切换 thread 时从服务器预加载草稿（`fetchDrafts()`）；有草稿时回复按钮显示橙色 `●`；草稿存服务端 SQLite（`/api/drafts`），刷新不丢
- **弹出框背景**：`StatusControl` 和 `MentionField` 下拉一律用 `bg-white dark:bg-zinc-900`，**不用 `bg-popover`**（CSS 变量未定义会透明）
- **已选中项高亮**：下拉列表中当前选中项 `bg-blue-50 dark:bg-blue-950 text-blue-700` + `✓` 标记

### 未读计数规则

- 只有 `type: proposal` 和 `type: reply` 计入未读；comment/mention/状态变更不计
- `append_standalone_mention` 不更新 `last_updated`，不影响 thread 排列顺序
- 未读数附在 `/api/threads` 响应的 `unread_count` 字段，不需单独调 `/api/inbox`

### Post frontmatter 约定

- AI 摘要字段名：`auto-summary`，写在 YAML frontmatter，不写进 body
- 旧 `summary` 键和 body 内嵌 `---summary---` 块在 `posts.py` 中向后兼容并自动迁移

### AI 助手（AIPane）

- **默认关闭**；点 post 上 "AI 回复" 或底部 "AI 写回复" 才打开
- 顶部两个槽：**回复对象（必选 1 个）** + **引用其他文件（最多 4 个）**
  - 点 post 的 "AI 回复" → 自动填该 post 为回复对象
  - 点底部 "AI 写回复" → 默认填最后一个 post
  - 没有回复对象时输入框/发送按钮全部禁用，强制选择
- **聊天默认不会生成草稿**——AI 受 prompt 严格约束（见 `ai/prompts.py`），只输出普通文本，提示用户点按钮
- 点击 "生成回复草稿" 按钮 → 注入 `[[GENERATE_REPLY_DRAFT]]` 前缀消息 → AI 必须返回 `<draft>` 包裹的完整正文 → 自动填入右侧 ReplyForm（已有内容会弹 confirm 询问覆盖）
- 对话 + 文件选择都持久化到 `ai_conversations`，切 thread/刷新不丢
- 发布 reply 时 `reply_to` → INDEX `refs` 加 `from`，`references` → 加 `refer`

### 已修复的关键 Bug（别再踩）

**Bug A：草稿重复创建（发布后幽灵草稿残留）**
- 根因：`useDraftAutosave` 2s debounce 的闭包里捕获了创建时的 `draftId=null`。父组件 `createDraft` 返回后设了 `replyDraftId=A`，但 timer 里的 `save()` 仍用旧 `null`，又创建了草稿 B。发布删 A，B 就残留。
- 修复：在 hook 内加 `draftIdRef = useRef(draftId)`，每次 render 同步 ref，`save()` 读 ref 而非闭包值。同时 `onUseDraftAsReply` 改为**先调 API persist、再更新 React 状态**，避免 ReplyForm 挂载时 autosave 以 `null` id 触发。

**Bug B：切 thread 后 AI 对话历史被清空**
- 根因：`AIPane` 的 `useEffect[threadKey]` 先把 `messages` 置 `[]` 然后异步 fetch 历史。同一 render 周期，`useEffect[pendingReplyTarget]` 同步触发，调 `persist(messages=[], ...)` 把 DB 的真实历史覆盖成空数组，等 fetch 返回时数据已不在。
- 修复：在 `pendingReplyTarget` effect 里加 `if (loading) return` 守卫，并把 `loading` 加入 deps。只有 fetch 完成后才写 pendingReplyTarget。

## 8. 功能完成情况

**已完成：**
飞书 OAuth + 首登 / 讨论列表 + 详情 / 发讨论 + 回复 / 飞书卡片通知 / 草稿 autosave / 状态徽章 + 排序 / 状态转移（含 reopen 原因）/ @mention 系统（撰写 + 飞书 DM 通知）/ Session 持久化 / shadcn/ui + Tailwind / Thread 列表内嵌未读红点 / GFM markdown（表格、任务列表）/ Post 折叠 + 内联回复 + 草稿指示 / **AI 助手（OpenRouter SSE，回复对象+引用文件，按钮触发草稿生成，对话持久化）** / **PAT + 管理员密码门 + 设置页**

**暂缓（有意为之）：**
附件上传 / RESULT 文件 / AI 摘要写入（post `auto-summary`、INDEX `files[].summary`）/ 多 tenant / 权限分级（PAT 当前 = 全权限）/ 搜索 / 键盘快捷键 / JSAPI 免登 / systemd+Caddy 部署

## 9. 当前状态 + 下一步

**详见 [`vision.md`](./vision.md)。** 那份文档讲"Pivot 要做什么、为什么、还差什么"，包括：
- §6：当前实现状态盘点（✅ / ⚠️ / ❌ 三档）
- §7：路线图（Phase A-G，按优先级）
- §10：新 AI 起手式

memo.md 只讲"现状怎么搭的"（操作细节、踩过的坑），vision.md 讲"要去哪儿"（目标、缺口、计划）。两份互补，**改方向相关内容只动 vision.md，避免两份不同步**。

**运维相关（不在 vision.md 范围）：**
- systemd + Caddy 部署
- 飞书真实 email（替换 commit author 的 `<pinyin>@pivot.local`）
- SQLite 备份（litestream 或 cron+rsync）

## 11. 约束与边界

- **不要启动服务器部署**——本地跑 MVP，上线由用户自己操作
- **不要主动 push 或改版本号**，等用户指示
- **不要动 `old/` 里的文件**——参考资料；要复用就拷贝到 server/ 再改
- **写代码前先问方向**
- **不加无关注释**；只写非显然的 why
- **关键路径要有单测**（git commit/push、OAuth、session、recovery、publish）
- **commit 风格**：`feat:` / `fix:` / `chore:` 前缀，简洁一句话；不主动 amend

## 12. 相关资源

- 本 repo：`/Users/ken/Codes/team-pivot-web`（remote: `hashSTACS-Global/team-pivot-web`）
- 数据仓库：`https://github.com/kellerman-koh/test-team-pivot.git`（自动 clone 到 `var/git/test-team-pivot/`）
- 数据仓库设计文档：`/Users/ken/Codes/teamDocs/CLAUDE.md`（§3 状态机、§4 数据结构）
- 原 APP 参考：`/Users/ken/Codes/team-pivot`（只读）

## 13. 本地快速开发

```bash
# 一次性
cd team-pivot-web
cp .env.example .env         # 填 FEISHU_APP_ID / SECRET / SESSION_SECRET / GIT_TOKEN
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

1. **先读 [`vision.md`](./vision.md)**——明白 Pivot 终极目标、当前缺口、下一步 Phase
2. **再读这份 memo**——掌握现状的实现细节、目录结构、约束、踩过的坑（§8 看已完成的功能盘点）
3. 改代码前看对应模块现有实现
4. 跑 `uv run pytest -q` 验证 baseline 是绿色
5. 写代码前确认方向（§11 第 3 条）
