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
- `server/posts.py::read_post` — 读 MD frontmatter
- `server/matter_index.py::atomic_write_yaml`（需补导出；_atomic_write_yaml 是私有）— 原子 tmp+rename YAML 写入
- `server/workspace.py::write_session` — 统一 pull→commit→push 包装器
- `server/doc_types.py` / `server/matter_validator.py` — 迁移出的 matter item 需过一遍 validator 保证合法

## 映射规则（核心决策）

### 1. 状态机映射

| 老 thread status | matter current_status | 理由 |
|---|---|---|
| `open` | `planning` | 老"讨论中"对应新"事项仍在计划中" |
| `pending` | `planning` | 老写入中状态，同 open |
| `concluded` | `finished` | 老"已达成结论"视为事项已收口；迁移后只能追加 `insight` 推进到 reviewed，无法再新增 act/verify/result（符合 matter 终态语义） |
| `closed` | `cancelled` | 老"已关闭"=事项到此为止 |
| `produced` | `finished` | 老"已转为项目"=结果已正式产出 |

**语义影响（concluded→finished 的副作用）**：matter 状态机规定 finished 态下**只允许**追加 `insight` 文件，且 insight 必然触发 `finished→reviewed`。也就是说被映射为 finished 的历史 matter，**不能再做实质推进**（不能再 append act/verify/result）——要么加一篇 insight 做复盘然后封存，要么就这样放着。这是 concluded→finished 的强决策面后果，用户已确认接受。

### 2. 文档类型映射

所有 legacy 帖子 frontmatter 的 `type = proposal | reply | comment` → matter `type = think`。

**不保留 `legacy_type` 附加字段**（产品文档 §八.4 明确排除任何非 §八.3 列出的字段，保留会违反 schema 单一事实源原则）。MD frontmatter 的老 type 字段**不改**（只改 INDEX），运维/AI 如需溯源可回看 MD frontmatter。

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

- `"X created thread"`、`"X replied"`：**丢弃**（文件本身的存在就代表这些事件）
- `"X mentioned" + file + mention{users, comments}`：定位对应 `timeline[i]`（按 file 路径精确匹配），追加到该 item 的 `comments[]`：`{created_at: 老 time, body: mention.comments, mentions: [user.open_id, ...], author: 从 event 前缀提取}`
- 状态变更事件（`"X 状态变更 A->B" / "X 从 ... 状态重新打开，原因：..."`）：**不合成 `status_change`** 到 timeline item（没法定位哪篇文件触发）；老的中间态丢弃，只保留 matter 顶层 `current_status` = 映射后的终态

定位失败的 mention（file 不在新 timeline 中）：丢弃 + 迁移报告记录 warning，不阻断。

### 5. matter header 字段

- `matter.id` = slug
- `matter.title` = 复用 `_thread_meta` 的三级 fallback（首文 frontmatter.title → 首文 body H1 → slug）
- `matter.current_status` = 映射表 §1 的结果
- `matter.created_at` = 老 `created`
- `matter.updated_at` = 老 `last_updated`

### 6. 边界约束

- **幂等**：若 `{slug}.index.yaml` 已存在（和老 `{slug}-discuss.index.yaml` 共存），比较内容：一致 → 跳过；不一致 → 报错停止（防止误覆盖真实 matter 数据）
- **MD 文件不动**：MD 内容、frontmatter、文件名均不改（产品文档 §八原则：原始事实不动）
- **un-indexed 前置清理**：迁移前先跑一次 `workspace.recover()`（已有逻辑能处理 legacy 和 matter 两类 un-indexed MD），避免遗漏文件
- **写入后删除旧文件**：`{slug}.index.yaml` 写成功 + fsync 后，再 `os.remove({slug}-discuss.index.yaml)`
- **单次 git commit**：整个迁移一次提交，message `chore: migrate legacy thread indexes to matter format`，committer = `team-pivot-web`，author 可以用迁移者账号

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
def migrate_one(workspace, legacy_index_path) -> (new_data: dict, warnings: list[str])
    """纯函数：读老 yaml + 对应 MD 文件 → 返回新 yaml dict + 警告列表。"""

def discover_legacy(index_dir: Path) -> list[Path]
    """找出所有 *-discuss.index.yaml（忽略 *.index.yaml 新格式）。"""

def apply_migration(workspace, legacy_paths, *, dry_run: bool) -> MigrationReport
    """串联 recover → migrate_one (对每条) → atomic write → delete legacy → 生成 report。"""

def main() -> int
    """CLI entry。"""
```

### 测试策略

`server/tests/test_migrate_index_schema.py`（纯函数单测 + 集成）：

- **纯函数 `migrate_one` 单测**（不走 IO）：
  - 典型 proposal+多 reply 老 index → 正确新 shape，`type=think`，creator/owner 一致，quote 链通
  - status 映射全 5 值
  - mention 事件挂到对应 file item 的 comments[]
  - 多 `type:from` refs → 取第一条 + warning
  - 孤立 mention（file 不在 timeline） → 丢弃 + warning
  - 帖子 frontmatter 缺失 author/created → fallback
  
- **集成 `apply_migration`**（临时目录）：
  - 造 2-3 份真实形态 legacy 文件（含 mention / reopen / concluded status）
  - `--dry-run`：断言没写任何文件、报告里字段正确
  - `--apply`：断言新 yaml 写成、老文件被删、report 记录全部 case
  - 幂等：再跑一次 `--apply` 不炸（发现无 legacy 文件后退出）
  - 冲突：预置 `{slug}.index.yaml` 和 `{slug}-discuss.index.yaml` 共存且内容不一致 → 报错停止

### 运行节奏

上线前：

1. 独立实例 clone production workspace 的只读副本
2. 在独立实例跑 `--dry-run`，检查 migration report 里每条 warning 是否可接受
3. 确认无误后在独立实例跑 `--apply`，人工 verify 新 matter 能通过 `/api/matters/{id}` 正常读
4. 主实例停服（或临时 read-only），同步最新 workspace，跑 `--apply`
5. `git push`，启服

## 验收

- `uv run python scripts/migrate_index_schema.py --workspace ./tmp-copy` 默认 dry-run 零 error 跑完，输出 report
- `--apply` 后 `tmp-copy/index/` 里无 `*-discuss.index.yaml`，仅 `*.index.yaml`
- 迁移产物 YAML 通过结构性检查（`matter` header 字段齐全、`timeline[].type ∈ VALID_DOC_TYPES`、必填字段非空）。**注意**：不跑 `validate_append`，因为它按"当前 current_status 允许什么类型"来校验，而历史文件写在 matter 不同阶段，无法逐条反向校验；结构性 sanity 足够
- `GET /api/matters/{id}` 对迁移后的 matter 能返回正确 timeline，含 mention 转成的 comments
- 单测 `uv run pytest server/tests/test_migrate_index_schema.py -q` 全绿

## 前置依赖

- P1–P4.6 均已合入（已满足）
- `workspace.recover()` 处理 matter-type un-indexed 的分支（已在 `server/recovery.py` 合入）
- 评审门：本 plan 的核心映射决策（§1 状态机映射、§2 type→think 统一）需用户确认

## 不在本阶段范围

- 前端对迁移后 matter 的自动拉取 UI 变更（无需：前端已是 matter 模型驱动）
- 老 `/api/threads/*` 接口的下线（留给 P5）
- concluded 人工审查流程（按上面 §1 规则自动映射为 `finished`，如个别 matter 判定不妥，运维在迁移后手动调整 `current_status` 字段；不做强制 per-matter 审查门）
