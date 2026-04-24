# Pivot Matter 模型迁移 · 开发计划（P1–P4）

## Context

014 号回复中的实施路径已对齐，现进入编码阶段。

**职责划分**
- 后端 P1 / P2 / P4：本人承担
- 前端 P3：同事承担
- P5：暂不制定，等 P1–P4 与 AI-monitor 独立设计就绪后再排

**参照文档**
- `AI-docs/pivot-product.md`
- `AI-docs/pivot-interface.md`
- `AI-docs/pivot-memo.md`

---

## 开发纪律（强制约束）

### 核心变更评审门

凡涉及以下类别，必须先在 PIVOT 讨论区发起 `think` 文件对齐，邓柯确认后才能动手；未预审不得合入：

- `matter_index` on-disk schema 字段集
- 6 态状态机迁移表、`status × type` 允许矩阵
- writer 层约束（哪类文件触发哪类 status_change）
- Matter API 对外形状（路径、请求体、响应体、错误码）
- `write_session` 锁行为 / 原子 tmp+rename / `workspace.recover()` 顺序
- 事件流（topic、字段集）与 AI-monitor 埋点契约
- 前端 `/t/:category/:slug` 路由语义的变更、新旧 pane 的切换策略

### 非核心偏离记录（changelog）

- 非核心实现细节完全按产品设计文档实现的不记。
- 若因实战情况偏离了产品设计文档（例如字段命名、排列顺序、次级约束的放宽/收紧），必须在 `AI-docs/coding-test-plan/deviations.md` 中登记：
  ```
  - <阶段-任务> | 原文档要求: ... | 实际实现: ... | 原因: ...
  ```

### 简洁约束（奥卡姆）

每个 PR 必须回答：新增实体/字段的不可复用理由；新增返回字段的自解释性。

### 一致性约束

接口形状严格对齐 `pivot-interface.md` 草案；不出现反直觉或 trick 设计。

### 分支与实例

- 开发分支：`matter-migration`（命名待与同事对齐；前端从后端 P2 合入点切分支）
- 独立部署 Pivot 实例：用于端到端验证
- 主干仅接收通过评审门的 PR
- commit 风格遵守 memo §11：`feat:` / `fix:` / `chore:` 前缀，简洁一句话

---

# 后端部分（本人承担）

## P1 · 词表与 `matter_index` 模块

**目标**：6 态状态机、5 类文档类型、§八 示例的 INDEX 读写落地；无用户可见变化。

### 任务拆解

1. `server/matter_status.py`：6 态枚举、`ALLOWED_TRANSITIONS`、`TRIGGER_TYPES_BY_TRANSITION`（哪类文件可触发哪类迁移）、`REASON_MIN_LEN`
2. `server/doc_types.py`：5 类文档枚举、`ALLOWED_TYPES_BY_STATUS`（§五）
3. `server/matter_index.py`：
   - dataclass：`Matter` / `FileItem` / `Comment` / `Verification`（字段集按 §八 示例）
   - `read_matter_index` / `write_matter_index`（原子 tmp+rename，key 顺序锁定）
   - `create_matter_index` / `append_file_item` / `append_comment` / `apply_status_change`
   - writer 层嵌入 status_machine + doc_types 约束
4. 单元测试：状态机全量迁移、违规拒绝、`status × type` 矩阵、roundtrip 字节一致、crash 注入

### 预审事项（核心）— 已决

- **schema**：`matter_index` on-disk 字段集完全采用 `pivot-product.md §八` 示例，不加不减
- **status × type 矩阵**：按 `pivot-interface.md` "最小服务端校验建议"字面照搬；两处软约束放宽：
  - `executing + result` 的"准备结束时才允许" → 放宽为"executing 状态下随时允许"
  - `reviewed` 的"原则上不再新增" → 收紧为"严格禁"
  - 以上两处放宽已记入 `AI-docs/coding-test-plan/deviations.md`
- **触发表**：状态迁移触发规则作为第二张表并列嵌入 writer 约束（think 触发 paused 进出；act 可带 planning→executing；result 触发 finished/cancelled；insight 触发 reviewed；verify 无触发权）
- **校验架构**：独立 `server/matter_validator.py` 纯函数层 + writer 内部兜底"双闸"。API 层先过 validator 以返回精准 422，writer 开头再调一次 validator 防绕过

### 交付物

`matter_status.py` / `doc_types.py` / `matter_validator.py` / `matter_index.py` + 配套 pytest

### 验收

- `uv run pytest -q` 全绿
- 状态机与允许矩阵单测 100% 分支覆盖
- 写→读→重写 YAML 字节一致

---

## P2 · Matter API

**目标**：按 `pivot-interface.md` 草案实现 Matter API，打通服务端最小闭环；埋下 AI-monitor 事件流。

### 任务拆解

1. 新增 `server/api/matters.py`，挂载到 `server/app.py`：
   - `GET /api/matters`（`status` / `owner` / `q`）
   - `GET /api/matters/{matter_id}`
   - `POST /api/matters`（`title` + `initial_file{type, summary, body, owner?, comments?}`）
   - `POST /api/matters/{matter_id}/files`（通用字段 + 类型专属体：think / act / verify / result / insight）
   - `POST /api/matters/{matter_id}/result`（便捷入口）
2. `server/publish.py` 新增 matter 分支；旧 `publish_proposal` / `publish_reply` 保留（Threads 旧接口仍在用）
3. AI-monitor 埋点：
   - `server/events.py`（结构化日志 + 进程内 pub/sub）：在 `create_matter` / `append_file_item` / `append_comment` / `apply_status_change` / `apply_result` 处 emit
   - `matter_index.snapshot(matter_id)` 只读快照 API
4. 服务端最小校验按 interface.md "最小服务端校验建议"
5. 契约测试：每接口 happy path + 违规路径；端到端 create → act → verify → result

### 预审事项（核心）

- `matter_id` 语义：`slug` / `category/slug` / 独立 id（与现 `discussions/<category>/<slug>/` 目录如何对应）
- `category` 在 matter 模型下的定位：仅分组标签 or 完全脱钩
- Threads 旧 API 下线节奏（P3 上线后保留多久）
- 事件流 topic 命名、字段集
- 错误码：`status_not_allowed` / `type_not_allowed` / `verifications_required` / `target_not_found` 等

### 交付物

- `server/api/matters.py` + 路由挂载
- `server/publish.py` matter 分支
- `server/events.py` + `snapshot` API
- 契约测试 + 端到端冒烟

### 验收

- interface.md 草案接口全部打通
- `uv run pytest -q` 全绿
- 手动 curl 跑通：创建 matter → append act → append verify → result
- 旧 `/api/threads/*` 回归不受影响

---

## P4 · verify.target 跨时间线白名单校验

**目标**：补齐 `verify.verifications[].target` 的跨时间线存在性与类型校验；P1/P2 已做完的 creator/owner、insight→reviewed 触发、全生命周期等不再重复。

### 范围对齐（与 P1/P2 去重）

- P1/P2 已完成、不在 P4 重做：
  - `creator/owner` 严格化（`_build_timeline_item` / `_body_to_item_preview` 已落）
  - `act.owner` 允许非 creator
  - `verifications[].judgement ∈ {passed, failed, cancelled}`（validator 已校验）
  - `insight` 携带 `status_change: finished|cancelled → reviewed` 时触发（trigger 表 + `apply_status_change` 已支持）
  - 全生命周期 `planning → executing → verify → result → reviewed` 端到端（`test_matters_api.py::test_full_lifecycle_planning_to_reviewed`）
- 从 P4 移除、交给 AI-monitor 自行设计：
  - `ai_candidate_*` 元数据通路（无权威文档依据，由 AI-monitor 设计时自定契约）
  - `reviewed` 独立事件 topic（`matter.status_changed` 已含 `to` 字段，消费者自行 filter）

### 任务拆解（本次实做）

1. `verify.verifications[].target` 白名单校验 —— 按 `pivot-product.md §九.4`（`verify` 验证和评价 `act`；每个 `act` 给出判断结果）推演的规则：
   - target 必须指向同 matter timeline 中已存在且 `type=act` 的文件；
   - 或 target 在当前 item 的 `refer[]` 里（视为跨 matter 白名单，纯函数不做跨文件类型验证，信任客户端声明——这条 fallback 是本阶段自行决策，已登记 `deviations.md`）。
   - 新增错误码：`verification_target_not_found` / `verification_target_not_act`。
2. 扩 `matter_validator.validate_append`：verify 走进类型专属分支时执行上面的白名单检查。
3. 测试补齐：
   - 本 matter 内 act 通过；
   - 本 matter 内非 act（think / verify / result / insight）拒绝，错误码 `verification_target_not_act`；
   - 不在 timeline 也不在 refer 拒绝，错误码 `verification_target_not_found`；
   - 不在 timeline 但在 item.refer 通过（跨 matter 白名单）。

### 预审事项（核心）

- 无。校验规则按 `pivot-product.md §九.4` 推演（"verify 验证 act" + "target 限定为 act"），跨 matter refer[] 白名单作为自行决策记入 `deviations.md`，不属核心评审门。

### 交付物

- `server/matter_validator.py` 扩展
- 对应 pytest 用例（新增 4 类）

### 验收

- `uv run pytest -q` 全绿（P4 新增用例 + 原有 311 项不退化）
- 新增 2 个错误码在 API 路径上可复现（由 API 层 422 返回）

---

## P4.5 · Threads → Matters 迁移缝合

**目标**：P1/P2/P4 已搭出 matter 基础设施，但 thread 模型原有的未读 / 收藏 / 通知 / 名字解析 / AI 会话这几块还没接到 matter 上。P4.5 把这些"已有能力"全部铺到 matter，保证前端 P3 切到 matter 之后不丢功能。

### 范围（7 项，全部不改 DB schema）

1. **A. matter 响应名字解析**：`GET /api/matters` / `GET /api/matters/{id}` 加 `creator_display / owner_display / *_avatar_url`；`comments[].author_display`；`mentions` 的 display 名数组。复用 `resolve_id / resolve_avatar_url / resolve_text` 的 `users → contacts → open_id` 回退链。
2. **B. matter 未读 + inbox**：**全部 timeline item 计未读**（决策：前端简单优先，不按 type 区分）。`server/inbox.py` 扩展扫 matter index；`GET /api/inbox` 合并 thread + matter；`GET /api/matters` 每项加 `unread_count`；`POST /api/matters/{id}/read` 复用 `read_state` 表（thread_key 列存 `category/slug`，matter_id 就是 slug）。
3. **C. matter 收藏**：`GET /api/matters` 每项加 `favorite`；`POST /api/matters/{id}/favorite` toggle；复用 `favorites` 表。
4. **D. `GET /api/categories` 合并统计**：按 category 聚合时同时含 thread + matter（matter 的 category 从 `timeline[0].file` 解出）。
5. **E. AI 接口 matter 化**：新增 `GET/PUT/DELETE /api/ai/matters/{id}/conversation` + `POST /api/ai/matters/{id}/chat`。`server/ai/context.py` 增加 `build_context_from_matter(matter_id, quote_target, refer[])` 分支。`ai_conversations` 表复用，thread_key 列存 `category/slug`。旧 `/api/ai/threads/*` 路由暂留（P5 再下线）。
6. **G. 通知调用点补齐**（复用现有 4 个 notifier 方法，不新增）：
   - `publish_matter_append` 调 `notify_new_reply`（语义 "XX 回复了某 matter" 仍然自然）
   - matter 文件触发 `status_change` 时调 `notify_status_change`
   - `publish_matter_comment` 有 mentions 时调 `notify_standalone_mention`
   - `publish_matter_create` 已调 `notify_new_thread`（不动）
7. **H. 集成测试扩充**：favorite toggle / read mark / unread count / AI matter chat / NoOpNotifier 侦测调用等新 case，随后全量跑一遍真后端。

### 决策记录

- 未读规则：**全部 timeline item 计未读**（对前端实现简单；不按 type 区分）
- 通知方法：**不新增，全部复用现有 4 个**（`notify_new_thread / notify_new_reply / notify_status_change / notify_standalone_mention`）；卡片文案可按 matter 语境微调但方法签名不动
- SQLite 表（`favorites / read_state / ai_conversations`）：**不动 schema**；thread_key 列存 `category/slug`（matter_id 就是 slug，键自然唯一）
- 名字解析字段命名：沿用老 thread 的 `<field>_display` / `<field>_avatar_url` 并列风格
- **matter 草稿**（P4.6 最终口径）：drafts 表新增一列 `matter_payload_json TEXT`（幂等 `ALTER TABLE ADD COLUMN`，不 rebuild），用于承载 matter 专属结构化字段（`doc_type / summary / owner / quote / refer / verifications / outcome / status_change`）；`type` 列保持 `proposal | reply` 不动，matter 首篇 = `proposal`、matter 追加 = `reply`。前端**复用** main 分支原有规范：`useDraftAutosave` + `PATCH /api/drafts/{id}` autosave → `saveNow()` → `publishDraft(id)` 调 `POST /api/drafts/{id}/publish`。`publish_draft` 只认 `matter_payload` 非空的草稿——缺了直接 `400 matter_payload_required`，历史 legacy 草稿由用户 `PATCH` 补全后重试。老 `publish_proposal / publish_reply` 分发分支已从 `publish_draft` 移除；想走老 thread 发布的仍可用 `POST /api/threads` 直发（不经草稿，P5 清理范围）。

### 从 P4.5 移除、后续独立立项

- **matter 真 recovery**：MD→INDEX 重建，两阶段写已大幅缩窗，接受运维层手工处理
- **事件流前端消费**：AI-monitor 接入阶段统一做

### 验收

- 7 项全部落地，无 DB schema 变更
- 集成测试真后端全过
- 旧 `/api/threads/*` 全部接口依然可用、行为不变
- `uv run pytest -q` 全绿

---

## P4.6 · matter 草稿接入 autosave + publishDraft 规范（已实施）

**目标**：把 matter 发布拉回 main 分支原有的 `useDraftAutosave → publishDraft` 规范路径，复用 `/api/drafts/*` 这套既有通道，不重复造轮子。drafts 表按最小侵入扩一列承载 matter 结构化字段。

### 实施完成的改动

**后端（本人）**

- `server/db.py::_migrate`：幂等新增列
  ```python
  if "matter_payload_json" not in cols:
      conn.execute("ALTER TABLE drafts ADD COLUMN matter_payload_json TEXT")
  ```
  **单条 ALTER，无表 rebuild**。老 drafts 行该列保持 `NULL`。`type` 的 `CHECK(proposal|reply)` 不动。
- `server/drafts.py`：`Draft` dataclass 增加 `matter_payload_json: str | None`；`DraftRepo.create / update / _row` SQL 读写新列。
- `server/api/drafts.py`：
  - `CreateDraftBody` / `UpdateDraftBody` 新增可选字段 `matter_payload: dict | None`
  - `_to_dict` 输出 `matter_payload`
  - **`publish_draft` 契约收紧**：
    - `matter_payload_json IS NULL` → `400 {code: "matter_payload_required"}`（**不再** fallback 到 `publish_proposal / publish_reply`）
    - `matter_payload` 非空 + `type=proposal` → `publish_matter_create`（matter 首篇；需 category + title）
    - `matter_payload` 非空 + `type=reply` → `publish_matter_append`（matter 追加；`thread_key` 最后一段作 `matter_id`）
  - 新增 `_publish_matter_from_draft` 辅助函数，包含 validator preflight（matter_payload 通过校验才进写路径）

**测试（单元 + 集成）**

- `server/tests/test_drafts_api.py`：重写 `test_publish_without_matter_payload_rejected`；新增 `test_matter_draft_crud_roundtrip / test_matter_draft_publish_creates_matter / test_matter_draft_publish_appends_file / test_matter_draft_publish_requires_doc_type / test_matter_draft_publish_requires_summary / test_matter_draft_publish_validator_rejects_bad_type / test_legacy_draft_rejected_without_matter_payload / test_legacy_draft_upgradable_via_patch`
- `server/tests/run_matter_integration.py`：新增 `case_f1_matter_via_drafts_publish`——真后端完整走 `POST /api/drafts → PATCH → POST /api/drafts/{id}/publish → GET /api/matters/{id}`，并校验追加路径

### 前端接口变化清单（P3 同事对接）

对照 `main` 分支 `NewThread.tsx` / `ThreadDetailPane.tsx` 的规范流程，matter UI 应当对齐。下面是后端已经落地的契约增量：

| 接口 | 变化 | 前端对应改动 |
|---|---|---|
| `POST /api/drafts` | 请求体可选新增 `matter_payload: object` | `createDraft()` wrapper 支持传 `matter_payload` |
| `PATCH /api/drafts/{id}` | 请求体可选新增 `matter_payload: object` | `updateDraft()` wrapper 支持传 `matter_payload`；`useDraftAutosave` 的 `payload()` 回调返回值里带上它 |
| `GET /api/drafts` / `GET /api/drafts/{id}` | 响应体新增字段 `matter_payload: object \| null`（老 thread 草稿恒为 null） | `Draft` 类型补字段 |
| `POST /api/drafts/{id}/publish` | **契约收紧**：`matter_payload` 为空直接 `400 {detail: {code: "matter_payload_required", message: ...}}`；非空则分发到 matter 路径 | 前端发起发布前确保 `saveNow()` 已落 matter_payload；收到 `matter_payload_required` 时提示用户"补全 matter 字段" |
| `POST /api/drafts/{id}/publish` 响应体 | matter 分支下返回 `{published: {matter_id, category, slug, filename, file, matter, item}, draft_id}`；老 thread 分支返回 `{published: {category, slug, filename}, draft_id}`。**目前 `publish_draft` 只会走 matter 分支，老响应形态仅出现在 `POST /api/threads` 直发上** | 跳转逻辑改用 `r.published.matter_id` 进 matter 详情页路径 |

**`matter_payload` 字段形态**（前端组装，JSON）：

```json
{
  "doc_type": "think|act|verify|result|insight",
  "summary": "...",
  "owner": "...",
  "quote": "discussions/<cat>/<slug>/<filename>",
  "refer": ["...", "..."],
  "verifications": [
    {"target": "...", "judgement": "passed|failed|cancelled", "comment": "..."}
  ],
  "outcome": "finished|cancelled",
  "status_change": {"from": "executing", "to": "finished"}
}
```

- `doc_type + summary` 必填；其余按 type 语义选填
- `verifications` 仅 verify 类型需要
- `outcome + status_change` 仅 result 类型的完整发布需要
- `quote / refer` 任意 type 都可选
- `owner` 不传默认 = creator（当前用户 pinyin）

### 前端最小改造点（P3 同事负责）

`web/src/api.ts`：
- `createDraft`、`updateDraft` 的 body 类型加可选 `matter_payload?: Record<string, unknown>`
- `Draft` 类型加 `matter_payload: Record<string, unknown> | null`
- `publishDraft` 响应类型：matter 场景下包含 `matter_id / file / matter / item`

`web/src/hooks/useDraftAutosave.ts`：
- `payload()` 回调签名可返回包含 `matter_payload` 字段的对象；现有 `updateDraft` 参数接收即可

`web/src/pages/NewMatter.tsx` 按 `main:NewThread.tsx:80-130` 的模板改写：
- 表单状态 → `useDraftAutosave({ type: "proposal", payload: () => ({ title, category, body_md, matter_payload: { doc_type, summary, owner } }) })`
- `submit()` 用 `await saveNow()` → `await publishDraft(id)` → `navigate(/m/${r.published.matter_id})`

`web/src/pages/MatterDetailPane.tsx` 按 `main:ThreadDetailPane.tsx:1168-1190` 模板：
- 追加文件表单 → `useDraftAutosave({ type: "reply", payload: () => ({ thread_key: matter_id, body_md, matter_payload: { doc_type, summary, quote, refer, verifications, outcome, status_change } }) })`

### 验收

- `uv run pytest -q` 329 passed + 1 Windows parked
- 集成真后端：18 case + MD index_state sweep 全过（含 `case_f1_matter_via_drafts_publish`）
- 老 thread 直发路径 `POST /api/threads` 不动，现有回归测试绿
- `POST /api/drafts/{id}/publish` 在无 `matter_payload` 时返回 `400 matter_payload_required`（前端按此提示用户补全）

---

# 前端部分（同事承担）

## P3 · Matter 详情页（前端主导）

**目标**：右栏从帖子列表切到时间线 + 文件卡片；最小闭环 A（paused 进出）与 B（planning → executing → finished/cancelled）UI 可完整驱动。

### 前置条件

- P2 合入主干，`/api/matters/*` 可 curl 连通
- `pivot-interface.md` 作为唯一契约来源

### 任务拆解

1. **API wrapper**：`web/src/api.ts` 新增 matter fetch 封装（list / detail / create / append file / result）
2. **页面替换**：`web/src/pages/MatterDetailPane.tsx` 替代 `ThreadDetailPane.tsx`，接 `/api/matters/{matter_id}`
3. **TimelineView 组件**：`web/src/components/TimelineView.tsx`
   - 顶部时间轴（按 created_at 排列文件节点），支持点击跳转
   - 下方文件流（按时间顺序展开的文件卡片）
4. **FileCard 组件**：`web/src/components/FileCard.tsx`
   - 展示：type badge / summary / creator / owner / quote / refer / verifications / comments / status_change
   - 折叠：默认 208px，点击展开全文（沿用 ThreadDetailPane 折叠体验）
   - 三入口按钮："新增 think / act / verify"，点击后自动把当前卡片文件填入新表单的 `quote`
5. **Result 生成入口**：`web/src/components/ResultConfirmDialog.tsx`
   - 页面顶部靠近时间轴，独立于文件卡片
   - 点击弹确认：明示将结束 matter 为 finished / cancelled
   - 调 `POST /api/matters/{id}/result`
6. **状态徽章与控制**：
   - `web/src/components/StatusBadge.tsx` 按 6 态重写，配置化（颜色 / 文案）
   - `web/src/components/StatusControl.tsx` 下线"裸状态切换"入口；状态变化必须通过新建对应类型文件触发（think → paused；result → finished/cancelled；insight → reviewed）
7. **创建流程**：`web/src/pages/NewThread.tsx` → `NewMatter.tsx` 或改造
   - 支持首项类型选择 `think` 或 `act`（默认 `think`）
   - 首项允许无 `quote`
8. **Dashboard context**：`web/src/pages/Dashboard.tsx`
   - `aiThreads` → `aiMatters` 等类型重命名
   - Outlet context 改名（Matter / MatterDetail）
9. **路由**：`web/src/App.tsx`
   - 新旧 pane 切换策略需预审（feature flag 渐进 vs 硬切换）
   - 是否把 `/t/:category/:slug` 改成 `/m/:matter_id` 需预审
10. **侧栏适配**：`web/src/components/ThreadListPane.tsx` 读 matter 字段

### AI-monitor UI 占位

Phase 3 只做占位，Phase 5 才升级为实渲染。位置：

- 文件卡片内："AI 摘要候选" 槽（summary 旁）、"AI 建议" 槽（卡片底部）
- 页面顶部："AI 观察 / 巡视" 条（时间轴上方）、"AI 下一步建议" 条
- 占位只渲染空 placeholder，不绑任何数据

### 交互细节

- `quote` 自动填充：用户点卡片 "新增 think/act/verify" → 新表单预填 `quote = 当前文件路径`
- `refer` 多选上限 4（沿用 AIPane 现有引用规则，前端自校验）
- verify 表单：从本 matter 内选择 `act` 多选 + 逐条 judgement（passed/failed/cancelled）+ comment
- insight 表单：可勾选"同时推进到 reviewed"
- 卡片默认折叠 208px，点击展开（沿用 ThreadDetailPane 体验）
- 未读计数：以后端返回为准；`think / act / verify / result / insight` 均记未读，comment / mention 不记

### 预审事项（核心）

- 新旧 pane 切换策略（feature flag vs 硬切换）
- 路由语义是否变更（`/t/...` vs `/m/...`）
- "新增"按钮与"生成 Result"按钮的状态感知（在哪些 matter 状态下禁用哪些入口）
- AI 槽位 placeholder 视觉形态（占位但不喧宾夺主）

### 交付物

- `MatterDetailPane` / `TimelineView` / `FileCard` / `ResultConfirmDialog`
- `StatusBadge` / `StatusControl` 重写
- `NewMatter` / Dashboard context 改名
- `api.ts` matter wrappers

### 验收

- `cd web && npm run build` 通过
- 本地 `npm run dev` + 后端独立实例联调跑通最小闭环 A、B
- 视觉 / 交互符合 product doc §十三 "Matter 详情页方向"
- 裸状态切换入口已完全下线

---

# 共用部分

## P5 · 暂不制定

等 P1–P4 推进 + AI-monitor 独立设计落地后再排。

## 测试策略（贯穿 P1–P4）

- 单元：每个新模块独立覆盖；状态机与允许矩阵 100% 分支
- 契约：Matter API 每接口 happy + 违规
- 端到端：脚本化跑完整 matter 生命周期（P4 结束时可用）
- 回归：`/api/threads/*` 旧测试保持全绿
- crash 注入：INDEX 写入中断恢复
- 前端：`npm run build` + 联调冒烟

## 附录 · 上线前一次性数据迁移

`scripts/migrate_index_schema.py`：

- 读全部 `index/*.index.yaml`，按 §八 示例重写
- 存量 discussion 归为 `current_status: planning` 的 matter
- `creator / owner / type / summary` 用最小合理默认
- 单次 git commit，committer 维持 `team-pivot-web`
- 运行时机：独立实例先验证，主实例上线切换前运行
- 完成后系统只认新 shape
