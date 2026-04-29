# 用户管理体系 · 代码改动地图

| 项 | 值 |
|---|---|
| 文件 | `AI-docs/designs/2026-04-28-user-management-impact-map.md` |
| 创建日期 | 2026-04-28 |
| 状态 | 调研产物（领导审核 spec 期间制作的 plan 输入） |
| 配套 spec | `2026-04-28-user-management-design.md` |

---

## 摘要

按 spec §9 要求对现有代码做了一次"改动地图"扫描，目的是在写实施计划前先把**所有要碰的文件 + 改动幅度**摸清楚，避免到了实施期才发现某些隐藏耦合。

**关键数字：**

| 指标 | 数量 |
|---|---|
| 后端含 `user_open_id` 的文件 | 20 个（116 处引用） |
| 后端含 `require_admin` / `X-Admin-Password` 的文件 | 4 个 |
| 前端含 `open_id` 的文件 | 7 个（40 处引用） |
| 前端含 `X-Admin-Password` 的文件 | 2 个 |
| 现有用户数据模型核心文件 | `server/users.py` + `server/db.py` |
| 现有 OAuth / 鉴权核心文件 | `server/auth/routes.py` + `server/auth/deps.py` + `server/auth/admin.py` + `server/auth/session.py` |

总体感知：**改动面广但每个点都不深**。多数文件只是把字段从 `user_open_id` 改名 `pivot_user_id`、把鉴权从 `require_admin`（密码）改为 `require_admin_user`（角色）；真正需要做新设计的是 §A 和 §B 两块。

---

## A. 用户身份层（核心，重构）

新增 / 重写的部分。这是改动密度最高的区域。

### A.1 新增模块（按 spec §3）

| 文件 | 新建 | 用途 |
|---|---|---|
| `server/pivot_users.py` | 新 | `PivotUser` 实体 + Repo（替代现有 `users.py`） |
| `server/external_bindings.py` | 新 | 外部身份绑定 Repo |
| `server/join_applications.py` | 新 | 加入申请 Repo + 同人匹配候选计算 |
| `server/invites.py` | 新 | 邀请码 Repo（生成/接受/失效） |
| `server/passwords.py` | 新 | bcrypt 哈希封装（依赖：bcrypt 包，需加到 `pyproject.toml`） |
| `server/api/admin_applications.py` | 新 | 管理员审批接口 |
| `server/api/admin_users.py` | 新 | 用户管理接口（暂停/恢复/标 deleted/升降级） |
| `server/api/admin_invites.py` | 新 | 邀请码管理接口 |
| `server/api/init.py` | 新 | `/init/status` + `/init/complete` |
| `server/api/auth_email_password.py` | 新 | 邮箱密码登录接口 |
| `server/api/invite_acceptance.py` | 新 | `/invite/<token>` 加载 + 接受接口 |

预计后端新增 ~11 个模块。

### A.2 现有模块重构

| 文件 | 改动 | 复杂度 |
|---|---|---|
| `server/users.py` | 替换为 `pivot_users.py`；保留 stub 或删除 | 中 |
| `server/db.py` | 加 4 张新表 schema；旧 `users` 留待迁移期间存在 | 低 |
| `server/auth/deps.py` | `_user_from_session` / `_user_from_bearer` 改为返回 `PivotUser`；session/PAT 关联键改为 `pivot_user_id`；新增 `require_admin_user` 替代 `require_admin` | 中 |
| `server/auth/admin.py` | **删除整个文件**（硬编码 `000123` 移除） | 低（但 3 个使用方要改） |
| `server/auth/routes.py` | OAuth callback 分支：已绑定走入口 1，未绑定建 `join_application`；新增邮箱密码登录、邀请接受路由；`/me` 返回新字段（role/status） | 高 |
| `server/auth/session.py` | session 创建/查找按 `pivot_user_id`；中间件加状态校验（status≠active 强制登出） | 中 |
| `server/contacts.py` | `upsert_from_login` 不变（仍写 contacts 镜像）；和 `pivot_user` 不再耦合 | 低 |
| `server/api_tokens.py` | PAT 字段 `user_open_id` → `pivot_user_id` | 低 |
| `server/drafts.py` / `server/inbox.py` / `server/read_state.py` / `server/favorites.py` / `server/ai_conversations.py` | 字段重命名（`user_open_id` → `pivot_user_id`） | 低（机械替换） |

### A.3 鉴权切换（移除 `require_admin`）

`require_admin` 被 3 处使用，全部要改为 `require_admin_user`：

| 文件 | 端点 | 改动 |
|---|---|---|
| `server/api/ai.py` | `GET /api/ai/settings`、`PUT /api/ai/settings` | 替换 dependency |
| `server/api/contacts.py` | `POST /contacts/sync` | 替换 dependency |
| `server/api/workspace.py` | `GET/PUT /admin/workspace-config` | 替换 dependency |

---

## B. 迁移层（一次性脚本）

| 文件 | 内容 |
|---|---|
| `scripts/audit_user_migration.py` | **已完成**（gap 期产物）：只读审计脚本 |
| `server/scripts/migrate_user_management.py` | 新增（实施期产物）：单事务迁移脚本，含 `--initial-admin <pinyin>` + `--dry-run`，按 spec §9 |
| `server/tests/test_migrate_user_management.py` | 新增：fixtures + 断言（行数对齐、外键全有、孤儿为空、initial-admin 命中） |

---

## C. 前端改动

### C.1 新页面 / 新组件

| 文件 | 用途 |
|---|---|
| `web/src/pages/Init.tsx` | 初始化页面（含警示语 + 飞书/邮箱密码二选一） |
| `web/src/pages/PendingApproval.tsx` | 申请已提交 / 等待审批的占位页 |
| `web/src/pages/InviteAccept.tsx` | 邀请链接接受页（设密码 + 填名） |
| `web/src/pages/admin/AdminApplications.tsx` | 待审批列表 + 审批 dialog |
| `web/src/pages/admin/AdminUsers.tsx` | 用户列表 + 治理操作 + 升降级 |
| `web/src/pages/admin/AdminInvites.tsx` | 邀请码生成 / 列表 / 失效 |
| `web/src/components/admin/MatchCandidates.tsx` | 同人匹配候选 chip 列表（reason 标签） |
| `web/src/components/admin/UserStatusBadge.tsx` | 用户状态徽章 |
| `web/src/components/admin/MergeUserDialog.tsx` | 合并到已有用户的搜索 dialog |

### C.2 修改的现有文件

| 文件 | 改动 |
|---|---|
| `web/src/api.ts` | 移除 `X-Admin-Password` 头；新增 admin/applications/users/invites 一组调用；登录入口加邮箱密码 | 中 |
| `web/src/pages/Login.tsx` | 增加邮箱密码登录表单（保留飞书扫码主入口） | 中 |
| `web/src/pages/AdminPage.tsx` | 删除"输入管理员密码"门控；改为基于 `me.role==='admin'` 路由守卫 | 中 |
| `web/src/App.tsx` | 路由守卫：检测 `init/status`，未初始化重定向 `/init`；user.status≠active 强制登出 | 中 |
| `web/src/components/Layout.tsx` / `UserBar.tsx` | 用户对象多了 `role` / `status` 字段；admin 才显示后台入口 | 低 |
| 各组件中 `open_id` 的引用（7 文件 / 40 处） | 多数是 mention 高亮、owner 选择器、文件作者展示——不直接动 schema，但要确认拿到的 `display_info` 含 `status` 以支撑 §7.2 渲染 | 低-中 |

### C.3 新增/修改的展示规则（spec §7）

`web/src/lib/displayUser.ts`（新增）：统一封装"按 status 渲染名字头像"的工具函数（active/suspended/deleted/unknown 四态映射到 className）。所有展示用户名的地方调用。

---

## D. 测试

新增 / 修改的测试（按测试金字塔分布）：

| 测试 | 范围 |
|---|---|
| `test_pivot_users.py` 等单测 | Repo 行为 |
| `test_join_applications.py` | 同人匹配候选生成 + 状态机 |
| `test_invites.py` | 邀请码生成 / 接受 / 过期 / 重放 |
| `test_admin_applications_api.py` | 审批接口 happy path + 护栏 |
| `test_admin_users_api.py` | 状态变更 / 升降级 / 在线管理员护栏 |
| `test_init_api.py` | /init 路由开放/关闭、并发抢占 |
| `test_auth_routes.py`（修改） | OAuth callback 三分支：已绑 / 未绑 / 已被拒 |
| `test_auth_session.py`（修改） | 中间件检测 status 变化强制登出 |
| `test_migrate_user_management.py` | 迁移脚本 + dry-run |
| 现有所有 `test_*.py`（修改） | fixture user 改用 `pivot_user_id`；`require_admin_user` 替换 `X-Admin-Password` 头 |

---

## E. 配置 / 部署

| 项 | 改动 |
|---|---|
| `pyproject.toml` | 加 `bcrypt`、`ulid-py`（或 stdlib uuid 替代）依赖 |
| `.env.example` | 移除 `ADMIN_PASSWORD` 字样（如有）；记录"首次部署需运行迁移并指定 --initial-admin" |
| `pivot-memo.md` | 更新 §4 鉴权层、§5 数据模型描述（迁移后） |
| `pivot-product.md` | 如有"管理员密码"提及需更新 |

---

## F. 改动量初估（用于评估实施期分配）

| 区域 | 文件数 | 复杂度 | 估时（理想日） |
|---|---|---|---|
| A. 用户身份层（新模块） | ~11 | 高 | 2-3 |
| A. 现有模块重构 | ~10 | 中 | 1-2 |
| A. 鉴权切换 | 3 | 低 | 0.25 |
| B. 迁移脚本 + 单测 | 2 | 中 | 0.5-1 |
| C. 前端新页面 + 组件 | ~9 | 中-高 | 1.5-2 |
| C. 前端现有修改 | ~6 | 低-中 | 0.5-1 |
| D. 单测 + 集成测 | ~10 | 中 | 1-1.5 |
| E. 配置 + 文档 | 4 | 低 | 0.25 |
| **合计** | ~55 | — | **6-10 天** |

这份估时和 brainstorm 阶段对用户给的 5-7 天预期吻合上限——领导审核完 spec 后可据此分子任务进 plan。

---

## G. 实施前要回答的开放问题（plan 阶段澄清）

1. **会话中间件状态校验的位置**：是放在 `_user_from_session` 里（每次请求都查），还是 session 上次活动过期机制？前者实时但有 DB 查询开销，后者最多 ~5 分钟延迟但便宜。
2. **邀请码 token 的链接 host**：管理员复制时给 `https://your-pivot/...` 还是相对路径？取决于部署形态（前端会知道 host）。
3. **`pivot_user.id` 用 ULID 还是 stdlib uuid4**：spec 写了 ULID（可排序、便于 debug），但 ULID 需要新依赖。stdlib uuid4 也能用，权衡值不值。
4. **bcrypt 工作因子**：默认 12 OK，还是按 Pivot 内部安全要求调？
5. **`/init` 期间路由守卫的实现**：FastAPI 中间件 vs 每条路由 dependency；中间件更全面但要小心放过 `/init` 自身和静态资源。
6. **前端 `display_info` 的获取**：现有 `/me`、posts API 的返回结构里要不要直接附 `status`，还是前端单独发请求按需查？前者改动多但展示一气呵成。

这些都是细节问题，留到 plan 写出来时定。

---

## 附：关键文件 grep 摘要

```
require_admin（4 处使用）：
  server/auth/admin.py:17       def require_admin(...)
  server/api/ai.py:21           import
  server/api/ai.py:91           GET /api/ai/settings
  server/api/ai.py:102          PUT /api/ai/settings
  server/api/contacts.py:8      import
  server/api/contacts.py:46     POST /contacts/sync
  server/api/workspace.py:8     import
  server/api/workspace.py:51    GET /admin/workspace-config
  server/api/workspace.py:62    PUT /admin/workspace-config

X-Admin-Password（前端 2 处）：
  web/src/api.ts                所有需要 admin 权限的请求 helper 在这里加 header
  web/src/pages/AdminPage.tsx   输入密码 → 暂存 → 后续请求带 header

user_open_id（后端 116 处 / 20 文件）：
  集中在 db.py / auth/* / api/* / drafts.py / inbox.py / read_state.py /
  favorites.py / ai_conversations.py / api_tokens.py / mcp/auth.py 及其单测
  机械替换为 pivot_user_id 即可，但要保证迁移脚本运行后再上线

open_id（前端 40 处 / 7 文件）：
  api.ts (3) / pages/MatterDetailPane.tsx (5) / pages/NewMatter.tsx (5) /
  components/matter/CreateFileDialog.tsx (9) / components/MentionField.tsx (10) /
  components/matter/FileCard.tsx (3) / components/matter/OwnerPicker.tsx (5)
  多数是 mention/owner 选人场景；display_info 改造时一并对齐
```
