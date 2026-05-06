# mentions rename + annotations 引入：实施计划

> **版本：V2（2026-05-06 重订，对齐设计 V2）**
> 跟随设计 V2 一并补两件事：annotation 全栈落地、mention/annotation 共用 stakeholder 通知规则（mention 收件人从 file.author/owner 扩到 file.creator + matter.owner + matter.creator）。
>
> **依据设计**：[`AI-docs/designs/2026-05-06-comments-to-mentions-design.md`](../designs/2026-05-06-comments-to-mentions-design.md)

## 0. 范围对照

写之前先对一遍尺度，避免后面 PR 越滚越大。本计划含三块改动：

- **Phase 1-5 = mentions rename + 通知规则统一**（既有代码改名 + mention 收件人扩到三 stakeholder）
- **Phase 6 = annotations 引入**（新增功能；复用 §3 引入的 stakeholder helper）

**纳入本期**：

mention 这边（Phase 1-5）：

- timeline 数据模型：外层 `comments` → `mentions`，内层 `mentions` → `targets`
- 后端写侧契约硬切：HTTP 路由、Pydantic 模型、events topic、SSE event name、MCP schema
- 后端读侧兼容：matter_index reader 双键归一化（设计里说的唯一兼容点）
- 后端集成：notify 文案与方法名、relevance handler、daily_report 用到 comments 的地方
- **新增 `_resolve_inline_stakeholders` helper**：解析 file.creator + matter.owner + matter.creator 三角色（去重 + 排自己），给 mention 路径用，annotation 也复用
- **mention 通知收件人扩大**：旧实现只通知 file.author/owner 两个人，新规则把 matter.owner 和 matter.creator 也加进去——这是 V2 修复的"通知盲点"，**不是纯字段改名**
- 前端：`api.ts` 类型 + API client、所有读 `item.comments` 的组件、SSE 事件名
- 测试：所有 `*comment*` 测试名/断言跟改 + 新场景"留言不 @"覆盖 stakeholder 通知

annotation（Phase 6）：

- timeline 数据模型新增 `annotations[]` 字段（与 `mentions[]` 平行，挂在被评价文件 timeline 项下）
- 后端：`AnnotationBody`、`POST /api/matters/{id}/annotations`、`publish_matter_annotation`、`matter_index.append_annotation`、events topic、MCP `add_annotation` 工具（**只支持新增，不支持编辑/删除**）
- 通知：复用 Phase 3 加的 `_resolve_inline_stakeholders`；新增 `notify_annotation`（DM-only，无群卡片）+ `_handle_annotation_appended` 写红点
- 前端：`TimelineAnnotation` 类型、`AnnotationDialog` 新组件（独立于 MentionPopover）、`FileCard` 渲染 annotations 区块
- 派生字段拒收：`weight` / `rating` / `dimension` / `sentiment` / `score_delta` 等一律 422（Pydantic + writer schema 双重把关）
- 特性开关 `PIVOT_ANNOTATION_ENABLED`（验收期可一键停写、不影响读）

**本期不做**（独立排期）：

- AI 派生评分（已在 `2026-05-06-scoring-attribution-plan.md` 排）
- scoring 模块的 DB 列 `source_comment_created_at` / `source_comment_author_id` / `source_kind == "comment"`——持久化字段，要 DB migration，不在本期承诺范围
- 历史 YAML 一次性 rewrite（留 TODO，等 reader 兼容跑稳后再做）
- `mention_unread_for_me` 字段名调整（设计 §3.5 明确不动）
- annotation 的编辑 / 删除接口（v1 只允许"加"，写错就再写一条新的更正）
- annotation 的 cross-matter 评价（v1 target 隐式 = 同 matter 同文件，跨 matter 留 v2）
- annotation 触发"评价被质疑"等额外红点（不通知评价者本人这类二级反馈）

---

## 1. 影响面热点

不是穷举，开工前每个 Phase 先用 `grep -rn` 二扫一遍。当前代码里 `comments` / `comment_` 在 server 下散在 30 个文件、244 处；前端 13 个文件、80 处。

### 1.1 后端（mention rename + stakeholder 统一）

| 文件 | 改名 / 新增内容 |
|------|---------|
| `server/matter_index.py` | reader 加 `_normalize_timeline_item`：老 YAML `comments` → `mentions`，内层 `mentions` → `targets`；写侧只输出新结构 |
| `server/matter_validator.py` | YAML schema：写侧只接受 `mentions` + `targets`，传 `comments` 直接 422 |
| `server/publish.py` | `publish_matter_comment` → `publish_matter_mention`；payload key + 注释 + 内部变量名全改；**新增 `_resolve_inline_stakeholders(matter_data, target_file, *, actor) -> list[str]`** 解析 file.creator + matter.owner + matter.creator 三角色（去重 + 排 actor）；mention 路径用它替换原 `_resolve_file_author_recipients`；emit payload 含 `stakeholder_open_ids` + `target_open_ids` 两份 |
| `server/api/matters.py` | Pydantic body `CommentIn` / `CommentBody` → `MentionIn` / `MentionBody`；嵌入字段 `comments: list[CommentIn]` → `mentions: list[MentionIn]`；字段 `mentions` → `targets`；路由 `POST /matters/{id}/comments` → `POST /matters/{id}/mentions`；`_comments_to_dict` 跟改 |
| `server/api/matters_events.py` | `_TOPIC_MAP` 里 `TOPIC_COMMENT_APPENDED: ("matter.updated", "comment_appended")` → `TOPIC_MENTION_APPENDED: ("matter.updated", "mention_appended")` |
| `server/events.py` | `TOPIC_COMMENT_APPENDED = "matter.comment_appended"` → `TOPIC_MENTION_APPENDED = "matter.mention_appended"` |
| `server/notify.py` | 方法 `notify_comment_on_file` → `notify_mention_on_file`；卡片文案"评论"→"提醒"；**接收 stakeholder 列表 + targets 列表两组收件人**——stakeholders 发 DM、targets 发 DM + 群卡片 |
| `server/relevance_writer.py` | `_handle_comment_appended` → `_handle_mention_appended`；payload key 跟改；**给 stakeholders + targets 都写红点**（之前只写 targets + file.author/owner） |
| `server/relevance_scanner.py` | 同上 |
| `server/relevance_events.py` | `REASON_COMMENT_MENTION` 是 DB 字符串值，**保留旧值**避免回填，仅注释说明 |
| `server/mcp/schemas.py` + `server/mcp/tools.py` | MCP tool input schema `comment` / `comments` 参数 → `mention` / `mentions`；已和 MCP 开发人员同步切换计划 |
| `server/daily_report/collect_matter.py` 等 | `comments[i].created_at` 这类访问跟改新 key |
| `server/db.py` | 注释里"comments 不 bump matter.updated_at"等说明同步更新 |

### 1.2 前端（mention rename）

| 文件 | 改名内容 |
|------|---------|
| `web/src/api.ts` | `TimelineComment` → `TimelineMention`；`TimelineFileItem.comments` → `mentions`；`mentions` → `targets`；`appendMatterComment` → `appendMatterMention`，URL 跟改 |
| `web/src/events/types.ts` | SSE event name 字面量 `"comment_appended"` → `"mention_appended"` |
| `web/src/components/matter/FileCard.tsx` | 渲染 `item.comments` → `item.mentions`；`MentionPopover.onSubmit` 数据形状跟改；`mention_unread_for_me` 字段名**保留不动**（设计 §3.5） |
| `web/src/pages/MatterDetailPane.tsx` | `submitComment` → `submitMention`，调用链跟改 |
| `web/src/pages/NewMatter.tsx` / `NewMatterGuidedFlow.tsx` | initial_file 里的 `comments` 字段提交时改成 `mentions` |
| `web/src/components/matter/CreateFileDialog.tsx` | 圈人留言提交时把 `comments[0]` 形状改成 `mentions[0]` |
| `web/src/components/MentionField.tsx` / `MentionUnreadDot.tsx` / `RelevanceChip.tsx` / `ThreadListPane.tsx` / `EvidenceDialog.tsx` / `mcpToolsGuide.ts` | grep 出来的引用全部跟改 |

### 1.3 历史数据

历史 matter index YAML 全是 `comments:` 开头。本期采用**方案 B：reader 双键兼容**：

- matter_index reader 同时认 `comments` 和 `mentions`，归一化到内存里都是 `mentions` / `targets`
- 写侧只写新 key，validator 严格只认新 key
- 用户的自然交互（在老 matter 里追加一条新 mention 或修改现有内容）会触发原子写回，老 YAML 自然升级
- 何时彻底清理 reader 这层归一化：等线上跑稳 1-2 周 + 一次性 rewrite 脚本扫完，作为单独 PR 做，**不在本期**

### 1.4 annotation 新增涉及

annotation 是纯增量改动，不影响既有代码路径。复用 §1.1 引入的 `_resolve_inline_stakeholders` helper。

后端：

| 文件 | 改动内容 |
|------|---------|
| `server/matter_index.py` | 新增 `append_annotation(path, *, target_file, annotation, now_iso)`；`_ITEM_KEY_ORDER` 加 `annotations`；新增 `_canonical_annotation`（key 顺序 `created_at, type, author, body`） |
| `server/matter_validator.py` | annotation schema 校验：`type` 白名单（v1 只 `evaluation`）、`body` 1-2000 字、显式拒派生字段 |
| `server/publish.py` | 新增 `publish_matter_annotation`；author / created_at 由 publish 注入，client 不允许传；**调用 §1.1 的 `_resolve_inline_stakeholders`** 解析三角色 |
| `server/api/matters.py` | Pydantic `AnnotationBody`（带 model_validator 拒派生字段）；`POST /api/matters/{id}/annotations`；`_render_item` 渲染 annotations 时注入 `author_display` / `author_view` |
| `server/events.py` | 新增 `TOPIC_ANNOTATION_APPENDED` |
| `server/api/matters_events.py` | `_TOPIC_MAP` 把 `TOPIC_ANNOTATION_APPENDED` 映射到 SSE `matter.updated`，reason `annotation_appended` |
| `server/relevance_writer.py` | **新增 `_handle_annotation_appended`**——订阅 `TOPIC_ANNOTATION_APPENDED`，给 payload 里的每个 stakeholder 写 `kind=annotation` 红点 |
| `server/relevance_events.py` | **新增 `KIND_ANNOTATION = "annotation"` + `insert_annotation(...)`**（schema 不动，kind 列多一个枚举值） |
| `server/notify.py` | **新增 `notify_annotation(...)` + 卡片 builder**：DM-only（无群卡片），文案"X 在 matter『...』里评价了你的文件 / 你负责的事项" |
| `server/mcp/schemas.py` + `server/mcp/tools.py` | 新增 `add_annotation` 工具；schema 与 HTTP body 一致 |
| `server/settings.py`（或等价位置） | 加 `PIVOT_ANNOTATION_ENABLED` env 开关；handler / MCP 注册时读取 |

前端：

| 文件 | 改动内容 |
|------|---------|
| `web/src/api.ts` | 新增 `TimelineAnnotation` 类型；`TimelineFileItem.annotations: TimelineAnnotation[]`；`appendMatterAnnotation` API client（503 → toast"评价功能维护中"） |
| `web/src/components/matter/AnnotationDialog.tsx` | **新建**评价输入弹窗（不带 @ 选择器，明确区分于 MentionPopover）|
| `web/src/components/matter/FileCard.tsx` | 渲染 annotations 区块（视觉上独立于 mentions 区，避免用户混淆）；触发 AnnotationDialog 的入口按钮；**不出删除按钮**——v1 不支持删除 |
| `web/src/events/types.ts` | SSE 事件 reason 新增 `"annotation_appended"`（订阅 `matter.updated` 的位置自动收到，不需要新订阅器）|

测试：

| 文件 | 改动内容 |
|------|---------|
| `server/tests/test_matter_index.py` | annotation 写 / 读 / canonical 顺序 |
| `server/tests/test_matter_validator.py` | annotation 字段校验（type 白名单、body 长度、拒派生字段）|
| `server/tests/test_matters_api.py` | annotation HTTP 端到端、author 自动注入、确认无 DELETE 路由暴露（404/405）|
| `server/tests/test_publish.py` | `publish_matter_annotation` 端到端调用 `_resolve_inline_stakeholders` 路径 |
| `server/tests/test_mcp_tools.py` | `add_annotation` MCP 工具 |
| `server/tests/test_relevance_writer.py` | **断言 annotation 路径给三 stakeholder 写红点**（不是不写！）；author 自己不写 |
| `server/tests/test_notify.py` | **断言 annotation 路径给三 stakeholder 发 DM**、**不发群卡片**；author 自己不发 |

annotation 不动 daily_report / scoring（这两个模块对 annotation 的消费要等 AI 派生层独立排期）。

---

## 2. Phase 拆分

6 个 Phase。Phase 1-5 是 mention 这边的改名 + 通知规则统一，每个走完一个 Commit Checkpoint 再开下一个。Phase 6 是 annotation 引入，独立 PR。

V2 跟 V1 节奏的差异：

- Phase 3 引入 `_resolve_inline_stakeholders` helper + 替换 mention 收件人逻辑（V1 这步只是改名）
- Phase 6 不再"完全独立"——它依赖 Phase 3 的 helper，所以排期上 Phase 6 必须在 Phase 3 之后，但跟 Phase 4-5 可以并行

### Phase 1：reader 双键归一化 + validator 严格化（地基）

**目的**：让读侧能同时吃两种 key 并归一化成新形状；写侧在 schema 层就只接受新 key。后续阶段中断不影响线上读。

- [ ] `server/matter_index.py`：新增 `_normalize_timeline_item(item)`，处理外层 `comments` → `mentions`、内层 `mentions` → `targets`；reader 加载完 YAML 后逐项归一化
- [ ] `server/matter_validator.py`：写侧 schema 只接受 `mentions` + `targets`，传 `comments` 直接 422
- [ ] `server/tests/test_matter_index.py`：加 fixture——旧 YAML（只含 `comments:`）和新 YAML（只含 `mentions:`）都要能 load 出一致的内存结构
- [ ] `server/tests/test_matter_validator.py`：加用例——`mentions` + `targets` 通过，`comments` 报 422
- [ ] 跑后端全量测试，确保 0 失败

**Commit Checkpoint**：`refactor(matter): reader normalizes comments/mentions; validator strict on new keys`

---

### Phase 2：写路径 + API + Pydantic 改名

**目的**：把所有写入路径切到 mentions。配合 Phase 1 的 reader，写出的新 YAML 就是新结构，老 YAML 也照样能读。

- [ ] `server/publish.py`：`publish_matter_comment` → `publish_matter_mention`；函数签名、payload key、内部变量名、注释全改
- [ ] `server/api/matters.py`：`CommentIn` → `MentionIn`，`CommentBody` → `MentionBody`；`InitialFileIn.comments` → `mentions`，`NewFileBody.comments` → `mentions`，`NewResultBody.comments` → `mentions`；内层字段 `mentions` → `targets`；路由 `POST .../comments` 直接改名到 `POST .../mentions`（无 alias）；helper `_comments_to_dict` → `_mentions_to_dict`
- [ ] `server/tests/test_matters_api.py`、`server/tests/test_publish.py`、其他 *comment* 命名的测试改名 + 断言改 key
- [ ] 跑后端全量测试

**Commit Checkpoint**：`refactor(matter): rename publish/api/pydantic from comments to mentions`

---

### Phase 3：events + SSE + relevance + notify + MCP + **stakeholder 统一**

**目的**：内部事件总线、对前端的 SSE 事件名、relevance 写入、飞书通知、MCP 全链路改名。**同时把 mention 通知接收人扩到三 stakeholder**——这是 V2 比 V1 多出来的工作量。**SSE 事件名 `comment_appended` 改成 `mention_appended` 是对前端的契约破坏，要和 Phase 4 同批发**。

- [ ] `server/events.py`：`TOPIC_COMMENT_APPENDED = "matter.comment_appended"` → `TOPIC_MENTION_APPENDED = "matter.mention_appended"`
- [ ] `server/api/matters_events.py`：`_TOPIC_MAP` 里 SSE 事件名 `comment_appended` → `mention_appended`
- [ ] `server/publish.py`：**新增 `_resolve_inline_stakeholders(matter_data, target_file, *, actor) -> list[str]`**——解析 file.creator + matter.owner + matter.creator，去重，排 actor，缺角色降级跳过
- [ ] `server/publish.py::publish_matter_mention`：把原来调 `_resolve_file_author_recipients` 的位置换成 `_resolve_inline_stakeholders`；emit payload 改成 `{stakeholder_open_ids: [...], target_open_ids: [...]}` 两份
- [ ] `server/relevance_writer.py` / `server/relevance_scanner.py`：handler 改名 `_handle_comment_appended` → `_handle_mention_appended`，payload key 跟改；**写红点改成给 stakeholders + targets 都写**
- [ ] `server/relevance_events.py`：`REASON_COMMENT_MENTION` 常量值**保留不变**（数据库里有大量旧值），仅在注释里写明"语义已改但值未动，避免回填"
- [ ] `server/notify.py`：方法名 `notify_comment_on_file` → `notify_mention_on_file`；接受 stakeholder 列表 + targets 列表两组收件人；stakeholders 发 DM、targets 发 DM + 群卡片；飞书卡片所有"评论"→"提醒"
- [ ] `server/mcp/schemas.py` / `server/mcp/tools.py`：input schema 参数名 `comment` / `comments` → `mention` / `mentions`，工具描述同步更新
- [ ] `server/daily_report/collect_matter.py` 等模块的 `comments[i]...` 访问跟改
- [ ] **`server/tests/test_publish.py` 加 `_resolve_inline_stakeholders` 单测**：去重 / 排自己 / 缺角色降级 / 三角色完全重叠（一个 actor 同时是 file.creator + matter.owner + matter.creator）的边界
- [ ] **`server/tests/test_relevance_writer.py` 加新场景**：在某文件下留言不 @ 任何人时，matter.owner 和 matter.creator 也应该收到 `kind=mention` 红点
- [ ] **`server/tests/test_notify.py` 加新场景**：同上场景，matter.owner 和 matter.creator 也应该收到 DM
- [ ] 全量测试 + 手测一次「@ 自己 / 不 @ 任何人留言 / AI 自动 @」三种通知效果，特别确认"留言不 @"路径下 stakeholder DM 都到位

**Commit Checkpoint**：`refactor(matter): rename to mention; unify stakeholder notification to three roles`

---

### Phase 4：前端类型 + 组件 + SSE listener

**目的**：前端跟着后端契约切换。**与 Phase 3 必须同批发**——SSE 事件名和 HTTP 路由都没留兼容，前后端版本错位会立刻 404 / 收不到事件。

- [ ] `web/src/api.ts`：`TimelineComment` → `TimelineMention`；`TimelineFileItem.comments` → `mentions`，内层 `mentions` → `targets`；`appendMatterComment` → `appendMatterMention`，URL 跟改
- [ ] `web/src/events/types.ts`：`"comment_appended"` 字面量 → `"mention_appended"`；订阅这个事件的位置跟改
- [ ] `web/src/components/matter/FileCard.tsx`：`item.comments` → `item.mentions`；提交一条 mention 的数据 shape 跟改；`mention_unread_for_me` 字段访问保持不变
- [ ] `web/src/pages/MatterDetailPane.tsx`：`submitComment` → `submitMention`，调用链跟改
- [ ] `web/src/pages/NewMatter.tsx`、`web/src/pages/NewMatterGuidedFlow.tsx`、`web/src/components/matter/CreateFileDialog.tsx`：initial_file / 文件提交里的 `comments[0]` 字段改成 `mentions[0]`
- [ ] `web/src/components/MentionField.tsx`、`MentionUnreadDot.tsx`、`RelevanceChip.tsx`、`ThreadListPane.tsx`、`EvidenceDialog.tsx`、`mcpToolsGuide.ts`：grep 出的引用逐个跟改
- [ ] grep `web/src` 残留的 `comment` / `Comment`，确认全是无关（unicode block comment 或第三方库）
- [ ] `npx tsc --noEmit` 0 错误

**Commit Checkpoint**：`refactor(web): rename comments to mentions in types/api/components/SSE`

---

### Phase 5：文档 + 后续 TODO

- [ ] `pivot-interface.md` / `CLAUDE.md` / 任何 docs 里提及 `comments` 字段的位置同步更新
- [ ] CLAUDE.md 加一行**"mention 通知 = 显式 @ targets + 三 stakeholder（file.creator + matter.owner + matter.creator）"**，避免后人想当然以为只 @ 谁就只通知谁
- [ ] `AI-docs/plans/` 留 TODO：等线上跑稳 1-2 周后做 `scripts/rewrite_comments_to_mentions.py`，扫所有历史 YAML 原地替换 + 备份；跑完后才能删 Phase 1 的 reader 归一化
- [ ] `AI-docs/plans/` 留 TODO：scoring 模块的 DB 列 `source_comment_*` → `source_mention_*` 需要 migration，单独立项；同时同步 scoring prompt 里的"comments"措辞

**Commit Checkpoint**：`docs(matter): update interface/CLAUDE; note follow-up rewrite + scoring migration`

---

### Phase 6：annotation 全栈引入

**目的**：在 Phase 1-5 基础上新挂一层 annotations 字段，承载用户对文件的评价。**纯增量、不破坏既有契约**——但通知和红点逻辑跟 mention 共用 Phase 3 引入的 `_resolve_inline_stakeholders`，所以排期上必须在 Phase 3 之后。建议在 Phase 1-5 全量上线 + 跑稳一周后开工。

#### 6.1 后端基础（matter_index + validator + publish + 通知挂上）

- [ ] `server/matter_index.py`：新增 `append_annotation(path, *, target_file, annotation, now_iso)`；`_ITEM_KEY_ORDER` 加 `annotations`；新增 `_canonical_annotation`（key 顺序 `created_at`、`type`、`author`、`body`）。**不实现 delete**，annotation 一旦写入就是 audit 痕迹
- [ ] `server/matter_validator.py`：annotation schema 校验——`type ∈ {evaluation}`（白名单，未知拒）、`body 1-2000`、显式拒收 `weight` / `rating` / `dimension` / `sentiment` / `score_delta` 等派生字段
- [ ] `server/publish.py`：`publish_matter_annotation(workspace, user, *, matter_id, target_file, type, body)`；author / created_at writer 注入；**调用 Phase 3 的 `_resolve_inline_stakeholders`** 解析三角色；emit payload 含 `stakeholder_open_ids`
- [ ] `server/events.py`：新增 `TOPIC_ANNOTATION_APPENDED = "matter.annotation_appended"`
- [ ] `server/relevance_events.py`：新增 `KIND_ANNOTATION = "annotation"` 常量 + `insert_annotation(...)` 仓库方法（schema 不动，kind 列多一个枚举值）
- [ ] `server/relevance_writer.py`：新增 `_handle_annotation_appended(event)` 订阅 `TOPIC_ANNOTATION_APPENDED`，给 payload 里每个 stakeholder 写 `kind=annotation` 红点
- [ ] `server/notify.py`：新增 `notify_annotation(...)` + 卡片 builder（DM-only 无群卡片，文案"X 在 matter『...』里评价了你的文件/你负责的事项"）
- [ ] `server/tests/test_matter_index.py`：annotation 写 / 读 / canonical 顺序
- [ ] `server/tests/test_matter_validator.py`：annotation 字段校验 + 拒派生字段 5 个用例
- [ ] `server/tests/test_publish.py`：`publish_matter_annotation` 端到端走通 stakeholder 解析 → emit → notify 链路
- [ ] `server/tests/test_relevance_writer.py`：`_handle_annotation_appended` 给三 stakeholder 写红点；author 自己不写
- [ ] `server/tests/test_notify.py`：`notify_annotation` 给三 stakeholder 发 DM；不发群卡片；author 自己不发
- [ ] 跑后端测试

**Commit Checkpoint**：`feat(matter): add annotations[] data layer with stakeholder notify + relevance`

#### 6.2 后端 API + 特性开关 + SSE

- [ ] `server/settings.py`（或等价位置）：加 `PIVOT_ANNOTATION_ENABLED` env 开关，默认 `True`
- [ ] `server/api/matters.py`：Pydantic `AnnotationBody`（`target_file` / `type` / `body`，model_validator 拒派生字段）；handler `POST /api/matters/{id}/annotations`；开关关掉时返回 `503` + `{code: "annotation_disabled"}`
- [ ] `server/api/matters.py::_render_item`：渲染 annotations 时为每条注入 `author_display` / `author_view`
- [ ] `server/api/matters_events.py`：`_TOPIC_MAP` 加 `TOPIC_ANNOTATION_APPENDED` → SSE `matter.updated`，reason `annotation_appended`
- [ ] `server/tests/test_matters_api.py`：annotation 端到端（写 / 422 拒派生字段 / 503 关闭开关 / 确认无 DELETE 路由 → 405 或 404）
- [ ] 跑后端测试

**Commit Checkpoint**：`feat(matter): add annotations API + feature flag + SSE`

#### 6.3 后端 MCP 工具

- [ ] `server/mcp/schemas.py`：`add_annotation` input schema（与 HTTP body 一致）
- [ ] `server/mcp/tools.py`：工具实现，复用 publish_matter_annotation；开关关掉时**不注册工具**（不在 `list_tools` 里出现）
- [ ] `server/tests/test_mcp_tools.py`：`add_annotation` 端到端 + 开关下不可见
- [ ] 通知 MCP 集成方有新工具

**Commit Checkpoint**：`feat(mcp): add add_annotation tool`

#### 6.4 前端

- [ ] `web/src/api.ts`：`TimelineAnnotation` 类型；`TimelineFileItem.annotations: TimelineAnnotation[]`；`appendMatterAnnotation` API client（503 → 给 toast 提示"评价功能维护中"）
- [ ] `web/src/components/matter/AnnotationDialog.tsx`：**新建**评价输入弹窗。明确区分于 MentionPopover——不带 @ 选择器、视觉色调改成中性、按钮文案"提交评价"而非"发送提醒"
- [ ] `web/src/components/matter/FileCard.tsx`：渲染 annotations 区块（与 mentions 区视觉分开，例如左侧加引用线 / 不同 chip 颜色）；触发 AnnotationDialog 的入口按钮。**不出删除按钮**——v1 不支持删除
- [ ] `web/src/events/types.ts`：reason 字面量加 `"annotation_appended"`
- [ ] grep 检查 `pnpm tsc --noEmit` 0 错误
- [ ] 手测：写一条 → 列表立刻刷出来 → 三 stakeholder 飞书 DM 收到 → 关闭开关后按钮置灰、API 503 toast 显示

**Commit Checkpoint**：`feat(web): add annotations rendering + AnnotationDialog`

#### 6.5 文档 + 联调

- [ ] `pivot-interface.md` 加 annotation API 段落
- [ ] `CLAUDE.md` 加 annotation 概念说明 + mention vs annotation 边界对照（**注明两者通知规则共享同一组 stakeholder**，避免后人想当然以为不一样）
- [ ] MCP 集成方公告：新增 `add_annotation` 工具说明（同时说明 v1 不提供删除工具）
- [ ] 端到端联调：从 web 写 → SSE 推 → 另一窗口看到 → 三 stakeholder 飞书 DM 全部到位
- [ ] 端到端联调：从 Claude Code 用 MCP 写 annotation → web 看到 → DM 到位

**Commit Checkpoint**：`docs(matter): annotation interface + MCP integration guide`

---

## 3. 验收

跟设计 §八 对齐，分两块。

**mentions rename + 通知规则统一（Phase 1-5）**：

1. 新写入的 matter index YAML 全部以 `mentions:` 开头，内层是 `targets:`。
2. 旧 matter（只含 `comments:`）能正常读、正常 @、正常收飞书提醒，**字段层面对比改名前 0 diff**。
3. **stakeholder 通知规则生效**（行为变化，重点回归）：在某文件下留言不 @ 任何人时，matter.owner 和 matter.creator 都能收到飞书 DM 和 relevance 红点（除非他们就是 author 本人）。手测路径：拿一个真 matter，A 在 B 创建的文件下留言（不 @），matter.owner 是 C、matter.creator 是 D → C 和 D 都收到 DM，A 自己不收。
4. 后端测试全绿；前端 `npx tsc --noEmit` 0 错误；E2E（如有）跑通。
5. MCP 集成方按约定切换完成；Claude Code 等外部调用方对得上新字段。

**annotations 引入（Phase 6）**：

6. 用户能从 FileCard 入口写 annotation，落进 YAML 的 `annotations[]`，author / created_at writer 自动注入。
7. annotation body 里夹带 `weight` / `rating` / `dimension` 等派生字段会被 Pydantic 拒（422）；writer schema 兜底（dict 即使绕过 Pydantic 也拒）。
8. annotation 写入**走与 mention 相同的 stakeholder 通知规则**（同一个 helper `_resolve_inline_stakeholders`）：file.creator + matter.owner + matter.creator 都收到 DM 和红点；author 自己不收。**不发群卡片**、**不 bump matter.updated_at**。
9. **没有 DELETE 路由 / 删除按钮 / MCP 删除工具**——grep 检查 + 路由列表检查双重确认；前端代码里搜不到 `deleteMatterAnnotation`。
10. MCP `add_annotation` 工具能从 Claude Code 调通，schema 与 HTTP 一致。
11. 特性开关 `PIVOT_ANNOTATION_ENABLED=false` 时：写入 503、前端按钮灰、MCP 工具不注册；读路径不受影响。

---

## 4. 风险 / 注意事项

### 4.1 mentions rename + stakeholder 统一（Phase 1-5）

写侧不留 alias + mention 收件人扩大，是 V2 比 V1 多出来的两件事，都要盯。

- **Phase 3 + Phase 4 必须同批发**。SSE 事件名和 HTTP 路由都硬切，旧前端调旧路由 404、收不到 `mention_appended` 事件就不会刷新。Phase 1-2 可以先发（写侧已切，但前端旧版本调旧 URL 仍会 404）—— 实操建议把 Phase 1-4 一起走一个发布窗口。
- **mention 收件人扩大是行为变化，不是字段改名**。线上跑 V2 之后，matter.owner 和 matter.creator 会开始收到他们之前收不到的 DM——可能让人感觉"突然变吵"。落地前在 release notes 里说清楚：从这个版本起，事项里只要有 mention 写入，事项 owner 和 creator 都会被通知；这是修复了之前漏发的 bug，不是新增 spam。
- **MCP 切换窗口已和开发人员对齐**。Phase 3 上线前发切换公告，注明老字段下线时间和新字段名（`mention` / `mentions`）。MCP tool description 上线后第一时间更新。
- **`REASON_COMMENT_MENTION` 常量值不动**（继续写 `"comment_mention"` 进 DB）。如果硬要改，需要全表 UPDATE 一遍历史行，得不偿失。注释里写清楚就行。
- **scoring 模块的 `source_comment_*` 列不动**。这是持久化字段，改它要 DB migration + 数据回填，远超本期"零行为变化"的承诺。Phase 5 的 TODO 留出来。
- **飞书卡片文案改动需要回归**：飞书消息里"评论"出现频率高，改"提醒"后请走一遍真实通知用例（含 @ 自己 / 不 @ / AI 自动 @）。
- **stakeholder 解析的 helper 必须排自己**——`actor` 同时是 file.creator / matter.owner / matter.creator 时（很常见：matter owner 给自己负责的事项里的某个文件做 mention），别给自己发 DM。`_resolve_inline_stakeholders` 必须有用例覆盖每种自我重叠场景。这条规则 mention 和 annotation 共享同一个 helper，覆盖一次就行。
- **降级：缺角色不算错**——matter.owner 没设、matter.creator 是未注册联系人没 open_id、文件 creator 离职 user 失效……都按"跳过该 stakeholder"处理，不要因为一个角色解析失败就拒绝整个 mention 写入。
- **回滚策略**：因为没留 alias，回滚就是 Phase 1-4 一起 revert。Phase 5 是纯文档，不影响行为。

### 4.2 annotations 引入（Phase 6）

风险点跟 rename 不一样——annotation 是**新写入的持久数据**，一旦用户开始写，回滚就意味着丢评价；并且每写一条都会立刻给三个 stakeholder 发飞书，骚扰面比 rename 大得多。

- **特性开关是回滚抓手**。`PIVOT_ANNOTATION_ENABLED=false` 关掉后：API 503、前端按钮灰、MCP 工具不注册。**读路径始终开**——已写入的 annotation 一直能看到。如果发现严重问题，先关开关止损，**已写入的 annotation 不要手工删**（DB / YAML 都不动），下个版本再决定怎么处理（很可能就保留）。
- **派生字段拒收必须有用例覆盖**——避免未来被人偷偷加 `weight: high` 这种字段进 body。Phase 6.1 + 6.2 各加一组用例（writer schema 一组、Pydantic 一组）。
- **写错怎么办**——v1 不提供删除 / 编辑接口。用户写错就在原位再写一条新的更正，旧的留作 audit 痕迹。代价是会有"垃圾评价"留下来（笔误、试操作），但避免了"评价被人删了"的争议和审计断链。如果将来确实需要清理，做一次性脚本（独立 PR），不在 v1 范围。
- **DM 而非群卡片**——产品决策。落地时 review 一遍 `notify_annotation` 实现，确认确实没走群消息分支。如果未来想要"评价被人质疑"等二级反馈红点，独立排期、独立 PR；落地时务必把这条写进 CLAUDE.md 提醒，避免后人想当然加上。
- **stakeholder 解析复用 Phase 3 helper**——如果 Phase 3 的 `_resolve_inline_stakeholders` 有 bug，annotation 也会跟着错。两个路径共享同一组单测就行，不要重复实现，也不要在 annotation 这边再包一层 wrapper。

---

## 5. 估算

**mentions rename + stakeholder 统一（Phase 1-5）**：

| Phase | 内容 | 工时 |
|-------|------|------|
| 1 | reader 双键归一化 + validator 严格化 | 0.5 d |
| 2 | publish + API + Pydantic 改名 | 0.5 d |
| 3 | events + SSE + relevance + notify + MCP + daily_report + **`_resolve_inline_stakeholders` + 替换 mention 收件人 + 新单测** | 1.5 d（V1 是 1.0 d，多 0.5 d） |
| 4 | 前端类型 + 组件 + SSE listener | 0.75 d |
| 5 | 文档 + 后续 TODO | 0.1 d |
| - | 全链路自测（含历史 YAML fallback、飞书卡片、MCP 切换、**留言不 @ 路径回归**） | 1.0 d（V1 是 0.75 d，多 0.25 d） |

**rename + 统一小计 ~4.35 人日**（V1 是 3.6，stakeholder 统一加 0.75）。

**annotations 引入（Phase 6，仅"加"，无改 / 删；通知 / 红点复用 Phase 3 helper）**：

| 步骤 | 内容 | 工时 |
|------|------|------|
| 6.1 | matter_index + validator + publish + 通知挂接 + 单测 | 0.75 d |
| 6.2 | API + Pydantic + 特性开关 + SSE + 单测 | 0.4 d |
| 6.3 | MCP 工具（仅 add） + 单测 | 0.2 d |
| 6.4 | 前端：types + AnnotationDialog + FileCard 渲染 + 手测 | 0.75 d |
| 6.5 | 文档 + 联调（HTTP / SSE / MCP / 飞书 DM 四路径）| 0.5 d |

**annotation 小计 ~2.6 人日**（比"无通知版本"+0.35 d，因为新增了 `_handle_annotation_appended` + `notify_annotation` + 对应单测；但通知 helper 复用，没重做）。

**总计 ~6.95 人日**。后续做一次性 YAML rewrite + scoring 列 migration + annotation AI 派生层各独立排期。
