# Index 重构设计：thread/discussion → matter + timeline-first

**作者**：岳碧林
**日期**：2026-04-23
**状态**：draft，待评审
**依据**：`AI-docs/pivot-product.md` 第六至九节、第十节
**后续依赖**：本重构是「Web 端 AI 助手自主读 index」改造（见 `2026-04-23-ai-autonomous-context-design.md`，后出）的先决条件。

---

## 一、目标与范围

### 1.1 目标

把当前以 `thread / discussion` 为核心的 index 模型，重构为以 `matter` 为顶层、`timeline` 为唯一演进结构的模型。产出：

- 新的 index YAML schema（timeline-first）
- 后端 index 读写接口的统一模块
- 现有 index 文件的迁移脚本
- 过渡期 API 路由（旧路径与新路径并存）
- 前端完整改造（matter 详情页时间线视图 + 文件卡片创建交互 + verify/result 专属展示）
- 迁移后 `concluded` matter 的人工语义审查

### 1.2 第一版范围（do）

按 `pivot-product.md` 第十节，第一版支撑两条最小闭环：

- `planning / executing -> paused -> 恢复`
- `planning -> executing -> finished / cancelled -> reviewed`

对应到本次交付，完整清单：

**后端**
- 新 schema 的**头部 + timeline**结构完全实现
- 文件类型五类（`think / act / verify / result / insight`）全部支持写入与读取
- `status_change` 字段支持以上闭环的状态迁移
- 数据迁移脚本与迁移报告
- API 路由过渡（新路径 + 旧路径别名）

**前端**（对应 `pivot-product.md` 第九.1.1、十三节）
- matter 详情页改造为时间线视图：顶部时间轴 + 下方文件流
- 文件卡片上"基于此新增 think / act / verify"的三个入口；创建时系统自动写 `quote`
- `verify` 文件的 `verifications` 列表展示（表格，展示 target/judgement/comment）
- `result` 文件的 `outcome` 高亮展示
- `result` 的页面级创建入口（matter 详情页顶部、靠近时间轴，附带"将结束 matter"的确认提示）

**迁移配套**
- 迁移后人工审查步骤：对所有原 `concluded` matter 输出清单，由人工判定目标状态（`finished / cancelled / paused / executing / planning`），不默认自动归入某一态（见 3.2、3.6）

### 1.3 架构明确排除（非"延后"，是"永远不在本次 schema 里"）

以下字段 / 概念是 `pivot-product.md` 第八.4、十一节明确排除的，本次 schema 不引入，后续也不轻易加：

- `anchor / current_anchor`（当前阶段依据文件）
- `importance`
- 独立的 `goal` / `task` 对象
- 独立的 `transitions` 列表与独立的 `files` 列表
- 拆分的 `id / filename / path`（统一用 `file` 作为 path-as-id）
- GTD 派生概念

---

## 二、新 index schema

### 2.1 文件布局

保持**一个 matter 一个 index 文件**，文件命名从 `{slug}-discuss.index.yaml` 改为 `{matter_id}.index.yaml`。

`matter_id` 沿用现有 slug（迁移阶段一对一）。后续如需重命名，提供单独工具处理。

### 2.2 顶层结构

```yaml
version: 1

matter:
  id: xxx-xxx-xxx                   # 等同现 slug
  title: 人读标题
  current_status: planning|executing|paused|finished|cancelled|reviewed
  created_at: 2026-04-23T10:00:00+08:00
  updated_at: 2026-04-23T15:30:00+08:00

timeline:
  - ...   # 见 2.3
```

`version` 字段用于后续 schema 迭代的防御性兼容。

**`matter.title` 的来源**：现行 `server/threads.py:_thread_meta` 靠找 `type: proposal` 的帖子来定位标题（从 frontmatter.title → body H1 → filename 派生）。新 schema 没有 `proposal` 类型，迁移与新建策略：

- **迁移期**：对每个旧 thread，沿用 `_thread_meta` 的三级 fallback（首文 frontmatter.title → 首文 body H1 → slug 反推）抽出 title 写入 `matter.title`。抽取失败则落 slug。
- **新建期**：matter header 的 title 在 matter 被创建时由用户显式指定（`POST /api/matters` body 必填 title）；不再依赖某个具体文件的类型。
- **更新**：matter.title 是 header 快照字段，允许用户通过专门接口修改（见 5.3），修改记录以一条 `think` 文件承载。

### 2.3 timeline item 结构

每一项对应一篇文件。字段集按 `pivot-product.md` 第八.2、八.3 节定义：

```yaml
- file: discussions/Pivot/xxx/005_xxx_act_abc123.md
  created_at: 2026-04-23T15:30:00+08:00
  creator: dengke                     # 谁创建了这篇文件
  owner: liuyu                        # 谁负责推进这篇文件
  type: think|act|verify|result|insight
  summary: 文件的最小解释

  quote: discussions/Pivot/xxx/004_xxx_think_def456.md   # 单值，主承接
  refer:                                                  # 数组，补充参考
    - discussions/OtherMatter/...
    - discussions/YetAnother/...

  verifications:                      # 仅 type=verify 时出现
    - target: discussions/Pivot/xxx/003_xxx_act_a1b2.md
      judgement: passed|failed|cancelled
      comment: 简短评价

  outcome: finished|cancelled          # 仅 type=result 时出现

  comments:
    - created_at: 2026-04-23T15:31:00+08:00
      author: dengke
      body: 文本
      mentions: [liuyu]

  status_change:                      # 仅触发状态迁移时出现
    from: executing
    to: finished

  legacy_type: proposal|reply|comment  # 迁移期保留，见 3.2
```

### 2.4 字段约束

- `file` 是文件项的唯一身份（path-as-id），全库唯一
- `type` 五选一，严格校验
- `quote` 可为空（仅 matter 的第一篇文件允许空）
- `refer` 默认空数组
- `verifications[].target` 必须指向同 matter 或 refer 可达的 `act` 文件
- `status_change.from` 必须等于当前 `matter.current_status`；写入成功后更新 `matter.current_status = status_change.to`、`matter.updated_at = now`
- `legacy_type`：迁移产物，新建文件不写入；只用于读时向老客户端展示
- 第八.4 节列出的所有字段（`goal / task / transitions / files / anchor / importance / title / id / filename / path`）**禁止进入 schema**

---

## 三、数据迁移

### 3.1 输入输出

- 输入：`index/{slug}-discuss.index.yaml` 形如

  ```yaml
  discussions:
    - path: ...
      status: open|concluded|closed
      files:
        - path: 001_xxx.md
          summary: ''
          refs:
            - type: from
              path: .../000_xxx.md
            - type: refer
              path: .../other-thread/xxx.md
  timeline:
    - time: ...
      event: "xxx mentioned"
      mention: {...}
  ```

- 输出：`index/{slug}.index.yaml`，结构如 2.2 / 2.3

### 3.2 字段映射表

| 旧字段 | 新字段 | 说明 |
|---|---|---|
| `discussions[0].path` | —— | 拆分为 `matter.id`（slug）与单篇文件的 `file` |
| `discussions[0].status` | `matter.current_status` | 现行 `server/status_machine.py` 五态的初始映射：`open → planning`、`concluded → planning`（按 `pivot-product.md` 第十节判定）、`closed → cancelled`、`produced → finished`（已产出正式结果）、`pending → planning`（写入中的文件，迁移时单独处理，见下）。所有 `concluded` 迁入后进入 3.6 人工审查；所有 `produced` 迁入后进入 3.6.1 专项审查（看是否其实应为 cancelled）。同时保留 `legacy_status_at_migration` 字段记录旧值用于审计 |
| `discussions[0].files[].path` | `timeline[].file` | 值前缀补 `discussions/{category}/{slug}/` 变成全路径 |
| `discussions[0].files[].summary` | `timeline[].summary` | 直接复用 |
| `refs[{type:from}]` | `timeline[].quote` | 取第一条 `type:from`；多于一条取第一条并警告（期望每篇最多一个 `from`） |
| `refs[{type:refer}]` | `timeline[].refer` | 保留顺序 |
| 帖子 frontmatter `type: proposal \| reply \| comment` | `timeline[].type = think` + `timeline[].legacy_type = 原值` | 统一映射为 `think`，保留原值 |
| 帖子 frontmatter `author` | `timeline[].creator` 和 `timeline[].owner` | 两字段都填 author（旧数据无 owner 概念） |
| 帖子 frontmatter `created` | `timeline[].created_at` | 直接复用 |
| `timeline[]`（事件流） | `timeline[].comments` 或 `timeline[].status_change` | 见 3.3 |

### 3.3 事件流迁移策略

旧 `timeline[]` 里三类事件：

- `{event: "xxx created thread", file}` → **丢弃**，thread 创建等价于第一篇文件的存在本身
- `{event: "xxx replied", file}` → **丢弃**，回帖等价于该文件在 timeline 里的存在
- `{event: "xxx mentioned", file, mention: {users, comments}}` → 转为**该 file 对应 timeline item 的 comments 列表追加一条**：

  ```yaml
  comments:
    - created_at: <原 time>
      author: <从 event 字符串前缀提取，如 "yuebilin mentioned" → yuebilin>
      body: <原 mention.comments>
      mentions: <原 mention.users 的 user 字段列表>
  ```

- 状态变化事件（旧 `_status_event` 生成的字符串，如 `"xxx 从 concluded 状态重新打开"`）→ 转为对应文件的 `status_change` 字段。无法定位文件时写入"孤立 comment"并记录迁移警告。

### 3.4 迁移脚本

位置：`server/migrations/migrate_index_v1.py`

接口：

```python
def migrate_index_file(old_path: Path, new_path: Path) -> MigrationReport:
    """
    将单个旧 index 文件迁移到新 schema。
    返回 MigrationReport 包含 warnings 列表。
    """

def migrate_all(index_dir: Path, dry_run: bool = True) -> list[MigrationReport]:
    ...
```

运行策略：

1. 先 `dry_run=True` 跑全库，输出 report 列表到 `var/migration-report.json`
2. 人工审查 warnings
3. `dry_run=False` 再跑；每个新文件写成功后删除对应旧文件（非原子，失败时保留两份，用 report 追查）

迁移脚本**只运行一次**，完成后入 archive，不作为常驻代码。

### 3.5 迁移验证

每次迁移同时跑一组不变量检查：

- 新 index 文件数 == 旧 index 文件数
- 每个旧 `files[].path` 在新 `timeline[].file` 中有且仅有一条对应项
- 每篇文件的 `comments` 数量 == 旧 timeline 中以该文件为 `file` 字段的 mention 事件数
- 每个旧 `refs` 条目在新 `quote / refer` 中都能找到落点

失败则中止、报错、不写入。

### 3.6 迁移后 `concluded` 人工审查

所有原 `concluded` matter 初步被映射为 `planning`。迁移脚本额外输出清单 `var/migration-concluded-review.md`：

```markdown
# Concluded 审查清单 (生成于 2026-04-23)

## {matter_id_1}
- title: ...
- 最后一条文件: 005_xxx_think_abc.md
- 旧 status: concluded
- 当前 status (初步): planning
- 建议目标态: [ ] finished  [ ] cancelled  [ ] paused  [ ] executing  [ ] planning
- 理由:

## {matter_id_2}
...
```

交付流程：

1. 迁移脚本产出该清单
2. 邓柯 / 刘昱 逐条勾选目标态，补理由
3. 岳碧林据此跑一次性脚本 `apply_concluded_review.py`，对每个 matter 追加一条 `think` 文件（或 `result` 文件，取决于目标态是否为终态）说明"迁移审查结论"，并触发 `status_change`

这保证状态语义不通过"后台一刀切"变更，而是每个 matter 都留一条可审计的时间线记录。

### 3.6.1 `produced` 状态专项审查

同 3.6 的形式，输出 `var/migration-produced-review.md`，逐条由人工定最终态（`finished / cancelled`）。`produced` 在现行状态机里没有出口（`ALLOWED_TRANSITIONS["produced"]` 为空集），实际用法少，审查成本可控。

### 3.7 `pending` 状态文件与 `index_state` 字段

现行架构：
- 每篇 post frontmatter 带 `index_state: un-indexed | indexed`
- `server/recovery.py:repair_partial_writes` 扫 un-indexed 的文件然后调 `create_thread_index / append_reply_to_index` 补进 index

迁移处理：

- **迁移前先跑一次 `repair_partial_writes`**，把所有 un-indexed 状态的文件补进旧 index，避免迁移时漏数据
- 迁移完成后，`index_state` 字段的定位：
  - **保留在 post frontmatter 里**：不挪到 timeline item，因为这是 post 层面的"写入原子性"标记，不是 index 层面的语义
  - `recovery.py` 改写为：扫 un-indexed → 调 `MatterIndex.append_item(...)` 补进新 schema，而不是调旧函数

### 3.8 `SUMMARY*.md` / `RESULT*.md` 文件

现行 `server/threads.py:_list_posts` 和 `server/posts.py:scan_un_indexed` 都**显式跳过**这些特殊文件。它们在数据库不存在，是直接放在 thread 目录下的静态产物。

迁移处理：

- **不作为 timeline item 迁入**
- 保留文件在 thread 目录（`discussions/{category}/{slug}/SUMMARY*.md`）作为 legacy artifact
- 迁移报告列出所有发现的 SUMMARY / RESULT 文件清单，交给邓柯 / 刘昱判断是否需要转写成 `insight` 或 `result` 类型的正式 timeline item（一次性脚本，不在主迁移流程）
- 新 schema 下不再生成 `SUMMARY*.md` / `RESULT*.md`；同等信息由 `insight` / `result` 类型文件承担

---

## 四、后端模块改造

### 4.1 新增模块：`server/matter_index.py`

职责：统一所有 index 读写。所有业务代码只通过这个模块访问 index，不再有 `yaml.safe_load(index_path)` 散落在各处。

接口（核心集）：

```python
@dataclass
class MatterHeader:
    id: str
    title: str
    current_status: str
    created_at: str
    updated_at: str

@dataclass
class TimelineItem:
    file: str
    created_at: str
    creator: str
    owner: str
    type: str                   # think|act|verify|result|insight
    summary: str
    quote: str | None
    refer: list[str]
    verifications: list[dict] | None
    outcome: str | None
    comments: list[dict]
    status_change: dict | None
    legacy_type: str | None


class MatterIndex:
    """单个 matter index 文件的读写句柄。"""

    @classmethod
    def load(cls, index_dir: Path, matter_id: str) -> "MatterIndex": ...

    @property
    def header(self) -> MatterHeader: ...

    @property
    def timeline(self) -> list[TimelineItem]: ...

    def find_item(self, file_path: str) -> TimelineItem | None: ...

    def append_item(self, item: TimelineItem) -> None: ...

    def append_comment(self, file_path: str, comment: dict) -> None: ...

    def apply_status_change(self, file_path: str, from_: str, to: str) -> None:
        """原子更新文件的 status_change 字段 + matter.current_status + updated_at。"""

    def save(self) -> None: ...   # 原子写
```

约束：

- 所有写操作走 `_atomic_write_yaml`（沿用现 `server/index_files.py` 的实现）
- 所有读操作都返回 dataclass 副本，不泄露可变字典
- `load` 失败（文件缺 / schema 不匹配）抛明确异常，不静默返回空

### 4.2 现有模块改造

**`server/index_files.py` 全体函数**（该模块整体改造为适配层，内部代理到 `MatterIndex`）：

| 函数 | 原行为 | 改造 |
|---|---|---|
| `create_thread_index` | 建 thread 时写初始 index（`discussions[].status=open`、timeline 首条 `created thread`） | 改为 `MatterIndex.create(matter_id, title, initial_item)`，写入新 schema 头部 + 首条 timeline item |
| `append_reply_to_index` | 回帖时写 `discussions[0].files[].path` + timeline `replied` 事件 | 改为 `MatterIndex.append_item(TimelineItem)`，`refs[]` 构造改走 `_build_reply_refs` 的新实现（见下） |
| `_build_reply_refs` | 构建旧 `refs: [{type: from, path}, {type: refer, path}]` | 重写为返回 `(quote: str, refer: list[str])`；调用方按 `TimelineItem.quote / refer` 赋值 |
| `append_standalone_mention` | 写旧 timeline 事件流（独立 @人事件） | 改为 `MatterIndex.append_comment(file_path, comment)` 挂到目标文件下 |
| `change_thread_status` | 写旧 `discussions[0].status` + timeline 文本事件 | 改为 `MatterIndex.apply_status_change(file_path, from_, to)`，写 `status_change` 到触发文件项 + 更新 header |
| `read_thread_index` | 读 `{status, last_updated}` 头部 | 改为返回 `MatterHeader` 的兼容 dataclass |
| `get_mentions_by_file` | 扫旧 timeline 聚合 mention | 改为从 `timeline[].comments` 聚合，返回结构不变 |

**其他受影响模块**：

| 模块 | 为什么被牵动 | 改造 |
|---|---|---|
| `server/threads.py:list_threads / get_thread / _thread_meta` | 扫 `index/` 拼 `ThreadMeta / ThreadDetail`；`_thread_meta` 靠 `type: proposal` 找主帖 | 改为通过 `MatterIndex.load` 读；title 改为从 `MatterHeader.title` 取（迁移时已抽），不再依赖 proposal 类型 |
| `server/recovery.py:repair_partial_writes / _repair_post` | 扫 un-indexed 文件、直接调 `create_thread_index / append_reply_to_index` | 改为调 `MatterIndex.create / append_item`（新 schema）。见 3.7 |
| `server/publish.py` | 发帖流程，调 `append_reply_to_index` / `create_thread_index` | 接口签名改：接受 `type` 参数（`think / act / verify / result / insight`），默认 `think`；quote 由前端传入 |
| `server/drafts.py` | 草稿保存；字段含 `reply_to / references` 对应未来的 quote/refer | 字段保持兼容，内部发布时映射到新 schema 的 `quote / refer` |
| `server/mentions.py` | 处理 @ 通知与 comment 关联 | 新 comment 写在 `timeline[].comments[]`；流程里调 `MatterIndex.append_comment` 替换 `append_standalone_mention` |
| `server/notify.py` | 飞书通知推送 | 接口不改，但数据来源切到新 schema；测试回归 |
| `server/favorites.py`, `server/read_state.py`, `server/inbox.py` | 以 `(category, slug)` 作为 thread 身份存 db | 第一版**保持 `(category, slug)` 键不变**（新 matter_id 就等于 slug）；后续若要引入纯 matter_id 维度再做 db migration。本次只做读写 shim 适配 |
| `server/git_ops.py` | Git 提交 / 同步；可能含 `"-discuss.index.yaml"` 文件名 | grep 后确认是否硬编码旧文件名；若有改为新命名 `.index.yaml`；逐提交保持 git 可读 |
| `server/ai/context.py:build_context_from_files` | 按三段路径读文件 | 保持接口不变，内部保留；A 阶段作为 `read_file` tool 底座复用 |
| `server/api/ai.py:list_ai_files` | 通过 `list_threads` 拼文件列表 | A 改造阶段连同 `/api/ai/files` handler 一起删除（见 A 文档） |
| `server/api/discussions_api` 等其他 handler | 依赖 `list_threads / get_thread` | 自动随 `threads.py` 改造受益；不需额外改代码，但回归测试要覆盖 |

### 4.3 已废弃但保留的函数

`server/index_files.py` 作为过渡期适配层保留；内部实现全部代理到 `MatterIndex`。迁移完成、所有调用方切到新模块 6 个月后再彻底删除。

### 4.4 数据库表盘点

`var/data.db`（SQLite，经 `server/db.py`）当前存储：

| 表 | 受影响程度 | 处理 |
|---|---|---|
| `users / api_tokens / sessions` | 不受影响 | 不动 |
| `ai_conversations` | 按 `(user, thread_key)` 存；A 改造会扩字段（`read_files`） | B 不动，留给 A |
| `drafts` | 按 `(user, thread_key)` 存；字段含 `reply_to / references` | 键不改；字段语义在 publish 时映射 |
| `favorites / read_state / inbox` | 以 thread 维度存 | 第一版键不改（matter_id 等于 slug），不做 db migration |
| `settings` | AI 相关配置 | 不动 |

**本次 B 不需要 alembic / schema migration 脚本**。数据库 schema 保持不变，通过应用层解释键值来兼容新 matter 身份。

---

## 五、API 路由过渡

### 5.1 策略

**旧路径别名 + 新路径并存**，不在本次做破坏性改动。

| 旧路径 | 新路径 | 说明 |
|---|---|---|
| `/api/threads/{category}/{slug}` | `/api/matters/{matter_id}` | 新路径服务新前端；旧路径内部重定向到新 handler |
| `/api/threads/{category}/{slug}/posts` | `/api/matters/{matter_id}/timeline` | 旧路径返回兼容结构，新路径返回 timeline 结构 |
| `/api/ai/threads/{category}/{slug}/...` | `/api/ai/matters/{matter_id}/...` | AI 相关路由，A 改造时直接用新路径 |

### 5.2 前端迁移窗口

- 本次交付：后端同时响应新旧路径，前端仍调旧路径
- 本次之后：前端逐步切新路径，旧路径在访问日志连续 30 天为零后拆除

### 5.3 具体响应结构

旧路径返回结构**字段一一保持**，不增不减，即使内部数据源已是新 schema。新路径直接返回 dataclass 序列化的 `{matter, timeline[]}`。

---

## 六、前端改造

本次前端作为整体交付，不走过渡路线。对应 `pivot-product.md` 第九.1.1、十三节。

### 6.1 matter 详情页时间线视图

改造 `web/src/pages/ThreadDetail` 相关组件（或新建 `MatterDetail`，旧路由以别名保留）：

- **顶部时间轴**：水平或垂直时间轴，按 `created_at` 排列 timeline item，可点击/拖动跳转到对应文件卡片
- **文件流区**：时间轴下方按时间顺序展示所有 timeline item 卡片
- **文件卡片**：默认折叠（摘要 + 类型徽章 + creator/owner），点击展开全文；展开体验沿用现 `ThreadDetail` 的折叠/展开逻辑，不另起新交互
- **类型徽章**：`think / act / verify / result / insight` 用不同颜色区分
- **引用关系展示**：卡片上显示 `quote` 指向（可点击跳转到对应卡片）、`refer` 数量（可展开看具体文件）

### 6.2 文件卡片上"基于此新增"入口

每个文件卡片提供三个入口按钮（需求原文第九.1.1 节）：

- **基于此新增 think**
- **基于此新增 act**
- **基于此新增 verify**

点击后：

1. 弹出文件创建表单（type 预选、quote 预填当前卡片对应文件路径）
2. 用户填 summary、owner、正文
3. 提交后调 `POST /api/matters/{matter_id}/timeline` 新增一条 item
4. `quote` 由前端自动从当前卡片带入，用户不可改（防止出现用户手动打破"基于某文件继续"的心智）

### 6.3 `verify` 专属展示

`type=verify` 的卡片额外展示 `verifications` 表格：

| Target | Judgement | Comment |
|---|---|---|
| path.md | passed/failed/cancelled 徽章 | 简短评价 |
| ... | ... | ... |

点击 Target 列跳转到对应 `act` 文件卡片。Judgement 三色：绿（passed）/ 红（failed）/ 灰（cancelled）。

### 6.4 `result` 专属展示与页面级入口

`type=result` 卡片在文件流里额外用 outcome 高亮：

- `outcome=finished`：蓝底"已完成"标签
- `outcome=cancelled`：灰底"已取消"标签

matter 详情页顶部（靠近时间轴）新增**页面级 result 创建入口**：

- 按钮文案"生成 Result"
- 点击先弹确认对话框：「创建 Result 代表当前 matter 将被正式结束为 finished 或 cancelled，确定继续？」
- 确认后进入 result 创建表单：outcome 必填、summary 必填、无 quote（result 对象直接是 matter 本身）
- 成功后自动触发 `status_change` 从当前态迁移到 `finished` 或 `cancelled`

### 6.5 既有 UI 的影响

- `FileTreeBrowser.tsx`、`AIPane.tsx` 在 A 改造里处理，本次 B 不动
- 讨论列表页（`Dashboard`、`ThreadListPane`、侧栏）：将 "thread" 文案替换为 "matter"，状态徽章从 `open / concluded / produced / closed / pending` 切换到 `planning / executing / paused / finished / cancelled / reviewed` 六态（涉及 `StatusBadge.tsx / StatusControl.tsx`）
- **`ThreadDetailPane.tsx` 的内联回帖表单**（当前代码中以 `replyBody / replyMentions / replyDraftId / replyTo / replyReferences` 等 state 直接管理，不存在独立 `ReplyEditor` 组件）：迁移为"基于此新增 think"的内部实现。具体动作：
  - 移除 `replyReferences` 相关 state 与 UI（跨 thread 引用逃生舱由 A 改造决策去除，B 顺手清理掉对 `references` 字段的前端写入）
  - 保留旧按钮文案"回复"直到用户习惯新术语；按钮行为等价于在当前 matter 末尾追加一条 `type: think`、`quote=当前 target` 的 timeline item
  - 与 A 的 `pendingReplyTarget` 机制保持兼容（用户点"AI 回复"时仍能把 target 带入，逻辑不变）
- `api.ts` 中 `fetchAIFiles`、与 `reference_files` 相关的字段，由 A 改造阶段统一清理

---

## 七、测试计划

### 7.1 单元测试

- `server/tests/test_matter_index.py`（新增）
  - `MatterIndex.load / save / append_item / append_comment / apply_status_change` 各自的正常与异常路径
  - 原子写失败时旧文件不被破坏
  - status_change 的 `from` 不匹配当前状态时抛异常

- `server/tests/test_migrate_index_v1.py`（新增）
  - 造几个典型旧 index 样本：空 timeline、有 mention、有 concluded、跨 thread refs、多 `type:from` 异常情况
  - 对每个样本跑迁移，断言新 schema 结构正确
  - 断言不变量检查（3.5 节）全部通过

- `server/tests/test_threads.py / test_recovery.py / test_index_files.py`（改造）
  - 这些测试现在直接构造旧 YAML；改为构造新 YAML 或通过 `MatterIndex` API 构造；断言输出保持兼容

- `server/tests/test_matter_api.py`（新增）
  - `POST /api/matters/{matter_id}/timeline` 创建新文件（think / act / verify / result）
  - quote 字段由请求带入、服务端校验合法性（必须是同 matter 或 refer 链可达）
  - result 创建时自动触发 status_change

### 7.1b 前端测试

**前置：当前项目没有前端测试栈**。`web/package.json` 不含 `vitest / jest / @testing-library`。本次先补最小测试基础设施：

- 安装 `vitest`、`@testing-library/react`、`@testing-library/user-event`、`jsdom`、`@vitest/ui`
- `vite.config.ts` 增加 test 配置（environment: jsdom、setupFiles）
- `package.json` 加 `"test": "vitest run"` 和 `"test:watch": "vitest"` 脚本
- 新建 `web/src/__tests__/` 目录 + `vitest.setup.ts`

测试用例：

- `web/src/__tests__/MatterDetail.test.tsx`
  - 时间线视图按时间排序
  - 点击时间轴跳转到对应卡片
  - 文件卡片默认折叠、点击展开
  - "基于此新增"按钮弹出表单、quote 预填正确、提交路径正确
- `web/src/__tests__/VerifyCard.test.tsx`
  - `verifications` 表格渲染正确
  - judgement 颜色对照正确
- `web/src/__tests__/ResultCreation.test.tsx`
  - 顶部"生成 Result"按钮弹确认对话框
  - 提交后触发状态迁移
- `web/src/__tests__/StatusBadge.test.tsx`
  - 六态 badge 文案 + 颜色

### 7.2 回归验证

选 3 个真实 thread 拷贝到 staging：一个纯讨论（open），一个有 mention，一个 concluded。

- 跑迁移脚本
- 启动服务
- 用浏览器走一遍："打开讨论列表 → 点进 thread → 看帖子 → 回帖 → 查看 index" 路径全部通
- 对比迁移前后服务端返回的 `/api/threads/...` JSON 应逐字段一致

### 7.3 性能

现有数据量小，不做性能基准。加一条 warning：如果将来单个 matter timeline item 数 > 500，`MatterIndex.load` 要考虑懒加载或分段。

---

## 八、实施步骤

以"代码可运行、测试绿"为节奏。每步跑全量测试。

1. **M1：新 schema 落地**
   - 实现 `server/matter_index.py` + 单测
   - 不接入任何现有调用方
   - 产出：能读写新 yaml 的模块

2. **M2：迁移脚本**
   - 实现 `server/migrations/migrate_index_v1.py` + 单测
   - `dry_run` 跑本地 pivot-database 全量
   - 产出：迁移报告 + 所有 warning 有解释

3. **M3：`index_files.py` 改造为适配层 + 牵动模块同步**
   - `index_files.py` 全体函数（`create_thread_index / append_reply_to_index / append_standalone_mention / change_thread_status / _build_reply_refs / read_thread_index / get_mentions_by_file`）内部代理到 `MatterIndex`
   - 同步改造 `threads.py` / `recovery.py` / `publish.py` / `drafts.py` / `mentions.py`（见 4.2）
   - `git_ops.py` 中对 index 文件名的 hardcoded 引用 grep 并改掉
   - 旧函数签名保持向下兼容；现有测试（`test_index_files.py / test_threads.py / test_recovery.py / test_drafts.py / test_discussions_api.py / test_mentions.py`）维持绿
   - 产出：服务层看到的行为不变，底层换了

4. **M4：真正迁移本地数据**
   - 关服务 → 跑迁移脚本 `dry_run=False` → 起服务 → 跑回归验证（7.2）
   - 产出：本地环境已切新 schema

5. **M5：新 API 路由与兼容别名**
   - `/api/matters/...` 实现（包含 `POST /api/matters/{matter_id}/timeline` 创建文件接口）
   - 旧路径内部重定向
   - 产出：新前端和 A 改造可接入

6. **M6：前端测试基础设施 + 时间线视图 + 文件卡片交互**
   - 安装 vitest + @testing-library 等（见 7.1b），加 `npm run test` 脚本
   - `MatterDetail` 组件：时间线 + 文件流 + 类型徽章 + 引用关系展示
   - 文件卡片"基于此新增 think / act / verify"三个入口 + 创建表单
   - `verify` 卡片的 `verifications` 表格展示
   - `result` 卡片高亮 + matter 详情页顶部的"生成 Result"入口与确认流程
   - 讨论列表、侧栏文案与状态徽章（`StatusBadge.tsx / StatusControl.tsx`）按新六态更新
   - `ThreadDetailPane.tsx` 内联回帖表单去除 `replyReferences` 相关 state 与 UI
   - 前端单测 + 本地跑通全链路

7. **M7：Concluded 人工审查**
   - 基于 M4 输出的 `var/migration-concluded-review.md` 与邓柯 / 刘昱对齐结论
   - 跑 `apply_concluded_review.py`，对每个 matter 追加一条迁移审查文件并触发状态迁移
   - 产出：所有 matter 的 `current_status` 反映真实状态

8. **M8：部署到服务端**
   - 先在本地自测通过（需求原文六的要求）
   - 部署流程中加一次性迁移步骤 + 审查脚本
   - 产出：线上完成重构

---

## 九、风险

- **迁移脚本的 `refs` 映射**：现有 `_build_reply_refs` 写入的 refs 不一定完整（历史数据里部分用户没勾 references，`refs` 为空）。新 schema 的 `quote` 在这种文件上也会是空。这是历史债务，迁移期**不主动补全**，仅记录；后续若 A 改造发现严重缺口再单独补刀。
- **Concluded 人工审查的工作量**：`concluded` matter 数量可能较多，M7 环节需要邓柯 / 刘昱逐条审阅。若数量过大，需要讨论是否先默认全部归入 `planning` 静态存在，再由用户在使用中自然推进。
- **原子性**：迁移过程不是原子（逐文件处理）。中途失败会留下部分新文件、部分旧文件。恢复策略：保留旧文件不删，直到全部新文件写成功；失败可重跑。
- **前端改造的回归面**：M6 改动文件较多（讨论列表、侧栏、详情页、回帖入口），需要覆盖完整手动回归；现有 E2E 如有缺口要补齐。
- **Git 提交**：新 index 文件是新路径，Git 会当作"删一批旧文件 + 加一批新文件"。建议单独一次提交，commit message 清晰标注为 schema 迁移。

---

## 十、评审关注点

请评审时重点反馈以下几个取舍：

1. **type 映射**（3.2）：统一映射为 `think` 是否合适？是否需要按 frontmatter `type` 做更细映射（如 `proposal → think`、`reply → think`、某些明显是方案的帖子 → `act`）？
2. **路由过渡窗口**：新旧并存多久？是否定死 30 天后拆旧路径，还是无期限保留
3. **迁移脚本运行时机**：部署到服务端时是否需要停机窗口，还是可以在线迁移（每个 matter 单独处理期间读写加文件锁）
4. **"生成 Result"按钮的位置与文案**：详情页顶部是否过于显眼？还是希望它收起在菜单里避免误触
5. **"回复"按钮文案过渡**：M6 中保留旧文案"回复"作为"基于此新增 think"的实现，等用户习惯再改——保留多久？
