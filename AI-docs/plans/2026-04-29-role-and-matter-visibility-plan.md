# Pivot 角色字段与 Matter 可见范围实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 只使用 `pivot_user.role` 一个字段支持多角色维护、Matter 可见范围选择、以及已发布 Matter 的 creator/owner 可见范围修改。

**Architecture:** `pivot_user.role` 保存 JSON 字符串数组。Matter / Category 可见范围以 Git/YAML 为事实源，SQLite 只做 ACL 查询缓存。所有 REST、搜索、Web AI、MCP、SSE、通知出口统一走 `PermissionService`。`admin` 只是后台管理角色，不自动拥有业务内容全局可读。

**Tech Stack:** Python 3.12 + FastAPI + SQLite + React 18 + Vite + shadcn/ui + Tailwind。

**配套文档：**
- spec: `AI-docs/designs/2026-04-29-role-and-matter-visibility-design.md`
- 依赖设计: `AI-docs/designs/2026-04-28-user-management-design.md`
- 依赖计划: `AI-docs/plans/2026-04-28-user-management-plan.md`

---

## File Structure

### 新增后端

| 文件 | 职责 |
|---|---|
| `server/visibility_scopes.py` | `VisibilityScope` / `CategoryVisibilityScope` 数据结构、序列化、校验 |
| `server/visibility_store.py` | 读写 `index/*.index.yaml` 与 `categories/*.yaml` 的可见范围 |
| `server/acl_cache.py` | 从 YAML 重建 SQLite ACL 缓存 |
| `server/permissions.py` | `PermissionService`，统一处理 Category / Matter 读写权限 |
| `server/api/visibility_options.py` | 双栏选择器数据接口 |
| `server/api/matter_visibility.py` | 读取和修改已发布 Matter 可见范围 |
| `scripts/migrate_visibility.py` | 现有 Category / Matter 默认 public 的迁移脚本 |
| `server/tests/test_visibility_store.py` | YAML 写入与缓存重建测试 |
| `server/tests/test_permissions.py` | 权限服务测试 |
| `server/tests/test_matter_visibility_api.py` | Matter 可见范围接口测试 |
| `server/tests/test_visibility_migration.py` | 迁移脚本测试 |

### 修改后端

| 文件 | 改动 |
|---|---|
| `server/db.py` | 移除 `pivot_user.role` 的 `admin/member` CHECK；默认值改为 JSON 数组；新增 ACL 缓存表 |
| `server/pivot_users.py` | `update_role` 接收角色数组；新增 distinct role 查询；兼容旧单字符串数据 |
| `server/api/admin_users.py` | 用户角色接口支持多选、新角色确认、拼写防御 |
| `server/api/matters.py` | 创建、详情、追加文件、评论、result、favorite、read、file_read 接入权限 |
| `server/api/contacts.py` 或 mentions 相关 API | @ 候选过滤为当前 Matter 可读用户 |
| `server/api/ai.py` | Web AI 工具读 Matter 前按 handler 校验权限 |
| `server/mcp/*` 或 MCP 工具模块 | list/read/search 继承或补齐 Matter 权限 |
| `server/sse.py` 或事件流模块 | live/replay 按 Matter 权限过滤；支持 `matter.visibility_changed` |
| `server/notify.py` | 非公开 Matter 不发群，只私信 owner 和可读的 @ 用户 |
| `server/app.py` | 装配新 service/router |

### 新增前端

| 文件 | 职责 |
|---|---|
| `web/src/components/visibility/VisibilityScopePicker.tsx` | 类飞书联系人选择的双栏可见范围选择器 |
| `web/src/components/visibility/VisibilitySummary.tsx` | 可见范围摘要 |

### 修改前端

| 文件 | 改动 |
|---|---|
| `web/src/api.ts` | 新增 roles/options/matter visibility API 类型与请求 |
| `web/src/pages/admin/AdminUsers.tsx` | 用户角色编辑支持多选、创建确认、未知角色提示 |
| `web/src/pages/NewMatter.tsx` / `NewMatterGuidedFlow.tsx` | 新建 Matter 时选择可见范围；新 Category 时提交 `new_category_visibility` |
| `web/src/pages/MatterDetailPane.tsx` | creator/owner 修改已发布 Matter 可见范围 |
| 全局错误页或 Matter 详情空态 | 不直接展示裸 `400` / `403` / `404`，转成业务页面或业务文案 |

---

## Phase 0 · 对齐与准备

### Task 0: 确认依赖用户管理分支状态

- [ ] **Step 1: 确认当前分支和工作区**

Run:

```bash
git status --short
git branch --show-current
```

Expected: 能看清当前工作区改动；如果同事用户管理分支还没合并，先确认本计划基于哪一个合并点实施。

- [ ] **Step 2: 确认用户管理基础模型**

Run:

```bash
rg -n "class PivotUser|pivot_user|update_role|admin_users" server
```

Expected: 能看到 `pivot_user` schema、用户角色修改接口或当前等价入口。

---

## Phase 1 · 角色字段与 ACL 缓存

### Task 1: 调整 `pivot_user.role` 为多角色数组

**Files:**
- Modify: `server/db.py`
- Modify: `server/pivot_users.py`
- Modify/Create: `server/tests/test_pivot_users.py`

- [ ] **Step 1: 写失败测试**

覆盖：

- `pivot_user.role` 可保存 `["member","技术部门"]`。
- 旧值 `"member"` 可以被兼容解析为 `["member"]`。
- `update_role(user_id, roles=[...])` 可以保存多角色。
- `list_roles()` 会展开所有 active 用户 role 数组并统计。
- 至少保留一个 active admin。

- [ ] **Step 2: 修改 schema**

把类似：

```sql
role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member'))
```

改为：

```sql
role TEXT NOT NULL DEFAULT '["member"]'
```

- [ ] **Step 3: 实现 role 编解码**

在 `server/pivot_users.py` 中增加：

- `_decode_roles(value: str) -> list[str]`
- `_encode_roles(roles: list[str]) -> str`
- `_validate_roles(roles: list[str]) -> list[str]`
- `list_roles()`

- [ ] **Step 4: 跑测试**

Run:

```bash
uv run pytest server/tests/test_pivot_users.py -v
```

Expected: PASS。

### Task 2: 新增 ACL 缓存表

**Files:**
- Modify: `server/db.py`
- Create: `server/tests/test_visibility_schema.py`

- [ ] **Step 1: 写 schema 测试**

缓存表建议：

```text
category_visibility_cache
category_visibility_role_cache
matter_visibility_cache
matter_visibility_role_cache
matter_visibility_user_cache
```

注意：不新增 `matter_visibility_audit`，审计依赖 Git log。

- [ ] **Step 2: 增加 DDL**

缓存表用于查询加速，重建来源是 YAML。

- [ ] **Step 3: 跑测试**

Run:

```bash
uv run pytest server/tests/test_visibility_schema.py -v
```

Expected: PASS。

---

## Phase 2 · YAML 事实源

### Task 3: 实现 Visibility Store

**Files:**
- Create: `server/visibility_scopes.py`
- Create: `server/visibility_store.py`
- Create: `server/acl_cache.py`
- Create: `server/tests/test_visibility_store.py`

- [ ] **Step 1: 写失败测试**

覆盖：

- Matter visibility 写入 `index/<matter_id>.index.yaml` 的 `matter.visibility`。
- Category visibility 写入 `categories/<name>.yaml`。
- 写入后保留原 YAML 的其他字段，例如 `current_status`。
- `rebuild_acl_cache()` 能从 YAML 重建 SQLite 缓存。
- 服务启动流程 `recover()` 后可以重建缓存。

- [ ] **Step 2: 实现 Scope 数据结构**

Matter:

```python
VisibilityScope(mode: Literal["public", "restricted"], roles: list[str], user_ids: list[str])
```

Category:

```python
CategoryVisibilityScope(mode: Literal["public", "restricted"], authorized_roles: list[str])
```

- [ ] **Step 3: 实现 YAML 读写**

要求：

- 使用 YAML 解析库，不做手写字符串拼接。
- `mode=public` 时清空授权列表。
- `mode=restricted` 时至少有一个授权角色或用户。

- [ ] **Step 4: 实现缓存重建**

`rebuild_acl_cache()` 从所有 category/matter YAML 读取 visibility，清空并重建 ACL 缓存表。

- [ ] **Step 5: 跑测试**

Run:

```bash
uv run pytest server/tests/test_visibility_store.py -v
```

Expected: PASS。

---

## Phase 3 · 用户角色管理接口

### Task 4: Admin 用户接口支持多角色和新角色确认

**Files:**
- Modify: `server/api/admin_users.py`
- Modify/Create: admin users API tests

- [ ] **Step 1: 写 API 测试**

覆盖：

- admin 可以给用户保存多个角色。
- `GET /api/admin/roles` 返回展开后的角色候选和人数。
- 请求包含未知角色且 `confirm_create_role=false` 时返回 `422 code=unknown_role suggestions[]`。
- 请求包含未知角色且 `confirm_create_role=true` 时允许创建。
- 不能删掉最后一个 active admin。

- [ ] **Step 2: 修改请求模型**

```python
class RoleUpdateIn(BaseModel):
    roles: list[str]
    confirm_create_role: bool = False
```

- [ ] **Step 3: 实现拼写防御**

如果有未知角色：

```json
{
  "code": "unknown_role",
  "unknown_roles": ["技朮部门"],
  "suggestions": ["技术部门"]
}
```

- [ ] **Step 4: 跑测试**

Run:

```bash
uv run pytest server/tests -k "admin and role" -v
```

Expected: PASS。

---

## Phase 4 · PermissionService

### Task 5: 实现 Category / Matter 读写权限

**Files:**
- Create: `server/permissions.py`
- Create: `server/tests/test_permissions.py`

- [ ] **Step 1: 写权限测试**

覆盖：

- public Category + public Matter：active 用户可读。
- public Category + restricted Matter：角色命中可读。
- public Category + restricted Matter：`user_ids` 命中可读。
- restricted Category：用户必须先命中 Category 角色。
- Matter 范围不能大于 Category。
- admin 不因为 `admin` 角色自动可读 restricted Matter。
- admin 如果被普通业务角色授权，可以按普通用户规则可读。
- `can_update_matter_visibility` 允许 creator。
- `can_update_matter_visibility` 允许 owner。
- 非 creator/owner 即使可读也不能改可见范围。
- 修改后 creator 和 owner 不可读时拒绝。

- [ ] **Step 2: 实现 PermissionService**

核心方法：

```python
def can_read_category(user_id: str, category_id: str) -> bool: ...
def can_read_matter(user_id: str, matter_id: str) -> bool: ...
def can_write_matter(user_id: str, matter_id: str) -> bool: ...
def can_update_matter_visibility(user_id: str, matter_id: str) -> bool: ...
def validate_matter_visibility_scope(matter_id: str, scope: VisibilityScope) -> None: ...
```

- [ ] **Step 3: 跑测试**

Run:

```bash
uv run pytest server/tests/test_permissions.py -v
```

Expected: PASS。

---

## Phase 5 · Matter 创建与修改范围

### Task 6: Matter 创建支持 visibility 和 new_category_visibility

**Files:**
- Modify: `server/api/matters.py`
- Modify: `web/src/api.ts`
- Modify/Create: Matter API tests

- [ ] **Step 1: 写后端测试**

覆盖：

- 创建 Matter 时保存 restricted visibility 到 YAML。
- Category 不存在时，缺少 `new_category_visibility` 返回 `422 code=missing_category_visibility`。
- Category 不存在时，`new_category_visibility` 和 Matter visibility 原子创建。
- Matter visibility 超过 Category 时返回 `422 code=visibility_scope_exceeds_category`。
- 创建成功后 ACL 缓存可立即生效。

- [ ] **Step 2: 修改创建请求模型**

增加：

```python
visibility: VisibilityScope | None
new_category_visibility: CategoryVisibilityScope | None
```

- [ ] **Step 3: 实现原子写入**

创建新 Category 时：

1. 校验 `new_category_visibility`。
2. 校验 Matter visibility 是 Category 子集。
3. 写 Category YAML。
4. 写 Matter index YAML。
5. 刷新 ACL 缓存。

- [ ] **Step 4: 跑测试**

Run:

```bash
uv run pytest server/tests -k "create_matter and visibility" -v
```

Expected: PASS。

### Task 7: creator/owner 修改已发布 Matter 可见范围

**Files:**
- Create: `server/api/matter_visibility.py`
- Modify: `server/app.py`
- Create: `server/tests/test_matter_visibility_api.py`

- [ ] **Step 1: 写 API 测试**

覆盖：

- creator 可以修改。
- owner 可以修改。
- 非 creator/owner 不可修改，返回 403。
- 不可见用户请求修改时返回同形 404。
- 新范围超过 Category 时返回 `422 code=visibility_scope_exceeds_category`。
- 修改成功后写入 YAML。
- 修改成功后 ACL 缓存刷新。
- 修改成功后发出 `matter.visibility_changed`。

- [ ] **Step 2: 实现 router**

Routes:

- `GET /api/matters/{matter_id}/visibility`
- `PUT /api/matters/{matter_id}/visibility`

- [ ] **Step 3: 跑测试**

Run:

```bash
uv run pytest server/tests/test_matter_visibility_api.py -v
```

Expected: PASS。

---

## Phase 6 · 数据出口权限拦截

### Task 8: Matter REST 出口统一接入 PermissionService

**Files:**
- Modify: `server/api/matters.py`
- Modify/Create: Matter API tests

- [ ] **Step 1: 写不可见用户测试**

覆盖：

- 不可见用户不在 Matter 列表看到该 Matter。
- 不可见用户请求详情返回 `404 {"code":"matter_not_found"}`。
- 不可见用户追加文件/评论/result 返回同形 404。
- 不可见用户 favorite/read/file_read 返回同形 404。
- 可见但无写权限用户写入时返回 403。

- [ ] **Step 2: 实现过滤**

- `GET /api/matters` 调 `filter_visible_matters`。
- `GET /api/matters/{id}` 失败返回同形 404。
- 写入类接口先判断可读；不可读同形 404；可读但不可写返回 403。

- [ ] **Step 3: 跑测试**

Run:

```bash
uv run pytest server/tests -k "matter" -v
```

Expected: PASS。

### Task 9: 搜索、Web AI、MCP、SSE、通知接入权限

**Files:**
- Modify: search related API/module
- Modify: `server/api/ai.py`
- Modify: MCP tools module
- Modify: SSE module
- Modify: `server/notify.py`
- Test: related tests

- [ ] **Step 1: 写出口测试**

覆盖：

- 不可见用户搜索不到 restricted Matter。
- Web AI `list_matters` 不返回不可见 Matter。
- Web AI `search_indexes` 不返回不可见 Matter。
- Web AI `read_matter_index` 不可读时拒绝。
- Web AI `read_post` / `read_posts` 不可读时拒绝。
- MCP 经 REST 读取继承同样限制。
- 直接文件读取工具注入 `permission_service/current_user` 后限制生效。
- SSE live 不把不可见 Matter event 放入该用户 queue。
- SSE replay 不 yield 不可见 Matter event。
- restricted Matter 不发群通知。
- restricted Matter 只私信 owner 和可读的 @ 用户。

- [ ] **Step 2: 实现 Web AI handler 权限**

每个 handler 直接读 index/Markdown 前都必须拿当前用户校验 Matter 权限。

- [ ] **Step 3: 实现 SSE 过滤**

规则：

- emit 阶段不筛选，全局 ring 存全部事件。
- live 阶段 put 用户 queue 前按 `can_read_matter(user, event.matter_id)` 过滤。
- replay 阶段对 ring slice 逐条过滤后再 yield。
- `matter.visibility_changed` 接收者为变更前可见用户 ∪ 变更后可见用户。

- [ ] **Step 4: 实现通知降级**

非 public Matter：

- skip group notification。
- DM owner 和 @ 用户。
- DM 前确认 receiver 仍可读该 Matter。

- [ ] **Step 5: 跑测试**

Run:

```bash
uv run pytest server/tests -k "ai or mcp or notify or sse or search" -v
```

Expected: PASS。

---

## Phase 7 · 前端

### Task 10: VisibilityScopePicker

**Files:**
- Create: `web/src/components/visibility/VisibilityScopePicker.tsx`
- Create: `web/src/components/visibility/VisibilitySummary.tsx`
- Modify: `web/src/api.ts`

- [ ] **Step 1: 增加 API 类型**

```ts
export type VisibilityScope = {
  mode: "public" | "restricted";
  roles: string[];
  user_ids: string[];
};

export type CategoryVisibilityScope = {
  mode: "public" | "restricted";
  authorized_roles: string[];
};
```

- [ ] **Step 2: 增加 options API**

`fetchVisibilityOptions(category?: string)` 调 `/api/visibility-options?category=...`。

要求：

- 后端响应不含 `admin` 角色。
- 后端响应的用户单选列表和角色下级预览不含 `role` 数组包含 `admin` 的用户。
- 后端响应不含 Category 外的角色和用户。
- 前端不允许手动构造超过 Category 的选择。

- [ ] **Step 3: 实现双栏选择器**

UI 要点：

- 模式切换：全部用户 / 指定范围。
- 弹窗标题：`选择可见范围`。
- 搜索 placeholder：`搜索用户、角色`。
- 左侧角色在前、用户在后。
- 角色行有图标、角色名、`下级 >`。
- 右侧显示 `已选：N 个`。
- 底部按钮：取消 / 确认。
- 不出现裸 `400` / `403`。

- [ ] **Step 4: 前端检查**

Run:

```bash
npm run lint
```

或仓库现有 web 检查命令。

Expected: PASS。

### Task 11: Admin 用户页支持多角色

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/pages/admin/AdminUsers.tsx`

- [ ] **Step 1: 增加 API 调用**

- `listAdminRoles()`
- `changeUserRole(id: string, roles: string[], confirmCreateRole?: boolean)`

- [ ] **Step 2: 改为多选和创建确认**

要求：

- 读取 `/api/admin/roles`。
- 支持多选已有角色。
- 支持输入新角色。
- 新角色必须通过确认动作创建。
- `unknown_role` 错误展示为创建确认，不展示裸 `422`。

- [ ] **Step 3: 前端检查**

Run:

```bash
npm run lint
```

Expected: PASS。

### Task 12: 新建和详情页接入可见范围

**Files:**
- Modify: `web/src/pages/NewMatter.tsx`
- Modify: `web/src/pages/NewMatterGuidedFlow.tsx`
- Modify: `web/src/pages/MatterDetailPane.tsx`

- [ ] **Step 1: 新建 Matter 页接入**

本地状态：

```ts
const [visibility, setVisibility] = useState<VisibilityScope>({
  mode: "public",
  roles: [],
  user_ids: [],
});
```

如果 Category 不存在，同时要求选择或确认 `new_category_visibility`。

- [ ] **Step 2: Matter 详情页增加修改入口**

只在后端返回当前用户可改时展示入口。不要只靠前端判断 owner。

保存时：

- 调 `PUT /api/matters/{id}/visibility`。
- 成功后刷新详情和列表缓存。
- `visibility_scope_exceeds_category` 展示 `可见范围不能超过所属分类`。
- 403 展示无权限提示或无权限页面。
- 不可见返回 404 时展示未找到/无权限页，不展示裸码。

- [ ] **Step 3: 处理 `matter.visibility_changed`**

前端收到后：

- 失效 Matter 列表缓存。
- 如果当前打开的详情受影响，重新拉取详情。
- 如果重新拉取返回同形 404，展示未找到/无权限页。

- [ ] **Step 4: 前端检查**

Run:

```bash
npm run lint
```

Expected: PASS。

---

## Phase 8 · 迁移

### Task 13: 现有数据默认 public 迁移

**Files:**
- Create: `scripts/migrate_visibility.py`
- Create: `server/tests/test_visibility_migration.py`
- Update: ops/runbook if repo has one

- [ ] **Step 1: 写迁移测试**

覆盖：

- `--dry-run` 不写文件。
- 已有 Category 迁移为 public。
- 已有 Matter 迁移为 public。
- 重复执行不重复写、不破坏已有 restricted 配置。
- 迁移失败时不留下半成品。

- [ ] **Step 2: 实现脚本**

要求：

- 单事务或等价原子保护。
- 输出将要修改的 Category/Matter 数量。
- 写入前提示备份路径或生成备份。
- 迁移后调用 `rebuild_acl_cache()`。

- [ ] **Step 3: 跑测试**

Run:

```bash
uv run pytest server/tests/test_visibility_migration.py -v
```

Expected: PASS。

---

## Phase 9 · 总体验证

### Task 14: 全量验证

- [ ] **Step 1: 后端全量测试**

Run:

```bash
uv run pytest
```

Expected: PASS。

- [ ] **Step 2: 前端检查**

Run:

```bash
npm run lint
npm run build
```

或仓库实际可用的 web 检查命令。

Expected: PASS。

- [ ] **Step 3: 手工验收**

Scenario:

1. admin 把 B 的角色改为 `["member", "技术部门"]`。
2. A 创建只给「技术部门」可见的 Matter。
3. B 能看到。
4. C 列表看不到、直接访问 URL 看到未找到/无权限页面、搜索无结果、AI/MCP 读不到。
5. admin 如果没有「技术部门」这类普通业务角色授权，也不能因为 admin 身份看到该 Matter。
6. 发帖和修改可见范围时，选择器不展示 `admin` 角色。
7. 如果 Matter 所属 Category 是 restricted，选择器不展示 Category 范围外的角色和用户。
8. 直接访问不可见 Matter 时页面不出现裸 `403` / `404` 文本。
9. 保存超过 Category 的范围时看到业务提示，不看到裸 `400`。
10. A 在 Matter 详情把 C 加入单独授权用户。
11. C 刷新后可以看到。
12. A 把 C 移出范围。
13. C 收到 `matter.visibility_changed` 后列表/详情刷新，重新变为不可见。

- [ ] **Step 4: 文档提交**

```bash
git add AI-docs/designs/2026-04-29-role-and-matter-visibility-design.md AI-docs/plans/2026-04-29-role-and-matter-visibility-plan.md
git commit -m "docs: refine role-array matter visibility plan"
```

---

## Implementation Notes

1. Category 创建入口本期先放在新建 Matter 流程里完成：当输入的 Category 不存在时，同步提交 `new_category_visibility`。
2. `pivot_user.role` 本期明确改为 JSON 字符串数组；后续如有查询性能问题，再评估是否增加派生缓存或索引。
