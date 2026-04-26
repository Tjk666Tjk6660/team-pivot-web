# 上线前一次性数据迁移 · 实施计划

## Context

P1–P4.6 后端改造 + P4.5 前端配套已全部落地；`feat/pivot-matter` 分支上的后端只认 matter 格式索引（`{matter_id}.index.yaml`），而工作区磁盘上还残留少量老 thread 格式索引（`{slug}-discuss.index.yaml`）。上线前必须做一次性迁移，把老索引改写成 matter 索引，完成后系统里只剩一种格式。

本计划的目标：落出一个**幂等、可 dry-run、可单 slug 定点、可全量执行**的 `scripts/migrate_index_schema.py`，配套单元测试和一次集成演练。

## 探索事实

### 老 thread 索引形态（`server/index_files.py`）

文件名 `{slug}-discuss.index.yaml`，顶层：

```yaml
origin_path: discussions/<category>/<slug>/
created: <iso>
last_updated: <iso>
discussions:
- path: discussions/<category>/<slug>/
  status: open|concluded|closed|produced|pending
  files:
  - {path: NNN_author_type_hash.md, summary: '', refs: [{type: from|refer, path: ...}]}
timeline:
- {time, event: "X created thread|replied|mentioned|状态变更 A->B", file?: ..., mention?: {users, comments}}
```

### 新 matter 索引形态（`server/matter_index.py`）

文件名 `{matter_id}.index.yaml`（matter_id = slug），顶层：

```yaml
version: 1
matter: {id, title, current_status, created_at, updated_at}
timeline:
- {file, created_at, creator, owner, type, summary, quote?, refer?[], comments?[], status_change?, verifications?[], outcome?}
```

### 生产/测试数据现状

- 工作区：`tests/test_output/git/test-discuss/`
- 老格式 `*-discuss.index.yaml`：约 4 个（`本地测试 / 测试 / 部署测试 / 重构UI`）
- 新格式 `*.index.yaml`：约 80+（IntegTest-* 集成测试产物 + `mermaid / m2 / 11 / 55555` 等真实数据）
- 两种格式共存于同一个 `index/` 目录；迁移只动老的、跳过新的

### 能复用的现有工具

- `server/threads.py::_thread_meta` — 从首个 `type: proposal` 帖子取 title（frontmatter.title → body H1 → slug fallback）
- `server/posts.py::read_post` / `write_post` — 读 / 写 MD frontmatter（写时保留 body 字节不变）
- `server/matter_index.py::atomic_write_yaml`（需补导出；_atomic_write_yaml 是私有）— 原子 tmp+rename YAML 写入
- `server/publish.py::_resolve_mentions_for_index` — open_id → pinyin 解析（注册用户落 pinyin，未注册兜底 open_id；commit f3ce04c 已确立的口径），mention → comments 路径直接复用
- `server/workspace.py::write_session` — 统一 pull→commit→push 包装器
- `server/doc_types.py` / `server/matter_validator.py` — 迁移出的 matter item 需过一遍 validator 保证合法

## 映射规则（核心决策）

### 1. 状态机映射

| 老 thread status | matter current_status | 理由 |
|---|---|---|
| `open` | `planning` | 老"讨论中"对应新"事项仍在计划中" |
| `pending` | `planning` | 老写入中状态，同 open |
| `concluded` | `executing` | 老"已达成结论"=plan 阶段已收口，转入执行阶段；通过将该 thread **最后一条有效 reply 改写为 act** 承载 `status_change: {from: planning, to: executing}`，保留后续 append act/verify/result 的推进能力 |
| `closed` | `cancelled` | 老"已关闭"=事项到此为止 |
| `produced` | `executing` | 老"已转为项目"=已开始执行；处理同 concluded |

**`concluded`/`produced` → `executing` 的具体落地**：迁移脚本在生成新 matter timeline 时，对来源为 `concluded`/`produced` 的 thread，按 §2 的 `Rule [pivot 选取]` 选定一篇 post 作为 pivot，把它改写为 `act`，并挂 `status_change: {from: planning, to: executing}`；matter 顶层 `current_status = executing`。其余 post 维持默认 `think`。

边界（无 reply 的 thread）：若 thread 仅有 proposal、无任何 reply，`pivot = proposal`——proposal 自身改写为 act 承载 status_change。这是受用户决策的处理口径，不再降级为 `planning`。

### 2. 文档类型映射

老 thread 的 `status` 是**索引级**字段（在 `discussions[0].status` 上，不在任何单篇 MD frontmatter 上），`type` 是**文件级**字段（在每篇 MD frontmatter 上）。迁移脚本必须先看 `status` 决定整个 thread 的处理路径，再针对每篇 MD 写 `type`：

```
Rule [thread → matter type 映射]：

  case status ∈ {open, pending}:
    matter.current_status = planning
    所有 MD frontmatter.type = think
    timeline 中所有 item.type = think

  case status == closed:
    matter.current_status = cancelled
    所有 MD frontmatter.type = think
    timeline 中所有 item.type = think
    （不注入 status_change，matter 直接以 cancelled 终态产出）

  case status ∈ {concluded, produced}:
    matter.current_status = executing
    pivot = thread 内序号最大的 reply MD（按文件名前缀 NNN 取 max）
    IF pivot 不存在（thread 仅有 proposal）:
        pivot = proposal MD
    pivot 的 frontmatter.type = act
    pivot 对应的 timeline item:
        type = act
        status_change = { from: planning, to: executing }
    其余 MD frontmatter.type = think
    其余 timeline item.type = think
```

字段值映射对照（独立看 type 一列，不含 status_change）：

| 老 frontmatter type | 新 frontmatter / timeline type | 触发条件 |
|---|---|---|
| `proposal` | `think` | 默认 |
| `proposal` | `act` | 仅当该 thread `status ∈ {concluded, produced}` 且 thread 无任何 reply（pivot 退化为 proposal） |
| `reply` | `think` | 默认 |
| `reply` | `act` | 仅当该 reply 是 `status ∈ {concluded, produced}` thread 的最大序号 reply（即 pivot） |
| `comment` | `think` | 防御性映射；实际数据中无 `type=comment` 文件（grep `pivot-mirror` + `tests/test_output/git/test-discuss` 均 0 命中） |

**MD frontmatter 改写口径**：
- **MD frontmatter 仅改 `type` 字段值**（按上表对应到新 type）
- 其他 frontmatter 字段（`author` / `created` / `index_state` 等）**全部保持原样**
- MD body 与文件名 **完全不改**

理由：产品设计文档没有定义"新版 frontmatter schema"，index timeline item 已承载完整 `creator` / `owner` / `created_at` 信息，frontmatter 不需要重复存储。`type` 字段必须改写，是为了让 read 路径（`posts.py::read_post` / `_thread_meta` 等）拿到的 frontmatter 与 index timeline item 类型一致，规避双重映射。

**不保留 `legacy_type` 附加字段**（产品文档 §八.4 明确排除任何非 §八.3 列出的字段，保留会违反 schema 单一事实源原则）。如需溯源原始 type，回看 git history。

### 3. timeline item 字段映射

| 老字段 | 新字段 | 备注 |
|---|---|---|
| `discussions[0].files[i].path` | `timeline[i].file` | 前缀补 `discussions/<category>/<slug>/` |
| `discussions[0].files[i].summary` | `timeline[i].summary` | 为空时保留 `""`，不自动填充（writer 层不强制非空） |
| 帖子 frontmatter `author` | `timeline[i].creator` 和 `timeline[i].owner` | 老数据无 owner 概念，默认两字段同值 |
| 帖子 frontmatter `created` | `timeline[i].created_at` | 缺失用 INDEX 顶层 `created` |
| `refs[{type:from, path}]` | `timeline[i].quote` | 取第一条；多于一条记警告 |
| `refs[{type:refer, path}]` | `timeline[i].refer` | 保留顺序；去掉 `type:from` |

### 4. 事件流迁移

老 `timeline[]` 是 flat event log，不直接塞进 matter timeline（matter 的 timeline 是文件流）。逐事件处理：

- **`"X created thread"` / `"X replied"` 事件 → 丢弃**
  理由：这些事件的所有信息（file 路径、creator、created_at）已经被新 timeline 的 file item 完整承载——file item 由迁移脚本通过 `discussions[0].files[i]` 直接生成，留事件等于双写同一事实。

- **`"X mentioned"` 事件 → 转为对应 file item 的 `comments[]`**
  按下方 `Rule [mention → comments]` 执行。

- **状态变更事件（`"X 状态变更 A->B"` / `"X 从 ... 状态重新打开，原因：..."`）→ 丢弃**
  理由：老事件没有"由哪份文件触发"的字段，无法重建到新 schema 的 `status_change`（它必须挂在具体 timeline item 上）。老中间态丢弃，只保留 matter 顶层 `current_status` = §1 映射后的终态；当映射结果为 `executing`（来源 concluded/produced），由 §1 落地步骤选定的 act item 单独承载 `status_change: {from: planning, to: executing}`。

```
Rule [mention → comments]：对老 timeline 中 event 含 "mentioned" 的事件：

  1. event.file 缺失 → 记 warning，丢弃，不阻断
  2. 按 event.file 在新 matter timeline 找 timeline[i]：
     - 找不到（file 已被删/重命名）→ 记 warning，丢弃，不阻断
     - 找到 → 进入 step 3
  3. 追加到 timeline[i].comments[]：
     {
       created_at: event.time,
       body:       event.mention.comments,
       mentions:   _resolve_mentions_for_index([open_id, ...]),
                   # 复用 server/publish.py::_resolve_mentions_for_index
                   # 注册用户落 pinyin，未注册兜底 open_id（commit f3ce04c 已确立的口径）
       author:     event.event 字符串前缀（如 "huangshengli mentioned" 取 "huangshengli"）
     }
  4. 同一 file 上多条 mention 按 event.time 升序追加，保持原时序
```

实测依据：扫了 pivot-mirror 全部老 index，共 19 条 mention 事件，**100% 带 file 字段**，父级定位天然可达。

### 5. matter header 字段

- `matter.id` = slug
- `matter.title` = 复用 `_thread_meta` 的三级 fallback（首文 frontmatter.title → 首文 body H1 → slug）
- `matter.current_status` = 映射表 §1 的结果
- `matter.created_at` = 老 `created`
- `matter.updated_at` = 老 `last_updated`

### 6. 边界约束

- **幂等**：若 `{slug}.index.yaml` 已存在（和老 `{slug}-discuss.index.yaml` 共存），比较内容：一致 → 跳过；不一致 → 报错停止（防止误覆盖真实 matter 数据）
- **MD body 与文件名不动**：MD body 内容、文件名严格保留；frontmatter **仅改 `type` 字段值**（按 §2 表格映射），其他 frontmatter 字段（`author` / `created` / `index_state` 等）原样保留。产品文档 §八原则"原始事实不动"的实施口径：body 与文件名是事实，严格保留；`type` 改写是为了让 frontmatter 与新 timeline item type 对齐，规避 read 路径双重映射
- **un-indexed 前置清理**：迁移前先跑一次 `workspace.recover()`（已有逻辑能处理 legacy 和 matter 两类 un-indexed MD），避免遗漏文件
- **写入后删除旧文件**：`{slug}.index.yaml` 写成功 + fsync 后，再 `os.remove({slug}-discuss.index.yaml)`
- **单次 git commit**：整个迁移一次提交，message `chore: migrate legacy thread indexes to matter format`，committer = `team-pivot-web`，author 可以用迁移者账号（备份与回滚详细机制见下方独立段）

## 备份与回滚

迁移本质是一次磁盘改写（写新 index、删老 index、改少量 MD frontmatter 的 type 字段）。备份与回滚靠以下三道防线，**不写代码层面的 `.bak` 备份文件**——git 自身就是备份：

**第一道：git 是天然备份**
- 迁移脚本运行时改动直接落在工作目录里，全部呈现为 working-tree diff
- 跑完整个迁移后用一次 `git commit` 落地（message: `chore: migrate legacy thread indexes to matter format`）
- 在 `git push` 之前所有改动都是本地 reversible 的：review 不通过 → `git reset --hard HEAD~1` 直接回滚到迁移前
- 成功后再 `git push`，远端历史清晰可追溯（含 commit message 标记是迁移产生）

**第二道：脚本运行前置检查**
- 脚本启动时检查 `git status` 必须 clean（无未提交改动），否则拒绝运行——避免迁移产物和无关 wip 改动混进同一个 commit
- 检查工作目录在 `main` 分支，且与 `origin/main` 同步（避免迁移到错误分支或基于过时副本）
- 检查通过后才进入实际写盘

**第三道：生产实例的独立离线快照**
- 上线前在生产服务器执行 `git bundle create var/backup/pre-migration-<UTC时间戳>.bundle --all`，导出全仓快照（含所有 ref + 完整 history）
- bundle 文件存档至独立位置（运维 ops 库或对象存储），作为 git 仓库本身受损时的最终兜底
- 这一步只在生产实例做，测试实例不需要

**中间态崩溃的处理**：
- `_atomic_write_yaml` 与 `posts.write_post` 内部都走 tmp+rename，保证**单文件**写原子，不会出现"半写完"的 yaml 或 frontmatter
- 跨文件层面（写完新 yaml 还没删老 yaml / 改完 index 还没改 MD frontmatter）**不强制原子**；脚本崩溃后磁盘可能处于"部分迁移"状态
- 重新跑 `--apply`：幂等检查会跳过已迁移完的 thread（新旧 yaml 内容一致 → skip），处理剩下的；不需要专门的 recovery 工具
- 真无法靠重跑恢复时：`git reset --hard <pre-migration-commit>` 直接回到迁移前状态，fork 一份新副本重跑

## 实施

### 文件

- 新增 `scripts/migrate_index_schema.py` — 迁移主脚本（独立入口，不挂 uvicorn）
- 新增 `server/tests/test_migrate_index_schema.py` — 单元测试

### 脚本入口

```
uv run python scripts/migrate_index_schema.py --workspace <path> [--apply] [--slug SLUG] [--report <file>]
```

模式（**默认 dry-run**，不加 flag 就是只读分析）：
- **不加 flag**：dry-run 默认行为。读全部老 index，打印将产生的新 YAML，写报告，**磁盘不动、不 commit**
- **`--apply`**：显式落盘 + git 提交（不自动 push，仍需人工确认后 push）
- **`--slug SLUG`**：定点单个 slug（用于 dry-run 调试某一条边界 case）
- **`--report <file>`**：migration report 输出路径（默认 `var/migration-report.json`）

选择默认 dry-run 理由：迁移是高风险、磁盘不可逆操作（老文件会被删）；默认 dry-run 相当于"不打枪就走不了火"，比"默认 apply"安全得多。

### 模块切分

```python
# scripts/migrate_index_schema.py

@dataclass
class MigrationItem:
    new_index_data: dict                          # 待写入 {slug}.index.yaml
    md_frontmatter_updates: list[tuple[Path, str]]  # [(md 路径, 新 type 值)]，仅改 type 字段
    warnings: list[str]

def migrate_one(workspace, legacy_index_path) -> MigrationItem
    """纯函数：读老 yaml + 对应 MD frontmatter → 返回新 yaml dict、
    待改写的 MD type 值清单、警告列表。不做 IO 写入。"""

def discover_legacy(index_dir: Path) -> list[Path]
    """找出所有 *-discuss.index.yaml（忽略 *.index.yaml 新格式）。"""

def preflight_checks(workspace) -> list[str]
    """运行前置检查（详见"备份与回滚"段第二道）：
    - `git status` 必须 clean
    - 当前分支必须是 `main` 且与 `origin/main` 同步
    返回失败原因列表（空列表 = 通过）。`--apply` 模式下任一项失败即拒绝执行。"""

def apply_migration(workspace, legacy_paths, *, dry_run: bool) -> MigrationReport
    """串联 preflight_checks → recover → migrate_one(对每条) → 原子写新
    index yaml → 原子改写指定 MD frontmatter 的 type 字段（body 不动）→
    删除老 yaml → 生成 report。dry_run=True 时跳过写入与前置检查的"clean
    工作树"硬约束（让用户能在 wip 状态下预演），仅产出 report。"""

def main() -> int
    """CLI entry。"""
```

### 测试策略

`server/tests/test_migrate_index_schema.py`（纯函数单测 + 集成）：

- **纯函数 `migrate_one` 单测**（不走 IO）：
  - 典型 proposal + 多 reply（status=open）老 index → 正确新 shape，proposal 与 reply 默认映射 `type=think`，creator/owner 一致，quote 链通
  - status 映射全 5 值（open/pending → planning；concluded/produced → executing；closed → cancelled）
  - **concluded/produced 路径**：最后一条 reply 改写为 `act`，timeline item 上挂 `status_change: {planning, executing}`；matter `current_status=executing`
  - **concluded/produced 但无 reply**：降级为 `current_status=planning` + warning
  - mention 事件挂到对应 file item 的 `comments[]`，mentions 用 `_resolve_mentions_for_index` 解析为 pinyin（注册用户）/ open_id（兜底）
  - 多 `type:from` refs → 取第一条 + warning
  - 孤立 mention（file 不在 timeline）→ 丢弃 + warning
  - 帖子 frontmatter 缺失 author/created → fallback

- **集成 `apply_migration`**（临时目录）：
  - 造 3-4 份真实形态 legacy 文件（含 open/concluded/closed 三种 status，含 mention / reopen 事件）
  - `--dry-run`：断言没写任何文件、报告里字段正确
  - `--apply`：断言新 yaml 写成、老 `*-discuss.index.yaml` 被删、report 记录全部 case；并断言 concluded 来源 thread 的最后一条 reply MD 的 frontmatter `type` 已被改写为 `act`，body 字节级未变
  - 幂等：再跑一次 `--apply` 不炸（发现无 legacy 文件后退出）
  - 冲突：预置 `{slug}.index.yaml` 和 `{slug}-discuss.index.yaml` 共存且内容不一致 → 报错停止

### 运行节奏

上线前：

1. **准备独立部署的 Pivot 测试实例**：fork 一份 production workspace（含完整 git history 与 `index/`）作为该实例的工作目录；独立部署后端 + 前端，确保 `/api/matters/*` 与 UI 端到端可用。"独立实例"是一个完整的运行中 Pivot 服务，不是只跑迁移脚本的工作目录副本。
2. 在测试实例跑 `--dry-run`，检查 migration report 里每条 warning 是否可接受。
3. 确认无误后在测试实例跑 `--apply`，**完成 4 项人工核对**：
   1. matter 状态机跳转正确（`planning → executing` 仅出现在 `concluded`/`produced` 来源的 thread 上，且挂在被改写为 act 的最后一条 reply 上）
   2. timeline 已过滤冗余 `created/replied/mention/状态变更` 事件，只保留 file item 与其 `comments[]`
   3. MD frontmatter `type` 已映射到新文件类型，body 字节级未变，文件名未变
   4. mention → comments 转换完整：`comment.mentions` 形如 pinyin（注册用户）/ open_id（未注册兜底），author 字段已填
4. 主实例停服（或临时 read-only），同步最新 workspace，跑 `--apply`。
5. `git push`，启服。

## 验收

- `uv run python scripts/migrate_index_schema.py --workspace ./tmp-copy` 默认 dry-run 零 error 跑完，输出 report
- `--apply` 后 `tmp-copy/index/` 里无 `*-discuss.index.yaml`，仅 `*.index.yaml`
- 迁移产物 YAML 通过结构性检查（`matter` header 字段齐全、`timeline[].type ∈ VALID_DOC_TYPES`、必填字段非空）。**注意**：不跑 `validate_append`，因为它按"当前 current_status 允许什么类型"来校验，而历史文件写在 matter 不同阶段，无法逐条反向校验；结构性 sanity 足够
- 来源为 `concluded`/`produced` 的 matter：`current_status=executing`；timeline 中存在恰好一条 `type=act` 且 `status_change={planning, executing}` 的 item，对应 MD 的 frontmatter `type=act`
- MD body 字节级未变（迁移前后 `git diff -- discussions/**.md` 仅显示 frontmatter `type` 行变化）
- `GET /api/matters/{id}` 对迁移后的 matter 能返回正确 timeline，含 mention 转成的 comments
- 单测 `uv run pytest server/tests/test_migrate_index_schema.py -q` 全绿

## 前置依赖

- P1–P4.6 均已合入（已满足）
- `workspace.recover()` 处理 matter-type un-indexed 的分支（已在 `server/recovery.py` 合入）
- 评审门：本 plan 的核心映射决策（§1 状态机映射、§2 type→think 统一）需用户确认

## 不在本阶段范围

- 前端对迁移后 matter 的自动拉取 UI 变更（无需：前端已是 matter 模型驱动）
- 老 `/api/threads/*` 接口的下线（留给 P5）
- concluded/produced 来源 matter 的人工审查流程：默认按 §1 自动映射为 `executing`（最后一条 reply 改写为 act 承载 status_change）。若个别 matter 判定其实已无后续推进，运维在迁移后手动追加一篇 `result` 文件触发 `executing → finished/cancelled`（走正常 matter 工作流，迁移脚本不做特殊处理）
