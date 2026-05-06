# 员工评价体系 — 落地实施 Plan

> 基于 Pivot matter「需求：员工评价体系需求与设计」timeline 001 / 003 / 005 / 007 与当前实现差距整理

---

## 更新记录

- **2026-05-06 v1**：初版 plan，按 001 / 003 / 005 拉差距分两阶段
- **2026-05-06 v2**：消化 006 / 007（lishuai / liuyu）反馈
  - Phase 1 已实现并合入（commit `d96635f`），所有 task ✅
  - 按 007 §2 建议，**annotation 数据模型拆分剥离到独立 matter**；本 matter 的评分模块降级为该模型的**消费方**——Phase 2 中 §2.2（数据模型拆分）和 §2.6（前端 annotation 创建入口）从范围内移出
  - 按 007 §1 补 Phase 2 三条遗漏：
    - attribution_basis enum 加 `verify_outcome`（覆盖 005 §4 表里"verify failed → 被验文件作者交付质量"的隐式归因）
    - 把 005 §4 第 2 条"长期 @ 不回 → 协作贡献负向"显式编入 prompt 规则
    - schema 层显式标注哪些字段是"用户原始输入"、哪些是"AI 派生解释"（dengke 003 §4 强调的边界）

---

## 总体策略

**两阶段落地，不一次性切到 360 模型。**

第 1 阶段：在现有 v0.3 owner-only 框架内补齐 005 提出的归因细则（仅改 prompt 与 schema）。

第 2 阶段：产品架构改动（mention/annotation 拆分 + 多 subject 评分），需先与产品方对齐再启动。

---

## 当前差距汇总

| # | 议题 | 需求最新版（003 + 005） | 当前实现 | 严重度 |
|---|---|---|---|---|
| 1 | **评分对象** | 任何人对 think/act 文件做评价；AI 按"文件作者 / 文本点名 / @ 谁"做归因 | **硬约束** subject = matter.owner，schema 拒收其他 subject | ⚠️⚠️⚠️ 阻塞 |
| 2 | **评分粒度** | 一个 matter 可以有多人多行评分 | `ScoringOutput.scores` `max_length=1` | ⚠️⚠️⚠️ |
| 3 | **自我评价过滤** | 评价者 == 文件作者 → 跳过 | 无任何过滤代码；prompt 里也没规则 | ⚠️⚠️ |
| 4 | **明确点名归因** | 文本明确指出 / `@`了别人 → 归被点名者 | prompt 里没有这条规则；schema 也不校验 | ⚠️⚠️ |
| 5 | **owner_change 原因归原 owner** | reason 含工作质量评价 → 归原 owner；纯中性说明 → 不入链 | prompt 提到"被 owner_change 转走是负向证据"但归因依然 = 当前 owner | ⚠️⚠️ |
| 6 | **评价范围** | 仅 think / act 可被评价；verify 是终点（result / insight 不再产生新评价） | 整条 timeline 全喂给 AI，无类型过滤 | ⚠️ |
| 7 | **mention / annotation 拆分** | 003 建议把 `comments` 拆成 `mention`（提醒）+ `annotation`（评价） | 数据模型仍用 `comments[]` 一锅端 | ⚠️⚠️（架构层） |
| 8 | **隐式评价（动作）** | verify failed → 被 verify 文件作者；长期 `@` 不回 → 被 `@` 的人 | 因为 subject 锁 owner，verify failed 永远归 owner | ⚠️⚠️ |

已对齐项（无需改动）：annotation 不让用户填 weight/rating（admin 配 commenter weights）、仅 finished 触发评分、admin-only 可见、五维度 + 权重、双层证据模型 + P1-P3、高权重发言人加权。

---

## Phase 1：归因细则对齐（低风险）✅ 已完成

> **状态：** 已实现并合入 `feat/user-management` 分支，commit `d96635f`。
> 单元测试 + E2E 全绿（test_scoring_schema / test_scoring_prompt / test_e2e_scoring）。

**目标：** 让现有 owner-only 评分在归因判断上符合 005 的规则——自我评价不入链、文本明确点名优先、owner_change reason 解析、评价范围限制 think/act。

**约束：** 不动数据模型，不动"一 matter 一行评分"约束。

### Task 1.1：扩 prompt 系统提示 ✅

**File:** [server/scoring/prompt.py](../../server/scoring/prompt.py) `_SYSTEM_PROMPT_TEMPLATE`

- [x] 新增 §**评价对象识别规则**段，注入决策链（005 §决策链）：

  ```
  收到一条评价（comment / verify / owner_change reason）:
    1. 评价者 == 文件作者 / 评价者 == 自己 → 跳过（自我评价不入链）
    2. 文本中明确点名 / @ 了 owner 以外的人 → 该证据不入 owner 评分链
    3. 否则 → 默认归文件作者；若文件作者 == matter.owner → 入链
  ```

- [x] 新增 §**评价范围限制**：仅来自 think / act 文件正文 + 其下评论 + verify 内容 + owner_change.reason 可入链；result / insight 仅作背景，不发起新证据
- [x] 新增 §**owner_change.reason 解析**：含工作质量评价 → 归原 owner；纯中性说明（"职责调整"等）→ 不入链

### Task 1.2：schema 加"反自我评价"校验 ✅

**File:** [server/scoring/schema.py](../../server/scoring/schema.py)

- [x] `EvidenceItem` 增加可选字段 `source_file_creator: str | None`（AI 必须标出证据所在文件的作者 pinyin）
- [x] `_validate_business_rules` 增加规则：
  - 若 `source_kind == "comment"` 且 `source_comment_author == subject_pinyin` → 拒收（自我评价违反 005 §6）
  - 若 `source_kind == "file"` 且 `source_file_creator == subject_pinyin` 且 polarity 为正 → 拒收（owner 自己写的 think / act 不能作为自身正向证据）
- [x] 新增 SchemaError 子类型 `SelfEvaluationError`，便于 worker 把这类失败和 AI 输出问题区分

### Task 1.3：serialize_timeline 标注文件作用 ✅

**File:** [server/scoring/prompt.py](../../server/scoring/prompt.py) `serialize_timeline`

- [x] 给每个 timeline 文件序列化时，按类型标注作用：
  - `think` / `act` → "（核心：可发起评价）"
  - `verify` → "（终点：作为对被验文件作者的事实证据）"
  - `result` / `insight` → "（背景：不发起新评价）"
- [x] owner_change item 序列化时显式标 "from_owner / to_owner / reason"，提示 AI 按 §**owner_change.reason 解析**判断

### Task 1.4：单测 ✅

**Files:** [server/tests/test_scoring_schema.py](../../server/tests/test_scoring_schema.py)、[server/tests/test_scoring_prompt.py](../../server/tests/test_scoring_prompt.py)

- [x] schema：自我评价 evidence → 拒收（comment + file 两路径）
- [x] schema：缺 `source_file_creator` 时 AI 输出仍可通过（向后兼容）
- [x] prompt：snapshot 新版 system prompt（防回归）
- [x] prompt：serialize_timeline 各文件类型标注正确
- [x] 增补 E2E 测试 [server/tests/test_e2e_scoring.py](../../server/tests/test_e2e_scoring.py)（9 条），覆盖 trigger → worker → store 全链路 + 自我评价拒收三种路径

### Task 1.5：联调验证（待人工执行）

- [ ] 找 1-2 个真实 finished matter 重跑评分（admin → 重新跑），比对新旧输出差异：
  - 自我评价是否消失
  - "他人 think 下评论 X 但点名 Y" 的证据，是否不再被错误归到 owner

### 验收清单（Phase 1）

- [ ] 自我评价（owner 在自己 think 下评论 / verify 自己的 act）不进证据链
- [ ] owner 的 think 下他人明确点名第三方的评价，不计入 owner 评分
- [ ] owner_change reason 含负向评价 → 归当前 owner（v1 仍是 owner-only，无法归原 owner，但 prompt 提示 AI 用 negative confidence 处理）
- [ ] 已有 admin 重跑入口能复现，老 run 保留

---

## Phase 2：切换到 360 评价模型（消费方改造）

**范围澄清（007 §2 决议）：** 评分模块**不再**自带数据模型拆分。`comments` → `mention` + `annotation` 的拆分由独立 matter 推进；本 phase 只做"评分系统如何消费 annotation"——多 subject 评分、归因依据落库、admin 视图改造。

**前置：** 独立的 annotation matter 给出可消费的数据接口（YAML 字段 / publish API / 历史兼容策略）。该 matter 与本 phase **并行推进、互不阻塞**；本 phase 的代码改动等接口稳定后启动。

### Task 2.1：设计稿（act）

**Pivot 内 act 一份「Matter 评分体系 v0.4 — 消费方改造」**，覆盖：

- [ ] 触发：finished 时 AI 解析 timeline 中 think / act 作者集合，每人一行评分
- [ ] 历史数据如何处理（schema_version 标记）
- [ ] 与 annotation matter 的接入点：评分模块从哪个字段读 annotation、读哪些状态、向后兼容窗口
- [ ] 决策：annotation 缺失时（老 matter / 新 matter 但没人评论）是否仍走 owner-only 兜底

**已剥离至 annotation matter（不在本 phase 范围）：**
- 数据模型：comments → mention + annotation 拆分（涉及 [server/publish.py](../../server/publish.py)、[server/notify.py](../../server/notify.py)、[server/matter_index.py](../../server/matter_index.py)）
- publish 层：`publish_annotation` 函数 / matter index 新增 `annotations: []` 字段
- 前端创建入口：[web/src/components/matter/CreateFileDialog.tsx](../../web/src/components/matter/CreateFileDialog.tsx)、`AnnotationDialog.tsx`、文件详情页"评价该文件"按钮
- mention vs annotation 的语义边界 / 是否单独 UI 入口

### ~~Task 2.2：数据模型拆分~~（已剥离至 annotation matter）

> 该 task 不再属于本 plan。等 annotation matter 给出可消费的数据接口后，本 phase 通过 §2.4 worker / §2.5 schema 接入 annotation 字段。

### Task 2.3：scoring schema 解锁多行

**Files:** [server/scoring/schema.py](../../server/scoring/schema.py)、[server/scoring/store.py](../../server/scoring/store.py)

- [ ] [schema.py](../../server/scoring/schema.py) `ScoringOutput.scores` 移除 `max_length=1`
- [ ] [schema.py](../../server/scoring/schema.py) `_validate_business_rules` 中 `subject_pinyin != expected_subject` 改为 `subject_pinyin not in candidate_subjects`
- [ ] `parse_and_validate(expected_subject)` → `parse_and_validate(candidate_subjects: set[str])`
- [ ] `matter_scores` 表 PK `(run_id, subject_user_id)` 已支持多行，无需改 schema；但 store 层 `write_results` 要支持批量

### Task 2.4：trigger / worker 多 subject + 隐式评价规则

**Files:** [server/scoring/trigger.py](../../server/scoring/trigger.py)、[server/scoring/worker.py](../../server/scoring/worker.py)、[server/scoring/store.py](../../server/scoring/store.py)、[server/scoring/prompt.py](../../server/scoring/prompt.py)

- [ ] trigger 不再只查 `matter.owner`：解析 timeline 中所有 think / act 文件的 creator，构成 candidate 集合
- [ ] `ScoringJob` 增加 `candidate_user_ids: list[str]` 字段
- [ ] worker 把 candidate pinyin 集合传给 prompt builder，AI 每人一行
- [ ] store 写入时按每行 candidate 分别落 `matter_scores`
- [ ] **prompt 规则补全（007 §1.2）**：把 005 §4 表里的两条隐式评价显式编入 system prompt：
  - `verify failed` / 多次 verify failed 后才 passed → 被 verify 文件作者的 **delivery 维度负向**
  - 长期被 `@` 不回复 → 被 `@` 的人的 **collaboration 维度负向**

### Task 2.5：annotation 归因依据落库 + 派生层边界

**Files:** [server/scoring/schema.py](../../server/scoring/schema.py)、[server/scoring/store.py](../../server/scoring/store.py)、[server/db.py](../../server/db.py)

- [ ] `EvidenceItem` 增加 `attribution_basis: Literal["file_creator", "explicit_mention", "at_target", "owner_change_reason", "verify_outcome"]` 字段
  - **`verify_outcome`（007 §1.1）** 覆盖 005 §4 表里 "verify failed → 被验文件作者交付质量" 的隐式归因——之前 4 个值都不适用
- [ ] 落到 `matter_score_evidence` 新列 `attribution_basis`
- [ ] AI prompt 要求每条 evidence 标 attribution_basis（按 005 决策链 + verify 隐式归因）
- [ ] **派生层边界声明（007 §1.3 / 003 §4）**：在 [server/scoring/store.py](../../server/scoring/store.py) `EvidenceWrite` / `MatterScoreEvidence` 上加注释，显式标注：
  - **用户原始输入**：`source_filename` / `source_comment_author_id` / `quote`（mention/annotation body 原文）
  - **AI 派生解释**：`dimension` / `polarity` / `confidence` / `attribution_basis` / `weight_applied` / `explanation`
  - 注释里点出"派生字段不能伪装成原始输入"——避免后续 admin override 等功能误把派生分当用户填的分

### ~~Task 2.6：前端 annotation 入口~~（已剥离至 annotation matter）

> annotation 创建入口（AnnotationDialog、文件详情页"评价该文件"按钮）属于 annotation 数据模型工作，由独立 matter 推进。本 phase 仅在 §2.7 的 EvidenceDialog 里增加 attribution_basis 展示列。

### Task 2.7：scoring 详情页改造

**Files:** [web/src/components/scoring/MatterScoresView.tsx](../../web/src/components/scoring/MatterScoresView.tsx)、[web/src/components/scoring/EvidenceDialog.tsx](../../web/src/components/scoring/EvidenceDialog.tsx)

- [ ] 单行 → 多行展示，每行一个 candidate
- [ ] 增加"为什么是这些人？"提示，列出 candidate 集合的来源（think / act 作者）
- [ ] EvidenceDialog 增加 **归因依据**列，渲染 attribution_basis：
  - `file_creator` → "文件作者"
  - `explicit_mention` → "文本点名"
  - `at_target` → "@ 提及"
  - `owner_change_reason` → "转交原因"
  - `verify_outcome` → "验收动作"

### Task 2.8：历史数据兼容

**File:** [server/db.py](../../server/db.py)

- [ ] `matter_scoring_runs` 增加 `schema_version INTEGER NOT NULL DEFAULT 1`
- [ ] 老 run（v0.3 单行）保持 v1，前端按 v1 展示
- [ ] 新 run 标 v2，前端按多行展示
- [ ] 不重算历史，admin 重跑时按 v2 重新评

### Task 2.9：测试

- [ ] [test_scoring_trigger.py](../../server/tests/test_scoring_trigger.py)：candidate 集合解析（含 owner_change 前后的作者）
- [ ] [test_scoring_schema.py](../../server/tests/test_scoring_schema.py)：多行评分通过、attribution_basis 校验（含 `verify_outcome`）
- [ ] [test_scoring_prompt.py](../../server/tests/test_scoring_prompt.py)：candidate 集合注入 prompt 正确；隐式评价规则（verify failed / 长期 @ 不回）出现在 system prompt
- [ ] [test_admin_scoring_api.py](../../server/tests/test_admin_scoring_api.py)：管理页跨 matter 列表多行展示
- [ ] [test_e2e_scoring.py](../../server/tests/test_e2e_scoring.py)：扩 multi-subject 用例 + verify failed 场景
- [ ] 端到端：用一个真实 multi-author 的 finished matter 跑通

### 验收清单（Phase 2）

- [ ] 一个有 zhangbo think + lisi act + wangwu act 的 matter，评分输出 3 行，分别对应 zhangbo / lisi / wangwu
- [ ] dengke 在 lisi 的 act 下评论 "wangwu 这次判断很准" → 该证据归 wangwu，不归 lisi（`attribution_basis=explicit_mention`）
- [ ] zhangbo 在自己 think 下回评 "我做得不错" → 不入证据链
- [ ] zhangbo → lisi 转交 reason="zhangbo 推进不力" → 该 reason 作为对 zhangbo 的负向证据，不归 lisi（`attribution_basis=owner_change_reason`）
- [ ] **wangwu 的 act 被 lisi verify failed → 自动归 wangwu delivery 负向**（`attribution_basis=verify_outcome`）
- [ ] **被 `@` 的人长期未回 → 该人 collaboration 维度负向**
- [ ] mention 仅作弱证据，annotation 作为强语义证据（依赖 annotation matter 落地）
- [ ] 历史 v1 的 run 仍能正常浏览

---

## 风险 & 决策项

| # | 议题 | 风险 | 决策建议 |
|---|---|---|---|
| 1 | **跨 matter 协调**：annotation 数据模型由独立 matter 推进 | 接口约定不一致 / 时序错配（评分先于 annotation 落地） | 评分 phase 2 启动前，annotation matter 先 act 一份"对外接口契约"（YAML 字段名、publish API 形态、向后兼容窗口）；评分 phase 2 设计稿引用该契约 |
| 2 | 老 matter 没 annotation 字段 | 历史 matter 进 finished 时如何评 | annotation 缺失时回退到"用 comments 当弱 annotation"，新 matter 走正式 annotation 路径——具体策略由 §2.1 决定 |
| 3 | AI 输出多人评分 token 成本 | 一次评分从 1 行变 N 行，prompt 也变长 | 留监控；如果超 50k 字符 truncation，按 think / insight 优先丢 |
| 4 | annotation 创建入口对用户的心理影响 | 让团队"评价别人"可能改变协作行为（参考 v0.3 决策 B） | 评分结果继续 admin-only；annotation 入口是否对全员开放由 annotation matter 决定 |
| 5 | Phase 1 与 Phase 2 之间的版本号 | 上线后 schema 一次小改一次大改 | Phase 1 不动 schema_version；Phase 2 才升 v2 |
| 6 | **派生层 vs 原始输入混淆**（007 §1.3） | admin override / 后续 audit 误把 AI 派生分当用户原始输入 | §2.5 在 schema/store 层显式注释字段归类；前端 EvidenceDialog 也要分两栏展示 |

---

## 落地建议

1. ✅ **Phase 1 已完成**（commit `d96635f`）—— 005 的归因细则已在现有架构内对齐
2. **annotation 数据模型独立成 matter** —— 评分 phase 2 不再自带这部分；新起一条 matter 由产品团队推进 mention / annotation 拆分边界、创建入口、迁移策略
3. **本 matter 内 act 一份「评分体系 v0.4 — 消费方改造」设计稿**，引用 annotation matter 的接口契约，明确 §2.1 的接入点
4. **Phase 2 启动条件**：annotation matter 给出可消费的接口（即使是 stub / placeholder 也行），本 phase 即可并行启动多 subject 评分 + 隐式评价规则 + attribution_basis 落库
5. **首次跑通后**人工抽样几个真实 multi-author finished matter，比对评分覆盖度（candidate 集合是否合理 / 自我评价是否仍有漏网）
