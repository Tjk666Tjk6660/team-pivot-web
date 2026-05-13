# team-pivot-web 后端路由总览

> 说明：本文档整理 `server/` 里 FastAPI 路由定义与 `server/app.py` 的挂载关系，按业务域分类，并标注源文件位置。

## 路由挂载入口

- 主应用入口：`server/app.py`
- 所有 API 路由通过 `app.include_router(...)` 挂载到主 FastAPI 应用
- MCP 子应用通过 `app.mount("/mcp", mcp_app)` 挂载

### 主要挂载关系

- `server/auth/routes.py` → 登录 / 回调 / 当前用户 / 退出
- `server/api/init.py` → 初始化管理员
- `server/api/auth_email_password.py` → 邮箱密码登录
- `server/api/auth_invite.py` → 邀请链接流程
- `server/api/*` → 业务 API
- `server/mcp/server.py` → `/mcp` 子应用

---

## 1. 认证与会话

### 1.1 飞书登录 / OAuth

**源文件**：`server/auth/routes.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/auth/entry` | 登录入口。根据是否已登录、是否是飞书客户端决定跳转到前端登录页或飞书预授权页。 |
| GET | `/login` | 发起飞书 OAuth 授权，跳转到授权地址。 |
| GET | `/auth/callback` | 飞书回调地址。处理 `code/state/error`，交换 token、创建 session、绑定用户或创建申请。 |
| GET | `/me` | 获取当前登录用户信息。 |
| POST | `/me/profile` | 更新当前用户资料（`pinyin`、`github_username`）。 |
| POST | `/logout` | 登出，删除 session cookie。 |

### 1.2 邮箱密码登录

**源文件**：`server/api/auth_email_password.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| POST | `/auth/login_email_password` | 邀请用户使用邮箱+密码登录，成功后创建 session。 |

### 1.3 初始化管理员

**源文件**：`server/api/init.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/api/init/status` | 判断系统是否还需要初始化管理员。 |
| POST | `/api/init/complete` | 完成首次初始化，创建首个管理员并写入邀请账号绑定。 |

### 1.4 邀请流程

**源文件**：`server/api/auth_invite.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/api/invite/{token}` | 获取邀请信息，供前端展示邀请页。 |
| POST | `/api/invite/{token}/start` | 启动邀请流程，生成/确认邀请态。 |

### 1.5 API Token

**源文件**：`server/api/tokens.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| POST | `/api/tokens` | 创建个人访问令牌（PAT）。 |
| GET | `/api/tokens` | 列出当前用户的令牌。 |
| DELETE | `/api/tokens/{short_id}` | 删除指定令牌。 |

---

## 2. 用户与个人设置

### 2.1 用户资料 / 搜索

**源文件**：`server/api/users.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/users/search` | 搜索用户，供前端圈人/检索使用。 |

### 2.2 联系人

**源文件**：`server/api/contacts.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/contacts` | 获取联系人列表。 |

### 2.3 个人偏好

**源文件**：`server/api/preferences.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/me/preferences` | 获取当前用户偏好设置。 |
| PUT | `/me/preferences/{key}` | 更新某个偏好项。 |

### 2.4 Markdown 样式设置

**源文件**：`server/api/markdown_styles.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/api/markdown/styles` | 获取 Markdown 样式列表。 |
| PUT | `/api/me/markdown-style` | 更新当前用户的 Markdown 样式。 |
| GET | `/api/admin/markdown-settings` | 管理员查看 Markdown 全局设置。 |
| PUT | `/api/admin/markdown-settings` | 管理员更新 Markdown 全局设置。 |

---

## 3. 工作区与配置

### 3.1 工作区状态与配置

**源文件**：`server/api/workspace.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/workspace/status` | 获取工作区状态。 |
| POST | `/workspace/refresh` | 刷新工作区。 |
| GET | `/workspace/mirror` | 获取镜像信息。 |
| GET | `/admin/workspace-config` | 管理员读取工作区配置。 |
| PUT | `/admin/workspace-config` | 管理员更新工作区配置。 |

### 3.2 主页

**源文件**：`server/api/app_home.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/home` | 返回应用首页所需数据。 |

---

## 4. Matter / 主题 / 动态流

### 4.1 Matter 主接口

**源文件**：`server/api/matters.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/matters` | 列出 matters。 |
| GET | `/matters/{matter_id}` | 获取 matter 详情。 |
| POST | `/matters/{matter_id}/files/{filename}/read` | 标记某文件已读。 |
| POST | `/matters/{matter_id}/events/read` | 标记 matter 事件已读。 |
| POST | `/matters/{matter_id}/read` | 标记 matter 已读。 |
| POST | `/matters/{matter_id}/favorite` | 收藏/取消收藏 matter。 |
| GET | `/matters/{matter_id}/visibility` | 获取 matter 可见性。 |
| PUT | `/matters/{matter_id}/visibility` | 更新 matter 可见性。 |
| POST | `/matters` | 新建 matter。 |
| POST | `/matters/{matter_id}/owner` | 更新 matter 负责人。 |
| POST | `/matters/{matter_id}/events` | 为 matter 追加事件。 |
| POST | `/matters/{matter_id}/files` | 为 matter 上传/关联文件。 |
| POST | `/matters/{matter_id}/result` | 提交 matter 结果。 |
| POST | `/matters/{matter_id}/mentions` | 添加 mention。 |
| POST | `/matters/{matter_id}/annotations` | 添加注释/标注。 |

### 4.2 Matter 事件流

**源文件**：`server/api/matters_events.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/matters/events` | 获取 matter 事件流。 |

### 4.3 讨论 / 线程

**源文件**：`server/api/discussions.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/categories` | 获取分类列表。 |
| GET | `/threads` | 列出讨论线程。 |
| GET | `/threads/{category}/{slug}` | 获取某个线程详情。 |
| POST | `/threads` | 新建线程。 |
| POST | `/threads/{category}/{slug}/posts` | 发表帖子。 |
| POST | `/threads/{category}/{slug}/mentions` | 添加线程 mention。 |
| POST | `/threads/{category}/{slug}/status` | 修改线程状态。 |
| POST | `/threads/{category}/{slug}/favorite` | 收藏/取消收藏线程。 |

### 4.4 收件箱

**源文件**：`server/api/inbox.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/inbox` | 获取收件箱数据。 |
| POST | `/threads/{category}/{slug}/read` | 标记线程已读。 |

### 4.5 草稿

**源文件**：`server/api/drafts.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/` | 列出草稿。 |
| POST | `/` | 新建草稿。 |
| GET | `/{draft_id}` | 获取草稿详情。 |
| PATCH | `/{draft_id}` | 更新草稿。 |
| DELETE | `/{draft_id}` | 删除草稿。 |
| POST | `/{draft_id}/publish` | 发布草稿。 |

> 注：实际挂载路径以 `app.include_router(...)` 的前缀为准；这里保留路由模块内定义的相对路径。

### 4.6 可见性选项

**源文件**：`server/api/visibility_options.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/visibility-options` | 获取可见性选项。 |

---

## 5. AI 与智能助手

### 5.1 AI 配置与对话

**源文件**：`server/api/ai.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/api/ai/settings` | 获取 AI 设置。 |
| PUT | `/api/ai/settings` | 更新 AI 设置。 |
| GET | `/api/ai/matters/{matter_id}/conversation` | 获取 matter 的 AI 对话。 |
| PUT | `/api/ai/matters/{matter_id}/conversation` | 更新 matter 的 AI 对话。 |
| DELETE | `/api/ai/matters/{matter_id}/conversation` | 删除 matter 的 AI 对话。 |
| POST | `/api/ai/matters/{matter_id}/chat` | 与 matter AI 助手聊天。 |

### 5.2 日常日报 v2

**源文件**：`server/api/daily_report_v2.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/jobs` | 列出日报任务。 |
| POST | `/jobs` | 创建日报任务。 |
| GET | `/jobs/{job_id}` | 获取任务详情。 |
| PUT | `/jobs/{job_id}` | 更新任务。 |
| PUT | `/jobs/{job_id}/status` | 更新任务状态。 |
| DELETE | `/jobs/{job_id}` | 删除任务。 |
| POST | `/jobs/{job_id}/run-now` | 立即执行任务。 |
| POST | `/manual-trigger` | 手动触发日报。 |
| GET | `/jobs/{job_id}/runs` | 列出任务执行记录。 |
| GET | `/runs/{run_id}` | 获取执行记录详情。 |
| POST | `/runs/{run_id}/cancel` | 取消执行。 |
| GET | `/admin-notify` | 获取管理员通知配置。 |
| PUT | `/admin-notify` | 更新管理员通知配置。 |
| GET | `/feishu-chats` | 获取飞书群聊列表。 |

---

## 6. 管理后台

### 6.1 管理员申请处理

**源文件**：`server/api/admin_applications.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `` | 管理员查看申请列表。 |
| GET | `/{application_id}/match-candidates` | 获取匹配候选人。 |
| POST | `/{application_id}/approve` | 审批通过申请。 |
| POST | `/{application_id}/reject` | 拒绝申请。 |
| POST | `/{application_id}/unblock` | 解除阻塞。 |

### 6.2 管理员邀请管理

**源文件**：`server/api/admin_invites.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `` | 列出邀请记录。 |
| POST | `` | 创建邀请。 |
| DELETE | `/{invite_id}` | 删除邀请。 |

### 6.3 管理员用户管理

**源文件**：`server/api/admin_users.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/roles` | 获取角色列表。 |
| POST | `/roles` | 创建角色。 |
| PATCH | `/roles/{role_name}` | 更新角色。 |
| PUT | `/roles/{role_name}/members` | 更新角色成员。 |
| GET | `/users` | 管理员查看用户列表。 |
| POST | `/users/{user_id}/suspend` | 暂停用户。 |
| POST | `/users/{user_id}/resume` | 恢复用户。 |
| POST | `/users/{user_id}/mark-deleted` | 标记删除。 |
| POST | `/users/{user_id}/restore` | 恢复用户。 |
| POST | `/users/{user_id}/role` | 调整用户角色。 |
| POST | `/users/{user_id}/reset-password` | 重置密码。 |

### 6.4 管理员评分系统

**源文件**：`server/api/admin_scoring.py`

| 方法 | 路径 | 描述 |
|---|---|---|
| GET | `/config` | 获取评分配置。 |
| PUT | `/config` | 更新评分配置。 |
| GET | `/runs` | 列出评分运行记录。 |
| GET | `/matters/unscored` | 查看未评分 matters。 |
| GET | `/matters` | 查看 matter 评分列表。 |
| GET | `/runs/{run_id}` | 查看指定运行详情。 |
| POST | `/matters/{matter_id}/rerun` | 重新评分某个 matter。 |
| POST | `/scores/{run_id}/override` | 覆盖评分结果。 |
| GET | `/commenter-weights` | 获取评论者权重。 |
| POST | `/commenter-weights` | 创建评论者权重。 |
| PUT | `/commenter-weights/{user_id}` | 更新某个用户权重。 |
| DELETE | `/commenter-weights/{user_id}` | 删除某个用户权重。 |
| GET | `/users-search` | 搜索用户（评分后台使用）。 |

---

## 7. 其他

### 7.1 主页 / Home

**源文件**：`server/api/app_home.py`

- `GET /home`

### 7.2 MCP 子应用

**源文件**：`server/mcp/server.py`

- 挂载路径：`/mcp`
- 用于外部 AI 客户端访问的 MCP HTTP 接口
- 具体子路由定义在 MCP 子应用内部

---

## 8. 路由文件索引

| 文件 | 说明 |
|---|---|
| `server/auth/routes.py` | 飞书登录、回调、当前用户、退出 |
| `server/api/init.py` | 初始化管理员 |
| `server/api/auth_email_password.py` | 邮箱密码登录 |
| `server/api/auth_invite.py` | 邀请流程 |
| `server/api/tokens.py` | API Token 管理 |
| `server/api/users.py` | 用户搜索 |
| `server/api/contacts.py` | 联系人 |
| `server/api/preferences.py` | 个人偏好 |
| `server/api/markdown_styles.py` | Markdown 样式设置 |
| `server/api/workspace.py` | 工作区状态与配置 |
| `server/api/app_home.py` | 首页数据 |
| `server/api/matters.py` | Matters 主接口 |
| `server/api/matters_events.py` | Matter 事件流 |
| `server/api/discussions.py` | 讨论/线程 |
| `server/api/inbox.py` | 收件箱 |
| `server/api/drafts.py` | 草稿 |
| `server/api/visibility_options.py` | 可见性选项 |
| `server/api/ai.py` | AI 配置与对话 |
| `server/api/daily_report_v2.py` | 日报任务与运行记录 |
| `server/api/admin_applications.py` | 管理员申请审批 |
| `server/api/admin_invites.py` | 管理员邀请管理 |
| `server/api/admin_users.py` | 管理员用户与角色管理 |
| `server/api/admin_scoring.py` | 管理员评分系统 |

---

## 9. 备注

1. 本文档以路由模块内的 `@router.*` 为准。  
2. 对于通过 `APIRouter(prefix=...)` 设置了前缀的模块，本文档使用最终对外路径。  
3. 若后续路由有新增，建议同步更新此文档。  
4. 当前文档未展开每个接口的请求/响应 schema，如需我可以继续补一版“接口入参/出参表”。
