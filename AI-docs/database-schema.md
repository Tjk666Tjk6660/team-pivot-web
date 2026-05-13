# team-pivot-web 数据库表设计与索引设计

> 说明：本文档根据 `server/db.py` 中的 `SCHEMA` 与迁移逻辑整理，概述整个项目的 SQLite 表结构、主键、唯一约束和索引设计。

## 1. 总体说明

- 数据库类型：SQLite
- 数据库文件：`data.db`
- 初始化与迁移入口：`server/db.py`
- 迁移逻辑负责：
  - 创建缺失表
  - 补充缺失字段
  - 重建/补齐索引
  - 回填历史数据
  - 校验旧版 `user_open_id` 兼容问题

---

## 2. 表设计总览

| 表名 | 作用 | 主要特点 |
|---|---|---|
| `users` | 旧版用户表 / 基础用户信息 | 主键为 `open_id` |
| `pivot_user` | 当前核心用户表 | 保存内部用户、角色、状态、登录信息 |
| `pivot_role` | 角色定义表 | 系统角色与业务角色统一管理 |
| `external_binding` | 外部账号绑定表 | 连接飞书/邀请/其他外部账号与内部用户 |
| `join_application` | 加入申请表 | 记录待审批/通过/拒绝的申请 |
| `invite` | 邀请表 | 邀请 token、使用状态、创建者 |
| `sessions` | 登录会话表 | Cookie session 管理 |
| `api_tokens` | 个人访问令牌表 | PAT / API token 管理 |
| `settings` | 系统设置表 | Key-Value 配置 |
| `contacts` | 联系人缓存表 | 飞书联系人同步结果 |
| `user_preferences` | 用户偏好表 | 个人设置 |
| `drafts` | 草稿表 | 草稿内容与分类 |
| `read_state` | 线程已读状态表 | 每用户每线程的已读游标 |
| `favorites` | 收藏表 | 每用户每线程收藏状态 |
| `ai_conversations` | AI 会话表 | 每用户每线程的 AI 消息历史 |
| `file_reads` | 文件阅读记录表 | 文件级已读信息 |
| `relevance_events` | 相关性事件表 | matter 相关提醒/阅读流 |
| `category_visibility_cache` | 分类可见性缓存 | 分类级可见性计算结果 |
| `category_visibility_role_cache` | 分类-角色可见性缓存 | 分类对应角色集合 |
| `matter_visibility_cache` | matter 可见性缓存 | matter 级可见性计算结果 |
| `matter_visibility_role_cache` | matter-角色可见性缓存 | matter 对应角色集合 |
| `matter_visibility_user_cache` | matter-用户可见性缓存 | matter 对应用户集合 |
| `matter_scoring_runs` | matter 评分运行表 | AI 评分运行审计与状态 |
| `matter_scores` | matter 评分结果表 | 每次运行对每个 subject 的评分 |
| `matter_score_evidence` | matter 评分证据表 | 评分解释、证据片段 |
| `scoring_commenter_weights` | 评分评论者权重表 | 管理员可调权重 |
| `git_push_outbox` | Git 推送 outbox | 写入与 push 解耦 |
| `daily_report_jobs` | 日报任务表 | 日报调度任务定义 |
| `daily_report_runs` | 日报执行记录表 | 日报运行历史 |

---

## 3. 各表详细设计

### 3.1 `users`

**作用**：旧版用户基础信息表，保留历史兼容。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `open_id` | TEXT | PRIMARY KEY | 用户唯一标识 |
| `union_id` | TEXT |  | 飞书 union id |
| `name` | TEXT | NOT NULL | 用户名称 |
| `avatar_url` | TEXT | NOT NULL DEFAULT '' | 头像地址 |
| `pinyin` | TEXT |  | 拼音 |
| `github_username` | TEXT |  | GitHub 用户名 |
| `created_at` | REAL | NOT NULL | 创建时间 |

---

### 3.2 `pivot_user`

**作用**：当前核心用户表。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | 内部用户 ID |
| `display_name` | TEXT | NOT NULL | 显示名 |
| `pinyin` | TEXT |  | 拼音 |
| `email` | TEXT | UNIQUE | 邮箱 |
| `avatar_url` | TEXT | NOT NULL DEFAULT '' | 头像 |
| `github_username` | TEXT |  | GitHub 用户名 |
| `role` | TEXT | NOT NULL DEFAULT '"[\"member\"]"' | 角色列表 JSON 文本 |
| `status` | TEXT | NOT NULL DEFAULT 'active' CHECK(...) | 状态：`active/suspended/deleted` |
| `status_note` | TEXT |  | 状态备注 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `updated_at` | REAL | NOT NULL | 更新时间 |
| `last_login_at` | REAL |  | 最近登录时间 |
| `status_changed_at` | REAL |  | 状态变更时间 |
| `status_changed_by` | TEXT |  | 状态变更操作者 |

**索引**

- `idx_pivot_user_role_status(role, status)`

---

### 3.3 `pivot_role`

**作用**：角色定义与管理。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `name` | TEXT | PRIMARY KEY | 角色名 |
| `label` | TEXT |  | 角色显示名 |
| `kind` | TEXT | NOT NULL DEFAULT 'business' CHECK(...) | `system` / `business` |
| `description` | TEXT |  | 描述 |
| `is_active` | INTEGER | NOT NULL DEFAULT 1 | 是否启用 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**索引**

- `idx_pivot_role_active(is_active, kind, name)`

---

### 3.4 `external_binding`

**作用**：内部用户与外部账号绑定。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | 绑定记录 ID |
| `pivot_user_id` | TEXT | NOT NULL REFERENCES pivot_user(id) | 内部用户 |
| `provider` | TEXT | NOT NULL | 外部平台，如飞书 |
| `external_id` | TEXT | NOT NULL | 外部平台用户 ID |
| `external_union_id` | TEXT |  | 外部 union id |
| `raw_profile` | TEXT |  | 原始 profile JSON |
| `password_hash` | TEXT |  | 密码哈希 |
| `bound_at` | REAL | NOT NULL | 绑定时间 |

**约束**

- `UNIQUE(provider, external_id)`

**索引**

- `idx_external_binding_user(pivot_user_id)`

---

### 3.5 `join_application`

**作用**：新用户申请加入系统的审批流。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | 申请 ID |
| `provider` | TEXT | NOT NULL | 来源平台 |
| `external_id` | TEXT | NOT NULL | 外部账号 ID |
| `external_union_id` | TEXT |  | 外部 union id |
| `raw_profile` | TEXT | NOT NULL | 原始资料 JSON |
| `suggested_match_user_id` | TEXT |  | 建议匹配的用户 |
| `status` | TEXT | NOT NULL DEFAULT 'pending' CHECK(...) | `pending/approved/rejected` |
| `applied_at` | REAL | NOT NULL | 申请时间 |
| `reviewed_at` | REAL |  | 审核时间 |
| `reviewed_by` | TEXT |  | 审核人 |
| `reject_reason` | TEXT |  | 拒绝原因 |
| `via_invite_id` | TEXT |  | 关联邀请 |

**索引 / 约束**

- `idx_join_app_pending_unique(provider, external_id)`，仅在 `status='pending'` 时唯一

---

### 3.6 `invite`

**作用**：邀请链接管理。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | 邀请 ID |
| `token_hash` | TEXT | NOT NULL UNIQUE | 邀请 token 哈希 |
| `created_by` | TEXT | NOT NULL | 创建者 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `expires_at` | REAL | NOT NULL | 过期时间 |
| `used_at` | REAL |  | 使用时间 |
| `used_by_user_id` | TEXT |  | 使用者 |

---

### 3.7 `sessions`

**作用**：登录会话。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | session id |
| `pivot_user_id` | TEXT | NOT NULL | 用户 ID |
| `expires_at` | REAL | NOT NULL | 过期时间 |
| `created_at` | REAL | NOT NULL | 创建时间 |

**索引**

- `idx_sessions_expires(expires_at)`

---

### 3.8 `api_tokens`

**作用**：个人访问令牌。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `token_hash` | TEXT | PRIMARY KEY | token 哈希 |
| `pivot_user_id` | TEXT | NOT NULL | 所属用户 |
| `name` | TEXT | NOT NULL | token 名称 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `last_used_at` | REAL |  | 最近使用时间 |
| `expires_at` | REAL | NOT NULL | 过期时间 |

**索引**

- `idx_api_tokens_user(pivot_user_id)`

---

### 3.9 `settings`

**作用**：全局键值配置。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `key` | TEXT | PRIMARY KEY | 配置键 |
| `value` | TEXT | NOT NULL | 配置值 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

---

### 3.10 `contacts`

**作用**：联系人同步缓存。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `open_id` | TEXT | PRIMARY KEY | 飞书 open_id |
| `union_id` | TEXT |  | 飞书 union_id |
| `name` | TEXT | NOT NULL | 名称 |
| `en_name` | TEXT |  | 英文名 |
| `pinyin` | TEXT |  | 拼音 |
| `avatar_url` | TEXT | NOT NULL DEFAULT '' | 头像 |
| `synced_at` | REAL | NOT NULL | 同步时间 |

**索引**

- `idx_contacts_name(name)`
- `idx_contacts_pinyin`：在迁移中按需补建

---

### 3.11 `user_preferences`

**作用**：用户偏好设置。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 ID |
| `key` | TEXT | NOT NULL | 偏好键 |
| `value` | TEXT | NOT NULL | 偏好值 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**主键**

- `(pivot_user_id, key)`

---

### 3.12 `drafts`

**作用**：草稿内容。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | TEXT | PRIMARY KEY | 草稿 ID |
| `pivot_user_id` | TEXT | NOT NULL | 创建者 |
| `type` | TEXT | NOT NULL CHECK(...) | `proposal/reply` |
| `title` | TEXT |  | 标题 |
| `category` | TEXT |  | 分类 |
| `body_md` | TEXT | NOT NULL DEFAULT '' | Markdown 内容 |
| `thread_key` | TEXT |  | 关联线程 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**索引**

- `idx_drafts_user(pivot_user_id, updated_at DESC)`

---

### 3.13 `read_state`

**作用**：线程已读游标。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 |
| `thread_key` | TEXT | NOT NULL | 线程键 |
| `last_read_post_filename` | TEXT | NOT NULL | 最近已读帖子文件名 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**主键**

- `(pivot_user_id, thread_key)`

---

### 3.14 `favorites`

**作用**：收藏关系。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 |
| `thread_key` | TEXT | NOT NULL | 线程键 |
| `created_at` | REAL | NOT NULL | 收藏时间 |

**主键**

- `(pivot_user_id, thread_key)`

**索引**

- `idx_favorites_user_created(pivot_user_id, created_at DESC)`

---

### 3.15 `ai_conversations`

**作用**：AI 会话持久化。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 |
| `thread_key` | TEXT | NOT NULL | 线程键 |
| `messages_json` | TEXT | NOT NULL DEFAULT '[]' | 消息数组 JSON |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**主键**

- `(pivot_user_id, thread_key)`

---

### 3.16 `file_reads`

**作用**：文件级阅读记录。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 |
| `matter_id` | TEXT | NOT NULL | matter |
| `filename` | TEXT | NOT NULL | 文件名 |
| `first_read_at` | REAL | NOT NULL | 首次阅读时间 |

**主键**

- `(pivot_user_id, matter_id, filename)`

**索引**

- `idx_file_reads_matter(matter_id, filename)`

---

### 3.17 `relevance_events`

**作用**：相关性事件流，用于 unread 提醒等。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | NOT NULL | 用户 |
| `matter_id` | TEXT | NOT NULL | matter |
| `filename` | TEXT | NOT NULL | 文件名 |
| `kind` | TEXT | NOT NULL | 事件类型 |
| `reason` | TEXT | NOT NULL | 触发原因 |
| `event_at` | TEXT | NOT NULL | 事件时间 |
| `actor_pinyin` | TEXT | NOT NULL | 触发人拼音 |
| `created_at` | REAL | NOT NULL | 记录时间 |
| `read_at` | REAL |  | 已读时间 |

**主键**

- `(pivot_user_id, matter_id, filename, kind, event_at, actor_pinyin)`

**索引**

- `idx_re_user_unread(pivot_user_id, read_at, matter_id)`

---

### 3.18 可见性缓存表

#### `category_visibility_cache`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `category_id` | TEXT | PRIMARY KEY | 分类 ID |
| `mode` | TEXT | NOT NULL DEFAULT 'public' CHECK(...) | 可见性模式 |
| `updated_at` | REAL | NOT NULL DEFAULT 0 | 更新时间 |

#### `category_visibility_role_cache`

| 字段 | 类型 | 约束 |
|---|---|---|
| `category_id` | TEXT | NOT NULL |
| `role` | TEXT | NOT NULL |

**主键**

- `(category_id, role)`

#### `matter_visibility_cache`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `matter_id` | TEXT | PRIMARY KEY | matter ID |
| `category_id` | TEXT | NOT NULL | 分类 ID |
| `mode` | TEXT | NOT NULL DEFAULT 'public' CHECK(...) | 可见性模式 |
| `creator_id` | TEXT |  | 创建者 |
| `owner_id` | TEXT |  | 负责人 |
| `updated_at` | REAL | NOT NULL DEFAULT 0 | 更新时间 |

**索引**

- `idx_matter_visibility_cache_category(category_id)`

#### `matter_visibility_role_cache`

- 主键：`(matter_id, role)`

#### `matter_visibility_user_cache`

- 主键：`(matter_id, pivot_user_id)`

---

### 3.19 `matter_scoring_runs`

**作用**：matter 评分运行记录。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `run_id` | TEXT | PRIMARY KEY | 运行 ID |
| `matter_id` | TEXT | NOT NULL | matter ID |
| `matter_category` | TEXT | NOT NULL | matter 分类 |
| `subject_user_id` | TEXT | NOT NULL | 被评分用户 |
| `triggered_by` | TEXT | NOT NULL | 触发来源 |
| `triggered_actor_id` | TEXT |  | 触发人 |
| `status` | TEXT | NOT NULL | 状态 |
| `error` | TEXT |  | 错误信息 |
| `model` | TEXT |  | 模型名 |
| `prompt_tokens` | INTEGER |  | prompt token 数 |
| `completion_tokens` | INTEGER |  | completion token 数 |
| `started_at` | REAL | NOT NULL | 开始时间 |
| `finished_at` | REAL |  | 完成时间 |
| `timeline_hash` | TEXT | NOT NULL | 时间线 hash |
| `schema_version` | INTEGER | NOT NULL DEFAULT 1 | 评分 schema 版本 |
| `skipped_subjects` | TEXT |  | 被 AI 明确跳过的 subject 列表 |

**索引 / 约束**

- `idx_scoring_runs_matter(matter_id, started_at DESC)`
- `idx_scoring_runs_idempotency(matter_id, timeline_hash)`，仅 `status IN ('queued','running')` 时唯一

---

### 3.20 `matter_scores`

**作用**：评分结果表。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `run_id` | TEXT | NOT NULL | 运行 ID |
| `subject_user_id` | TEXT | NOT NULL | subject 用户 |
| `matter_id` | TEXT | NOT NULL | matter ID |
| `overall` | REAL | NOT NULL | 综合评分 |
| `confidence` | TEXT | NOT NULL | 置信度 |
| `rationale` | TEXT | NOT NULL | 理由 |
| `delivery` | REAL |  | delivery 维度 |
| `accountability` | REAL |  | accountability 维度 |
| `collaboration` | REAL |  | collaboration 维度 |
| `judgment` | REAL |  | judgment 维度 |
| `process` | REAL |  | process 维度 |
| `human_override_overall` | REAL |  | 人工覆盖总分 |
| `human_override_note` | TEXT |  | 人工覆盖备注 |
| `human_override_by` | TEXT |  | 人工覆盖人 |
| `human_override_at` | REAL |  | 人工覆盖时间 |

**主键**

- `(run_id, subject_user_id)`

**索引**

- `idx_matter_scores_matter(matter_id, subject_user_id)`

---

### 3.21 `matter_score_evidence`

**作用**：评分证据明细。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增 ID |
| `run_id` | TEXT | NOT NULL | 评分运行 |
| `matter_id` | TEXT | NOT NULL | matter |
| `subject_user_id` | TEXT | NOT NULL | subject |
| `dimension` | TEXT | NOT NULL | 评分维度 |
| `polarity` | TEXT | NOT NULL | 正负向 |
| `confidence` | TEXT | NOT NULL | 置信度 |
| `source_kind` | TEXT | NOT NULL | 来源类型 |
| `source_filename` | TEXT | NOT NULL | 来源文件名 |
| `source_file_type` | TEXT | NOT NULL | 文件类型 |
| `source_comment_created_at` | TEXT |  | 评论时间 |
| `source_comment_author_id` | TEXT |  | 评论作者 |
| `source_annotation_created_at` | TEXT |  | 标注时间 |
| `source_annotation_author_id` | TEXT |  | 标注作者 |
| `attribution_basis` | TEXT |  | 归因依据 |
| `weight_applied` | REAL | NOT NULL DEFAULT 1.0 | 实际权重 |
| `quote` | TEXT | NOT NULL | 证据引用 |
| `explanation` | TEXT | NOT NULL | 解释 |

**索引**

- `idx_evidence_run_subject(run_id, subject_user_id, dimension)`

---

### 3.22 `scoring_commenter_weights`

**作用**：评分系统中评论者权重。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `pivot_user_id` | TEXT | PRIMARY KEY | 用户 |
| `weight` | REAL | NOT NULL | 权重 |
| `label` | TEXT | NOT NULL | 显示标签 |
| `note` | TEXT |  | 备注 |
| `updated_at` | REAL | NOT NULL | 更新时间 |
| `updated_by` | TEXT | NOT NULL | 更新人 |

---

### 3.23 `git_push_outbox`

**作用**：本地写入与 git push 异步解耦。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增 ID |
| `tenant_id` | TEXT | NOT NULL DEFAULT 'default' | 租户 ID |
| `enqueued_at` | REAL | NOT NULL | 入队时间 |
| `status` | TEXT | NOT NULL DEFAULT 'pending' CHECK(...) | `pending/in_flight/succeeded/failed` |
| `attempts` | INTEGER | NOT NULL DEFAULT 0 | 尝试次数 |
| `last_attempt_at` | REAL |  | 最近尝试时间 |
| `last_error` | TEXT |  | 最近错误 |
| `succeeded_at` | REAL |  | 成功时间 |
| `reason` | TEXT |  | 入队原因 |

**索引**

- `idx_git_push_outbox_pending(tenant_id, status, enqueued_at)`，仅覆盖 `pending/in_flight`

---

### 3.24 `daily_report_jobs`

**作用**：日报任务配置。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 任务 ID |
| `name` | TEXT | NOT NULL | 任务名 |
| `view` | TEXT | NOT NULL | `company/personal` |
| `status` | TEXT | NOT NULL DEFAULT 'active' | `active/paused/archived` |
| `push_time` | TEXT | NOT NULL | 触发时间 `HH:MM` |
| `push_freq` | TEXT | NOT NULL DEFAULT 'weekdays' | 频率 |
| `window_hours` | INTEGER | NOT NULL DEFAULT 24 | 时间窗口 |
| `channel` | TEXT | NOT NULL DEFAULT 'feishu' | 推送渠道 |
| `receiver_type` | TEXT | NOT NULL | 接收类型 |
| `receiver_ids` | TEXT |  | JSON 数组 |
| `next_run_at` | REAL |  | 下一次执行时间 |
| `last_run_id` | INTEGER |  | 上次运行记录 ID |
| `last_status` | TEXT |  | 最近运行状态缓存 |
| `retry_count` | INTEGER | NOT NULL DEFAULT 0 | 重试次数 |
| `last_notified_at` | REAL |  | 上次通知时间 |
| `created_by` | TEXT |  | 创建者 |
| `created_at` | REAL | NOT NULL | 创建时间 |
| `updated_at` | REAL | NOT NULL | 更新时间 |

**索引**

- `idx_daily_report_jobs_active_due(status, next_run_at)`
- `idx_daily_report_jobs_status(status)`

---

### 3.25 `daily_report_runs`

**作用**：日报运行历史。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 运行 ID |
| `job_id` | INTEGER |  | 关联任务 |
| `trigger_type` | TEXT | NOT NULL CHECK(...) | `scheduled/manual/retry/makeup` |
| `view` | TEXT | NOT NULL | 冗余视图 |
| `started_at` | REAL | NOT NULL | 开始时间 |
| `finished_at` | REAL |  | 结束时间 |
| `status` | TEXT | NOT NULL DEFAULT 'running' CHECK(...) | `running/succeeded/failed/partial/skipped` |
| `rc` | INTEGER |  | 返回码 |
| `cards_sent` | INTEGER |  | 已发送卡片数 |
| `cards_total` | INTEGER |  | 总卡片数 |
| `ai_tokens_in` | INTEGER |  | 输入 token |
| `ai_tokens_out` | INTEGER |  | 输出 token |
| `error` | TEXT |  | 错误信息 |
| `debug_json` | TEXT |  | 调试信息 |

**索引**

- `idx_daily_report_runs_job_started(job_id, started_at DESC)`
- `idx_daily_report_runs_started(started_at)`

---

## 4. 索引设计汇总

### 用户与权限相关

- `idx_pivot_user_role_status(role, status)`
- `idx_pivot_role_active(is_active, kind, name)`
- `idx_external_binding_user(pivot_user_id)`
- `idx_api_tokens_user(pivot_user_id)`
- `idx_sessions_expires(expires_at)`

### 内容与阅读状态相关

- `idx_drafts_user(pivot_user_id, updated_at DESC)`
- `idx_favorites_user_created(pivot_user_id, created_at DESC)`
- `idx_file_reads_matter(matter_id, filename)`
- `idx_re_user_unread(pivot_user_id, read_at, matter_id)`
- `idx_contacts_name(name)`
- `idx_contacts_pinyin`（迁移补建）

### 可见性相关

- `idx_matter_visibility_cache_category(category_id)`

### 评分系统相关

- `idx_scoring_runs_matter(matter_id, started_at DESC)`
- `idx_scoring_runs_idempotency(matter_id, timeline_hash)`（部分唯一索引）
- `idx_matter_scores_matter(matter_id, subject_user_id)`
- `idx_evidence_run_subject(run_id, subject_user_id, dimension)`

### 写入与任务调度相关

- `idx_git_push_outbox_pending(tenant_id, status, enqueued_at)`（部分索引）
- `idx_daily_report_jobs_active_due(status, next_run_at)`
- `idx_daily_report_jobs_status(status)`
- `idx_daily_report_runs_job_started(job_id, started_at DESC)`
- `idx_daily_report_runs_started(started_at)`

---

## 5. 主键与唯一约束设计特点

### 复合主键常见场景

- `read_state(pivot_user_id, thread_key)`
- `favorites(pivot_user_id, thread_key)`
- `ai_conversations(pivot_user_id, thread_key)`
- `file_reads(pivot_user_id, matter_id, filename)`
- `relevance_events(...)`
- `matter_scores(run_id, subject_user_id)`

### 唯一约束常见场景

- `external_binding(provider, external_id)`
- `pivot_user.email`
- `api_tokens.token_hash`
- `invite.token_hash`
- `join_application` 的 pending 去重唯一索引
- `matter_scoring_runs` 的 in-flight 幂等约束

---

## 6. 迁移与兼容说明

`server/db.py` 里的 `_migrate()` 说明了项目采用“**启动时自动迁移 + 补齐索引 + 历史数据兼容**”的策略，重点包括：

1. 旧列兼容检查
   - 如果下游表还存在 `user_open_id`，启动会直接拒绝，并提示执行迁移脚本。

2. 字段补齐
   - 如 `contacts.pinyin`、`pivot_role.label` 等历史缺失字段会在迁移中补齐。

3. 索引补建
   - 部分索引放在迁移逻辑里创建，避免旧库首次启动时因字段不存在而失败。

4. 预置数据修复
   - 系统预置角色会在迁移结束时补齐。

---

## 7. 备注

- 这是根据 `server/db.py` 的 SQLite schema 整理的数据库设计文档。
- 某些业务逻辑表的具体用途，还需要结合 `server/api/*.py`、`server/*repo.py` 和迁移脚本一起看会更完整。
- 如果你愿意，我可以继续补一版：
  - **按业务模块分组的 ER 关系说明**
  - **每张表对应的读写接口/仓储类映射**
  - **表之间的外键/逻辑关联图**
