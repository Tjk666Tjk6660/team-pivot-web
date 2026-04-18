# team-pivot-web · 构建备忘

新 Claude Code session 先读这个。**这是项目现状的权威文档**，memo 和代码有出入时以代码为准，但请立刻更新 memo。

## 1. 项目目标

把原 `team-pivot`（飞书 IM bot + EC pipeline APP）改造为**独立 Web 应用**，交互形态类似邮件客户端，数据仓库继续用 Git（`teamDocs` 模式），只通过**飞书 OAuth2 鉴权**登录，不开放自主注册。

## 2. 为什么不继续做 EC skill

- EC 是 IM bot 运行时，pipeline + 卡片回复范式承载不了富 UI
- 邮件客户端式交互（双栏阅读 / 键盘 / 拖拽）必须是真正的 Web 前端
- 飞书可以通过机器人菜单 / 群卡片按钮跳转 Web H5，鉴权用飞书 JSAPI 免登，无需 EC 中转
- EC bot 保留做"通知推送 + 快速发帖"的轻交互，和 Web 并行互补

## 3. 技术栈（实际采用）

| 层 | 选型 | 状态 |
|---|---|---|
| 前端 | React 18 + Vite + TypeScript + React Router 7 + react-markdown | ✅ 已搭 |
| shadcn/ui + Tailwind | 未用（当前 inline 样式，MVP 够用） | ⏳ 未做 |
| TanStack Query | 未引入（`useState + fetch` 足够 MVP） | ⏳ 未做 |
| 后端 | Python 3.12 + FastAPI + Uvicorn（sync handlers in threadpool） | ✅ |
| 包管理 | **uv**（非 poetry / requirements.txt） | ✅ |
| Git | 纯 subprocess 封装（不用 GitPython） | ✅ |
| SQLite | 标准库 `sqlite3`（非 aiosqlite，sync handlers 够用） | ✅ |
| Session | 内存 dict + 签名 cookie（itsdangerous） | ✅ |
| 飞书 SDK | `lark-oapi`（OAuth）；`httpx` 直调（IM 通知） | ✅ |
| 日志 | 标准库 `logging`，`LOG_LEVEL` env 切换 | ✅ |
| 部署 | Ubuntu 24 LTS + systemd + Caddy | ⏳ 未做 |

## 4. 目录结构（实际）

```
team-pivot-web/
├── old/                              # 原 APP 代码归档（参考用，不动）
├── server/                           # FastAPI 后端
│   ├── app.py                        # create_app() 工厂 + 依赖装配
│   ├── config.py                     # 从 .env 读配置
│   ├── logging_setup.py              # 日志配置
│   ├── db.py                         # SQLite 连接 + schema 初始化
│   ├── auth/
│   │   ├── feishu_oauth.py           # lark-oapi 封装 code → token → user_info
│   │   ├── session.py                # 内存 SessionStore（sid → open_id）
│   │   └── routes.py                 # /login /auth/callback /me /logout /me/profile
│   ├── api/
│   │   ├── discussions.py            # GET/POST threads、thread detail
│   │   ├── drafts.py                 # CRUD + /publish
│   │   └── inbox.py                  # GET /inbox + POST .../read
│   ├── users.py                      # UserRepo（SQLite）
│   ├── drafts.py                     # DraftRepo
│   ├── read_state.py                 # ReadStateRepo
│   ├── workspace.py                  # Workspace：clone/pull/write_session/recover
│   ├── git_ops.py                    # subprocess 封装（clone/pull/commit/push）
│   ├── posts.py                      # markdown+frontmatter 读写 + 两阶段 pending
│   ├── threads.py                    # 目录扫描 → ThreadMeta/ThreadDetail
│   ├── index_files.py                # index/<slug>-discuss.index.yaml 读写
│   ├── inbox.py                      # compute_inbox（未读计算）
│   ├── mentions.py                   # open_id → 用户名解析
│   ├── publish.py                    # publish_proposal/publish_reply（写路径共享入口）
│   ├── recovery.py                   # 启动时扫 un-indexed 修复
│   ├── notify.py                     # FeishuNotifier / NoOpNotifier 卡片通知
│   └── tests/                        # pytest，101 个 passing
└── web/                              # React 前端
    ├── src/
    │   ├── main.tsx / App.tsx        # BrowserRouter + 根组件
    │   ├── api.ts                    # 所有 fetch 封装
    │   ├── hooks/useDraftAutosave.ts # 2s debounce 自动存草稿
    │   ├── lib/time.ts               # relativeTime
    │   ├── components/
    │   │   ├── UserBar.tsx           # 头像 + 名 + 登出
    │   │   └── StatusBadge.tsx       # 5 色状态徽章
    │   └── pages/
    │       ├── Login.tsx             # Sign in with Feishu
    │       ├── ProfileSetup.tsx      # 首登 pinyin 收集
    │       ├── Home.tsx              # Inbox + Drafts + Discussions 三栏
    │       ├── NewThread.tsx         # 发讨论表单（autosave）
    │       └── ThreadDetail.tsx      # posts 列表 + Reply 表单（autosave）
    └── vite.config.ts                # /login /auth /me /logout /api 代理到 :8000

.env                                  # 本地配置（git 忽略）
.env.example                          # 模板
var/                                  # 运行时数据（git 忽略）
  data.db                             # SQLite
  git/test-team-pivot/                # 数据仓库工作副本
  log/pivot.log                       # tee 日志（手动开启）
  .feishu-token-<app_id>.json         # 飞书 tenant token 缓存
```

**生产目录（目标，未部署）**：`/opt/team-pivot-web/` 代码、`/var/lib/team-pivot-web/` 数据、`/etc/systemd/system/team-pivot-web.service`、`/etc/caddy/Caddyfile`。

## 5. 从 old/ 实际 port 了什么

| 文件 | 去向 | 改动 |
|---|---|---|
| `old/tools/git_ops.py` | `server/git_ops.py` | 加 committer_name/email 参数；加日志 |
| `old/tools/threads.py` | `server/threads.py` | 改名结构，去掉 EC 环境依赖，加 status/last_updated |
| `old/tools/atomicity.py` | `server/posts.py` + `server/recovery.py` | write_post_pending / mark_indexed / scan_un_indexed 三件套 |
| `old/tools/index.py` | `server/index_files.py` | 只用到 read/create/append，没 port 状态机 ALLOWED_TRANSITIONS |
| `old/tools/notify/feishu_bot.py` + `feishu_token.py` | `server/notify.py` | 合并，用 httpx 直调替代 requests + 自管 token cache |

**没 port**：`pipelines/`、`bin/`、`SKILL.md`、EC 卡片交互、LLM gateway、`old/tools/drafts.py`（改 SQLite 了）、`card_formatter.py`（重新写了极简模板）。

## 6. 鉴权与会话（实现状态）

| 功能 | 状态 |
|---|---|
| 外部浏览器 OAuth 流程（`/login` → 飞书 → `/auth/callback`） | ✅ |
| 首登 pinyin + github_username 收集 | ✅ |
| 签名 cookie + 内存 session | ✅ |
| **JSAPI 免登（飞书 WebView 内嵌路径）** | ❌ 未实现 |
| 飞书 email 收集到 users 表 | ❌ 未做（现在 git author 用 `<pinyin>@pivot.local` 合成邮箱） |

飞书后台必须配置：App ID/Secret、回调白名单 `http://localhost:8000/auth/callback`、`contact:user.base:readonly` 权限、机器人能力 + IM 权限（若开通知）。

## 7. 数据模型（实际）

```sql
-- 已实现
users(open_id PK, union_id, name, avatar_url, pinyin, github_username, created_at)
drafts(id PK, user_open_id, type, title, category, body_md, thread_key, created_at, updated_at)
read_state(user_open_id, thread_key, last_read_post_filename, updated_at, PK(user, thread_key))

-- 砍掉（决策讨论见对话记录）
threads_index ❌   posts_index ❌
-- 决策：threads 规模几十到几百，直读文件系统够用；
-- SQLite 只存"用户私有状态"（users/drafts/read_state），
-- 内容本体全在 git。
```

**Git 仍是权威源**。SQLite 只做 per-user 状态缓存，不做内容索引。

Session 放内存 `SessionStore`（重启丢失），不存 DB。用户登录后 sid cookie 存服务端 map。

## 8. Git 写流程

实际用 `threading.Lock`（不是 asyncio.Lock——FastAPI sync handler 跑在线程池）。流程：

```python
with workspace.write_session(message, author_name, author_email):
    # pull --rebase                  ← 获取远端最新
    # caller 写文件
    # git commit --author="pinyin <pinyin@pivot.local>"
    #   -c user.name=team-pivot-web -c user.email=team-pivot-web@pivot.local
    # git push（失败 → rebase + 重试 3 次）
```

**两阶段原子写**（抗崩溃）：
1. `write_post_pending`：帖子写入时 frontmatter 标 `index_state: un-indexed`
2. 更新 index yaml（原子 tmp+rename）
3. `mark_indexed`：翻标志到 `indexed`

三步全在 write_session 里，git 看到的是最终态 + 一次 commit。

**启动恢复 `workspace.recover()`**：
- 扫所有 `index_state: un-indexed` 的文件
- 按 filename 类型（proposal/reply）补 index 条目 + 翻标志
- 如果工作树脏，commit "chore: recover..."

List 接口过滤 un-indexed 文件，避免过渡态给用户看到。

## 9. MVP 完成情况（vs memo 第一版 §9）

| 条目 | 状态 | commit |
|---|---|---|
| 1. 飞书 OAuth 外部 + 首登 pinyin | ✅ | `feat: feishu OAuth login loop` / `feat: SQLite users table + first-login pinyin setup` |
| 2. Inbox（未读聚合，按讨论分组） | ✅ | `feat: inbox with per-user unread tracking` |
| 3. 讨论列表 + 详情（时间线） | ✅ | `feat: read-only discussions API` / `feat: thread detail page + title/author resolution` |
| 4. 发讨论 + 回复（走 git commit/push） | ✅ | `feat: write path for new discussions + replies, with two-phase crash recovery` |
| 5. 飞书卡片通知 | ✅ | `feat: feishu card notifications on publish` |
| **额外**：草稿 CRUD（autosave） | ✅ | `feat: drafts CRUD with autosave + atomic publish` |
| **额外**：日志体系 | ✅ | `feat: logging infrastructure with LOG_LEVEL env toggle` |
| **额外**：status 徽章 + last_updated 排序 | ✅ | `feat: thread status + last-updated from index YAML files` |

memo 明确"暂缓"的条目仍未做：附件上传、summarize/result 管理、多 tenant、权限分级、搜索。

## 10. 和设计文档的差异（未完成/有意为之）

对照 `/Users/ken/Codes/teamDocs/CLAUDE.md` 的 §3/§4：

| 设计条目 | 当前 | 备注 |
|---|---|---|
| 5 个状态名 (open/concluded/produced/closed/pending) | ✅ | UI 徽章正常显示 |
| **状态转移动作**（`open ↔ concluded`、`reopen`、`closed/pending`） | ❌ | 当前只能读 status，不能改 |
| `reopen` 动作 + timeline 记原因 | ❌ | — |
| `RESULT` 文件（结论） | ❌ | 设计有，memo 暂缓 |
| Post frontmatter `summary`（AI 摘要） | ❌ | 需要 LLM，暂缓 |
| INDEX `files[].summary` | ⚠️ 空串 | 预留字段，等 LLM |
| INDEX `files[].refs` | ⚠️ proposal 空；reply 已加 `from` | 跨讨论的 `refer` / `blocked_by` 未做 |
| INDEX timeline `mention` 字段 | ❌ | 需配合 @mention 特性 |
| Post frontmatter `created` | ✅ | 已和设计文档对齐（曾经错叫 `created_at`） |

## 11. 下一步计划（按优先级）

### 业务闭环

1. **状态转移动作**（设计 §3.2）——让用户在 Web 点"标记为已解决 / 暂搁 / 重新打开 / 关闭"，实现 ALLOWED_TRANSITIONS，timeline 记录"从 X 状态转移到 Y，原因：..."，reopen 要求写原因
2. **@mention 系统**——撰写时 `@张三` 解析为 `<at user_id="ou_xxx">`，写进 INDEX timeline 的 `mention` 字段；飞书卡片通知把被 @ 的人 ping 出来（需要 users 表扩展，或调飞书 `/contact/v3/users/batch_get` 预热 user map）

### UX 打磨

3. **shadcn/ui + Tailwind**——当前 inline 样式粗糙，替换为正规设计系统
4. **键盘快捷键**（j/k 翻列表、r 回复等邮件客户端式交互）
5. **GFM markdown**（表格、任务列表）——给 react-markdown 加 `remark-gfm`

### 上线

6. **systemd + Caddy 部署模板**（memo §4 已规划）
7. **真正的飞书邮箱**——登录时 `UserRepo.upsert_from_feishu` 保存 email，commit author 用真邮箱替换 `<pinyin>@pivot.local`
8. **SQLite 备份**（litestream 或 cron+rsync）—— 草稿 / read_state 持久化

### 新能力（依赖 LLM）

9. **AI 摘要**（post `summary`、INDEX `files[].summary`）
10. **RESULT 文件生成**（讨论达成结论时自动总结 → `concluded`）
11. **JSAPI 免登**（飞书机器人菜单内嵌 WebView）

**建议顺序**：1 → 2 → 6 → 3。1+2 闭合业务，6 让团队其他人能用，3 再打磨视觉。9/10 等 LLM 策略定了再做。

## 12. 约束与边界（别越线）

- **不要启动服务器部署**——本地跑 MVP 为主，上线由用户自己做
- **不要主动 push 或改版本号**，等用户指示
- **不要动 `old/` 里的文件**——参考资料；要复用就拷贝到 server/ 再改
- **写代码前先问方向**（之前擅自 error-handling 被回滚过）
- **不加无关注释**；只写非显然的 why
- **关键路径要有单测**（git commit/push、OAuth、session、recovery、publish）
- **commit 风格** `feat:` / `fix:` / `chore:` 前缀，简洁一句话；**不主动 amend**
- **飞书应用权限 / 群机器人添加** 是用户的事，代码不尝试自动化

## 13. 相关资源

- 本 repo：`/Users/ken/Codes/team-pivot-web`（remote: `hashSTACS-Global/team-pivot-web`）
- 数据仓库：`https://github.com/kellerman-koh/test-team-pivot.git`（workspace，自动 clone 到 `var/git/test-team-pivot/`）
- 原 APP：`/Users/ken/Codes/team-pivot`（参考，不动）
- 同仓数据副本：`/Users/ken/Codes/teamDocs`（手工 clone，和 team-pivot 共享）
- EC 代码：`/Users/ken/Codes/EnClaws`（只参考）
- 飞书 OAuth：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/web-app-access-token
- 飞书 IM（通知用）：https://open.feishu.cn/document/server-docs/im-v1/message/create
- `lark-oapi` Python SDK：https://github.com/larksuite/oapi-sdk-python
- 数据仓库设计文档：`/Users/ken/Codes/teamDocs/CLAUDE.md`（§3 状态机、§4 数据结构）

## 14. 本地快速开发

```bash
# 一次性
cd team-pivot-web
cp .env.example .env         # 填 FEISHU_APP_ID / SECRET / SESSION_SECRET / GIT_TOKEN
uv sync                      # 装 Python 依赖
cd web && npm install        # 装前端依赖

# 每次开发（两个终端）
# 终端 1：后端
uv run uvicorn --factory server.app:create_app --reload --port 8000 2>&1 \
  | tee -a var/log/pivot.log

# 终端 2：前端
cd web && npm run dev

# 浏览器打开
http://localhost:5173

# 测试
uv run pytest -q              # 101 passing
```

调试日志切 DEBUG：`.env` 改 `LOG_LEVEL=DEBUG` 重启。

## 15. 对新 session 的起手式

```
1. 读这份 memo（§9 知道已完成、§10 知道差距、§11 知道下一步）
2. 如果要改代码：先看 server/ 和 web/src/ 的现有结构，对应模块已有实现
3. 跑 uv run pytest 验证你的 baseline 是绿色
4. 按 §11 的优先级和当前对话上下文决定做哪一步
5. 写代码前确认方向（§12 第 4 条）
```
