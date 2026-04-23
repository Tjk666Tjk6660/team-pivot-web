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

### 预审事项（核心）

- `matter_index` 的 on-disk 字段集：完全采用 §八 示例，不加不减
- `status × type` 允许矩阵：对齐 interface.md "最小服务端校验建议"
- writer 层约束嵌入方式：append 时内联校验 vs 独立 validator 层

### 交付物

`matter_status.py` / `doc_types.py` / `matter_index.py` + 配套 pytest

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

## P4 · creator/owner + verify/insight/reviewed 完善

**目标**：责任字段严格化；verify / insight 后端闭环；`reviewed` 可达；AI 候选写入通路就绪。

### 任务拆解

1. creator/owner 严格化
   - writer：`creator` = 当前用户 pinyin；`owner` = 请求体值，未传默认 creator；`act` 允许 owner ≠ creator
   - 名称解析沿用 `users → contacts → open_id` 回退链
2. verify 补齐
   - `verifications[].target` 必须指向本 matter 内已存在且 `type=act` 的文件
   - `judgement ∈ {passed, failed, cancelled}`
3. insight → reviewed
   - 仅 `insight` 可触发 `finished|cancelled → reviewed`
   - 前置：matter 必须在 finished 或 cancelled
4. AI 候选字段通路
   - writer 接受可选 `ai_candidate_*` 元数据（summary / quote / refer / verifications.comment / status_change）
   - 事件流记录采纳 / 丢弃
5. `reviewed` 终态事件：独立 topic，供 AI-monitor 停止巡视
6. 测试：owner 分叉、verify target 非法拒绝、insight 非终态拒绝、AI 候选采纳/丢弃两路径

### 预审事项（核心）

- `ai_candidate_*` 元数据 shape 与落点（frontmatter / INDEX / 独立侧表）
- `reviewed` 入口：`insight` 自动触发 vs 用户显式确认
- `verify.target` 校验范围：仅本 matter 内，还是允许跨 matter

### 交付物

- writer 层校验强化
- AI 候选字段通路 + 采纳事件
- reviewed 终态事件

### 验收

- `uv run pytest -q` 全绿
- 端到端跑完整生命周期：`planning → act 触发 executing → verify → result 触发 finished → insight 触发 reviewed`
- AI 候选采纳/丢弃在事件流中可观察

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
