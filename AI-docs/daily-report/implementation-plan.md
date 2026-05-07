# Pivot 日报 · 实施现状(v2)

> 配套产品文档:[`product-design.md`](./product-design.md)
> 详细技术设计:[`v2-multi-job-design.md`](./v2-multi-job-design.md)
>
> 本文档专注**工程视角**:模块结构 / 数据流 / 测试矩阵。已落地、可参照代码。

## 模块布局

```
server/daily_report/
├── jobs_repo.py              # daily_report_jobs 表 CRUD + 状态机
├── runs_repo.py              # daily_report_runs 表 CRUD + 365 天清理
├── job_scheduler.py          # asyncio scheduler:每 60s poll 一次
├── runner.py                 # run_daily_report_for_job(job, ...) 唯一入口
├── window.py                 # compute_window(now, push_hour, push_minute, window_hours)
├── types.py                  # TimeWindow / MatterEvent / UserActivity / TeamSummary
├── collect_matter.py         # 扫 index/*.index.yaml 收 matter 事件
├── aggregate.py              # 按用户聚合 + TeamSummary
├── shared_facts.py           # 公司/个人视角共用的事实层
├── company_narrate.py        # 公司视角 AI 叙事(tone + summary)
├── personal_narrate.py       # 个人视角 AI 叙事(逐人简评)
├── render.py                 # build_company_card / build_personal_card / build_admin_alert_card
└── tests/                    # 单元测试(见下方测试矩阵)

server/api/
└── daily_report_v2.py        # 13 个 admin 端点(jobs CRUD / runs / admin-notify / feishu-chats)

server/notify.py              # 加 send_card_to_chats / send_card_to_users / send_admin_alert / list_bot_chats

server/app.py                 # lifespan 启动 JobScheduler;mount build_daily_report_v2_router

web/src/pages/admin/
└── DailyReportSection.tsx    # 日报 section 全套 UI(任务列表 / 编辑抽屉 / 历史抽屉 / 手动触发卡)
```

## 数据库 schema

新增两张表(见 `server/db.py` SCHEMA):

```sql
-- view / status / push_freq / channel / receiver_type / window_hours 的合法值
-- 都在代码层(jobs_repo Literal + Pydantic JobIn/JobUpdateIn)校验,DB 不加 CHECK
CREATE TABLE daily_report_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  view TEXT NOT NULL,                            -- 'company' | 'personal'
  status TEXT NOT NULL DEFAULT 'active',         -- 'active' | 'paused' | 'archived'
  push_time TEXT NOT NULL,                       -- "HH:MM"
  push_freq TEXT NOT NULL DEFAULT 'weekdays',    -- 11 值,见 jobs_repo.PushFreq
  window_hours INTEGER NOT NULL DEFAULT 24,      -- 1-168 由 Pydantic 守
  channel TEXT NOT NULL DEFAULT 'feishu',        -- v1 仅 feishu
  receiver_type TEXT NOT NULL,                   -- 'groups' | 'users'
  receiver_ids TEXT,                             -- JSON array; NULL = 全部 bot 群
  next_run_at REAL,
  last_run_id INTEGER,
  last_status TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_notified_at REAL,
  created_by TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE daily_report_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER,                                -- NULL = 手动一次性触发
  trigger_type TEXT NOT NULL
    CHECK(trigger_type IN ('scheduled', 'manual', 'retry', 'makeup')),
  view TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK(status IN ('running', 'succeeded', 'failed', 'partial', 'skipped')),
  rc INTEGER,
  cards_sent INTEGER, cards_total INTEGER,
  ai_tokens_in INTEGER, ai_tokens_out INTEGER,
  error TEXT,
  debug_json TEXT
);
```

时间戳列统一存 Unix epoch REAL(`time.time()`);Python 层 ↔ tz-aware datetime(Asia/Shanghai)的换算在 repo 里统一处理。

外键关系**不走 DB cascade**:每天 365 天清理时,代码层先 `UPDATE jobs SET last_run_id=NULL WHERE last_run_id IN (...)`,再 `DELETE FROM runs WHERE id IN (...)`。

`daily_report_jobs` 的所有字段值集合(`view / status / push_freq / channel / receiver_type` + `window_hours` 数值范围)都在代码层维护(`jobs_repo` Literal 类型 + Pydantic `JobIn`/`JobUpdateIn` 校验),**不**进 SQLite CHECK 约束 — SQLite 的 CHECK 不支持 ALTER,后续扩枚举不需要走表重建迁移。

> 注:`daily_report_runs` 表的 `trigger_type` / `status` 仍带 CHECK,这两个枚举短期不会扩,等真要动时再顺手清。

## 调度状态机(`job_scheduler.py`)

参数(代码内常量,不暴露 settings):

| 常量 | 默认值 | 说明 |
|---|---|---|
| `POLL_INTERVAL_SEC` | 60 | 每 60 秒 poll 一次 jobs.list_due |
| `MISSED_TOLERANCE_MIN` | 30 | 漏跑 ≤30 分钟立即补,>30 分钟发漏跑卡 |
| `MAX_RETRY` | 3 | 失败重试上限(达上限后发失败卡 + 重置周期) |
| `RETRY_DELAY_MIN` | 5 | 失败后下次 next_run_at 推迟分钟数 |
| `RUNS_RETENTION_DAYS` | 365 | 每天清理 365 天前的 runs |

Poll 主循环:

```
loop every 60s:
  for job in jobs_repo.list_due(now):
    if job.id in self._running_threads and thread.is_alive(): skip
    if now - job.next_run_at > 30min:
      _handle_missed(job)         # 写 skipped run + 发漏跑卡 + 推下一周期
    else:
      _run_one_job_safely(job)    # 在 thread 里跑(LLM 慢调用不阻塞 asyncio loop)
                                  # 成功 → retry=0, next=下一周期
                                  # 失败 + retry<3 → retry++, next=now+5min
                                  # 失败 + retry==3 → 发失败卡, 重置 retry=0, next=下一周期

  if today not in self._last_cleanup_date:
    runs_repo.delete_before(now - 365d) → ids
    jobs_repo.clear_last_run_id_in(ids)
    self._last_cleanup_date = today
```

## API 端点(全部 `Depends(require_admin)`)

| Method | 路径 | 作用 |
|---|---|---|
| GET | `/api/admin/daily-report/jobs` | 列任务(默认过滤 archived) |
| POST | `/api/admin/daily-report/jobs` | 创建任务 |
| GET | `/api/admin/daily-report/jobs/{id}` | 任务详情 |
| PUT | `/api/admin/daily-report/jobs/{id}` | 部分更新配置 |
| PUT | `/api/admin/daily-report/jobs/{id}/status` | 切 active / paused / archived |
| DELETE | `/api/admin/daily-report/jobs/{id}` | 软删(置 archived) |
| POST | `/api/admin/daily-report/jobs/{id}/run-now` | 立即跑该 job 一次 |
| GET | `/api/admin/daily-report/jobs/{id}/runs?page=&size=` | 任务运行历史 |
| GET | `/api/admin/daily-report/runs/{run_id}` | 单条 run 详情(含 debug_json) |
| POST | `/api/admin/daily-report/manual-trigger` | 不绑 job 的一次性触发 |
| GET | `/api/admin/daily-report/admin-notify` | 取系统通知接收人 |
| PUT | `/api/admin/daily-report/admin-notify` | 写系统通知接收人 |
| GET | `/api/admin/daily-report/feishu-chats` | bot 所在群列表(供 UI 多选) |

完整字段、Pydantic 形态见 `server/api/daily_report_v2.py`;完整接口契约同步在 [`pivot-interface.md`](../pivot-interface.md) 里。

## 设置项(SQLite settings 表)

只 2 个 key,配置最少化:

| Key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `daily_report.admin_notify_chat_ids` | JSON list | `[]` | 系统通知接收群,空 = fallback 全部 bot 群 |
| `daily_report.admin_notify_open_ids` | JSON list | `[]` | 系统通知接收人 DM,空 = 不发 DM |

任务的所有配置项都在 `daily_report_jobs` 表里,**不**通过 settings 表读写;原 v0.2 的 `daily_report.{enabled, push_time, push_freq, time_window_hours, company_enabled, personal_enabled}` 已废弃,代码不再读。

## 前端

`web/src/pages/admin/DailyReportSection.tsx` 是日报 section 唯一入口,放在 `/admin` 页的"日报配置" section 内。包含:

- **任务列表** + "新建任务"按钮 — 每行展示视角 / 状态 / 频率 / 窗口 / 接收人摘要 / 下次运行 / icon 操作(历史 / 立即运行 / 暂停-恢复 / 编辑 / 归档)
- **任务编辑抽屉** — 右侧滑入,完整字段,radio 卡选接收类型,启用/暂停 toggle
- **运行历史抽屉** — 右侧滑入,分页 20/页,展开每条看 debug_json
- **手动触发卡** — 独立卡,view + 窗口 + 接收人,触发后轮询 run 状态
- **系统通知接收人卡** — 默认折叠,展开后选群 + 选人

`web/src/api.ts` 的 v2 fetcher 在 `// ── Daily Report v2 (multi-job) ──` 注释块下;旧 v0.2 fetcher 已删除。

## 测试矩阵(`server/tests/test_daily_report_*`)

| 测试文件 | 覆盖 |
|---|---|
| `test_daily_report_window.py` | compute_window:跨天、跨月、闰年边界 |
| `test_daily_report_collect_matter.py` | fake yaml 解析,timeline + comments 双重过滤 |
| `test_daily_report_shared_facts.py` | 聚合层不丢字段、tone 阈值 |
| `test_daily_report_company_narrate.py` | mock AI:正常 JSON / 缺字段 / 非 JSON / 越界 → fallback |
| `test_daily_report_personal_narrate.py` | mock AI:同上 + per-user 切换 |
| `test_daily_report_render.py` | 卡片关键字段 + AI/fallback template 颜色不同 |
| `test_daily_report_jobs_repo.py` | jobs CRUD + due query + 状态切换 + receiver_ids JSON 序列化 + 部分更新 + clear_last_run_id_in |
| `test_daily_report_runs_repo.py` | runs CRUD + 分页 + 365 天清理批次 |
| `test_daily_report_job_scheduler.py` | compute_next_run_at + poll 状态机(成功 / 失败重试 / 上限 / 漏跑) + 365 天清理 + 启停 |
| `test_daily_report_v2_api.py` | 13 个端点 + admin auth + run-now / manual-trigger thread 跑 + 分页 + 系统通知 round-trip |

整目录 75+ 用例全过。

## 已知坑(部署时注意)

- **AI 调用走主服务的 chat 设置**(`ai.openrouter_api_key` / `ai.base_url` / `ai.model`),没配 key 时 narrative 会走 fallback(浅蓝色卡 + "AI 缺席"提示),不会让 job 整体失败
- **scheduler 内嵌主服务**,主服务挂掉就停;这是有意为之(简化部署),由监控告警发现就行,不要再加 systemd timer 形成双调度
- **365 天清理**只在每天首次 poll 时跑一次(基于 `_last_cleanup_date` 当天日期);跨日不会重跑
- **回填漏跑**只在主服务重启后的下一次 poll 触发,不主动追跑历史
