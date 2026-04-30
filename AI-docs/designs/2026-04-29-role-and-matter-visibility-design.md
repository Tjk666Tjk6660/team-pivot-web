# Pivot 角色字段与 Matter 可见范围设计

| 项 | 值 |
|---|---|
| 文件 | `AI-docs/designs/2026-04-29-role-and-matter-visibility-design.md` |
| 创建日期 | 2026-04-29 |
| 关联需求 | `需求：Pivot 数据隐私功能需求与设计` |
| 依赖 | `2026-04-28-user-management-design.md` / `2026-04-28-user-management-plan.md` |

---

## 0. 需求概览

本期基于已有用户管理体系扩展，角色只落在一个字段：

```text
pivot_user.role
```

但这个字段从固定的 `admin/member` 改为多角色集合。建议 DB 仍用 `TEXT`，内容保存为 JSON 字符串数组：

```json
["member", "技术部门", "客户A项目组"]
```

一个用户可以同时有多个角色。管理员可以在用户管理后台给用户增加、删除普通业务角色，例如 `行政部门`、`技术部门`、`客户A项目组`。这些角色值会进入后续 Matter 可见范围选择器。

本期要补齐三件事：

- 用户管理后台允许修改用户的 `pivot_user.role` 多角色集合。
- 创建 Matter 时可以选择可见范围：全部用户 / 指定角色 / 指定用户。
- Matter 已发布后，`creator ∪ owner` 可以修改该 Matter 的可见范围。

---

## 1. 关键决策

| 项 | 决策 |
|---|---|
| 角色来源 | 只使用 `pivot_user.role` 字段 |
| 多角色表达 | `pivot_user.role` 保存 JSON 字符串数组 |
| 新增角色方式 | 管理员给用户添加新角色名；后续该角色名进入候选 |
| `admin` 角色 | 系统保留角色，用于管理后台权限；不可删除；不出现在可见范围选择器；不提供业务全局可读 |
| Category 可见范围 | 公开 / 指定角色 |
| Matter 可见范围 | 公开 / 指定角色 + 指定用户 |
| Matter 越界规则 | Matter 可见范围只能等于或小于所属 Category 可见范围 |
| 修改已发布 Matter 可见范围 | `timeline[0].creator ∪ timeline[0].owner` 可改 |
| 不可见 Matter 后端返回 | 统一返回 `404 {"code":"matter_not_found"}`，与真实不存在保持同形 |
| 可见范围持久化 | Git/YAML 是事实源；SQLite 只做列表和过滤缓存 |
| 审计方式 | 依赖 Git log，不新增独立 audit 表 |
| Web AI | 直接读文件前必须按当前用户做权限校验 |
| MCP | 走 REST 的 MCP 继承 REST 权限；直接文件工具也必须补权限 |
| SSE | 全局事件环不筛选；live/replay 发给用户前按 `can_read_matter` 过滤 |
| 通知 | 完全公开保留现有群通知；非公开一律不发群，只私信 owner 和可读的 @ 用户 |

---

## 2. 角色模型

### 2.1 `pivot_user.role`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| role | TEXT | 是 | JSON 字符串数组，默认 `["member"]` |

实现要求：

- 移除 DB 层 `CHECK(role IN ('admin','member'))`。
- 后端把 `role` 解析为字符串数组。
- 数组不能为空。
- 每个角色名非空、长度受限、不能包含控制字符。
- `admin` 和 `member` 是内置保留角色。
- 至少保留一个 active admin，避免后台无人可管。
- 角色候选从所有 active 用户的 `role` 数组展开后去重生成。
- 可见范围选择器排除 `admin` 角色。

### 2.2 `admin` 的边界

`admin` 是系统管理角色，不是业务可见范围角色。

本期规则：

- `admin` 不可删除。
- `admin` 用于访问用户管理等后台功能。
- `admin` 不出现在发帖和修改可见范围的角色列表里。
- `role` 数组包含 `admin` 的用户不出现在可见范围选择器的用户单选列表和角色下级预览里。
- `admin` 不自动可读所有 Matter。
- 如果某个 admin 用户需要读某个非公开 Matter，需要通过普通业务角色获得权限；本期不提供在可见范围选择器里单独勾选 admin 用户的入口。

这样做是为了避免「后台管理员」和「业务内容可见人」混在一起。后续如果需要超管临时查看业务内容，应另行设计 break-glass 和审计流程。

---

## 3. 可见范围事实源

### 3.1 YAML 为事实源

可见范围必须写入 Git 管理的 YAML，而不是只写 SQLite。

Matter 可见范围写入：

```text
index/<matter_id>.index.yaml
```

字段位于 `matter.visibility`，与 `current_status` 同级，例如：

```yaml
matter:
  id: demo
  current_status: executing
  visibility:
    mode: restricted
    roles:
      - 技术部门
    user_ids:
      - user_zhangsan
```

Category 可见范围写入：

```text
categories/<category_name>.yaml
```

例如：

```yaml
category:
  name: 技术需求
  visibility:
    mode: restricted
    authorized_roles:
      - 技术部门
      - 客户A项目组
```

SQLite 可以维护派生缓存，例如 `category_visibility_cache`、`matter_visibility_cache`、`matter_visibility_role_cache`、`matter_visibility_user_cache`，用于列表过滤和查询加速。缓存不是事实源。

服务启动时流程：

1. `recover()` 恢复 Git/YAML 状态。
2. `rebuild_acl_cache()` 从 YAML 重建 SQLite 权限缓存。
3. 后续写入 Matter / Category 可见范围时，先写 YAML 并提交，再刷新缓存。

### 3.2 VisibilityScope

Matter 使用统一结构：

```json
{
  "mode": "restricted",
  "roles": ["技术部门"],
  "user_ids": ["user_zhangsan"]
}
```

Category 使用：

```json
{
  "mode": "restricted",
  "authorized_roles": ["技术部门"]
}
```

规则：

- `mode=public` 时，`roles/user_ids/authorized_roles` 应为空。
- `mode=restricted` 时，至少要有一个授权角色或授权用户。
- Matter 的 `roles` 必须是 Category `authorized_roles` 的子集。
- Matter 的 `user_ids` 对应用户必须至少拥有 Category 内某个授权角色，不能绕过 Category 扩大范围。

---

## 4. 权限服务

新增 `server/permissions.py`，统一处理 Category / Matter 的读写判断。

核心方法：

```python
class PermissionService:
    def can_read_category(self, user_id: str, category_id: str) -> bool: ...
    def can_read_matter(self, user_id: str, matter_id: str) -> bool: ...
    def can_write_matter(self, user_id: str, matter_id: str) -> bool: ...
    def can_update_matter_visibility(self, user_id: str, matter_id: str) -> bool: ...
    def filter_visible_matters(self, user_id: str, matters: list[MatterSummary]) -> list[MatterSummary]: ...
    def list_mentionable_users(self, user_id: str, matter_id: str) -> list[PivotUser]: ...
    def validate_matter_visibility_scope(self, matter_id: str, scope: VisibilityScope) -> None: ...
```

读权限计算：

```text
Category public:
  Matter public -> 全部 active 用户可读
  Matter restricted -> 用户任一角色命中 Matter.roles，或用户 ID 命中 Matter.user_ids，可读

Category restricted:
  用户必须先命中 Category.authorized_roles
  Matter public -> Category 内可读用户可读
  Matter restricted -> 再命中 Matter.roles 或 Matter.user_ids，可读
```

`admin` 不参与上述业务读权限的快捷放行。

`can_update_matter_visibility` 规则：

- 当前用户必须是 Matter 首个 timeline 文件中的 `creator` 或 `owner`。
- 当前用户必须已经能读该 Matter。
- 新范围不能超过所属 Category 范围。
- 修改后 creator 和 owner 必须仍可读，否则拒绝。

---

## 5. 接口设计

### 5.1 用户角色接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/admin/roles` | 返回当前可选角色，来自所有 active 用户 `role` 数组展开去重 |
| `POST` | `/api/admin/users/{user_id}/role` | 修改用户 `pivot_user.role` 多角色集合 |

`POST /api/admin/users/{user_id}/role` 请求：

```json
{
  "roles": ["member", "技术部门"],
  "confirm_create_role": false
}
```

角色拼写防御：

- 如果请求里包含当前候选中不存在的新角色，且 `confirm_create_role` 不是 `true`，返回 `422`。
- 返回结构包含 `code=unknown_role` 和 `suggestions[]`。
- 前端要区分「选择已有角色」和「创建新角色」，避免输错字就生成一个新角色。

示例：

```json
{
  "code": "unknown_role",
  "unknown_roles": ["技朮部门"],
  "suggestions": ["技术部门"]
}
```

### 5.2 可见范围选择器数据

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/visibility-options?category=...` | 返回双栏选择器所需的全部、角色、用户候选 |

返回示例：

```json
{
  "all": { "label": "全部用户", "value": "public" },
  "roles": [
    {
      "role": "技术部门",
      "users": [{ "id": "u1", "display_name": "张三" }]
    }
  ],
  "users": [{ "id": "u1", "display_name": "张三" }]
}
```

返回规则：

- `roles` 不返回 `admin`。
- `users` 不返回 `role` 数组包含 `admin` 的用户。
- 角色下级预览同样不展示 `role` 数组包含 `admin` 的用户。
- 如果当前 Category 是 restricted，返回的 `roles` 和 `users` 必须裁剪到 Category 可见范围内。
- 前端选择器里的用户和角色不能大于 Category。
- 左侧列表按「角色在前、用户在后」展示；搜索同时命中角色名和用户 display name。
- 右侧返回当前已选角色和用户，便于编辑已发布 Matter 时回显。

### 5.3 Matter 创建

`POST /api/matters` 增加：

```json
{
  "visibility": {
    "mode": "restricted",
    "roles": ["技术部门"],
    "user_ids": []
  }
}
```

如果创建 Matter 时 Category 不存在，请求必须同时带上 `new_category_visibility`：

```json
{
  "category": "技术需求",
  "new_category_visibility": {
    "mode": "restricted",
    "authorized_roles": ["技术部门"]
  },
  "visibility": {
    "mode": "restricted",
    "roles": ["技术部门"],
    "user_ids": []
  }
}
```

后端要求：

- 新 Category 和新 Matter 必须原子创建。
- Category 可见范围和 Matter 可见范围必须同时写 YAML。
- Matter 可见范围必须是 Category 可见范围的子集。
- 如果缺少 `new_category_visibility`，返回 `422 {"code":"missing_category_visibility"}`，前端展示可理解文案，不直接显示 `400`。
- 如果 Matter 可见范围超过 Category，返回 `422 {"code":"visibility_scope_exceeds_category"}`。

### 5.4 修改已发布 Matter 可见范围

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/matters/{matter_id}/visibility` | 读取当前范围 |
| `PUT` | `/api/matters/{matter_id}/visibility` | creator 或 owner 修改已发布 Matter 的可见范围 |

`PUT` 成功后：

- 更新 `index/<matter_id>.index.yaml` 的 `matter.visibility`。
- 重新构建或增量刷新 SQLite ACL 缓存。
- 发出 `matter.visibility_changed` 事件。
- 刷新 Matter 详情返回里的 `visibility`。
- 非公开 Matter 不触发群通知。

---

## 6. 前端设计

### 6.1 用户角色编辑

在用户管理页面扩展角色编辑：

- 角色选择读取 `/api/admin/roles`。
- 支持多选，一个用户可同时选中多个角色。
- 支持创建新角色，但新角色必须有明确确认动作。
- 如果后端返回 `unknown_role`，前端展示「该角色不存在，是否创建新角色」一类确认，不直接显示 `422`。
- 保存后更新该用户 `pivot_user.role` 多角色集合。

### 6.2 VisibilityScopePicker

新增通用组件 `VisibilityScopePicker`，用于新建 Matter 和编辑已发布 Matter。

形态参考飞书「选择联系人」双栏弹窗：

- 顶部提供 `全部用户` / `指定范围` 两种模式。
- 选择 `指定范围` 后打开双栏弹窗。
- 左侧顶部是搜索框，占位文案：`搜索用户、角色`。
- 左侧列表先显示角色，再显示用户。
- 角色行显示角色图标、角色名、`下级 >` 入口。
- 点击角色 checkbox 表示授权当前所有 `pivot_user.role` 包含该值的用户。
- 点击 `下级 >` 进入该角色下用户预览，可返回上一级。
- 用户行显示头像和姓名，勾选后表示额外授权该用户。
- 右侧固定展示已选角色和用户，顶部显示 `已选：N 个`。
- 右侧每项可移除。
- 弹窗底部是 `取消` / `确认`。
- 不展示 `admin` 角色。
- 不展示 `role` 数组包含 `admin` 的用户。
- 如果 Category 是 restricted，左侧只展示 Category 范围内可选的角色和用户。

页面错误处理：

- 列表页中不可见 Matter 不出现，不显示 `403`。
- 详情页直接访问不可见 Matter 时，后端返回同形 `404 matter_not_found`；前端展示独立的未找到/无权限页面或空态，不直接把 `404` / `403` 文本展示给用户。
- 保存可见范围超过 Category 时，后端返回 `visibility_scope_exceeds_category`，前端展示业务文案，例如 `可见范围不能超过所属分类`，不直接显示 `400`。
- 用户没有编辑权限时，隐藏修改入口；伪造请求返回 `403` 时，前端转成无权限提示或无权限页面。

### 6.3 Matter 详情修改入口

Matter 详情页在当前用户满足 `creator ∪ owner` 且可读时显示「可见范围」入口：

- 展示当前范围摘要：公开 / 指定范围。
- 点击打开 dialog。
- 保存前提示影响：被移出范围的人将无法再访问该 Matter。
- 保存后刷新详情、列表缓存和 timeline。

---

## 7. 数据出口

| 出口 | 规则 |
|---|---|
| Matter 列表 | `filter_visible_matters` 过滤 |
| Matter 详情 | 不可见统一返回 `404 {"code":"matter_not_found"}` |
| 追加文件 / 评论 / result | 先 `can_read_matter`，再校验写权限；不可见同形 404 |
| 收藏 / 已读 / file_read | 不可见同形 404 |
| @ 选择器 | `list_mentionable_users`，只返回当前 Matter 可读用户 |
| 搜索 | 只搜索和返回可读 Matter |
| Web AI | `list_matters`、`search_indexes`、`read_matter_index`、`read_post`、`read_posts` 每个 handler 都要校验当前用户 |
| MCP | 走 REST 的自然继承；直接读文件的工具必须注入 permission_service/current_user |
| SSE live | event 入全局 ring；发到用户 queue 前按 `can_read_matter` 过滤 |
| SSE replay | 从 ring 切片后逐条按 `can_read_matter` 过滤再 yield |
| `matter.visibility_changed` | 推给变更前可见用户 ∪ 变更后可见用户；前端收到后失效列表/详情缓存 |
| IM 通知 | 非公开 Matter 不发群；只私信 owner 和可读的 @ 用户 |

不可见统一返回 404 是为了避免通过错误码泄露 Matter 是否存在。

---

## 8. 迁移方案

已有 Matter / Category 默认公开。

新增脚本：

```text
scripts/migrate_visibility.py
```

要求：

- 支持 `--dry-run`。
- 单事务迁移。
- 幂等，可重复执行。
- 迁移前有备份和回滚说明。
- 为所有现有 Category 写入 public visibility YAML。
- 为所有现有 Matter 写入 public visibility YAML。
- 迁移后执行 `rebuild_acl_cache()`。

---

## 9. 验收标准

主线验收：

> 管理员把 B 的 `pivot_user.role` 改为 `["member", "技术部门"]`；A 创建只给「技术部门」可见的 Matter；B 能看到，C 在列表、搜索、SSE、IM、AI、MCP 中都看不到；A 后续把 C 作为单独用户加入范围后，C 立即可见。

具体验收：

| 场景 | 预期 |
|---|---|
| 管理员给用户添加新角色 | 新角色确认后进入角色候选 |
| 管理员误输入相似角色 | 后端返回 `422 unknown_role suggestions[]`，前端引导确认创建 |
| active admin 查看未授权 restricted Matter | 不因 admin 身份放行；不可见时返回同形 404 |
| admin 被普通业务角色授权 | 可以按普通用户规则访问；选择器里不展示 admin 用户，只展示可授权的业务角色 |
| 发帖或修改可见范围 | 不展示 `admin` 角色 |
| 用户任一角色命中 Matter 授权 | 用户获得 Matter 可读权限 |
| 用户被移除某角色 | 后续不能再读只依赖该角色授权的 Matter |
| 新建公开 Matter | 所有 active 用户可见；群通知保持现有逻辑 |
| 新建指定角色 Matter | 只有命中角色或单独授权用户可见；不发群 |
| 新建不存在 Category | 必须带 `new_category_visibility`，Category 与 Matter 原子创建 |
| creator 修改已发布 Matter 范围 | 新范围实时生效，并写入 YAML |
| owner 修改已发布 Matter 范围 | 新范围实时生效，并写入 YAML |
| 非 creator/owner 修改范围 | 页面隐藏入口；伪造请求后端返回 403，前端转成业务提示 |
| Matter 范围超过 Category | 前端选择器不允许选出越界范围；伪造请求后端拒绝，前端展示业务文案 |
| @ 不可见用户 | 前端不出现；伪造请求后端阻断 |
| 不可见用户直接访问 URL | 后端返回同形 404；前端展示未找到/无权限页面或空态 |
| 不可见用户用 AI/MCP 读取 | 返回无权限或空结果，不泄露内容 |
| SSE replay | 不包含用户不可读 Matter 的历史事件 |
| 修改可见范围 | 变更前可见用户和变更后可见用户都会收到 `matter.visibility_changed` |

---

## 10. 本期不做

| 项 | 原因 |
|---|---|
| 组织架构同步 | 先手动维护 `pivot_user.role`，后续再接企业通讯录部门 |
| Category 专属群通知 | 群成员和 Category 权限一致性未设计，本期非公开一律不发群 |
