# team-pivot-web · 构建备忘

新 Claude Code session 先读这个。

## 1. 项目目标

把原 `team-pivot`（飞书 IM bot + EC pipeline APP）改造为**独立 Web 应用**，交互形态类似邮件客户端，数据仓库继续用 Git（`teamDocs` 模式），只通过**飞书 OAuth2 鉴权**登录，不开放自主注册。

## 2. 为什么不继续做 EC skill

- EC 是 IM bot 运行时，pipeline + 卡片回复范式承载不了富 UI
- 邮件客户端式交互（双栏阅读 / 键盘 / 拖拽）必须是真正的 Web 前端
- 飞书可以通过机器人菜单 / 群卡片按钮跳转 Web H5，鉴权用飞书 JSAPI 免登，无需 EC 中转
- EC bot 保留做"通知推送 + 快速发帖"的轻交互，和 Web 并行互补

## 3. 技术栈（已定）

| 层 | 选型 |
|---|---|
| 前端 | React 18 + Vite + TypeScript + shadcn/ui + Tailwind + React Router 7 + TanStack Query |
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| Git | GitPython + 少量 subprocess（沿用 `old/tools/git_ops.py` 封装） |
| 缓存 | SQLite (aiosqlite)：索引 threads / posts / read_state / drafts / users |
| Session | 签名 cookie（itsdangerous）+ 服务端 session（先内存/SQLite，不引入 Redis） |
| 飞书 SDK | `lark-oapi`（官方 Python） |
| 部署 | **Ubuntu 24 LTS 专机直接部署**（不用 Docker）：systemd 跑 uvicorn + Caddy 反代 + 自动 HTTPS |

## 4. 目录规划

```
team-pivot-web/
├── old/                          # 原 APP 代码归档（全部可选复用素材）
├── server/                       # FastAPI 后端（待建）
│   ├── app.py
│   ├── auth/                     # feishu_oauth, session
│   ├── api/                      # discussions, drafts, replies, inbox
│   ├── git/                      # workspace, repo_layout
│   ├── cache/                    # SQLite models, scanner
│   └── feishu/                   # notify（复用 old/tools/notify/）
├── web/                          # React 前端（待建，Vite 初始化）
│   └── src/ routes components lib api
├── pyproject.toml                # 新的 Python 项目配置
├── requirements.txt              # 或用 uv/poetry 二选一
└── deploy/
    ├── team-pivot-web.service    # systemd unit
    └── Caddyfile                 # 反代配置
```

服务器运行时目录（Ubuntu 24）：

```
/opt/team-pivot-web/               # 代码 + .venv
/var/lib/team-pivot-web/
  git/                             # teamDocs 工作副本
  data.db                          # SQLite
  uploads/                         # 附件暂存
/etc/systemd/system/team-pivot-web.service
/etc/caddy/Caddyfile
```

## 5. old/ 里值得复用的东西

不要动，按需**拷贝/改写**到 server/ 下：

- `old/tools/git_ops.py` — clone/pull/commit/push 的原子性封装
- `old/tools/threads.py` — 从 Git 目录读取 thread 列表/post 列表
- `old/tools/index.py` — 讨论 summary / 状态索引
- `old/tools/drafts.py` — 草稿 CRUD（但现在草稿要改成 SQLite 而非文件系统）
- `old/tools/notify/feishu_bot.py` + `feishu_token.py` — 飞书 token 管理 + 卡片推送
- `old/adapters/feishu/card_formatter.py` — CardKit v2 卡片模板（通知用）
- `old/pipelines/*/steps/*.py` — 业务逻辑参考，不要直接搬 pipeline 架构

**不要复用**：`pipelines/` 的 YAML + runner、`bin/app-runner.py`、`bin/llm_gateway.py`、`SKILL.md`、EC / 卡片交互、LLM stub 相关。这些属于 EC APP 范式，Web 版不需要。

## 6. 鉴权设计

**双路径**（同一套后端 session）：

1. **浏览器外部访问**（开发 / 桌面）
   - `GET /login` → 302 到 `https://open.feishu.cn/open-apis/authen/v1/authorize?app_id=&redirect_uri=&state=`
   - 回跳 `/auth/callback?code=` → 后端用 `app_access_token` 换 `user_access_token` → 拉 `/authen/v1/user_info` → 建 session → 302 `/`
2. **飞书内嵌 WebView**（机器人菜单/卡片跳转）
   - 前端 `tt.requestAuthCode({appId})` → POST `/auth/jsapi-exchange {code}` → 后端换 token 建 session

**首登引导**：
- 飞书返回的 `open_id` 作主键
- DB 里没记录时，一次性收集 `pinyin_name`（用于 git author、分支名）；`github_username` 可选
- `users(open_id PK, union_id, name, avatar_url, pinyin, github_username, created_at)`

**session**：签名 cookie 存 `session_id`，服务端表 `sessions(id, user_open_id, expires_at)`。

**飞书应用配置**（需要业主在飞书后台做）：
- App ID / App Secret（放 `.env`）
- 回调域名白名单
- 打开"获取用户邮箱"/"身份信息" 权限
- 机器人菜单项 → 指向 Web 地址

## 7. 数据模型（SQLite）

```sql
users(open_id PK, union_id, name, avatar_url, pinyin, github_username, created_at)
sessions(id PK, user_open_id, expires_at, created_at)
threads_index(project, slug, title, creator_open_id, status,
              last_activity_at, summary_md, PRIMARY KEY(project, slug))
posts_index(id PK, project, slug, seq, author_open_id, filename,
            created_at, raw_path)
read_state(user_open_id, thread_key, last_read_post_id,
           PRIMARY KEY(user_open_id, thread_key))
drafts(id PK, user_open_id, type, title, body_md, thread_key,
       created_at, updated_at)
```

Git 仍是权威源；SQLite 是索引/缓存，启动时 + 每次 push 后做增量扫描重建。

## 8. Git 并发

服务端单把 asyncio.Lock 串行 `pull → commit → push`；push 失败自动 rebase 重试 3 次，超时返回 "并发冲突，请刷新"。不搞多 worktree 锁。

## 9. MVP 范围（第一刀）

1. 飞书 OAuth 登录（外部 + JSAPI 两路）+ 首登 pinyin 引导
2. Inbox（未读聚合，按讨论分组）
3. 讨论列表（按 project 分）+ 讨论详情（时间线列 posts）
4. 新建草稿 + 发布讨论 + 回复讨论（走 git commit/push）
5. 机器人通知（发布成功后推飞书卡片）

**暂缓**：附件上传、`summarize` / `result` 管理、多 tenant、权限分级、搜索。

## 10. 推荐推进顺序

建议 **2 → 1 → 3 的切入顺序**，理由：先打通鉴权能暴露所有外部依赖（飞书 App 配置、HTTPS、回调链路）；脚手架和数据层是可控工作。

1. **先做飞书 OAuth 登录闭环**（server auth/ + 前端 /login 页 + 一个空白已登录首页）
2. 再搭骨架（FastAPI 路由分层 + Vite 前端脚手架 + systemd/Caddy 模板）
3. 再写数据层（git 封装 + SQLite scanner + thread/post API）
4. 最后做 UI 和通知

## 11. 约束与边界（别越线）

- **不要启动服务器部署**。本地跑 MVP 为主，上线由用户自己做
- **不要主动 push 或改版本号**，等用户指示（保留这个规范）
- **不要动 `old/` 里的文件**——那是参考资料；要复用就拷贝到 server/ 再改
- **写代码前先问方向**（之前因擅自 error-handling 被回滚过）
- **不加无关注释**；CLAUDE.md 说"默认不写注释，只写非显然的 why"
- **测试先**：关键路径（git commit/push、OAuth token exchange、session）要有单测
- **commit 风格**沿用 `chore:` / `feat:` / `fix:` 前缀，简洁一句话

## 12. 相关 repo / 资源

- 本 repo：`/Users/ken/Codes/team-pivot-web`（remote: `hashSTACS-Global/team-pivot-web`，private）
- 原 APP：`/Users/ken/Codes/team-pivot`（remote: `hashSTACS-Global/team-pivot`）
- 数据仓库：`/Users/ken/Codes/teamDocs`（和 team-pivot 共享）
- EC 代码：`/Users/ken/Codes/EnClaws`（只参考，不动）
- 飞书 OAuth 文档：`https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/web-app-access-token`
- `lark-oapi` Python SDK：`https://github.com/larksuite/oapi-sdk-python`

## 13. 下一步具体起手式

新 session 可以这样起步：

```
1. 读 memo.md
2. 读 old/docs/architecture.md（了解原 APP 设计思路）
3. 创建 server/ 和 web/ 目录骨架
4. 写 server/auth/feishu_oauth.py（先写 provider 的 token 交换逻辑 + 测试）
5. 写一个最小的 FastAPI app：/login, /auth/callback, /me
6. 前端用 Vite 建 web/，加 /login 页和登录后跳转
7. 飞书 App 的 App ID/Secret 放 .env（先占位，用户配齐再跑通）
```
