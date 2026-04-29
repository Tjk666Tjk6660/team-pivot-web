# Pivot 与我相关未读 · 实施计划

## Context

matter 列表把未读拆成红 / 灰：跟我相关的事走红色强提示，普通时间线更新走灰色弱提示。再加一个"全部 / 与我相关"筛选，状态服务端持久化（跨设备）。判定纯靠程序规则，不引入 AI。

三条硬约束（对应 [`relevance-unread-tech-design-v3.1.md`](./relevance-unread-tech-design-v3.1.md)）：

- 同一文件被 @ 多次 → 红点累加（不去重）。
- 已读后再次被 @ → 红点重新出现（每条 @ 是独立事件）。
- 自己触发的动作不投递给自己（self-exclusion）。

口径对齐：

- **mention "已读"跟卡片正文阅读绑定**——`POST /matters/{id}/files/{f}/read` 触发清读，跟 [`read-state-tech-design.md`](./read-state-tech-design.md) 共用同一个端点和触发器。点 matter 标题不算阅读。
- 现有 `read_state` 表（matter 级未读高水位线）服务于 gray 数计算，本期**不动**；新表 `relevance_events` 跟它正交。
- 飞书 DM（`server/notify.py`）保持原有 mention 推送，跟红点是两条独立通道。

## 关键事实（决定方案可行性）

- **DB 迁移天然兼容**：`server/db.py` 用 `CREATE TABLE IF NOT EXISTS`，新表追加到 SCHEMA 末尾即可。
- **判定信号已结构化**：`comments[].mentions: [open_id]` 是 publish 路径写入的（`server/publish.py:625`），实时写无需解析正文。
- **事件总线已存在**：`server/events.py` 的 `TOPIC_FILE_APPENDED / TOPIC_MATTER_CREATED / TOPIC_COMMENT_APPENDED` 三个 topic 已在 `publish.py` 三条写入路径 emit；本期只是新增订阅者。
- **文件级 read 端点已上线**：`POST /matters/{id}/files/{f}/read` 由 `read-state-tech-design.md` 实现并合入（commit `d2e4c86`），本期只在它身上多挂一段 side effect，不抢端点所有权。
- **SSE 通道已具备**：`/api/matters/events` 推 `matter.updated`，前端 `MatterEventsProvider` 触发 list / detail refetch 自动带上新字段，事件层不动。
- **Repo / API 模板**：`server/file_reads.py` + `server/api/matters.py` 文件级 read 端点是最近邻参照样本。

## 数据契约（锁定）

### SQLite 表

加在 `server/db.py` 的 `SCHEMA` 末尾：

```sql
CREATE TABLE IF NOT EXISTS relevance_events (
    user_open_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,    -- basename
    kind          TEXT NOT NULL,    -- 'file' | 'mention'
    reason        TEXT NOT NULL,    -- file: owner_assigned/reply_to_my_*/...
                                    -- mention: comment_mention
    event_at      TEXT NOT NULL,    -- ISO 8601
    actor_pinyin  TEXT NOT NULL,
    created_at    REAL NOT NULL,
    read_at       REAL,             -- NULL = 未读
    PRIMARY KEY (user_open_id, matter_id, filename, kind, event_at, actor_pinyin)
);
CREATE INDEX IF NOT EXISTS idx_re_user_unread
    ON relevance_events(user_open_id, read_at, matter_id);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_open_id TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    updated_at   REAL NOT NULL,
    PRIMARY KEY (user_open_id, key)
);
```

- 复合 PK 让 file 行（每文件一条）和 mention 行（每条评论一条）在同一文件上不撞键。
- `event_at` 用 ISO 字符串（matter index 里就是 ISO，PK 直接复用，不需要类型转换）。
- `INSERT OR IGNORE`（real-time writer 用）+ `SELECT-then-INSERT`（scanner 用）共同保证幂等。

### 列表接口扩展

`GET /api/matters` 每个 item 增加：

```jsonc
{
  "id": "...",
  "unread_count": 8,           // 老字段保持 = red + gray,老前端不破
  "red_unread_count": 4,
  "gray_unread_count": 4
}
```

### 详情接口扩展

`GET /api/matters/{matter_id}` 每个 timeline item 增加 / 评论行增加：

```jsonc
{
  "file": "...",
  "relevance_reason": "reply_to_my_file",   // null 表示文件级不相关
  "comments": [
    { ..., "mention_unread_for_me": true }  // 评论级,每条独立
  ]
}
```

### HTTP 端点

```
POST /matters/{id}/files/{filename}/read   (在 read-state 设计端点上挂 side effect)
  → file_reads 首读记录 + 该文件下所有未读 relevance_events 置 read_at=now

GET  /api/me/preferences                   (沿用通用 KV 风格)
  → 200 {"matter_list_filter": "mine", ...}
PUT  /api/me/preferences/{key}
  body {"value": "mine"}
  → 200 {"key": "matter_list_filter", "value": "mine"}
```

`{key}` 走白名单（本期只接受 `matter_list_filter`），防止表被滥用。

## 服务端实现

### 新增 `server/relevance.py`

`compute_relevance(item, matter_data, user) -> (ok, reason)`，按优先级首个命中即返回：

| 优先级 | reason | 条件 |
|---|---|---|
| 1 | `owner_assigned` | item.owner == user.pinyin 且 item.creator != user.pinyin |
| 2 | `reply_to_my_file` | item.quote 指向的文件 .creator == user |
| 3 | `reply_to_my_owned` | item.quote 指向的文件 .owner == user |
| 4 | `verify_my_file` | item.verifications[*].target 任一指向用户的文件 |
| 5 | `in_my_matter` | matter 首篇 proposal.creator == user |

mention 不在这里判定，writer / scanner 直接根据 `comment.mentions` 写。

### 新增 `server/relevance_events.py`（Repo）

```python
class RelevanceEventsRepo:
    # writer 用,INSERT OR IGNORE 抗并发
    def insert_file(self, ...) -> bool: ...
    def insert_mention(self, ...) -> bool: ...
    # scanner 用,显式 SELECT-then-INSERT
    def exists(self, *, user_open_id, matter_id, filename,
               kind, event_at, actor_pinyin) -> bool: ...
    # 已读 / 详情 / 列表
    def mark_all_read_for_file(self, user_open_id, matter_id, filename) -> int: ...
    def unread_breakdown_per_matter(self, user_open_id) \
            -> dict[str, tuple[int, int]]: ...
    def unread_mention_keys_for_matter(self, user_open_id, matter_id) \
            -> set[tuple[str, str, str]]: ...
```

### 新增 `server/relevance_writer.py`（事件总线订阅）

`install(events_bus, users_repo, repo, workspace) -> Unsubscribe`：

| 事件 | 行为 |
|---|---|
| `TOPIC_FILE_APPENDED` / `TOPIC_MATTER_CREATED` | 对所有用户跑 `compute_relevance`，命中 `insert_file` |
| `TOPIC_COMMENT_APPENDED` | 每个 mentions[i] 解析 → self-exclusion → 未注册联系人过滤 → `insert_mention` |

写入失败 swallow + warning，由 scanner 兜底。

### 新增 `server/relevance_scanner.py`（全量幂等扫描）

```python
def scan_all() -> ScanReport:
    inserted = skipped = 0
    for matter, item in walk(indices):
        # file 级:对所有用户跑 compute_relevance
        # mention 级:遍历 comments[].mentions
        # 每条候选先 Repo.exists(),不存在才 INSERT
    return ScanReport(inserted, skipped)
```

触发点：
- **启动一次**（默认开，env `RELEVANCE_BACKFILL_ON_STARTUP=False` 可关）
- **每小时定时**：`server/app.py` 注册 hourly task
- **CLI**：`python -m server.relevance_scanner`

### 改 `server/inbox.py`

新增 `compute_matter_unread_breakdown(...) -> dict[str, tuple[int, int]]`：

```python
state = read_states.all_for_user(user_open_id)
breakdown = repo.unread_breakdown_per_matter(user_open_id)
# breakdown: {matter_id: (red_files, red_mentions)}
for matter:
    unread_filenames = [f for f in filenames if f > state.get(key)]
    rf, rm = breakdown.get(matter_id, (0, 0))
    red  = rf + rm
    gray = max(len(unread_filenames) - rf, 0)
```

`unread_breakdown_per_matter` 一条 GROUP BY：

```sql
SELECT matter_id,
       SUM(kind='file')    AS files,
       SUM(kind='mention') AS mentions
  FROM relevance_events
 WHERE user_open_id = ? AND read_at IS NULL
 GROUP BY matter_id
```

### 改 `server/api/matters.py`

1. **list 接口**（`GET /api/matters`）：调 `compute_matter_unread_breakdown`，给每个 summary 注 `red_unread_count` / `gray_unread_count`，老 `unread_count` 维持 red+gray 总和。
2. **详情接口**（`GET /api/matters/{matter_id}`）：装配 timeline 时调一次 `unread_mention_keys_for_matter` 拿集合；每个 timeline item 注 `relevance_reason`（kind='file' 行的 reason 列），每条 comment 注 `mention_unread_for_me`（按 `(filename, comment_at, author)` 查集合）。
3. **文件级 read 端点**（`POST /matters/{id}/files/{f}/read`）：在现有 `file_reads.mark` 之后调 `repo.mark_all_read_for_file(...)`。

### 新增 `server/api/preferences.py`

```python
@router.get("/api/me/preferences")
def list_preferences(user) -> {key: value, ...}: ...

@router.put("/api/me/preferences/{key}")
def set_preference(key, body, user):
    if key not in ALLOWED_KEYS: raise 400
    ...
```

### 改 `server/app.py`

- 装配 `RelevanceEventsRepo(db)`、`UserPreferenceRepo(db)`，注入路由。
- startup hook：`if RELEVANCE_BACKFILL_ON_STARTUP: scan_all()`。
- 注册 `relevance_writer.install(...)` 订阅事件总线。
- 起 hourly task：`asyncio.create_task(_hourly_scan_loop())`。

## 客户端实现

### 类型与 API 调用

`web/src/api.ts` 扩展：

```ts
export type MatterSummary = {
  ...,
  red_unread_count?: number;
  gray_unread_count?: number;
};
export type Reason = "owner_assigned" | "reply_to_my_file" | "reply_to_my_owned"
                   | "verify_my_file" | "in_my_matter";
export type TimelineItem = { ..., relevance_reason?: Reason | null };
export type Comment      = { ..., mention_unread_for_me?: boolean };

export async function fetchPreferences(): Promise<Record<string, string>>;
export async function setPreference(key: string, value: string): Promise<void>;
```

### Dashboard 筛选 + 角标（`web/src/pages/Dashboard.tsx`）

- mount 时 `fetchPreferences()`，用 `matter_list_filter` 初始化 filter state（默认 `"all"`）。
- 切换控件：`onChange` 先 `setPreference()` 再 `setState`；失败回滚。
- 列表渲染：`filter === "mine"` 时本地过滤 `red_unread_count > 0`。
- 角标拆色：red badge 用红色样式，gray dot 用灰色弱提示，都为 0 时整组不渲染。

### 详情页相关性 chip + 评论红点

- 新组件 `web/src/components/matter/RelevanceChip.tsx`：根据 `relevance_reason` 渲染对应文案 chip（"@ 提到你" / "你被设 owner" / 等）。`null` 时返回 null。
- 新组件 `web/src/components/matter/MentionUnreadDot.tsx`：评论行右侧的小红点 + tooltip "@你 未读"。
- `FileCard.tsx`：头部加 `<RelevanceChip reason={item.relevance_reason} />`；评论行（已存在）末尾加 `<MentionUnreadDot show={comment.mention_unread_for_me} />`。

文案映射在前端：

```ts
const REASON_LABEL: Record<Reason, string> = {
  owner_assigned: "你被设为 owner",
  mentioned: "@ 提到你",
  reply_to_my_file: "回复你创建的文件",
  reply_to_my_owned: "回复你负责的文件",
  verify_my_file: "verify 你的文件",
  in_my_matter: "你创建的 matter",
};
```

## 设计边界

- **不做"逐条 mention 单独 ack"**：本期"开了文件 = 该文件下全 ack"，跟 `file_reads` 触发口径一致。
- **不做正文 @ 识别**：当前只处理 `comments[].mentions`。proposal/reply 文件正文 markdown 里的 `@xxx` 不进表。
- **不做 reason 升级**：`INSERT OR IGNORE` 保留首次 reason；后续命中更高优先级也不替换。
- **不做"@ 的 matter 自动冒到列表顶"**：`updated_at` 语义不动，靠用户切到 mine 视图来定位。
- **不广播实时已读推送**：未读已经实时（事件总线 + SSE），已读由用户操作触发，下次 refetch 看到即可。

## 实施阶段

```
Phase 0 ─┬─► Phase 1 (DB + Repo)        ─┐
         ├─► Phase 2 (compute_relevance) ─┤
         ├─► Phase 3 (writer + scanner)  ─┤
         ├─► Phase 4 (API: list/detail/  ├─► Phase 8 (联调验收)
         │           file-read/prefs)    │
         └─► Phase 5 (前端类型 + API)    ─┤
              ├─► Phase 6 (Dashboard)   ─┤
              └─► Phase 7 (FileCard)   ──┘
```

Phase 1 / 2 / 5 并行；Phase 3 依赖 1+2；Phase 4 依赖 1+2；Phase 6/7 依赖 5。

| Phase | 内容 | 工作量 |
|---|---|---|
| 0 | 切分支 `feat/relevance-unread`；本地 sanity（核对 `db.py` SCHEMA 末尾、`events.py` 三 topic、文件级 read 端点位置） | 0.2 h |
| 1 | `db.py` 加 `relevance_events` / `user_preferences`；新建 `server/relevance_events.py`（Repo + 单测覆盖 file/mention insert、exists、mark_all_read_for_file、unread_breakdown_per_matter、unread_mention_keys_for_matter） | 0.5 d |
| 2 | 新建 `server/relevance.py` `compute_relevance` + 5 条规则单测 + self-exclusion 用例 | 0.3 d |
| 3 | 新建 `server/relevance_writer.py`（订阅 3 topic）+ `server/relevance_scanner.py`（exists → insert，统计 inserted/skipped） + 启动 / hourly / CLI 接入；`server/app.py` 注入 + startup hook | 0.5 d |
| 4 | `server/inbox.py` 加 `compute_matter_unread_breakdown`；`server/api/matters.py` list 注 red/gray + 详情注 relevance_reason / mention_unread_for_me + 文件级 read 端点挂清读 side effect；新建 `server/api/preferences.py`（GET/PUT + 白名单）；`tests/test_matters_api.py` + `test_relevance_writer.py` + `test_relevance_scanner.py` 增量用例 | 0.7 d |
| 5 | `web/src/api.ts` 类型扩展 + `fetchPreferences` / `setPreference` | 0.2 d |
| 6 | `Dashboard.tsx` filter 控件 + 服务端 prefs 读写 + red/gray 角标 + 列表本地过滤 | 0.5 d |
| 7 | `FileCard.tsx` 接 RelevanceChip + 评论行接 MentionUnreadDot + REASON_LABEL 文案表 | 0.5 d |
| 8 | 联调：5 次 @ → red=5；展开文件 → 该文件清；再 @ → red=1；切设备 prefs 同步；scan 历史回灌；模拟实时写入失败后 hourly scan 补回 | 0.5 d |

合计约 **3 人日**，前后端可并行。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | 领导在 F 评论里 @ 当前用户 5 次 | red 显示 5 |
| 2 | 当前用户展开 F | F 下所有未读 mention 清，red −5 |
| 3 | 当前用户读完 F 后领导再次 @ | red +1，列表 SSE refetch 后立即可见 |
| 4 | 别人之间互相 @，跟当前用户无关 | 不写记录，red 不变 |
| 5 | 自己 @ 自己 / 自己回复自己的文件 | 不写记录 |
| 6 | 设备 A 切到 "mine"，设备 B 登录 | 设备 B 默认 "mine" 视图 |
| 7 | 详情页文件 owner = 当前用户（被别人设） | 文件卡显示 "你被设为 owner" chip |
| 8 | 评论里 @ 当前用户但已读 | 该评论行无红点；同文件里其他未读 mention 仍亮 |
| 9 | 点 matter 标题进详情但不展开任何文件 | red 不变（mention 不会被一锅端清） |
| 10 | 关掉 real-time writer 模拟漏写，等 hourly scan | 缺失行被 scanner 补回，inserted 计数 > 0 |
| 11 | StrictMode 双调用 effect | 同一 mention 不重复落表（PK 兜底） |
| 12 | matter 中 5 篇新文件 + 3 次 @ 都集中在第一篇 | red = 4（1 文件 + 3 mention），gray = 4 |

## 风险与回滚

| 风险 | 对策 |
|---|---|
| real-time writer 异常 swallow 后 silently 漏写 | scanner hourly 兜底；监控 `relevance writer error rate`，连续异常告警 |
| 启动回灌噪音（老用户瞬间一片红） | 默认开启 `RELEVANCE_BACKFILL_ON_STARTUP`；低峰部署 + 提前知会用户；急的话临时设 `False`，由首个 hourly tick 慢慢带 |
| PK 6 列字符串性能 | 十万行内够用，百万级再换自增 ID + 唯一索引；监控查询 P99 |
| 同一秒两条评论各 @ 同一人撞 PK | `_now_iso()` 当前精度到秒，第二条 IGNORE。概率极低；需要时把 publish 时间戳精度提到毫秒，表结构不动 |
| user_preferences 表被滥用 | API 层 key 白名单（本期只 `matter_list_filter`） |
| `compute_relevance` 跨 matter 查 quote 文件 | 限定在同 matter 内查 timeline；跨 matter 引用不在判定范围（设计已收口） |
| DM 与红点不同步 | 两条独立通道；总线异常时 DM 已发但红点没出，最坏 1h 红点延迟 |

**回滚**：

- 前端：删 `Dashboard.tsx` filter 控件 + 角标渲染、删 RelevanceChip / MentionUnreadDot 即可静默关闭；列表展示退化到 `unread_count` 单数字。
- 后端：详情 / list 接口注的字段是纯加法，老前端忽略即可；`relevance_writer` install 移除即停止实时写入，scanner / 表保留无副作用。

## 交付清单

```
新增：
  server/relevance.py
  server/relevance_events.py
  server/relevance_writer.py
  server/relevance_scanner.py
  server/api/preferences.py
  server/tests/test_relevance.py
  server/tests/test_relevance_events.py
  server/tests/test_relevance_writer.py
  server/tests/test_relevance_scanner.py
  server/tests/test_user_preferences_api.py
  web/src/components/matter/RelevanceChip.tsx
  web/src/components/matter/MentionUnreadDot.tsx

修改：
  server/db.py                                   # +relevance_events, +user_preferences
  server/inbox.py                                # +compute_matter_unread_breakdown
  server/api/matters.py                          # list red/gray;详情 relevance_reason / mention_unread_for_me;文件级 read 挂清读
  server/app.py                                  # 注入 Repo + startup scan + hourly task + writer install
  server/tests/test_matters_api.py               # 增量用例
  web/src/api.ts                                 # 类型扩展 + prefs 接口
  web/src/pages/Dashboard.tsx                    # filter + prefs + 角标
  web/src/components/matter/FileCard.tsx         # 接 RelevanceChip + MentionUnreadDot
```

## 后期扩展（不在本期）

按 [`relevance-unread-tech-design-v3.1.md`](./relevance-unread-tech-design-v3.1.md) §六对齐：

- **"我的 @" catch-up 视图**：`GET /api/me/relevance?kind=mention&status=unread` 跨 matter 聚合，复用单表。
- **正文 @ 识别**：加 body parser 在 publish 路径解析正文 `@xxx`，kind 仍为 mention，event_at 用 item.created_at。
- **mention `last_attention_at`**：mine 视图按"最近被 @"排序时加 `MAX(event_at) WHERE kind='mention' AND read_at IS NULL`。
- **reason 升级**：把 file 行的 INSERT OR IGNORE 换成应用层 SELECT-then-UPSERT，只在新 reason 优先级更高时覆盖。
- **DM 与红点对账观测**：`/api/admin/metrics/relevance` 暴露 unread 总数、最近 scan 修复行数、写入异常计数。
