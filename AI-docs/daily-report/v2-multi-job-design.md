# Pivot 日报 v2 · 多任务管理设计

> 配套 v0.2 落地版的演进。本文档将"单一全局配置 + 2 开关"模型升级为"N 条独立定时任务 + 历史记录"模型。
>
> 决策由 huangshengli + dengke 在 2026-04-29 / 04-30 讨论确定。

---

## 〇、决策清单(对话沉淀)

| 决策点 | 结果 |
|---|---|
| 数据模型 | `daily_report_jobs` 表,N 条任务可加可删 |
| 任务字段 | name + view + 时间配置 + receivers + 运行状态 + 重试计数 |
| view | `company` / `personal`(取代"类型",留 v3 加 weekly/monthly 的口子) |
| schedule_mode | **不要**,oneshot/指定时间不进 jobs 表(走手动触发) |
| 手动触发 | 不入 jobs 表,但**记录到 runs 表**(`job_id=NULL` + `trigger_type='manual'`) |
| runs 历史表 | 加,记录每次 fire 的完整生命周期 |
| 漏跑判定 | 用 `last_run_id → runs.status` 查实际状态(冗余 cache `jobs.last_status` 加速) |
| 漏跑策略 | ≤ 30 分钟漏跑 → 立即补跑;> 30 分钟 → 通知 admin,不补跑 |
| 失败重试 | 自动重试最多 3 次,每次间隔 5 分钟;3 次后发失败通知 |
| 通知接收人 | 加 `daily_report.admin_notify_chat_ids` + `admin_notify_open_ids`,fallback 到所有 bot 群 |
| receivers 颗粒度 | 飞书:群多选 / 个人 open_id 多选(复用现有 mention picker) |
| 渠道 | 仅飞书(钉钉/微信暂不开放,字段留口子) |
| push_freq | `daily` / `weekdays` / `mon` / `tue` / `wed` / `thu` / `fri` / `sat` / `sun` / `month_start` / `month_end`(共 11 值,在代码层 Literal 校验,不进 DB CHECK) |
| 调度实现 | **每分钟扫表**(SQLite poll,简单 + 重启友好 + 多 worker 留口子) |
| 轮询间隔 | 60 秒 |
| 任务删除 | `status='archived'` 软删,**永不真删**(保留审计) |
| runs 历史保留 | **365 天**清理,清理时代码层 `UPDATE jobs SET last_run_id=NULL WHERE last_run_id IN (...)` |
| 任务详情入口 | 任务卡片"历史"按钮 → **抽屉式**侧滑 → 分页运行记录(每页 20 条,时间倒序) |
| 系统通知配置入口 | 日报 tab 内顶部折叠面板,默认收起 |

---

## 一、数据模型

### 1.1 jobs 表

```sql
-- 字段值集合(view / status / push_freq / channel / receiver_type)统一在
-- 代码层校验(jobs_repo Literal + Pydantic JobIn/JobUpdateIn);
-- window_hours 范围(1-168)同样在 Pydantic 层守。SQLite CHECK 不支持 ALTER,
-- 放表里只会成为扩枚举的绊脚石。
CREATE TABLE daily_report_jobs (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  name                  TEXT NOT NULL,                                 -- 用户命名
  view                  TEXT NOT NULL,                                 -- 'company' | 'personal'

  -- 调度配置
  status                TEXT NOT NULL DEFAULT 'active',                -- 'active' | 'paused' | 'archived'
  push_time             TEXT NOT NULL,                                 -- 'HH:MM' (Asia/Shanghai)
  push_freq             TEXT NOT NULL DEFAULT 'weekdays',              -- 见 jobs_repo.PushFreq(共 11 值)
  window_hours          INTEGER NOT NULL DEFAULT 24,                   -- Pydantic 层限定 1-168

  -- 渠道 + 发送目标
  channel               TEXT NOT NULL DEFAULT 'feishu',                -- v1 仅 feishu
  receiver_type         TEXT NOT NULL,                                 -- 'groups' | 'users'
  receiver_ids          TEXT,                                          -- JSON array;NULL = 默认全部 bot 群(只对 groups 有效)

  -- 运行状态
  next_run_at           TEXT,                                          -- ISO 8601 (active 时才有值)
  last_run_id           INTEGER REFERENCES daily_report_runs(id),
  last_status           TEXT,                                          -- 冗余 cache:succeeded/failed/partial/missed/skipped/running
  retry_count           INTEGER NOT NULL DEFAULT 0,
  last_notified_at      TEXT,                                          -- 上次"漏跑/失败通知"时间(去重)

  -- 元信息
  created_by            TEXT,                                          -- creator open_id
  created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_jobs_active_due ON daily_report_jobs(status, next_run_at);
CREATE INDEX idx_jobs_status ON daily_report_jobs(status);
```

### 1.2 runs 表

```sql
CREATE TABLE daily_report_runs (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id                INTEGER REFERENCES daily_report_jobs(id),       -- NULL = 手动触发(不属于任何 job)
  trigger_type          TEXT NOT NULL
                        CHECK(trigger_type IN ('scheduled', 'manual', 'retry', 'makeup')),
  view                  TEXT NOT NULL,                                  -- 冗余:即使 job 删了也能查历史

  started_at            TEXT NOT NULL,
  finished_at           TEXT,
  status                TEXT NOT NULL DEFAULT 'running'
                        CHECK(status IN ('running', 'succeeded', 'failed', 'partial', 'skipped')),
  rc                    INTEGER,
  cards_sent            INTEGER,
  cards_total           INTEGER,                                        -- 期望发出的卡数(2 张就是 cards_sent/cards_total)
  ai_tokens_in          INTEGER,
  ai_tokens_out         INTEGER,
  error                 TEXT,                                           -- 错误摘要(<= 200 字)
  debug_json            TEXT                                            -- 完整 debug payload(用于详情查看)
);

CREATE INDEX idx_runs_job_started ON daily_report_runs(job_id, started_at DESC);
CREATE INDEX idx_runs_started ON daily_report_runs(started_at);          -- 给 365 天清理用
```

### 1.3 settings 表新增 admin 通知键

```
daily_report.admin_notify_chat_ids   JSON 数组  ["oc_xxx", ...]   群多选
daily_report.admin_notify_open_ids   JSON 数组  ["ou_xxx", ...]   人多选
```

无配置时 fallback 到所有 bot 群。

### 1.4 外键 + 清理策略

- `jobs.last_run_id` 引用 `runs.id`,**不设 ON DELETE 级联**(SQLite SET NULL 行为不一致,代码层处理)
- runs 365 天清理时:
  ```sql
  -- 1. 找出要删的 run id
  SELECT id FROM runs WHERE started_at < ?
  -- 2. 把 jobs 中引用这些 id 的字段置空
  UPDATE jobs SET last_run_id = NULL WHERE last_run_id IN (...)
  -- 3. 删 runs
  DELETE FROM runs WHERE started_at < ?
  ```
- jobs 表 `archived` 状态记录**永不真删**(保留审计,UI 列表过滤掉 archived)

---

## 二、API 端点

| 方法 | 路径 | 用途 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/admin/daily-report/jobs` | 列出所有 active + paused job | admin |
| `POST` | `/api/admin/daily-report/jobs` | 新建 job | admin |
| `GET` | `/api/admin/daily-report/jobs/{id}` | 取单条 job 详情 | admin |
| `PUT` | `/api/admin/daily-report/jobs/{id}` | 更新 job 配置 | admin |
| `PUT` | `/api/admin/daily-report/jobs/{id}/status` | 切换 active/paused/archived | admin |
| `DELETE` | `/api/admin/daily-report/jobs/{id}` | 软删除(置 archived) | admin |
| `POST` | `/api/admin/daily-report/jobs/{id}/run-now` | 立即运行该 job 一次(retry 类型,不影响 next_run_at) | admin |
| `GET` | `/api/admin/daily-report/jobs/{id}/runs?page=N&size=20` | 该 job 的运行历史(分页) | admin |
| `GET` | `/api/admin/daily-report/runs/{run_id}` | 单条 run 详情(error / debug_json) | admin |
| `POST` | `/api/admin/daily-report/manual-trigger` | 手动一次性触发(不绑 job) | admin |
| `GET` | `/api/admin/daily-report/admin-notify` | 取系统通知接收人配置 | admin |
| `PUT` | `/api/admin/daily-report/admin-notify` | 更新系统通知接收人 | admin |
| `GET` | `/api/admin/daily-report/feishu-chats` | 飞书群列表(给"选群"UI 用) | admin |

### 关键 payload 例

```jsonc
// POST /jobs
{
  "name": "公司视角 · 管理层早报",
  "view": "company",
  "status": "active",
  "push_time": "09:30",
  "push_freq": "weekdays",
  "window_hours": 24,
  "channel": "feishu",
  "receiver_type": "groups",
  "receiver_ids": ["oc_admin_group", "oc_managers"]
}

// PUT /jobs/{id}/status
{ "status": "paused" }    // 或 active / archived

// POST /manual-trigger
{
  "view": "company",                     // 或 personal,或 ["company", "personal"]
  "window_hours": 24,
  "since": null,                         // 可选:具体时间窗口
  "until": null,
  "receiver_type": "groups",
  "receiver_ids": null,                  // null = 默认 bot 全部群
  "dry_run": false,
  "no_ai": false
}

// GET /jobs/{id}/runs?page=1&size=20
{
  "items": [
    {
      "id": 12345,
      "trigger_type": "scheduled",
      "started_at": "2026-04-30T09:30:01+08:00",
      "finished_at": "2026-04-30T09:31:22+08:00",
      "status": "succeeded",
      "rc": 0,
      "cards_sent": 2,
      "cards_total": 2,
      "ai_tokens_in": 1480,
      "ai_tokens_out": 320,
      "error": null
    }
  ],
  "page": 1,
  "size": 20,
  "total": 142
}
```

---

## 三、Scheduler 实现

### 3.1 主循环(每分钟扫表)

```python
class JobScheduler:
    POLL_INTERVAL_SEC = 60
    MISSED_TOLERANCE_MIN = 30
    MAX_RETRY = 3
    RETRY_DELAY_MIN = 5

    async def _loop(self):
        last_cleanup_date = None
        while not self._stop_event.is_set():
            try:
                now = datetime.now(tz=CHINA_TZ)
                await self._poll_and_fire(now)
                # 每天一次清理(同进程内自然防重复)
                today = now.date()
                if last_cleanup_date != today:
                    self._cleanup_old_runs(now)
                    last_cleanup_date = today
            except Exception:
                log.exception("scheduler iteration failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.POLL_INTERVAL_SEC)
                return
            except asyncio.TimeoutError:
                continue
```

### 3.2 fire 一个 job 的状态机

```
[scheduler 找到 due job]
        │
        ▼
   是漏跑吗?
   (now - next_run_at)
        │
        ├─ ≤ 30 min(可补)
        │    ▼
        │  [立即 fire]
        │
        └─ > 30 min(无意义补)
             ▼
          ┌──────────────────────────────┐
          │ 写一条 run, status='skipped' │
          │ 发漏跑通知卡(去重 last_notified_at)│
          │ next_run_at = 下个周期        │
          │ retry_count = 0              │
          └──────────────────────────────┘

[fire job]
        │
        ▼
   新 thread 跑 runner(LLM 慢调用)
        │
        ├─ 成功 (rc=0)
        │    ▼
        │  ┌──────────────────────────────┐
        │  │ runs.status='succeeded'       │
        │  │ jobs.last_*  更新             │
        │  │ retry_count = 0              │
        │  │ next_run_at = 下个周期         │
        │  └──────────────────────────────┘
        │
        └─ 失败
             ▼
           retry_count + 1
             │
             ├─ < 3
             │    ▼
             │  ┌──────────────────────────────┐
             │  │ runs.status='failed'          │
             │  │ next_run_at = now + 5 min    │  ← 自动重试
             │  └──────────────────────────────┘
             │
             └─ >= 3
                  ▼
                ┌──────────────────────────────┐
                │ runs.status='failed'          │
                │ 发失败通知卡                   │
                │ retry_count = 0              │
                │ next_run_at = 下个周期         │
                │ last_notified_at = now       │
                └──────────────────────────────┘
```

### 3.3 next_run_at 计算

```python
def compute_next_run_at(
    *, now: datetime, push_time: str, push_freq: str,
) -> datetime:
    """支持的 push_freq:
      - 'daily'              每天
      - 'weekdays'           仅 Mon–Fri
      - 'mon' .. 'sun'       仅指定单个 weekday
      - 'month_start'        每月 1 日
      - 'month_end'          每月最后一日(28/29/30/31 自动算 via calendar.monthrange)

    通用规则:从 (今天 push_time) 起步,now 已过则推到明天,
    再按 freq 含义往后推到下一个匹配日。坏 freq 兜底 daily。
    """
```

### 3.4 防重复 fire 三道防线

1. **DB 层**:fire 前**先 UPDATE next_run_at = 下个周期**(乐观锁),即使下次 poll 也不会重复 pick
2. **内存层**:`self._running: dict[int, threading.Thread]`,跑中跳过
3. **runs 表**:每次 fire 都 INSERT 一行,审计可查

### 3.5 启动时漏跑扫描

主服务启动后第一次 poll 自然会处理 `next_run_at < now` 的 job(走漏跑分支)。**不需要单独的"启动恢复"逻辑**。

### 3.6 通知去重

漏跑 / 失败通知发出后,`last_notified_at` 更新。下轮 poll 检测时:
- 漏跑:`next_run_at` 已经被推到下个周期,自然不再 due
- 失败:`retry_count = 0` 且 `next_run_at` 已推到下个周期

无需额外去重逻辑,状态机自然驱动。

### 3.7 manual trigger / run-now 端点

走独立路径,**不影响 jobs 表的调度状态**:

- `POST /manual-trigger`(无 job 关联):直接调 runner,runs 表 INSERT 一行 `job_id=NULL, trigger_type='manual'`
- `POST /jobs/{id}/run-now`:用 job 配置跑一次,runs INSERT 一行 `job_id=N, trigger_type='retry'`,**不动 next_run_at / retry_count / last_status**

---

## 四、UI 设计

### 4.1 主 tab 三块结构

```
┌─────────────────────────────────────────────────────────────┐
│ [日报配置 tab]                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ▶ ⚙ 系统通知接收人 (折叠面板,默认收起)                      │
│   未配置 → 漏跑/失败通知发到所有 bot 群                       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ 📋 定时任务                              [+ 添加任务]        │
│                                                             │
│ ┌─────────────────────────┐ ┌─────────────────────────┐   │
│ │ [job 卡片 1]             │ │ [job 卡片 2]             │   │
│ │ ...                      │ │ ...                      │   │
│ └─────────────────────────┘ └─────────────────────────┘   │
│ ┌─────────────────────────┐                                │
│ │ [job 卡片 3]             │                                │
│ │ ...                      │                                │
│ └─────────────────────────┘                                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ▶ 手动触发(独立子区)                                       │
│   [view 选择] [receivers 多选] [窗口小时数]                  │
│   [▶ 立即生成并发送] [Dry-run] [No-AI]                       │
│   最近一次手动触发结果(类似 v0.2 last-run 板)                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 任务卡片(单条)

```
┌──────────────────────────────────────┐
│ 公司视角 · 管理层早报      [公司视角] │
│ 🟢 运行中  retry: 0                   │
│ ─────────────────────────────────── │
│ ⏰ 09:30  ·  📅 仅工作日  ·  ⏱ 24h  │
│ 📨 飞书 · 3 群                        │
│   └─ 管理层群、技术团队、运营群         │
│                                       │
│ 上次:✓ 04-29 09:30:42 (rc=0, 80s)    │
│ 下次:04-30 09:30                      │
├──────────────────────────────────────┤
│ [⏸ 暂停] [✏ 编辑] [👁 历史] [▶ 立即跑]│
└──────────────────────────────────────┘
```

状态 chip 颜色:
- 🟢 active(运行中)
- 🟡 paused(已暂停)
- 🔴 last_status=failed(最近失败,需关注)

### 4.3 添加 / 编辑任务模态(居中,移动端全屏)

```
┌────────────────────────────────────────┐
│ 添加定时任务                       [×] │
├────────────────────────────────────────┤
│                                        │
│ 任务名称                               │
│ [_________________________________]   │
│                                        │
│ 报告类型                               │
│ ( ● 公司视角  ○ 个人视角 )            │
│                                        │
│ ─── 时间设置 ─────────────────────  │
│ 推送时间        统计窗口(小时)         │
│ [09:30   ⏰]    [24]                   │
│                                        │
│ ( ● 仅工作日  ○ 每天 )                │
│                                        │
│ ─── 发送目标 ─────────────────────  │
│ 渠道:[飞书 ▾] (其他暂不开放)           │
│                                        │
│ ( ● 群组  ○ 个人 )                    │
│                                        │
│ [选择群组(留空=默认全部 bot 群)]       │
│ [管理层群 ✕] [技术团队 ✕] [+ 选群]     │
│                                        │
│ □ 创建后立即暂停                       │
│                                        │
├────────────────────────────────────────┤
│                  [取消]  [保存]        │
└────────────────────────────────────────┘
```

receiver_type=个人时:

```
[选择用户]
[张三 ✕] [李四 ✕] [王五 ✕] [+ 添加用户]   ← 复用 mention picker 组件
```

### 4.4 历史记录抽屉(★ 新增)

点任务卡 [👁 历史] 按钮 → 从右侧滑入,占屏 50%(移动端全屏)。

```
┌────────────────── × ────────┐
│ 🕒 历史记录                  │
│ 公司视角 · 管理层早报         │
├────────────────────────────┤
│                              │
│ [筛选: 全部 ▾] [触发方式 ▾] │
│                              │
│ ┌──────────────────────────┐ │
│ │ 04-30 09:30:01           │ │
│ │ 定时 · ✓ 成功            │ │
│ │ 卡片 2/2 · 耗时 80s · token in/out 1480/320 │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ 04-29 09:30:01           │ │
│ │ 定时 · ✓ 成功            │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ 04-28 09:30:32           │ │
│ │ 重试 · ✓ 成功(retry 2)   │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ 04-28 09:25:01           │ │
│ │ 定时 · ⚠ 失败             │ │← 点开看 error
│ │ ai_error: TimeoutError    │ │
│ │ [查看完整 debug]          │ │
│ └──────────────────────────┘ │
│ ...                          │
│                              │
│ ─────────────────────       │
│ [< 上一页] 1 2 3 ... [下一页 >] │
│ 共 142 条                    │
└────────────────────────────┘
```

每条卡:
- 时间(完整 timestamp)
- 触发方式 chip(scheduled / manual / retry / makeup)
- 状态 chip(✓ succeeded / ⚠ failed / 〇 partial / ⊘ skipped)
- 关键指标:cards_sent/total · 耗时 · token in/out
- 失败行:展开看 error 字段
- "查看完整 debug" 按钮 → 弹小窗显示 debug_json

分页:每页 20 条,默认按 started_at DESC。

### 4.5 系统通知接收人(折叠)

```
▼ ⚙ 系统通知接收人(展开)

  漏跑 / 失败提醒会发到这里。两者都未配置则发到所有 bot 在的群。

  接收群:
  [管理层群 ✕] [+ 选群]

  接收个人(open_id):
  [@张三 ✕] [@李四 ✕] [+ 选人]    ← 复用 mention picker

  [保存]
```

### 4.6 手动触发(独立子区)

```
▶ 手动触发

  报告类型: ( ☑ 公司视角  ☑ 个人视角 )    ← 多选
  时间窗口: ( ● 过去 N 小时:[24]  ○ 自定义起止: [____] - [____] )
  发送目标: ( ● 群:[+ 选群]  ○ 人:[+ 选人] )

  □ Dry-run(不发飞书)
  □ No-AI(fallback 文案)

  [▶ 立即生成并发送]

  ┌── 最近一次触发 ──────────────────┐
  │ run_id: ... · started 14:32:21    │
  │ ✓ 成功 · 2 张卡 · 80s             │
  └─────────────────────────────────┘
```

---

## 五、v0.2 旧配置处理

不做数据迁移。v0.2 settings 中的 6 个 key:

```
daily_report.enabled
daily_report.company_enabled
daily_report.personal_enabled
daily_report.time_window_hours
daily_report.push_time
daily_report.push_freq
```

v2 代码完全不读这些 key,所以**留在 DB 里也无害,作死键忽略**。如果想清理,部署后跑一条 SQL 即可:

```sql
DELETE FROM settings WHERE key IN (
  'daily_report.enabled',
  'daily_report.company_enabled',
  'daily_report.personal_enabled',
  'daily_report.time_window_hours',
  'daily_report.push_time',
  'daily_report.push_freq'
);
```

新部署 v2 后,管理员从 admin UI 重新配置任务即可。原本每天 09:30 跑两份的行为,管理员手动建两条 jobs 即可恢复。

> 上线提醒:v2 部署当天告知管理员"日报配置面板有重大调整,需重新建任务",避免错过当天报告。

---

## 六、工程实施顺序(分 phase)

### Phase 1 · 后端基础(2-3 人日)

- 新建 `daily_report_jobs` / `daily_report_runs` 表 + Database 自动创建
- `JobsRepo` / `RunsRepo`(get/list/insert/update/delete/分页)

### Phase 2 · Scheduler 重写(2-3 人日)

- 新 `JobScheduler` 替代 v0.2 单 job scheduler
- 实现 poll 主循环 / fire 状态机 / 漏跑检测 / 重试逻辑
- 每日 365 天 runs 清理 + 代码层 jobs.last_run_id = NULL
- 改造 runner 接受 job 对象(view + receivers + window_hours 都从 job 来)

### Phase 3 · 后端 API(2 人日)

- 12 个端点(jobs CRUD + runs 列表 + manual trigger + admin-notify + feishu-chats)
- 飞书群列表查询(`im/v1/chats` API,可能需要 cache 1-2 分钟)

### Phase 4 · 前端 UI(4-5 人日)

- 任务卡片 + 卡片网格(响应式 1-2 列)
- 添加 / 编辑任务模态
- 历史记录抽屉(分页)
- 系统通知接收人折叠面板
- 手动触发独立子区
- 飞书群多选 + mention picker 复用

### Phase 5 · 测试 + 文档(2 人日)

- jobs / runs repo 单测
- scheduler 状态机单测(漏跑 / 重试 / 通知去重)
- API 端点测试
- e2e 创建 job → wait → 自动 fire → 检查 runs → manual run-now → archive
- 更新 product-design / implementation-plan / README 到 v2

**合计 12-15 人日**(去掉迁移逻辑)。

---

## 七、关键风险 + 兜底

| 风险 | 兜底 |
|---|---|
| 飞书 chats API 限流 | cache 群列表 1-2 分钟,key 失效再刷新 |
| jobs 表行数过多导致 poll 慢 | active+due 用复合索引,实测 1000 条 < 5ms |
| LLM 调用 timeout 锁住 thread | 每个 fire thread 跟踪 80% timeout 超时上报 |
| runs 365 天清理时事务过大 | 分批删除(每批 1000 条),或用 LIMIT |
| 多 admin 同时编辑 job | UPDATE WHERE updated_at = ?(乐观锁,UI 提示"已被其他管理员修改") |
| 时区 / 夏令时(中国不用,但其他客户可能) | 全 ISO 8601 with tz,内部统一 Asia/Shanghai 转换 |

---

## 八、v3 后续方向(不在 v2 范围)

- cron 表达式或 weekday bitmask(每周一三五 / 每月 1 号)
- 多 IM 渠道(钉钉 / 企业微信 / Slack)
- per-job 自定义 prompt 模板
- 周报 / 月报 view 类型
- 跨 worker 锁(SELECT FOR UPDATE)

---

## 九、需要你最后过一眼的点

1. UI 草图是否有需要调整的(任务卡片字段顺序 / 历史抽屉信息密度等)
2. API 端点路径命名是否合适(`/jobs` vs `/scheduled-jobs` 之类)
3. 工程实施顺序与时间预估是否能接受

OK 开干?
