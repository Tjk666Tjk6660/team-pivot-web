# 失效文档功能 · 实施方案(P1–P5)

## Context

设计方案见 `AI-docs/invalidate-self/product-design.md`(v2 评审稿,基于 dengke 001 需求 + liuyu 003 反馈)。本文是设计方案落到代码层的执行清单。

**核心定位**:失效是声明式撤回,不是隐藏机制;事件项是 timeline 上的非文件型记录(无 md 落盘,仅 index yaml)。

**职责划分**
- P1–P5 全部:本人承担(后端 + 前端 + 文档)

**参照文档**
- `AI-docs/invalidate-self/product-design.md` — 设计方案 v2
- `AI-docs/pivot-product.md` — schema 规范(实施时同步更新)
- `AI-docs/pivot-interface.md` — API 文档(实施时同步更新)
- `AI-docs/pivot-memo.md` — 实现现状

---

## 开发纪律(沿用现有约束)

### 核心变更评审门

凡涉及以下类别,必须先在 PIVOT 讨论区发起 think 对齐,dengke 确认后才能动手:

- timeline 形态变更(事件项是新增的 timeline entry 形态,本身已经过 002→004 评审,无需再过)
- 反写字段集变化(`invalidated_*` 4 字段,已过评审)
- API 路径与请求体形状(`POST /api/matters/{id}/events`,本文档新增,需 dengke 二次过审)
- writer 层约束变化
- 事件流(新 SSE 主题、字段集)

### 简洁约束

每次 commit 必须能回答:新增实体/字段为何不可复用;新增返回字段是否自解释。

### 分支策略

- 直接在 `main` 分支开发,不另开分支
- commit 风格:`feat:` / `fix:` / `chore:` 前缀,单行

---

# 后端部分

## P1 · 数据层

**目标**:把 v2 设计稿的字段集、事件项形态、反写规则、6 条校验规则落到代码层,无用户可见变化。

### 任务拆解

1. **`server/doc_types.py`** — 新增 reason 枚举
   ```python
   VALID_INVALIDATION_REASONS = frozenset({"misposted", "inaccurate"})  # 文件项 invalidated_reason
   VALID_EVENT_REASONS = frozenset({"misposted", "inaccurate", "restored"})  # 事件项 reason
   ```

2. **`server/matter_index.py`** — 事件项支持 + 反写函数
   - `_EVENT_KEY_ORDER`:事件项 canonical key 顺序常量(`creator / created_at / quote / reason / summary`)
   - `_normalize_event_item(item: dict) -> dict`:事件项 normalize(参考现有 `_normalize_item`)
   - `_normalize_item` 入口扩展:根据 `type` 字段是否存在分发到文件项 / 事件项 normalize
   - `_FILE_ITEM_INVALIDATION_KEYS`:文件项反写字段在 canonical 顺序中的位置(放在 `comments` 之前)
   - `_reverse_write_invalidation(index_data, event)`:把事件项的影响反写到目标文件项的 `invalidated_*` 4 字段
     - reason ∈ {misposted, inaccurate}:`invalidated=True`,设 `invalidated_at / invalidated_reason / invalidated_by`
     - reason == restored:`invalidated=False`,其他三个字段保留
   - `append_event(index_path, event)` 新函数:原子写入事件项 + 触发反写
     - 调用 `_atomic_write_yaml`(已有 tmp+rename 机制)

3. **`server/matter_validator.py`** — 6 条新规则
   - `_validate_event_creator_matches_target(event, index_data)`:事件项 `creator` == quote 指向文件项的 `creator`
   - `_validate_event_target_state(event, index_data)`:
     - reason ∈ invalidation reasons → 目标必须 `invalidated != True`
     - reason == restored → 目标必须 `invalidated == True`
   - `_validate_event_target_not_event(event, index_data)`:quote 必须指向有 `type` 字段的文件项,不能指向另一条事件项
   - `_validate_event_target_in_same_matter(event, index_data)`:quote 路径必须在本 matter timeline 内
   - `_validate_event_target_not_comment`:comment 不能成为失效目标(quote 路径必须是 timeline 顶层文件,不是某文件下的 comment)
     - 注:comment 在 yaml 里嵌在 `timeline[i].comments[]`,不是独立 timeline entry,quote 自然不会指向它;但需在校验里显式拒绝传入 comment-shaped 路径作为防御
   - `_validate_event_no_quote_to_invalidated_file`:其他 timeline entry 的 `quote / refer` 不能指向已失效文件(§5.3 引用阻断,实际是创建文件路径上的校验,不是事件本身)

4. **`server/recovery.py`** — `repair_partial_writes` 不需要变更
   - 失效事件无 md 文件,不会产生 `un-indexed` 状态。`_atomic_write_yaml` 已保证 yaml 写入原子。

### 测试

- `test_event_item_normalization`:事件项 canonical key 顺序固定;字节一致 roundtrip
- `test_reverse_write_invalidation`:三种 reason 各自对反写字段的影响正确
- `test_reverse_write_restoration_preserves_metadata`:恢复仅翻转 bool,不清空其他字段
- 6 条 validator 规则各 1 个 happy path + 1 个 reject path
- `test_crash_after_validation_no_partial_state`:验证写 yaml 前崩溃不留半残状态

### 交付物

`doc_types.py` / `matter_index.py` / `matter_validator.py` 改动 + 配套 pytest

### 验收

- `uv run pytest -q` 全绿
- 6 条 validator 规则 100% 分支覆盖
- timeline yaml 写→读→重写字节一致

---

## P2 · 写路径 + API

**目标**:`POST /api/matters/{id}/events` 端点上线,完整闭环失效/恢复操作。

### 任务拆解

1. **`server/publish.py`** — 新增 publish 函数
   ```python
   def publish_matter_event(
       workspace: Workspace,
       user: User,
       matter_id: str,
       target_file: str,
       reason: str,
       summary: str | None = None,
       *,
       contacts: ContactsRepo,
       notifier: Notifier,
   ) -> dict:
       """在 write_session 内:校验 → 写 index → 触发事件总线"""
   ```
   - 在 `Workspace.write_session()` 锁内执行(与现有 publish_matter_create / publish_matter_append 同形态)
   - 调用 `matter_validator.validate_event(...)` 兜底校验
   - 调用 `matter_index.append_event(...)` 写盘
   - 触发 `events.emit("matter.event_appended", ...)`
   - 触发 `notifier.notify_matter_event(...)`(P3 实现)
   - 不创建 md 文件——这是与 publish_matter_append 的关键差异

2. **`server/api/matters.py`** — 新端点
   ```
   POST /api/matters/{matter_id}/events
   Request: {
     target_file: string,                              # 必填
     reason: "misposted" | "inaccurate" | "restored",  # 必填
     summary?: string                                  # 可选
   }
   Response: {
     event: { creator, created_at, quote, reason, summary? },
     target: {
       file, invalidated, invalidated_at, invalidated_reason, invalidated_by
     }
   }
   ```
   - API 层先调 `matter_validator.validate_event_request(...)` 返回精准 422
   - 调用 `publish.publish_matter_event(...)`
   - 错误码:
     - `target_not_found` 404
     - `event_creator_mismatch` 403(creator 不是 target 文件的作者)
     - `target_already_invalidated` 409(已失效又发失效)
     - `target_not_invalidated` 409(未失效发恢复)
     - `target_is_event_item` 422
     - `target_cross_matter` 422
     - `invalid_reason` 422

3. **`server/events.py`** — 新主题
   ```python
   TOPIC_MATTER_EVENT_APPENDED = "matter.event_appended"
   ```
   - emit 触发点:`publish_matter_event` 写盘成功后
   - payload:`{matter_id, target_file, creator, created_at, reason, summary?}`

### 测试

- `test_post_event_invalidate_happy_path`:失效成功 → 返回 201 + 反写字段
- `test_post_event_restore_happy_path`:恢复成功 → 反写 invalidated=False
- `test_post_event_creator_mismatch`:非作者操作 → 403
- `test_post_event_already_invalidated`:重复失效 → 409
- `test_post_event_target_cross_matter`:跨 matter quote → 422
- `test_post_event_emit_event_appended`:成功后 events 总线收到主题
- 端到端集成:create matter → append act → invalidate act → restore act → 反写状态正确

### 交付物

`publish.py` / `api/matters.py` / `events.py` 改动 + pytest

### 验收

- `uv run pytest server/tests/test_matters_api.py -q` 全绿
- 端到端测试覆盖 happy path + 5 种错误路径
- AI-docs/pivot-interface.md 已补 `/events` 端点契约

---

## P3 · SSE + 飞书通知

**目标**:失效/恢复事件实时推送给所有打开该 matter 的客户端,并触发飞书卡片广播。

### 任务拆解

1. **`server/api/matters_events.py`** — SSE 主题映射
   - 订阅 `events.TOPIC_MATTER_EVENT_APPENDED`,转发给 SSE 客户端为 `matter.event_appended` 事件
   - SSE payload 与 events 总线 payload 一致(`{matter_id, target_file, creator, created_at, reason, summary?}`)

2. **`server/notify.py`** — 飞书卡片
   - 新增 `Notifier.notify_matter_event(matter_id, target_file, creator, reason, summary)`
     - reason ∈ invalidation:卡片标题"作者撤回了 <文件名>",正文展示理由 + 可选 summary
     - reason == restored:卡片标题"作者恢复了 <文件名>"
   - `FeishuNotifier` 实现:复用 `_card_shell` + `_broadcast`(同 publish_matter_append 的级别)
   - 卡片按钮链接到 `/m/<matter_id>`(走 `_matter_url`)
   - 老 thread 通道不受影响(本功能仅 matter 路径触发)

### 测试

- `test_sse_event_appended`:模拟客户端订阅,publish 后能收到正确 SSE payload
- `test_notify_matter_event_invalidation`:mock notifier 验证卡片字段
- `test_notify_matter_event_restoration`:mock notifier 验证卡片字段
- `test_notify_matter_event_no_op_notifier`:NoOpNotifier 不报错

### 交付物

`api/matters_events.py` / `notify.py` 改动 + pytest

### 验收

- SSE 推送测试通过
- 卡片人眼检查在飞书群正确渲染(本地灰度 1 次)

---

# 前端部分

## P4 · 前端时间线渲染 + 操作 UI

**目标**:用户能在 matter 详情页对自己的文件触发失效/恢复;时间线正确渲染事件项与已失效徽标。

### 任务拆解

1. **`web/src/api.ts`** — 新增 fetch wrapper
   ```typescript
   export async function postMatterEvent(matterId: string, body: {
     target_file: string;
     reason: "misposted" | "inaccurate" | "restored";
     summary?: string;
   }): Promise<{ event: ...; target: ... }>
   ```

2. **`web/src/events/MatterEventsProvider.tsx`** — 处理新 SSE 主题
   - 收到 `matter.event_appended`:
     - 把事件项追加到本地 timeline(按 `created_at` 排序插入)
     - 找到 `file == target_file` 的文件项,立即更新 `invalidated / invalidated_at / invalidated_reason / invalidated_by` 4 字段

3. **`web/src/pages/MatterDetailPane.tsx`** — timeline 渲染分支
   - 读 timeline,对每条 entry 判断:
     - 有 `type` → 文件项,走现有渲染
     - 无 `type` 但有 `reason` → 事件项,渲染为轻量横条卡(`⊘ <creator> 于 <时间> 失效了 <target>:<reason>`,或 `↺ <creator> 于 <时间> 恢复了 <target>`)
   - 文件项渲染加 `invalidated` 徽标分支:有 `invalidated: true` → 顶部标"已失效(<reason 中文>)"徽标;原文仍展示

4. **`web/src/components/matter/`** — 新 UI 组件
   - `InvalidateActionMenu.tsx`:文件卡上的"失效"/"恢复"操作菜单(仅作者本人可见;通过 `current_user.pinyin === item.creator` 判断)
   - `InvalidateDialog.tsx`:弹窗内 radio 选 reason(misposted / inaccurate 二选一)+ 可选 summary 输入框 + 确认按钮
   - `RestoreDialog.tsx`(可与上合并):恢复无需选 reason,仅可选 summary 输入框
   - `InvalidatedBadge.tsx`:文件卡顶部的"已失效(理由)"徽标

### 不需要做的(明确写出)

- ❌ 不需要 `is_visible_to` 客户端过滤(失效不影响可见性)
- ❌ 不需要修改 AI 面板逻辑(AI 工具直接读到带 invalidated 元数据的内容)
- ❌ 不需要 draft 层(失效操作不走草稿流程)

### 测试

- 手动 UI 自检:
  - 失效后徽标正确显示,原文可展开
  - 非作者用户不看到操作菜单
  - 已失效文件不能被新文档 `quote / refer`(后端拒绝,前端要展示错误)
  - AI 面板能读到已失效文件原文
  - SSE 推送下徽标实时更新

---

# 文档同步(P5)

## P5 · AI-docs 同步

**目标**:per CLAUDE.md 强约束,schema 与 API 变更必须在同次 commit 同步更新规范文档。

### 任务拆解

1. **`AI-docs/pivot-product.md`** — schema 规范
   - §八 timeline schema:补"事件项"形态说明 + 文件项反写字段集
   - 新增"§九.X 失效/恢复事件"小节,描述语义、reason 枚举、反写规则
   - 强调失效不影响 matter 状态机(§三 / §五状态矩阵不动)

2. **`AI-docs/pivot-interface.md`** — API 文档
   - 新增 `POST /api/matters/{matter_id}/events` 完整契约
   - 请求体、响应体、所有错误码
   - SSE 新主题 `matter.event_appended` 字段

### 验收

- 文档与代码在同一次 commit 提交
- 任意外部 client(VS Code 插件、MCP)按 pivot-interface.md 即可调通新端点

---

# 实施顺序与依赖

```
P1 数据层
  ↓(数据结构稳定)
P2 写路径 + API
  ↓(API 稳定可调)
P3 SSE + 通知
  ↓
P4 前端
  ↓
P5 文档同步
```

全程串行(单人开发)。P5 文档同步建议跟随 P1 / P2 的 commit 同步落地(schema + API 文档与代码一起进 git)。

---

# 风险与缓解

| 风险 | 缓解 |
|---|---|
| 事件项无 md 文件,git diff 看起来"只有 yaml 变更",作者 commit 不直观 | commit message 模板化:`feat(invalidate): <reason> <target_file>` 让 git log 自解释 |
| 反写函数与 timeline append 不同步导致状态不一致 | 反写写在 `append_event` 函数内部,与 yaml 写入是同一原子操作;不暴露独立反写 API |
| 已失效文件被新文档 quote 引用的检查放在哪里 | 在文件项创建路径(publish_matter_create / publish_matter_append)的校验里加,而不是事件路径——这是 §5.3 的实现位置 |
| SSE payload 与 timeline yaml 字段不一致 | payload 字段集与 yaml event item 字段一一对应,通过同一 dataclass 序列化,源头一致 |
| 前端 SSE 状态更新逻辑出错导致徽标不刷 | 端到端测试覆盖 SSE 流;前端组件 mock SSE payload 单测 |

---

# 验收门(总)

- [ ] P1:数据层单测 + validator 6 规则全绿
- [ ] P2:`POST /events` 端到端 + 6 错误码全覆盖
- [ ] P3:SSE 推送 + 飞书卡片人眼检
- [ ] P4:前端 UI 自检通过(失效徽标、操作菜单、SSE 实时更新)
- [ ] P5:`pivot-product.md` + `pivot-interface.md` 已同步
- [ ] 灰度环境端到端跑一遍:创建 matter → 发 act → 失效 → 恢复 → 失效 → quote 已失效文件被拒绝
