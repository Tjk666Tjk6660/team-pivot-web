# Matter Owner 责任人机制：设计方案

> **Goal:** 给 Matter 引入"当前责任人"语义，让事项的责任归属在入口可见、变更可追溯、能被 scheduler / AI 低成本读取。第一版用开放协作模型，不引入审批流。

**依据需求**：用户口述需求（2026-04-29），见末尾附录。

**关联机制**：
- 现有文件级 `owner`（每条 timeline item 上的 owner，表示某个 act/think 的执行人或作者）继续保留，与本次新增的 matter 级 owner **不冲突、各表一意**。
- 现有 status 单向状态机（[server/matter_status.py](../../server/matter_status.py)）；本次 owner 变更**默认不触发** status 变更，但允许同一次操作里同时携带 status_change（详见 §二.5）。

---

## 一、概念区分

| 概念 | yaml 落盘字段 | render 层衍生字段 | 表达 | 写入时机 |
|------|--------------|-----------------|------|---------|
| **Matter owner**（本次新增） | `matter.owner` | `matter.owner_display` / `matter.owner_avatar_url` | 这件事**当前由谁负责持续推进** | 创建时默认 = 创建者；之后只能通过 owner 变更操作改 |
| Act / Think owner（既有） | `timeline[i].owner` | `timeline[i].owner_display` / `..._avatar_url` | **这条文件**的执行人 / 作者 | 每条 timeline item 各自携带，不被 matter owner 变更影响 |
| Creator（既有） | `timeline[0].creator` | `creator_display` / `creator_avatar_url`（list 顶层与详情 timeline 各处） | matter 的发起人 | 创建时写一次，永不变 |

**display / avatar 字段一律不落盘**，由 `_summarize_matter` / `_render_matter_detail` 在响应时实时解析（参考既有 [server/api/matters.py:524-527](../../server/api/matters.py#L524-L527) 对 creator/owner 的处理）。理由：用户改昵称 / 头像后，历史 yaml 不需要回写；也让所有"显示名"逻辑只在一个地方维护。

**核心断言**：matter owner 与 act owner 是两层语义。"A 推进整个 matter；其中某个 act 由 B 执行"是允许的，且需在 UI 上表达清楚——matter 卡片显示 matter owner，每条 act 卡片仍显示该 act 自己的 owner。

---

## 二、整体方案

### 2.1 数据模型：matter index 增加 owner 字段

`{matter_id}.index.yaml` 的 `matter:` block 仅增加 **一个** 字段（display 走 render 层即时解析，不落盘）：

```yaml
matter:
  id: 新需求-日报推送
  title: 新需求-日报推送
  current_status: planning
  owner: lisi           # ← 新增；与现有 creator / timeline[i].owner 同格式
  created_at: '2026-04-28T10:51:44+08:00'
  updated_at: '2026-04-29T10:08:20+08:00'
timeline:
  - file: discussions/...
    creator: zhangsan
    owner: zhangsan         # 文件级 owner（既有），独立于 matter.owner
    type: think
    ...
```

**字段语义**：
- `owner`：注册用户 = pinyin，未注册联系人 = open_id 兜底——与现有 `creator` / `timeline[i].owner` 完全同格式
- **不允许为空字符串**——"未分配"用 `null` / 缺字段表达，UI 展示"未分配"
- `owner_display` / `owner_avatar_url` **不进 yaml**，由 `_summarize_matter` / `_render_matter_detail` 解析后塞进 API 响应（mirror 现有 `creator_display` / `creator_avatar_url` 的实现）

### 2.2 数据模型：timeline 增加 owner_change 事件

owner 变更**进入同一条 timeline**（避免引入第二条事件流），但 entry 形态与既有文件型 item 不同：

```yaml
timeline:
  # ... 文件型 item
  - type: owner_change      # ← 新增 type
    created_at: '2026-04-29T09:30:00+08:00'
    actor: wangwu           # 操作人（pinyin / open_id），同 creator 格式
    from_owner: lisi   # null 表示"原为未分配"
    to_owner: zhangsan
    reason: 后续执行由张三负责推进
```

display 字段（`actor_display` / `from_owner_display` / `to_owner_display` / `actor_avatar_url` 等）**不进 yaml**——同 §2.1，由 render 层即时解析后塞进 API 响应给前端。

**与文件型 item 的差异**：
- **没有** `file` / `body` / `summary` —— 不写 MD 文件
- **没有** `creator` —— actor 表达执行该操作的人，含义不同于 creator
- **不参与** `current_status` / `ALLOWED_TYPES_BY_STATUS` 校验（owner 变更在所有状态下都允许，包括 reviewed / cancelled）
- **可以**与 `status_change` 同 entry 出现（"转交并推进状态"场景，见 §2.5）

新增 `VALID_EVENT_TYPES = frozenset({"owner_change"})` 与既有 `VALID_DOC_TYPES` 并列；`matter_validator.validate_append` 在入口处先按 type 分流。

### 2.3 后端 API：新增 owner 转交端点

```
POST /api/matters/{matter_id}/owner
{
  "to_owner": "ou_xxxxxx",         // 必填，新 owner 的 open_id（前端 OwnerPicker 输出）
  "reason": "后续执行由李四负责推进",  // 必填，min_length=1, max_length=200
  "status_change": {                // 可选；若提供则一次操作完成转交+推进
    "from": "planning",
    "to": "executing"
  }
}
```

**行为**：
1. 校验 matter 存在；
2. 校验 `to_owner` 能被 `users.get_by_any_id()` 解析（不存在则 422 `owner_unknown`）；
3. 校验 `to_owner` ≠ 当前 `matter.owner`（避免空操作 → 422 `owner_unchanged`）；
4. 校验 reason 非空（前端必填，后端兜底 → 422 `reason_required`）；
5. 若 `status_change` 提供，走 §2.5 的合并迁移校验——仅允许 `planning → executing`，否则 422 `status_change_not_allowed_by_event`；`from` 必须 == 当前 `matter.current_status`（→ 409 `status_stale`）；
6. 写 timeline owner_change item（可能携带 status_change）；
7. **原子更新** `matter.owner` 和（若有）`matter.current_status`，刷 `matter.updated_at`；
8. 返回 `{matter, item}`，前端用返回值刷新缓存。

**返回 200，body：**

```json
{
  "matter": {
    "id": "...",
    "owner": "zhangsan",
    "owner_display": "张三",
    "owner_avatar_url": "...",
    ...
  },
  "item": {
    "type": "owner_change",
    "actor": "zhaoliu",
    "actor_display": "赵六",
    "actor_avatar_url": "...",
    "from_owner": "wangyu",
    "from_owner_display": "王五",
    "to_owner": "lisi",
    "to_owner_display": "李四",
    "reason": "..."
  }
}
```

`*_display` / `*_avatar_url` 是后端 render 层的实时解析结果，**仅存在于 API 响应**，不落盘。

**事件总线**：内部发一条 `TOPIC_MATTER_OWNER_CHANGED = "matter.owner_changed"` 走既有 `emit()`，payload 含 `matter_id / actor / from_owner / to_owner / reason / at`。SSE 对外沿用既有 `matter.updated` event，并在 payload 中带 `reason: "owner_changed"`；监听端（Dashboard）收到后刷新该 matter 的本地缓存。

### 2.4 创建路径：默认 owner = 创建者，也可显式指定他人

`POST /api/matters` body 新增可选字段 `owner_id`，与既有 `initial_file.owner`（**文件级**owner，落到 `timeline[0].owner`）**完全分离**：

```jsonc
POST /api/matters
{
  "category": "Pivot",
  "title": "客服流程优化方案",
  "owner_id": "ou_xxxxxx",     // ← 新增；可选；缺省 = 创建者
  "initial_file": {
    "type": "think",
    "summary": "...",
    "body": "...",
    "owner": "ou_yyyyyy"             // 既有；该 think 文件本身的 owner
  }
}
```

**两个 owner 互不影响**：

| 字段 | 作用域 | 默认值 |
|------|-------|-------|
| `owner_id` | matter 级——`matter.owner`，谁负责整件事 | 缺省 = 创建者 pinyin |
| `initial_file.owner` | 文件级——`timeline[0].owner`，这条 think/act 文件本身的执行人 / 作者 | 缺省 = 创建者 pinyin（既有） |

**`publish_matter_create` 内部行为**：

```python
matter_owner_pinyin = (
    _resolve_owner_for_index(body.owner_id, users)
    if body.owner_id
    else user.pinyin
)
matter_block = {
    "id": matter_id,
    "title": title,
    "current_status": "planning",
    "owner": matter_owner_pinyin,    # 仅落盘 canonical id
    "created_at": now,
    "updated_at": now,
}
```

**关键决策**：创建时直接指定他人为 owner，**不**生成 owner_change timeline 事件。"创建即指定"和"创建后转交"语义不同——前者是 matter 出生时的归属，后者是变更事件。第一条 timeline item（think/act）已经记录了 creator，配合 matter.owner 就能完整表达"X 创建了这件事，Y 推进它"。强行在创建瞬间塞一条 owner_change（from_owner=X, to_owner=Y）反而冗余。

`owner_id` 校验失败时返回 422 `owner_unknown`，与 §2.3 转交端点共用错误码。

**前端入口**（NewMatter）：在表单里加一个"指定责任人（可选）"OwnerPicker 字段，缺省灰文提示"默认 = 你自己"。

### 2.5 转交 + 状态变更：允许一次操作完成

需求 §7 给的典型场景："转交执行"——`owner: 张三 → 李四` 同时 `status: planning → executing`。第一版**支持**这个能力，但仅限于一条最自然的迁移路径。

**支持的合并迁移**（仅一条）：

| 迁移 | 语义 | 是否允许 owner_change 携带 |
|------|------|------------------------|
| `planning → executing` | 转交给执行人，事项即进入执行 | ✅ |
| `planning → paused` | 暂停 | ❌（需 think 解释为何停） |
| `executing → paused` / `paused → executing` / `paused → planning` | 重新规划 / 重启 / 暂停 | ❌（需 think 表达调整理由） |
| `executing → finished` / `executing → cancelled` | 结案 | ❌（需 result 给出结论） |
| `finished → reviewed` / `cancelled → reviewed` | 复盘归档 | ❌（需 insight 复盘内容） |

理由：除 `planning → executing` 外，所有其他迁移都需要内容载体（解释 / 结论 / 复盘）；owner_change 自身不带这种载体。如果将来发现还有其他自然合并场景，再扩展。

**API**：`POST /api/matters/{id}/owner` 的 body 携带可选 `status_change`：

```jsonc
{
  "to_owner": "ou_xxx",
  "reason": "李四负责正式启动执行",
  "status_change": {                  // 可选
    "from": "planning",
    "to": "executing"
  }
}
```

**校验**：
- `status_change` 提供时，必须满足 `(from, to)` 是合法迁移（[matter_status.py:ALLOWED_TRANSITIONS](../../server/matter_status.py#L12-L19)）
- 且必须满足 `(from, to) ∈ EVENT_TRIGGERS_BY_TRANSITION[(from, to)]` 包含 `"owner_change"`——第一版仅 `("planning", "executing")` 一条
- `from` 必须等于当前 `matter.current_status`（避免并发漂移）
- 不满足时返回 422，错误码：`status_change_not_allowed_by_event`

**底层数据**：写**一条** owner_change timeline entry，携带 `status_change` 字段（与现有文件型 item 携带 `status_change` 同结构）；`_apply_status_change` 复用既有逻辑更新 `matter.current_status`：

```yaml
- type: owner_change
  created_at: '2026-04-29T09:30:00+08:00'
  actor: dengke
  from_owner: zhangsan
  to_owner: lisi
  reason: 李四负责正式启动执行
  status_change:
    from: planning
    to: executing
```

**前端 timeline 渲染**：用户原话"明确记录两件事，不要让 owner change 藏在 status change 的备注里"——所以 UI 把这一条 entry **拆成两条邻接的视觉行**：

```
┌─────────────────────────────────────────────────────┐
│ 👤 王五 将 Owner 从 张三 → 李四                       │
│ 原因：李四负责正式启动执行                              │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ ⏩ 状态：planning → executing                         │
└─────────────────────────────────────────────────────┘
```

底层一条 entry / 渲染层两行视觉，是因为：
- 数据原子性：转交 + 状态推进要么都成功要么都失败，复用既有 `_atomic_write_yaml`
- 视觉清晰度：用户要的是"两件事都被独立看到"，UI 拆行能直接满足
- 简化 scheduler / AI：读 timeline 时还是一条 entry，type 一个，两件事都在同一个时间戳下

**新增 helper**（[server/matter_status.py](../../server/matter_status.py)）：

```python
EVENT_TRIGGERS_BY_TRANSITION: dict[tuple[str, str], frozenset[str]] = {
    ("planning", "executing"): frozenset({"owner_change"}),
}

def can_event_type_trigger(event_type: str, from_state: str, to_state: str) -> bool:
    return event_type in EVENT_TRIGGERS_BY_TRANSITION.get((from_state, to_state), frozenset())
```

`matter_validator.validate_append` 走 owner_change 分支时，若 entry 带 status_change，就调 `can_event_type_trigger`；不带就跳过 status 校验。

### 2.6 前端：列表展示 owner

`MatterSummary` 类型 + 后端 `_summarize_matter` 输出新增：

```ts
export type MatterSummary = {
  // 既有字段保持不动
  owner: string | null;            // ← 新增
  owner_display: string | null;    // ← 新增（null = 未分配）
  owner_avatar_url: string | null; // ← 新增
};
```

[ThreadListPane.tsx](../../web/src/components/ThreadListPane.tsx) 的 `MatterRow` 在 meta 行加固定占位 owner 块：

```tsx
<div className="mt-1 flex items-center gap-2">
  <OwnerChip
    name={matter.owner_display ?? "未分配"}
    avatarUrl={matter.owner_avatar_url}
    unassigned={!matter.owner}
  />
  <div className="min-w-0 flex-1 truncate text-[10px] ...">{meta}</div>
  <StatusBadge ... />
</div>
```

**`OwnerChip` 渲染规则**（新增组件 `web/src/components/matter/OwnerChip.tsx`）：

- 高度固定（`h-5`），左侧 16px 圆头像 + 右侧最大宽度 `max-w-[6rem] truncate` 的姓名
- `unassigned` 状态：占位灰头像（`bg-[var(--surface-mute)]`）+ "未分配" 文案 + 浅文字色提示
- hover 整个 chip 显示完整姓名（`title={matter.owner_display ?? "未分配"}`）
- **不抢 title 视觉**：title 字号 14、owner 字号 11，owner 灰文，符合需求 §4 "title 仍是主信息"

**布局稳定性**：列表 row 的 `flex` 给 OwnerChip 一个 `shrink-0 min-w-[5rem]`，防止不同名字长度导致 status badge 和元信息布局抖动。

### 2.7 前端：详情顶部卡片展示 owner + 转交入口

[MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) 顶部 matter 卡片在 status badge 旁显示 owner：

```tsx
<div className="flex items-center gap-3">
  <OwnerBadge name={detail.matter.owner_display} avatarUrl={detail.matter.owner_avatar_url} />
  <button
    onClick={() => setTransferOpen(true)}
    className="text-xs text-[var(--text-mute)] hover:text-[var(--accent)]"
  >
    转交负责人
  </button>
</div>
```

**`TransferOwnerDialog`**（新增 `web/src/components/matter/TransferOwnerDialog.tsx`）：

- 复用既有 `OwnerPicker`（联系人搜索 + 选择）
- 字段：当前 owner（只读展示）/ 新 owner（OwnerPicker） / 变更原因（Textarea，必填，min 1 / max 200）
- 按钮：取消 / 确认转交（提交前校验 reason 非空 + new owner ≠ current owner）
- 提交后调 `POST /api/matters/{id}/owner` → 返回值更新本地缓存 → toast 成功 → 关 dialog

**入口可见性**：第一版**所有已登录成员都能点开**（开放协作，需求 §8）。不做权限灰显。

### 2.8 前端：timeline 渲染 owner_change

`TimelineItem` 类型扩展（[web/src/api.ts](../../web/src/api.ts)）：

```ts
export type TimelineItem =
  | TimelineFileItem           // 既有形态（file, type ∈ DocType, ...）
  | TimelineOwnerChangeItem;   // ← 新增

export type TimelineOwnerChangeItem = {
  type: "owner_change";
  created_at: string;
  actor: string;
  actor_display: string;
  actor_avatar_url: string | null;
  from_owner: string | null;
  from_owner_display: string | null;
  to_owner: string;
  to_owner_display: string;
  reason: string;
  status_change?: { from: string; to: string } | null;  // ← 仅合并迁移时存在
};
```

**视觉**（[TimelineStrip.tsx](../../web/src/components/matter/TimelineStrip.tsx) + 卡片层）：

- TimelineStrip（弧线节点条）上 owner_change 用一个**更小的菱形节点**而非现有的圆/方，区分"事件"vs"文件"
- 文件流主列表中，owner_change 渲染为一行轻量条目（不是 FileCard）：

```
┌─────────────────────────────────────────────────────┐
│ 👤 王五 将 Owner 从 张三 → 李四                       │
│ 原因：后续执行由李四负责推进                            │
│ 09:30                                                │
└─────────────────────────────────────────────────────┘
```

- 当 entry 同时携带 `status_change` 时，**额外**渲染一条邻接的状态行（按需求 §7："明确记录两件事，不要让 owner change 藏在 status change 的备注里"）：

```
┌─────────────────────────────────────────────────────┐
│ 👤 王五 将 Owner 从 张三 → 李四                       │
│ 原因：后续执行由李四负责推进                            │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ ⏩ 状态：planning → executing                         │
└─────────────────────────────────────────────────────┘
```

- 不可展开、不挂 comments、不挂 readers
- AI / scheduler 通过 `read_matter_index` 工具读到这条 entry 时，能直接根据 type + status_change 字段区分

---

## 三、各组件改动清单

### 后端

| 路径 | 改动 |
|------|------|
| `server/doc_types.py` | 新增 `VALID_EVENT_TYPES = frozenset({"owner_change"})`；保留 `VALID_DOC_TYPES` 不动 |
| [server/matter_status.py](../../server/matter_status.py) | 新增 `EVENT_TRIGGERS_BY_TRANSITION` 仅含 `("planning", "executing"): {"owner_change"}` + `can_event_type_trigger()` helper |
| [server/matter_validator.py](../../server/matter_validator.py) | `validate_append` 入口先按 type ∈ EVENT 分流；event 走 `_validate_owner_change_shape`（reason 非空、from_owner 与当前 matter.owner 一致、to_owner 非空、to_owner ≠ from_owner）；若 entry 带 `status_change` 则走 `can_event_type_trigger` 校验 |
| [server/matter_index.py](../../server/matter_index.py) | `_normalize_item` 增加 owner_change 分支（不 fallback owner=creator——event 没有 creator 概念）；`create_matter_index` 接受 `matter_owner` 参数写入 matter block；新增 `apply_owner_change(path, *, item, now_iso)` 同时写 timeline、`matter.owner`、（可选）`matter.current_status`，全部在一次 `_atomic_write_yaml` 内 |
| [server/api/matters.py](../../server/api/matters.py) | `NewMatterBody` 新增 `owner_id?: str`（matter 级，与既有 `initial_file.owner` 完全分离）；新增 `OwnerChangeBody` + `POST /api/matters/{id}/owner` 路由（接受可选 `status_change`）；`_summarize_matter` 输出 `owner / owner_display / owner_avatar_url`；`_render_matter_detail` 同步；`_render_item` owner_change 分支解析 `actor_display / from_owner_display / to_owner_display` |
| [server/publish.py](../../server/publish.py) | `publish_matter_create` 接受可选 `matter_owner_pinyin`（缺省 = `user.pinyin`）写入 matter block；新增 `publish_matter_owner_change(workspace, user, *, matter_id, to_owner, reason, status_change=None)` 走 write_session、emit `TOPIC_MATTER_OWNER_CHANGED`（payload 含 `status_change` 字段，下游 SSE 可同时刷 status） |
| `server/events.py`（或对应 topics 文件） | 新增内部 topic `TOPIC_MATTER_OWNER_CHANGED = "matter.owner_changed"`；SSE 对外映射为 `matter.updated` + `reason: "owner_changed"` |
| [server/api/ai.py](../../server/api/ai.py) / [server/ai/tools.py](../../server/ai/tools.py) | `read_matter_index` MCP 工具天然返回 owner_change（已在 timeline 内）；`build_system_prompt` 提到 matter.owner 的语义，让 AI 在 reply 时知道"现在这件事归谁推进" |

### 前端

| 路径 | 改动 |
|------|------|
| [web/src/api.ts](../../web/src/api.ts) | `MatterSummary` / `MatterMeta` / `MatterDetail.matter` 加 `owner / owner_display / owner_avatar_url`；`TimelineItem` 改 union；`createMatter` 入参增加可选 `owner_id`；新增 `transferMatterOwner(matter_id, to_owner, reason, status_change?)` |
| `web/src/components/matter/OwnerChip.tsx` | 新增；列表用 |
| `web/src/components/matter/OwnerBadge.tsx`（或复用 OwnerChip 的 size 变体） | 详情顶部用 |
| `web/src/components/matter/TransferOwnerDialog.tsx` | 新增；OwnerPicker + reason textarea + 可选"同时推进至 executing"复选框（仅当当前 status == planning 时显示）+ 确认 |
| [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx) / [NewMatterGuidedFlow.tsx](../../web/src/pages/NewMatterGuidedFlow.tsx) | classic form 增加"指定责任人（可选，默认你自己）"OwnerPicker；guided flow 在 mentions 步骤前后插入一个 owner 步骤（也可缩到 mentions 步骤一并选） |
| [web/src/components/ThreadListPane.tsx](../../web/src/components/ThreadListPane.tsx) | `MatterRow` meta 行加 OwnerChip；占位宽度处理 |
| [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) | 顶部卡片加 OwnerBadge + 转交按钮；接 TransferOwnerDialog；timeline 渲染层加 owner_change 分支组件 `OwnerChangeRow`（带 status_change 时再渲一行 status 视觉条） |
| [web/src/components/matter/TimelineStrip.tsx](../../web/src/components/matter/TimelineStrip.tsx) | 节点渲染按 type 分形（owner_change = 小菱形 / 灰色） |
| `web/src/components/matter/OwnerChangeRow.tsx` | 新增；timeline 内的轻量事件条 |
| [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx) | SSE 监听 `matter.updated`，在 `reason === "owner_changed"` 时 invalidate 该 matter 缓存 |

### 测试

| 路径 | 覆盖 |
|------|------|
| `server/tests/test_matters_owner.py`（新增） | 创建时默认 owner、转交成功、reason 必填、owner_unknown、from_owner 与当前 mismatch 时 409、timeline 增加 owner_change、matter.owner 同步、SSE event |
| `server/tests/test_matter_validator.py` | 加 owner_change 分支用例 |
| `web/src/components/matter/OwnerChip.test.tsx`（可选 v1） | unassigned 占位、name 截断 |
| `web/src/components/matter/TransferOwnerDialog.test.tsx` | reason 必填、new ≠ current、提交调 API |

### 迁移

| 路径 | 改动 |
|------|------|
| `server/scripts/backfill_matter_owner.py`（新增） | 一次性脚本：扫所有 `*.index.yaml`，若 `matter.owner` 缺失则用 `timeline[0].creator` 填入；用 `_atomic_write_yaml` 落盘 |
| `server/recovery.py` | 启动期检测：如发现 matter.owner 缺失，记 warning，但**不**自动回填（让运维主动跑脚本，避免静默改数据） |

---

## 四、关键决策与边界

### 4.1 已确认决策清单

| 决策点 | 取值 | 落点 |
|--------|------|------|
| 转交是否能与 status_change 合并到一次操作 | **是**——但仅限 `planning → executing` 一条迁移；底层一条 owner_change entry 携带 status_change，前端 timeline 渲染拆两条视觉行 | 二.5 |
| 创建时是否允许指定他人为 owner | **是**——`POST /api/matters` 增加可选 `owner_id`；缺省 = 创建者；不生成 owner_change 事件 | 二.4 |
| owner 变更入口可见性 | **全员可见**（开放协作，需求 §8） | 二.7 |
| reason 长度上限 | **200 字**（保持简短，复杂理由可放评论） | 二.3 |
| owner_change 是否能在 reviewed / cancelled 状态下发生 | **允许**（"已结案 matter 重新指派复盘人"是合理用例） | 二.2 |
| 历史 matter 缺 owner 的处理 | **显式跑脚本回填 + UI"未分配"占位**（数据迁移要可见） | §五 |

### 4.2 不变量

- matter.owner 永远是字符串或缺失（不是 `""`）；UI 看缺失 = "未分配"
- 同一 matter 在任一时刻最多 1 个 owner（不引入"co-owner"概念，避免责任糊化）
- owner_change entry 一旦写入不再改（reason 写错的处理：补一条 owner_change 把 owner 转回原人 + reason 注明纠错；不删 entry）
- owner 不做软删除——某成员离职后其 pinyin 仍在 timeline / matter.owner 里出现，UI 渲染时若 users 表查不到则降级显示原 pinyin / open_id（同 creator 的现有兜底）

### 4.3 与既有质量门、状态机的关系

- 质量门（[bodySource.ts](../../web/src/lib/bodySource.ts)）：与 owner 无关。owner 变更不写文件、不过质量门
- status 状态机：owner 变更不影响 status；status 变更不影响 owner——两条独立轨道
- act / think file owner：保持各自独立。matter owner 转交后，历史 act 的 file owner **不**回填

### 4.4 scheduler / AI 怎么用

- scheduler code：扫 `index_dir/*.index.yaml` 的 `matter.owner` + `matter.updated_at` + `matter.current_status`，做"我的 / 长期无更新 / 未分配"分组
- AI 工具 `read_matter_index` 的返回里 timeline 已经带 owner_change，AI 可以直接读到"上次转交时间 / 原因"
- "我负责的 Matter" 列表：前端加 `?owner=<pinyin>` 查询参数，后端 `_matter_has_owner` 已经存在文件级 owner 检索——本期改造为同时支持 matter 级 owner 检索（`?matter_owner=...` 或保留 `?owner=...` 含义优先匹配 matter.owner，找不到再 fallback 到 file owner，**待批**）

---

## 五、迁移与兼容

### 5.1 现有 index 文件

现有所有 `*.index.yaml` 的 `matter:` block 没有 `owner / owner_display`。两种处理：

1. **回填脚本**：`scripts/backfill_matter_owner.py`，对每个 index 取 `timeline[0].creator` 写入 `matter.owner`，并解析 display_name 写入 `matter.owner_display`。一次性运行，幂等（已存在 owner 则跳过）。
2. **运行时兜底**：`_summarize_matter` / `_render_matter_detail` 读取时，若 `matter.owner` 缺失则走 fallback：
   - 优先读 `matter.owner`
   - 缺失则用 `timeline[0].creator`
   - 若 timeline 也空（理论不存在）→ `null`（UI "未分配"）

第一版**两个都做**：上线脚本回填存量，但代码层保留兜底，避免迁移漏掉某个文件时直接 500。

**回填脚本的边界（P0）**：脚本必须**幂等**，且对几类异常 corner 要 defensive：

| 输入 | 处理 |
|------|------|
| matter.owner 已存在（之前跑过） | **跳过**，不重写。第二次运行不应改任何文件 |
| timeline 为空 | 跳过 + log warning（理论不可能发生，但 yaml 可能被人手编过） |
| timeline[0] 是 owner_change 而非文件 entry | 跳过 + log warning（不应发生，但 defensive） |
| timeline[0].creator 字段缺失（极旧数据） | 跳过 + log warning |
| timeline[0].creator 是 ou_xxx（未注册联系人） | 直接当 matter.owner，render 层自然 fallback 显 open_id 截断 |
| 中途 crash | 已落盘的 index 是完整的（_atomic_write_yaml）；重跑安全 |

### 5.2 API 兼容

- `GET /api/matters` 响应增加字段——前端老版本会忽略未知字段，**向后兼容**
- `GET /api/matters/{id}` 同上
- `POST /api/matters/{id}/owner` 是新端点——老前端不调用，无影响

### 5.3 MCP 工具兼容

`read_matter_index` 返回里 timeline 现在多了 `type: owner_change` 的 entry——外部 MCP 客户端（包括非本项目的）需要能容忍未知 type。**契约层面**这是可接受的扩展（schema 用 `additionalProperties: true` 或不强约束 type）；但 MCP 工具描述（[server/mcp/schemas.py](../../server/mcp/schemas.py)）应当显式声明 `owner_change` 是 timeline entry 的合法 type，并解释字段含义，让外部 AI 知道怎么读。

详细 MCP schema 处理见 §6.4。

---

## 六、边界与异常处理

设计层之外的实现期边界值清单。所有条目都按"必须解决（P0）/ 应该明确（P1）"分级；P2 优化项不在本节，留给实施期判断。

### 6.1 未分配状态下的转交（P0）

matter 处于未分配（`matter.owner` 为 `null` / 缺失）时仍允许转交。整条链路的处理：

| 层 | 行为 |
|----|------|
| TransferOwnerDialog | 当前 owner 区域显"未分配"灰文；其他字段照常 |
| API body | `from_owner` 字段允许传 `null` 或不传；validator 不报"必填" |
| validator 校验 | `from_owner == matter.owner` 比较时，`null == null` / `None == None` 视为相等 |
| timeline entry | 落盘 `from_owner: null`（yaml 里写 `from_owner: ~` 或省略）；render 层把 `from_owner_display` 解析为 `null` |
| UI timeline | "X 将 Owner 从 **未分配** → 李四" |
| 通知 | 没有"原 owner"可通知；只通知新 owner 与创建者（见 §2.7 通知规则） |

### 6.2 转交合并 + 未分配 owner + status_change（P0）

"接手一个无主 matter，并直接进入 executing" 是常见救场场景。三件事同一调用合法：

```jsonc
POST /api/matters/{id}/owner
{
  "to_owner": "ou_xxx",
  "reason": "我接手这件事并启动执行",
  "status_change": { "from": "planning", "to": "executing" }
  // from_owner 不传 / null —— matter 当前未分配
}
```

校验链路：

1. matter.current_status == "planning" ✓
2. `from_owner == matter.owner` 都是 null ✓
3. `to_owner != from_owner` —— null vs "ou_xxx" 不相等 ✓
4. `can_event_type_trigger("owner_change", "planning", "executing")` → True ✓

落盘后 matter.owner = "lisi"，matter.current_status = "executing"，timeline 一条 owner_change entry 携带 status_change。

### 6.3 timeline 顺序契约（P1）

timeline 永远按**写入顺序**展示，前端**不**按 `created_at` 重排。理由：

- [matter_index.py:181](../../server/matter_index.py#L181) 是 `setdefault("timeline", []).append()`，append-only 写入顺序就是事实顺序
- `created_at` 可能受系统时钟偏移影响（多机 / 用户手动改本地时间），按时间排会出现"晚写的事件被插到前面"的错乱
- 前端只用 `created_at` 渲染相对时间（"3 小时前"），不参与排序

不变量：**写入顺序 = 时间真理**。

### 6.4 MCP schema 兼容（P0）

[server/mcp/schemas.py](../../server/mcp/schemas.py) 当前的 timeline entry schema 如果对 `type` 字段是严格 enum（`enum: [think, act, verify, result, insight]`），外部 MCP 客户端拿到 `type: owner_change` 会 schema validation fail。

**v1 处理**：
- enum 显式扩展：`type: enum: [think, act, verify, result, insight, owner_change]`
- 同时在 schema description 里说明 owner_change entry 的字段集（actor / from_owner / to_owner / reason / status_change?）和缺失字段（无 file / body / summary）
- MCP 工具描述里加一段："timeline 包含两类 entry：文件型（type ∈ {think, act, verify, result, insight}）和事件型（type == owner_change）。事件型不带 file 字段。"

让外部 AI 把 owner_change 当成"显式信息"而不是"未知噪音"。

### 6.5 NewMatter UI 上的两个 owner 不能混（P1）

classic form 既有 `OwnerPicker`（act 文件级 owner，仅 act 类型才显示）；本期新增的是 matter 级 owner picker。两个同框会让用户糊涂。

**布局与文案约定**：

| Picker | 位置 | 文案 |
|--------|------|------|
| **matter 级 owner**（新增） | 标题下、category 旁 | "**责任人**（推进这件事的人，可选 · 默认你自己）" |
| 文件级 owner（既有） | act 表单内（act 类型时） | "**Owner**（执行人 · 默认你自己）" |

guided flow：原 6 步 → 7 步。在 mentions（圈人）**之前**新增"指定责任人"步骤（默认自己，可一键跳过）；mentions 顺移。

```
Step 1 话题  → 2 类型  → 3 种类  → 4 标题  → 5 责任人 → 6 圈人  → 7 AI 起草
                                              ↑ 新增
```

如果用户在第 5 步跳过，bridge 到 classic form 的 fallback 也保持 owner = creator。

### 6.6 owner 解析失败时的兜底（P1）

`_resolve_owner_for_index`（[publish.py:675](../../server/publish.py#L675)）已有兜底：

- 注册用户 → pinyin
- 联系人但没注册（无 pinyin）→ 保留原 open_id
- 完全找不到 → 保留原值

matter.owner / timeline owner_change 落盘**复用同一函数**，行为一致。响应阶段 `resolve_id` / `resolve_avatar_url` 同步兜底：

| owner 字段值 | owner_display | owner_avatar_url |
|------|--------------|------------------|
| 已注册 user pinyin | user.name | user.avatar_url |
| 联系人 open_id | contact.name | contact.avatar_url |
| 未知 pinyin/open_id（极端 corner） | 原值截断（如 `ou_abc12...`） | null |

UI 始终能显示**某种**字符串，不会出现 undefined / 空白。

### 6.7 owner_id 指向自己等价于不传（P1）

API 兼容：`POST /api/matters` 时 `owner_id` 传创建者自己的 open_id 应等价于不传。后端解析后两者都让 matter.owner = creator.pinyin。**不**作为错误，**不**作为去重的特殊路径——`_resolve_owner_for_index(自己的 open_id) == user.pinyin` 自然落到正确值。

只在前端 OwnerPicker 体感上给一个轻微优化：选中"自己"时灰文提示"默认就是你"，鼓励用户清空选择，但不强制。

### 6.8 owner_change yaml key 顺序（P1）

[matter_index.py:_ITEM_KEY_ORDER:17-31](../../server/matter_index.py#L17-L31) 现在按文件型 entry 的字段定义 key 顺序（`file → created_at → creator → owner → type → ...`）。owner_change 字段集不一样：

```
type, created_at, actor, from_owner, to_owner, reason, status_change?
```

**处理**：`_normalize_item` 走 owner_change 分支时使用独立的 key 顺序常量：

```python
_OWNER_CHANGE_KEY_ORDER = (
    "type",
    "created_at",
    "actor",
    "from_owner",
    "to_owner",
    "reason",
    "status_change",
)
```

不混进既有 `_ITEM_KEY_ORDER`，避免文件型 entry 的字段顺序被牵连。`_reorder` 函数已经支持任意 key 顺序数组，只要分支里传对就行。

### 6.9 撤销误操作的指引（P1·文档级）

v1 没有 undo 按钮。误操作（转错人 / reason 写错）的处理由**用户自助**完成：

- **转错人**：再点一次"转交"，把 owner 转回去 / 转给正确的人；reason 写"纠正上一步误操作"。timeline 上留两条邻接 owner_change，审计完整可追溯。
- **reason 写错**：同上，发起一条新的 owner_change（owner 不变也行——但 §2.3 校验要求 `to_owner != from_owner`，所以**纯 reason 修正不被支持**；这是 v1 的已知 limitation）。

UI 上详情页 owner 卡片旁加一行小灰字提示："转错了？再转一次即可，所有变更都会留痕。"

---

## 七、测试矩阵

### 7.1 自动化

后端：

- 创建 matter（不带 `owner_id`）→ matter.owner == 创建者；timeline 没有 owner_change
- 创建 matter（带 `owner_id` 指向他人）→ matter.owner == 该他人；timeline 仍只有 1 条 think/act 文件 entry，无 owner_change
- 创建 matter：`owner_id` 不存在 → 422 `owner_unknown`
- 创建 matter：matter 级 owner 与 `initial_file.owner` 互不影响（指定 matter owner = A，文件 owner = B，落盘后 matter.owner=A、timeline[0].owner=B）
- 转交：reason 非空 → 200，matter.owner 更新，timeline 增加一条 owner_change
- 转交：reason 空 → 422 `reason_required`
- 转交：to_owner 不存在 → 422 `owner_unknown`
- 转交：to_owner == 当前 owner → 422 `owner_unchanged`
- 并发：两个客户端同时点转交（A → B 与 A → C），第二个请求 `from_owner` 与当前不一致 → 409 `owner_stale`
- 转交合并 status：planning + `status_change={planning→executing}` → 200，matter.owner 与 matter.current_status 同时更新；timeline 仅 1 条 owner_change entry，但带 status_change 字段
- 转交合并 status：executing + `status_change={executing→paused}` → 422 `status_change_not_allowed_by_event`（v1 仅允许 planning→executing）
- 转交合并 status：planning + `status_change={planning→executing}` 但当前 status 已被别人改成 executing → 409 `status_stale`
- SSE：转交后内部 event bus 发 `matter.owner_changed`，SSE 客户端收到 `matter.updated` + `reason: "owner_changed"`；payload 可扩展携带 status_change（合并迁移时）
- 历史 matter（matter.owner 缺失）：`GET /api/matters/{id}` 不报错，返回 owner_display = creator 兜底
- 回填脚本：跑一遍后所有 index 都有 owner，第二次跑（已存在 owner）幂等不改
- 转交在 reviewed 状态下 → 200（决策 4.1）；不允许带 status_change（reviewed 是终态）
- AI MCP `read_matter_index`：timeline 含 owner_change 不报 schema 错

边界值（覆盖 §六）：

- §6.1 未分配状态转交：matter.owner=null + body 不传 from_owner → 200，落盘 from_owner: null
- §6.1 未分配状态转交：body 传 from_owner=null 显式 → 200，等价处理
- §6.1 未分配状态转交后再转交：第二次 from_owner 必须 = 第一次的 to_owner，否则 409 owner_stale
- §6.2 接手未分配 + 启动 executing：planning + null + status_change={planning→executing} → 200，三件事原子完成
- §6.3 timeline 写入顺序：手动 yaml 注入 created_at 早于已有 entry，前端不应重排（API 响应 timeline 仍按写入顺序）
- §6.4 MCP schema：用 jsonschema 校验 read_matter_index 返回，含 owner_change 也通过
- §6.6 owner 解析失败兜底：matter.owner = 不存在的 ou_xxx → 响应里 owner_display = 截断字符串、owner_avatar_url = null
- §6.7 创建时 owner_id = 自己：等价于不传，matter.owner = creator.pinyin
- §6.8 owner_change yaml key 顺序：落盘后字段顺序固定为 type → created_at → actor → from_owner → to_owner → reason → status_change?

前端：

- `OwnerChip`：unassigned 状态文案 / 占位
- `MatterRow`：owner 名字超长不撑破布局
- `TransferOwnerDialog`：reason 必填校验、与当前 owner 相同时按钮禁用、当前 status==planning 时显示"同时推进至 executing"复选框
- NewMatter classic form / guided flow：可选指定他人为 owner；不指定时 owner == 自己
- 详情页：转交成功后顶部卡片 owner 即时刷新，不需要 reload；合并迁移时 status badge 也跟着变
- 详情页 timeline：合并 entry 渲染为两条邻接视觉行（owner 行 + status 行）

### 7.2 手测（验收标准对齐）

| 验收项 | 路径 | 通过条件 |
|--------|------|---------|
| 新建默认 owner = 创建者 | NewMatter → 不指定 owner → 提交 | 详情卡片 owner = 自己 |
| 新建可指定他人 owner | NewMatter → OwnerPicker 选 X → 提交 | 详情卡片 owner = X；timeline 没有 owner_change |
| 列表展示 owner | 左侧 ThreadListPane | 看到头像+姓名，名字超长不抖布局 |
| 详情顶部卡片展示 owner | 进入任一 matter | owner 头像+姓名出现在 status 旁 |
| 详情可发起转交 | 点"转交负责人" | 弹窗出现，含 OwnerPicker + reason |
| reason 必填 | 不填 reason 直接确认 | 按钮 disabled 或前端 toast |
| 转交后 index header 更新 | 转交后刷新页 / 不刷 | 顶部 owner 即时变 |
| 转交后 timeline 新增独立事件 | 转交后看 timeline | 出现 "X 将 Owner 从 张三 → 李四 · 原因：…" 一行 |
| 事件记录完整 | 用 read_matter_index 读 | actor / from_owner / to_owner / reason / created_at 齐全 |
| owner 变更不动 status（默认） | 转交前 planning / 转交后还是 planning | ✓ |
| 一次操作转交 + 推进至 executing | TransferOwnerDialog 勾"同时推进至 executing"提交 | matter.owner 与 status 同时变；timeline 上 owner 行下方紧邻一条 status 行 |
| 非 planning→executing 的合并被拒 | executing 状态下勾"同时推进"（UI 应灰显），强行调 API | 422 `status_change_not_allowed_by_event` |
| 历史 matter "未分配" | 找一个 matter.owner 缺失 + 没跑回填的 index | 列表/详情显示"未分配" |

---

## 八、附录：原始需求摘要

> Matter 应增加 owner 字段；index header 写入；列表展示头像+姓名；详情卡片展示 + 转交入口（必填原因）；timeline 独立 owner_change 事件；owner 变更不自动改状态；开放协作模型不做权限。

完整需求文本归档在 `AI-docs/discussions/...`（占位）。

---

## 九、待批决策清单

§4.1 的设计决策已与用户确认（2026-04-29）。§六 边界值清单同步落定。剩余尚未拍板的细节只有一项：

| 决策 | 推荐 | 落点 |
|------|------|------|
| `?owner=` 查询参数语义 | 优先匹配 `matter.owner`，找不到再 fallback 文件级 owner | §4.4 |

无阻塞设计层的其他待批，转入实施计划文档（`AI-docs/plans/2026-04-29-matter-owner-plan.md`，待写）。
