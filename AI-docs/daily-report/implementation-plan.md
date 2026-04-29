# Pivot 日报 · 实施计划 (v0.2)

> 配套产品文档:[`product-design.md`](./product-design.md)
> 部署 + 调试速查:[`scripts/daily-report/README.md`](../../scripts/daily-report/README.md)
>
> 本文档专注**工程视角**:模块结构 / 数据流 / 测试矩阵 / 关键设计决策。
> 产品决策见 product-design.md;部署细节见 README.md;不重复。

---

## 一、模块结构

```
server/daily_report/
├── __init__.py
├── types.py              事实层 dataclass(TimeWindow / MatterEvent / UserActivity / TeamSummary)
├── window.py             [since, until) 时间窗口推算 + parse_iso_window
├── collect_matter.py     扫 index 提取 timeline 事件
├── aggregate.py          events → UserActivity[] + TeamSummary
├── shared_facts.py       SharedFacts 派生层(file_type_breakdown / verify_judgements
│                         / top_active_matters / matter_status_breakdown)
├── company_narrate.py    公司视角 LLM 调用(call C),输出 { summary, tone }
├── personal_narrate.py   个人视角 LLM 调用(call P),输出 { entries[] }
├── render.py             build_company_card / build_personal_card
├── runner.py             串起来:collect → aggregate → shared_facts → 两次 LLM → 渲染 → broadcast
├── scheduler.py          asyncio 后台调度,挂 FastAPI lifespan
└── config_keys.py        SQLite settings 配置键

server/api/
└── daily_report.py       admin 端点:GET/PUT /config / POST /trigger / GET /last-run

server/ai/oneshot.py      generate_text 同步包装(asyncio.run + stream_chat 收集 text deltas)
server/notify.py          _http_get/post_with_retry SSL 抖动一次性重试
server/users.py           UserRepo.list_all 全员加载
server/git_ops.py         (无新增,v0.1 的 log_commits 已删除)

scripts/daily-report/
├── README.md             部署 + 调试速查(给运维)
└── run.py                CLI 入口(运维 / 回放 / 调试,非 production 主路径)

web/src/
├── api.ts                fetchDailyReportConfig / updateDailyReportConfig /
│                         triggerDailyReport / fetchDailyReportLastRun
└── pages/AdminPage.tsx   DailyReportSection 卡片
```

**v0.1 已删除模块**(从 git 历史看):
- `score.py` / `attribution.py` / `collect_git.py` —— 评分 + git 数据源整套
- `git_ops.py::log_commits` 函数
- 对应所有测试

---

## 二、数据流

```
[内置 scheduler 在 push_time 唤醒]   或   [admin POST /trigger]
                    │
                    ▼
            run_daily_report
                    │
                    ▼
   collect_matter_events(index_dir, window)
                    │
                    ▼
       aggregate(events, all_users, window)
        → (UserActivity[], TeamSummary)
                    │
                    ▼
   build_shared_facts(events, activities, summary, window)
        派生:matter_status_breakdown / file_type_breakdown
              / verify_judgements / top_active_matters
                    │
                    ▼
       ┌───────────┴───────────┐
       ▼                       ▼
  call C(公司视角)        call P(个人视角)
  → CompanyNarrative      → PersonalNarrative
       │                       │
       ▼                       ▼
  build_company_card      build_personal_card
       │                       │
       └───────────┬───────────┘
                   ▼
        notifier.broadcast_card
            (两张独立卡)
```

两次 LLM 调用**互不依赖**(共享 SharedFacts,但 prompt / 输出独立)。任一失败仅影响该报告,另一份照常输出。

---

## 三、关键设计决策

### 3.1 SharedFacts 集中派生指标

为什么不让两个 narrate 各自从 raw events 算 file_type_breakdown / top_active_matters?

- 单一来源:同一份事实给两个 LLM,避免计数偏差
- 复用:测试 / 渲染 / 调试也读同一份
- LLM 输入构造时直接 dict,不需要每次计算

### 3.2 LLM 输入用 `category/slug` 而不是 matter title

`top_active_matters[].path` = `Pivot/数据迁移方案`,不是单纯 title。

理由:
- title 是自然语言,LLM 容易自由"聚类"成虚构产品方向("UI 优化 / AI 集成"等)
- path 是引用 token,LLM 更倾向当 ID 引用而非语义重组
- prompt 明确禁止"把 path 中的 category 当方向归类"

### 3.3 个人视角无活动者由程序填,不喂 LLM

`narrate_personal` 把 active 用户的 input/output 喂 LLM,inactive 用户**不进 prompt**,直接由程序填固定字符串"今天没有任何输入和输出"。

理由:
- LLM 看不到无活动用户的数据时,不会编造任何叙述
- 防御 LLM 出现"较为安静""活动较少"等模糊话术(dengke 明确禁止)
- 节省 token

### 3.4 进程内 asyncio scheduler vs 外部 systemd timer

v0.1 用 systemd timer,v0.2 改为进程内。

| 维度 | systemd timer | 进程内 |
|---|---|---|
| 部署 | 单独装 unit + 改 user/path | 主服务一启就跑 |
| 状态可观测 | journalctl + 自定义日志 | 跟主服务日志同流 + last-run 字典 |
| 主服务 / 调度同生死 | 独立(主服务挂日报照跑) | 一起(主服务挂日报也停) |
| 多 worker | 不影响 | **会重复 fire**(单 worker 假设) |

我们选进程内,因为:
- 部署简化(只要 rsync + restart 主服务)
- 配置改完即时生效(scheduler 每轮 sleep 重读 settings,无需重装 unit)
- prod 当前是单 uvicorn 进程,不存在多 worker 重复触发问题

### 3.5 LLM 慢调用不阻塞 asyncio loop

scheduler 在时间到时,把 `run_daily_report` offload 到新 thread(`threading.Thread`),不在 asyncio coroutine 里直接跑。

理由:
- `run_daily_report` 是同步 + LLM 慢调用(60-180s),阻塞 asyncio loop 会拖累整个 FastAPI 进程
- thread daemon=True,主进程退出不等
- 副作用:无法安全 abort 中途的 LLM 调用,主服务停止时只能让线程跑完(graceful shutdown 注释明确)

### 3.6 配置懒初始化(SQLite settings)

`Database.__init__` 只建表,不预填默认值。读路径 inline 默认值:

```python
_read_bool(settings, KEY_ENABLED, default=True)
(settings.get(KEY_PUSH_TIME) or "09:30").strip()
```

首次保存(admin 点保存)才把行写进 DB。好处:
- 加新 key 无需 schema migration
- 改默认值无需 DB 更新(没保存过的实例自动用新默认)
- 删 key 无需 DB 清理

---

## 四、测试矩阵

| 测试文件 | 覆盖 | 用例数 |
|---|---|---|
| `test_daily_report_window.py` | 时间窗口推算、跨月、闰年、tz 边界 | 7 |
| `test_daily_report_collect_matter.py` | yaml 解析、timeline + comments 双过滤、created_at 兜底 | 11 |
| `test_daily_report_shared_facts.py` | category_of / 派生指标 / activity_score 排序 / immutability | 13 |
| `test_daily_report_company_narrate.py` | happy AI / fallback / schema 错 / tone 越界 / 截断 | 16 |
| `test_daily_report_personal_narrate.py` | LLM 漏返回 / 多返回 / 无活动者程序填 / 不喂 inactive | 11 |
| `test_daily_report_render.py` | 公司卡 + 个人卡布局 / template 颜色 / 合并行 / 免责声明 | 12 |
| `test_daily_report_scheduler.py` | _next_fire_at / push_freq weekday-skip / 启停 / 重复 fire 防御 | 15 |
| `test_daily_report_api.py` | GET/PUT config / 401 / trigger / last-run / 后台 thread crash | 7 |
| `test_ai_oneshot.py` | generate_text 收集 deltas / timeout / AIError | 5+ |
| `test_notify.py` | broadcast_card 委托 / SSL 重试(后续可加) | 既有 + 1 |
| `test_users.py` | list_all 包含已注册全员 | 既有 + 1 |

不写实发飞书的 e2e。LLM 一律 mock。

---

## 五、降级路径汇总

| 失败点 | 处理 | exit code |
|---|---|---|
| `daily_report.enabled = 0` | runner 跳过,日志 INFO | 0 |
| db_path 不存在 | runner 报错,日志 ERROR | 2 |
| workspace_index_dir 不存在 | runner 报错 | 2 |
| 全员 0 活动 + 0 matter | 公司视角 `status="no_activity"` 固定文案;个人视角全员"无活动"行;**仍发卡** | 0 |
| 公司视角 LLM 异常 / schema 错 | `CompanyNarrative.status="fallback"`,卡片 wathet,内容退化为统计陈述 | 0(发了) |
| 个人视角 LLM 异常 | `PersonalNarrative.status="fallback"`,活跃成员走程序 stub,inactive 仍固定 | 0 |
| 飞书 SSL 抖动 | notify._http_get/post_with_retry 重试 1 次 | 大概率成功 |
| 飞书发送失败(2 次都不行) | 该卡片 broadcast_errors 记录,**另一卡不受影响** | 1(部分发) |
| AI 配置缺失(api_key 空) | 两份报告都进 fallback,卡片仍发(标注"AI 生成失败") | 0 |
| 主服务重启 | scheduler 优雅停;**正在跑的 LLM thread 不打断**(daemon=True 但等线程结束) | n/a |

---

## 六、性能 / token 实测

基于 prod 数据(11 用户 / 19 matter / 55 文件 / 13 状态变更):

| 调用 | 输入 token | 输出 token | 端到端 |
|---|---|---|---|
| 公司视角 (qwen3.6-plus) | ~1500 | ~250 | 50-90s |
| 个人视角 (qwen3.6-plus) | ~3000 | ~400 | 60-120s |

公司视角 timeout 设 120s,个人视角 180s,实测够用。

---

## 七、未来迭代方向

- **多 worker 锁** —— SQLite 时间戳:scheduler fire 前先 INSERT (timestamp, scheduler_id),CONFLICT 即跳过本次
- **补跑** —— 主服务启动后看 last-run.finished_at,若超过一个 push_time 周期,立即补一次
- **AI 正文读取下钻** —— 公司视角 LLM 在 summary 不足时调用 `read_matter_file` 工具(MCP 工具);单次报告读取上限 + 后端记录 token 消耗
- **个人日报独立路由** —— 选项推到个人 IM 会话(隐私感更好,terry #010 主张),需在个人 narrate 后接 FeishuNotifier.dm_user
- **周报 / 月报** —— 复用 SharedFacts 派生层,把窗口扩大,LLM prompt 重写为聚合视角
