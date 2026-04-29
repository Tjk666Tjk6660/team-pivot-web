# Pivot 与我相关未读 · 技术设计方案V2

| | |
|---|---|
| 状态 | 待评审 |
| 涉及组件 | `server/db.py` · `server/relevance_events.py`（新增） · `server/relevance.py` · `server/relevance_writer.py` · `server/relevance_scanner.py` · `server/inbox.py` · `server/api/matters.py` · `server/api/preferences.py` · `web/src/pages/Dashboard.tsx` · `web/src/components/matter/FileCard.tsx` |

## 一、需求背景

matter 列表把未读拆成红 / 灰：跟我相关的事走红色强提示，普通时间线更新走灰色弱提示。再加一个"全部 / 与我相关"筛选，状态服务端持久化（跨设备）。判定纯靠程序规则，不引入 AI。

三条硬约束决定了设计形态：

| 场景 | 期望 |
|---|---|
| 同一文件被 @ 5 次 | 红点 = 5（每次都计） |
| 我读完文件后又被 @ | 红点 +1（已读后再次被 @ 必须能感知） |
| 别人之间互相 @，跟我无关 | 不动（只在我作为被 @ 对象时写记录） |

仓库现成可复用：`comments[].mentions` 已经是结构化字段；飞书 DM 按 mention 在发，跟红点正交；SSE 已经在推 `matter.updated`，前端 refetch 自动带上新字段。

整体走"实时写入 + 扫描补录"双轨：实时路径 swallow 异常，靠 hourly scanner 兜底。

## 二、目标

第一期上线后，用户在 matter 列表和详情页上能直接看出：

1. 哪些 matter 有跟自己明确相关的未读内容，用红色强提示。
2. 哪些 matter 只是有普通更新、不一定跟自己相关，用灰色弱提示。
3. 列表顶部有一个"全部 / 与我相关"切换开关，选过的状态会被记住——下次回到列表是上次选的视图，换浏览器或换设备登录也能恢复。
4. 进入 matter 详情页后，能看出每个文件、每条评论是否跟自己相关，以及为什么相关（被 @、文件 owner 是我、回复了我创建 / 负责的文件、在我创建的 matter 里等等）。
5. 同一文件被 @ 多次能累计感知：连续 @ 5 次红点就显示 5；之前已经读过后再被 @，红点会重新出现。
6. 自己触发的动作不会出现在自己的红色未读里——自己 @ 自己、自己回复自己的文件，都不计入。
7. 已读的触发口径跟卡片正文阅读保持一致：用户真正展开或看到具体文件才算读，单纯点 matter 标题进详情不算。

不做（摘自需求文档"暂不包含"节）：

> 第一期不做独立 inbox 页面、AI 推荐、AI 优先级、todo / 已处理 / 忽略等管理状态。

## 三、技术方案

### 3.1 数据模型

`server/db.py` SCHEMA 末尾新增：

```sql
-- 与我相关的"事件"。kind 区分文件级关系与评论级 @,共用一套写入和已读语义。
CREATE TABLE IF NOT EXISTS relevance_events (
    user_open_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,    -- basename
    kind          TEXT NOT NULL,    -- 'file' | 'mention'
    reason        TEXT NOT NULL,    -- file: owner_assigned/reply_to_my_*/...
                                    -- mention: comment_mention
    event_at      TEXT NOT NULL,    -- ISO 8601 (file=item.created_at, mention=comment.created_at)
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

PK 把 `kind` + `event_at` + `actor_pinyin` 都纳入：file 行（每文件一条）和 mention 行（每条评论一条）在同一文件上不撞键。`event_at` 用 ISO 字符串是因为 matter index 里就是 ISO，直接复用，不需要类型转换。

不存评论 body：matter index 是评论原文权威源，详情接口已经返回正文，DM 也带正文。relevance_events 只存"事件指针 + 已读状态"。

### 3.2 相关性判定

`server/relevance.py` 的 `compute_relevance(item, matter_data, user) -> (ok, reason)` 只判定文件级关系，按优先级首个命中即返回：

| 优先级 | reason | 条件 |
|---|---|---|
| 1 | `owner_assigned` | item.owner == user 且 item.creator != user |
| 2 | `reply_to_my_file` | item.quote 指向的文件 .creator == user |
| 3 | `reply_to_my_owned` | item.quote 指向的文件 .owner == user |
| 4 | `verify_my_file` | item.verifications[*].target 任一指向用户的文件 |
| 5 | `in_my_matter` | matter 首篇 proposal.creator == user |

mention 不走 `compute_relevance`，writer / scanner 直接根据 `comment.mentions` 写 `kind='mention'`、`reason='comment_mention'`。

### 3.3 实时写入

`server/relevance_events.py` 单 Repo：

```python
class RelevanceEventsRepo:
    # writer 用,内部 INSERT OR IGNORE 抗并发
    def insert_file(self, user_open_id, matter_id, filename, *,
                    reason, event_at, actor_pinyin) -> bool: ...
    def insert_mention(self, user_open_id, matter_id, filename, *,
                       comment_at, actor_pinyin) -> bool: ...
    # scanner 用
    def exists(self, *, user_open_id, matter_id, filename,
               kind, event_at, actor_pinyin) -> bool: ...
    # 已读 / 列表 / 详情
    def mark_all_read_for_file(self, user_open_id, matter_id, filename) -> int: ...
    def unread_breakdown_per_matter(self, user_open_id) \
            -> dict[str, tuple[int, int]]: ...
    def unread_mention_keys_for_matter(self, user_open_id, matter_id) \
            -> set[tuple[str, str, str]]: ...
```

`server/relevance_writer.py` 订阅事件总线：

| 事件 | 行为 |
|---|---|
| `TOPIC_FILE_APPENDED` / `TOPIC_MATTER_CREATED` | 对所有用户跑 compute_relevance，命中 `insert_file` |
| `TOPIC_COMMENT_APPENDED` | 每个 mentions[i] 解析、self-exclusion、未注册联系人过滤后 `insert_mention` |

去重行为：同一 comment 里 @ 同一人两次 → PK 撞，按一次算；不同 comment 各 @ 一次 → event_at 不同，各自落表，red 累加。

### 3.4 已读语义：文件级触发

跟 [`pivot已读状态支持`](https://pivot.enclaws.com/m/%E6%96%B0%E9%9C%80%E6%B1%82-pivot%E5%B7%B2%E8%AF%BB%E7%8A%B6%E6%80%81%E6%94%AF%E6%8C%81) 共用同一个端点和触发器。**点 matter 标题不算阅读**——只有用户真正展开 / 看到具体文件，该文件下的 relevance_events 才被消化。

| 用户动作 | 端点 | 写入 |
|---|---|---|
| 点 matter 标题 | `POST /matters/{id}/read` | 只推 `read_state` 高水位线（给 gray 用） |
| 长文展开 / 短文进视口 | `POST /matters/{id}/files/{f}/read` | file_reads 首读 + 该文件的未读 relevance_events 全清 |

`mark_all_read_for_file` 一条 SQL：

```sql
UPDATE relevance_events SET read_at = ?
 WHERE user_open_id = ? AND matter_id = ? AND filename = ?
   AND read_at IS NULL
```

只动当前文件——5 个 mention 分散在 3 个文件，看哪个清哪个，没看的留红。**不在 matter 维度一锅端清。**

文件级 read 端点本身由 read-state 设计提供，本期只在它上面多挂这一段 side effect，不抢端点所有权。两个设计错开上线也不破坏对方语义。

### 3.5 列表 red / gray 拆分

`server/inbox.py` 加 `compute_matter_unread_breakdown`：

```python
def compute_matter_unread_breakdown(...) -> dict[str, tuple[int, int]]:
    state = read_states.all_for_user(user_open_id)
    breakdown = relevance_events.unread_breakdown_per_matter(user_open_id)
    # breakdown: {matter_id: (red_files, red_mentions)}

    result = {}
    for index_path in indices:
        unread_filenames = [f for f in filenames if f > state.get(key)]
        rf, rm = breakdown.get(matter_id, (0, 0))
        red = rf + rm
        gray = max(len(unread_filenames) - rf, 0)
        result[key] = (red, gray)
    return result
```

`unread_breakdown_per_matter` 一条 GROUP BY 拿全部：

```sql
SELECT matter_id,
       SUM(kind='file')    AS files,
       SUM(kind='mention') AS mentions
  FROM relevance_events
 WHERE user_open_id = ? AND read_at IS NULL
 GROUP BY matter_id
```

举例：5 篇新文件 + 3 次 @ 都集中在第一篇 → red = 1+3 = 4；gray = 5−1 = 4。

### 3.6 详情接口

`GET /api/matters/{matter_id}` 加两个字段：

```jsonc
{
  "timeline": [
    {
      "file": "...",
      "relevance_reason": "reply_to_my_file",   // 文件级,null 表示不相关
      "comments": [
        { ..., "mention_unread_for_me": true }  // 评论级,每条独立
      ]
    }
  ]
}
```

实现：拼装时调一次 `unread_mention_keys_for_matter` 拿 `(filename, comment_at, actor_pinyin)` 集合，遍历 timeline 时 set 查表填 `mention_unread_for_me`；`relevance_reason` 直接来自 `kind='file'` 那行的 reason 列。一次 SELECT，O(M+N) 拼装。

前端用 `if (item.relevance_reason)` 判断是否相关，不再有 `is_relevant` 这种冗余布尔。

### 3.7 扫描补录

real-time writer 走异步回调，可能因总线异常 / 进程重启漏写。`server/relevance_scanner.py` 全量幂等扫，补漏不污染。

**scanner 用显式 SELECT-then-INSERT**，每条候选先 `Repo.exists` 查 PK，不存在才 INSERT。好处：

- **可观测**：能区分跳过 vs 新增，扫完报 `inserted=N skipped=M`，实时通道是否健康一目了然。
- **可扩展**：未来需要"行存在但要纠正 reason"时，已经查过现状，加分支即可。
- **代价小**：N 条候选多 N 次 PK 索引 lookup（常数级），整体耗时主要被 index 文件读盘吃掉，DB 不是瓶颈。

real-time writer 路径继续用 `INSERT OR IGNORE`——单事件落表延迟敏感、并发 race 多，数据库原子去重更安全。两条路径用的 Repo 方法分开。

代码骨架：

```python
def scan_all() -> ScanReport:
    inserted = skipped = 0
    for matter, item in walk(indices):
        # file 级
        for user in users.all():
            ok, reason = compute_relevance(item, matter, user)
            if not ok:
                continue
            if relevance_events.exists(
                user_open_id=user.open_id, matter_id=matter.id,
                filename=item.filename, kind="file",
                event_at=item.created_at, actor_pinyin=item.author,
            ):
                skipped += 1
                continue
            relevance_events.insert_file(...)
            inserted += 1
        # mention 级
        for comment in item.comments:
            for mention_id in comment.mentions:
                target = users.get_by_any_id(mention_id)
                if target is None or target.pinyin == comment.author:
                    continue
                if relevance_events.exists(
                    user_open_id=target.open_id, matter_id=matter.id,
                    filename=item.filename, kind="mention",
                    event_at=comment.created_at, actor_pinyin=comment.author,
                ):
                    skipped += 1
                    continue
                relevance_events.insert_mention(...)
                inserted += 1
    log.info("scan_all done: inserted=%d skipped=%d", inserted, skipped)
    return ScanReport(inserted=inserted, skipped=skipped)
```

触发点：

- **启动一次**（默认开，`RELEVANCE_BACKFILL_ON_STARTUP=False` 可关）
- **每小时定时**：`server/app.py` 注册 hourly task 全量扫
- **CLI**：`python -m server.relevance_scanner`

定时任务永远跑全量，启动开关只影响"是否阻塞 startup 等扫一次完成"。

### 3.8 SSE 与前端

复用现有 SSE。`matter.updated` 来时前端 `MatterEventsProvider` 触发 refetch，新字段自动到位。

UI 改动：

- `Dashboard.tsx`：red / gray 角标 + filter 控件 + 服务端 prefs 读写。
- `FileCard.tsx`：相关性 chip（读 `relevance_reason`） + 评论行小红点（读 `mention_unread_for_me`）。

### 3.9 边界情况

- **一条评论 @ 三个人**：三行 mention 各落表，user_open_id 不撞。
- **同一 comment 里 @ 同一人两次**：PK 撞，按一次算。
- **同一秒内两条评论各 @ 同一人**：`_now_iso()` 当前精度到秒，PK 撞、第二条丢。概率极低；需要时把 publish 时间戳精度提到毫秒，表结构不动。
- **用户从没打开 matter**：`read_at` 永远 NULL，红点常驻——这是设计意图。
- **N > 99**：UI 截断"99+"。
- **DM 与红点不同步**：总线异常时 DM 已发但红点没出，最坏 1h 红点延迟由 hourly scanner 补回。
- **文件 reason 升级**（in_my_matter 后被改成 owner_assigned）：`INSERT OR IGNORE` 保留首次 reason，本期不做升级。

## 四、时序图

### 4.1 已读后再次被 @

```
t=0   领导在 F 评论 @ B
       → DM 一条 + relevance_events 1 行(kind=mention, read_at=NULL)
       red=1

t=1   B 进 matter X(POST /matters/X/read)
       └─ read_state 高水位推进,relevance_events 不动
       red 还是 1

t=2   B 展开 F 或 F 是短文进视口(POST /matters/X/files/F/read)
       ├─ file_reads.mark_first_read
       └─ UPDATE relevance_events SET read_at=now
              WHERE matter=X file=F AND read_at IS NULL
       F 下未读全清,red=0

t=3   领导再次在 F 评论 @ B
       INSERT OR IGNORE 新行(comment_at=t3,新 PK,read_at=NULL)
       SSE matter.updated → B 浏览器 fetchMatters → red=1 ✓
```

### 4.2 列表查询

```
GET /api/matters
  ├─ relevance_events.unread_breakdown_per_matter(user)  ← 1 条 GROUP BY
  │   → {matter: (red_files, red_mentions)}
  ├─ read_state.all_for_user(user)
  │   → {key: last_read}
  └─ 遍历 indices 拼装:
      red  = red_files + red_mentions
      gray = max(total_unread - red_files, 0)
```

## 五、实施分工


| 阶段 | 内容 | 负责 | 估时 |
|---|---|---|---|
| 后端 1 | `db.py` 加表；`relevance_events.py` Repo + 单测 | 后端 | 0.5 d |
| 后端 2 | `relevance.py` `compute_relevance` 5 条规则 + 单测 | 后端 | 0.3 d |
| 后端 3 | `relevance_writer.py` 三事件订阅 + self-exclusion | 后端 | 0.4 d |
| 后端 4 | `relevance_scanner.py` 全量扫（exists → insert）；启动 + hourly + CLI | 后端 | 0.4 d |
| 后端 5 | 文件级 read 端点挂清读 side effect；list red/gray；详情字段 | 后端 | 0.5 d |
| 后端 6 | `api/preferences.py` filter 状态读写 | 后端 | 0.2 d |
| 后端 7 | 集成测试：多次 @ 累加、读后再 @、file+mention 混合 | 后端 | 0.4 d |
| 前端 1 | `api.ts` 类型扩展 | 前端 | 0.2 d |
| 前端 2 | `Dashboard.tsx` filter + prefs + 角标 | 前端 | 0.5 d |
| 前端 3 | `FileCard.tsx` chip + 评论红点 | 前端 | 0.5 d |
| 联调 | 多人多场景验收 | 前后端 | 0.5 d |

交付清单：

```
新增:
  server/relevance_events.py
  server/relevance.py
  server/relevance_writer.py
  server/relevance_scanner.py
  server/api/preferences.py
  web/src/components/matter/RelevanceChip.tsx
  web/src/components/matter/MentionUnreadDot.tsx
  + 对应单测

修改:
  server/db.py                           # +relevance_events, +user_preferences
  server/inbox.py                        # +compute_matter_unread_breakdown
  server/api/matters.py                  # list red/gray;文件级 read 挂清读;详情字段
  server/app.py                          # startup scan + hourly task
  web/src/api.ts
  web/src/pages/Dashboard.tsx
  web/src/components/matter/FileCard.tsx
```

风险点：

- **写入失败兜底**：实时路径异常 swallow + warning，scanner 1h 内补回；监控 `relevance writer error rate`。
- **PK 6 列字符串性能**：十万行内够用，百万级再换自增 ID + 唯一索引。
- **启动回灌噪音**：默认开启意味着部署完成时老用户会瞬间收到大量未读红点。低峰部署 + 提前知会；急的话 `RELEVANCE_BACKFILL_ON_STARTUP=False`，改靠 hourly tick 慢慢带。

## 六、后期扩展

- **"我的 @" catch-up 视图**：`GET /api/me/relevance?kind=mention&status=unread`，跨 matter 聚合，复用单表。
- **正文 @ 识别**：当前只处理 `comments[].mentions`。需要时加 body parser，kind 仍为 mention，event_at 用 item.created_at。
- **mention `last_attention_at`**：mine 视图按"最近被 @"排序，加 `MAX(event_at) WHERE kind='mention' AND read_at IS NULL`。
- **reason 升级**：把 file 行的 `INSERT OR IGNORE` 换成应用层 SELECT-then-UPSERT，只在新 reason 优先级更高时覆盖。本期不做。
- **DM 与红点对账观测**：`/api/admin/metrics/relevance` 暴露 unread 总数、最近 scan 修复行数、写入异常计数。
