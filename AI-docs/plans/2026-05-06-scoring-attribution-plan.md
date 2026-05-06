# 员工评价体系 — 落地实施 Plan

> 基于 Pivot matter「需求：员工评价体系需求与设计」timeline 001 / 003 / 005 与当前实现差距整理

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

## Phase 1：归因细则对齐（低风险）

**目标：** 让现有 owner-only 评分在归因判断上符合 005 的规则——自我评价不入链、文本明确点名优先、owner_change reason 解析、评价范围限制 think/act。

**约束：** 不动数据模型，不动"一 matter 一行评分"约束。

### Task 1.1：扩 prompt 系统提示

**File:** [server/scoring/prompt.py](../../server/scoring/prompt.py) `_SYSTEM_PROMPT_TEMPLATE`

- [ ] 新增 §**评价对象识别规则**段，注入决策链（005 §决策链）：

  ```
  收到一条评价（comment / verify / owner_change reason）:
    1. 评价者 == 文件作者 / 评价者 == 自己 → 跳过（自我评价不入链）
    2. 文本中明确点名 / @ 了 owner 以外的人 → 该证据不入 owner 评分链
    3. 否则 → 默认归文件作者；若文件作者 == matter.owner → 入链
  ```

- [ ] 新增 §**评价范围限制**：仅来自 think / act 文件正文 + 其下评论 + verify 内容 + owner_change.reason 可入链；result / insight 仅作背景，不发起新证据
- [ ] 新增 §**owner_change.reason 解析**：含工作质量评价 → 归原 owner；纯中性说明（"职责调整"等）→ 不入链

### Task 1.2：schema 加"反自我评价"校验

**File:** [server/scoring/schema.py](../../server/scoring/schema.py)

- [ ] `EvidenceItem` 增加可选字段 `source_file_creator: str | None`（AI 必须标出证据所在文件的作者 pinyin）
- [ ] `_validate_business_rules` 增加规则：
  - 若 `source_kind == "comment"` 且 `source_comment_author == subject_pinyin` → 拒收（自我评价违反 005 §6）
  - 若 `source_kind == "file"` 且 `source_file_creator == subject_pinyin` 且 polarity 为正 → 拒收（owner 自己写的 think / act 不能作为自身正向证据）
- [ ] 新增 SchemaError 子类型 `SelfEvaluationError`，便于 worker 把这类失败和 AI 输出问题区分

### Task 1.3：serialize_timeline 标注文件作用

**File:** [server/scoring/prompt.py](../../server/scoring/prompt.py) `serialize_timeline`

- [ ] 给每个 timeline 文件序列化时，按类型标注作用：
  - `think` / `act` → "（核心：可发起评价）"
  - `verify` → "（终点：作为对被验文件作者的事实证据）"
  - `result` / `insight` → "（背景：不发起新评价）"
- [ ] owner_change item 序列化时显式标 "from_owner / to_owner / reason"，提示 AI 按 §**owner_change.reason 解析**判断

### Task 1.4：单测

**Files:** [server/tests/test_scoring_schema.py](../../server/tests/test_scoring_schema.py)、[server/tests/test_scoring_prompt.py](../../server/tests/test_scoring_prompt.py)

- [ ] schema：自我评价 evidence → 拒收（comment + file 两路径）
- [ ] schema：缺 `source_file_creator` 时 AI 输出仍可通过（向后兼容）
- [ ] prompt：snapshot 新版 system prompt（防回归）
- [ ] prompt：serialize_timeline 各文件类型标注正确

### Task 1.5：联调验证

- [ ] 找 1-2 个真实 finished matter 重跑评分（admin → 重新跑），比对新旧输出差异：
  - 自我评价是否消失
  - "他人 think 下评论 X 但点名 Y" 的证据，是否不再被错误归到 owner

### 验收清单（Phase 1）

- [ ] 自我评价（owner 在自己 think 下评论 / verify 自己的 act）不进证据链
- [ ] owner 的 think 下他人明确点名第三方的评价，不计入 owner 评分
- [ ] owner_change reason 含负向评价 → 归当前 owner（v1 仍是 owner-only，无法归原 owner，但 prompt 提示 AI 用 negative confidence 处理）
- [ ] 已有 admin 重跑入口能复现，老 run 保留

---

## Phase 2：切换到 360 评价模型（产品架构改动）

**前置：** 与 zhangbo / dengke / liuyu 在 matter 内 act 一份 v0.4 设计稿（mention / annotation 拆分边界、annotation 创建入口、多 subject 评分的可见范围）。**未签字前不动代码。**

### Task 2.1：设计稿（act）

**Pivot 内 act 一份「Matter 评分体系 v0.4 — 切到 360 模型」**，覆盖：

- [ ] 数据模型：comments → mention + annotation 的拆分（涉及 publish.py / notify.py / matter_index 全链）
- [ ] 触发：finished 时 AI 解析 timeline 中 think / act 作者集合，每人一行评分
- [ ] 决策：annotation 是否需要单独 UI 入口；普通 mention 是否仍能作为弱证据
- [ ] 历史数据如何处理（schema_version 标记）

**风险提示：** comments → mention / annotation 拆分**远超 scoring 模块**，影响 [server/publish.py](../../server/publish.py)、[server/notify.py](../../server/notify.py)、[server/matter_index.py](../../server/matter_index.py)、[web/src/components/matter/CreateFileDialog.tsx](../../web/src/components/matter/CreateFileDialog.tsx)、[web/src/components/MentionField.tsx](../../web/src/components/MentionField.tsx) 等。设计稿里要算清这部分预算。

### Task 2.2：数据模型拆分

**Files:** [server/db.py](../../server/db.py)、[server/matter_index.py](../../server/matter_index.py)、[server/publish.py](../../server/publish.py)

- [ ] matter index YAML 新增 `annotations: []` 字段（与 `comments` / `mentions` 并列）
- [ ] `comments` 字段语义收窄：仅承载"提醒 / 讨论"，不再承担评价
- [ ] 数据迁移：历史 comments 全部保留为 mention 性质（不强制改类型）
- [ ] publish 新增 `publish_annotation` 函数，独立于 `publish_matter_comment`
- [ ] 新增 SQLite 表 `matter_annotations`（如果需要持久化；或仅落 git 索引）

### Task 2.3：scoring schema 解锁多行

**Files:** [server/scoring/schema.py](../../server/scoring/schema.py)、[server/scoring/store.py](../../server/scoring/store.py)

- [ ] [schema.py](../../server/scoring/schema.py) `ScoringOutput.scores` 移除 `max_length=1`
- [ ] [schema.py](../../server/scoring/schema.py) `_validate_business_rules` 中 `subject_pinyin != expected_subject` 改为 `subject_pinyin not in candidate_subjects`
- [ ] `parse_and_validate(expected_subject)` → `parse_and_validate(candidate_subjects: set[str])`
- [ ] `matter_scores` 表 PK `(run_id, subject_user_id)` 已支持多行，无需改 schema；但 store 层 `write_results` 要支持批量

### Task 2.4：trigger / worker 多 subject

**Files:** [server/scoring/trigger.py](../../server/scoring/trigger.py)、[server/scoring/worker.py](../../server/scoring/worker.py)、[server/scoring/store.py](../../server/scoring/store.py)

- [ ] trigger 不再只查 `matter.owner`：解析 timeline 中所有 think / act 文件的 creator，构成 candidate 集合
- [ ] `ScoringJob` 增加 `candidate_user_ids: list[str]` 字段
- [ ] worker 把 candidate pinyin 集合传给 prompt builder，AI 每人一行
- [ ] store 写入时按每行 candidate 分别落 `matter_scores`

### Task 2.5：annotation 归因依据落库

**Files:** [server/scoring/schema.py](../../server/scoring/schema.py)、[server/scoring/store.py](../../server/scoring/store.py)

- [ ] `EvidenceItem` 增加 `attribution_basis: Literal["file_creator", "explicit_mention", "at_target", "owner_change_reason"]` 字段
- [ ] 落到 `matter_score_evidence` 新列 `attribution_basis`
- [ ] AI prompt 要求每条 evidence 标 attribution_basis（按 005 决策链）

### Task 2.6：前端 annotation 入口

**Files:** [web/src/components/matter/](../../web/src/components/matter/)

- [ ] 新建 `AnnotationDialog.tsx`，独立于 `CreateFileDialog` / `MentionField`
- [ ] 文件详情页增加"评价该文件"按钮（仅 think / act 类型显示）
- [ ] 评分查看页 `EvidenceDialog` 增加 attribution_basis 列（"归因依据：文件作者 / 文本点名 / `@`提及 / 转交原因"）

### Task 2.7：scoring 详情页改造

**File:** [web/src/components/scoring/MatterScoresView.tsx](../../web/src/components/scoring/MatterScoresView.tsx)

- [ ] 单行 → 多行展示，每行一个 candidate
- [ ] 增加"为什么是这些人？"提示，列出 candidate 集合的来源（think / act 作者）

### Task 2.8：历史数据兼容

**File:** [server/db.py](../../server/db.py)

- [ ] `matter_scoring_runs` 增加 `schema_version INTEGER NOT NULL DEFAULT 1`
- [ ] 老 run（v0.3 单行）保持 v1，前端按 v1 展示
- [ ] 新 run 标 v2，前端按多行展示
- [ ] 不重算历史，admin 重跑时按 v2 重新评

### Task 2.9：测试

- [ ] [test_scoring_trigger.py](../../server/tests/test_scoring_trigger.py)：candidate 集合解析（含 owner_change 前后的作者）
- [ ] [test_scoring_schema.py](../../server/tests/test_scoring_schema.py)：多行评分通过、attribution_basis 校验
- [ ] [test_scoring_prompt.py](../../server/tests/test_scoring_prompt.py)：candidate 集合注入 prompt 正确
- [ ] [test_admin_scoring_api.py](../../server/tests/test_admin_scoring_api.py)：管理页跨 matter 列表多行展示
- [ ] 端到端：用一个真实 multi-author 的 finished matter 跑通

### 验收清单（Phase 2）

- [ ] 一个有 zhangbo think + lisi act + wangwu act 的 matter，评分输出 3 行，分别对应 zhangbo / lisi / wangwu
- [ ] dengke 在 lisi 的 act 下评论 "wangwu 这次判断很准" → 该证据归 wangwu，不归 lisi
- [ ] zhangbo 在自己 think 下回评 "我做得不错" → 不入证据链
- [ ] zhangbo → lisi 转交 reason="zhangbo 推进不力" → 该 reason 作为对 zhangbo 的负向证据，不归 lisi
- [ ] mention 仅作弱证据，annotation 作为强语义证据
- [ ] 历史 v1 的 run 仍能正常浏览

---

## 风险 & 决策项

| # | 议题 | 风险 | 决策建议 |
|---|---|---|---|
| 1 | Phase 2 comments → mention / annotation 拆分波及范围广 | 影响 publish / notify / 前端 / MCP，可能需要前后端同步发布 | 设计稿里先决定是否真要拆，还是只新增 annotation 字段不动 comments |
| 2 | 老 matter 没 annotation 字段 | 历史 matter 进 finished 时如何评 | v2 模型回退到"用 comments 当弱 annotation"，新 matter 才正式分流 |
| 3 | AI 输出多人评分 token 成本 | 一次评分从 1 行变 N 行，prompt 也变长 | 留监控；如果超 50k 字符 truncation，按 think / insight 优先丢 |
| 4 | annotation 创建入口对用户的心理影响 | 让团队"评价别人"可能改变协作行为（参考 v0.3 决策 B） | 先在 admin-only 灰度跑一段，再决定是否对全员开放评分查看 |
| 5 | Phase 1 与 Phase 2 之间的版本号 | 上线后 schema 一次小改一次大改 | Phase 1 不动 schema_version；Phase 2 才升 v2 |

---

## 落地建议

1. **先做 Phase 1**：改 prompt + schema + 测试，提一个 PR。把 005 的归因细则在现有架构内做完，立刻有效果。
2. **在 matter 里发一条 act**：「评分体系 v0.4 设计稿」，对齐 zhangbo / dengke / liuyu 三方对 mention / annotation 拆分的取舍——**这是产品决策，不是技术决策**。
3. **设计稿签字后再启动 Phase 2**。
