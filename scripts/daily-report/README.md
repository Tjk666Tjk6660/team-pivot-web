# 团队日报 · 部署 + 调试速查

v0.2 主轴(基于 dengke #013):

- 只读 Pivot matter 数据,不接代码仓库
- 生成两份独立 LLM 报告(公司视角 + 个人视角)
- 共享底层事实数据,不共享 LLM 中间结果
- 默认每天 09:30 (Asia/Shanghai) 自动推到所有 bot 在的飞书群

设计 / 实施细节见:
- `AI-docs/daily-report/product-design.md`

---

## 1. 上线流程(简化版,无需 systemd timer)

v0.2 把调度器**集成到主服务进程**了,FastAPI lifespan 启动时挂个 asyncio
后台任务,睡到下一个推送时刻 → fire → 再睡。**部署只需要部署主服务,
不再需要单独配置 systemd timer**。

### 1.1 部署最新代码

按现有 rsync 流程同步到 `/opt/team-pivot-web/`,然后:

```bash
sudo systemctl restart team-pivot-web.service
```

主服务一启动,内置调度器就开始工作。

### 1.2 第一次跑,从 admin 验证

1. 浏览器进 `/admin`,输入管理员密码
2. 找到 **"日报配置 · 公司视角 / 个人视角"** 卡片
3. 默认配置 `enabled / company_enabled / personal_enabled` 都开启,推送时刻 09:30
4. 在最下方点 **"立即触发"** —— 勾上 dry-run 不发飞书,验证流水线
5. 取消 dry-run 再点一次 —— 真发到所有 bot 在的群,看效果
6. 等到次日 09:30,定时调度器会自动跑

### 1.3 关掉 / 开启日报

- **临时停推**:UI 上把"总开关 enabled"关掉再保存。调度器仍在跑但每次 fire 都会跳过
- **彻底停**:改 `daily_report.enabled` 为 `0` 也行,或者重启主服务前从 settings 表删除该配置项
- **暂停某一份**:UI 上把"公司视角"或"个人视角"开关单独关掉

---

## 2. 配置项一览

所有配置都在 `/admin` UI 上调,落到 SQLite `settings` 表。

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `daily_report.enabled` | bool | true | 总开关 |
| `daily_report.company_enabled` | bool | true | 公司视角报告开关 |
| `daily_report.personal_enabled` | bool | true | 个人视角报告开关 |
| `daily_report.time_window_hours` | int | 24 | 统计时间窗口(小时) |
| `daily_report.push_time` | str | "09:30" | 每日推送时刻(HH:MM,Asia/Shanghai) |
| `daily_report.allow_ai_read_body` | bool | false | AI 正文读取(预留,v0.2 暂未启用) |

---

## 3. 调试 / 运维

### 3.1 手动触发(从 admin UI)

`/admin` → 日报配置 → 立即触发 → 选 dry-run / no-AI 组合 → 看 last-run 状态

### 3.2 命令行回放(任意时间窗口)

适合"补昨天没跑成功的日报""调试新 prompt"这类场景。

```bash
cd /opt/team-pivot-web

# Dry-run + no-AI(最快、最省、不发飞书)
uv run python scripts/daily-report/run.py --dry-run --no-ai \
  --since 2026-04-26T09:30:00+08:00 \
  --until 2026-04-27T09:30:00+08:00 \
  --report-out /tmp/daily-report-debug.json

# Dry-run + 真 AI 调用(看 LLM 输出但不发卡)
uv run python scripts/daily-report/run.py --dry-run \
  --since 2026-04-26T09:30:00+08:00 \
  --until 2026-04-27T09:30:00+08:00

# 真发飞书(同时跑 AI 和广播)
uv run python scripts/daily-report/run.py \
  --since 2026-04-26T09:30:00+08:00 \
  --until 2026-04-27T09:30:00+08:00
```

### 3.3 查看主服务日志(含调度器日志)

```bash
sudo journalctl -u team-pivot-web.service -n 200 | grep daily_report
```

调度器关键日志:
- `daily-report scheduler started` —— 主服务启动时
- `daily-report scheduler sleeping Ns until ...` —— 每轮等下一次 fire
- `daily-report scheduled fire done rc=0` —— 一次成功
- `daily-report fire skipped: previous run still in progress` —— 上一次 LLM 还没跑完(罕见)

---

## 4. 已知约束

| 约束 | 说明 |
|---|---|
| 单 worker 假设 | 调度器在主进程内,如果以后 uvicorn 起多 worker(`--workers N`),会重复 fire。需要 SQLite 时间戳锁,目前未实现 |
| 不补跑 | 主服务挂了过夜恢复后,要等下一个推送时刻才会跑;管理员可在 `/admin` 手动触发补一次 |
| LLM 不可中断 | 推送中(LLM 慢调用)主服务重启,系统会等线程跑完才退出 |

---

## 5. 故障排查

| 现象 | 排查 |
|---|---|
| 群里没收到日报 | 1) `daily_report.enabled` 是否 0;2) 主服务日志 grep daily_report;3) 飞书 SSL 抖动(`_ssl.c:993` 类) —— notify.py 有重试,仍不行就重启主服务 |
| 卡片渲染异常 | `/admin` 立即触发选 dry-run 看 last-run debug,卡片 JSON 是否完整 |
| AI 总是 fallback | 1) `settings.ai.openrouter_api_key` 是否配置;2) 调用超时(`120s` for company / `180s` for personal,慢模型可能不够) |
| 推送时刻改了但还是按老时间跑 | 重启主服务一次。调度器在每轮 sleep 计算时读最新值,但当前 sleep 还是老 push_time |

---

## 6. 二期方向(未来)

- 多 worker 锁(SQLite 时间戳)
- 补跑机制(检测到主服务从超过 push_time 状态启动则立即补一次)
- AI 正文读取(`allow_ai_read_body` 配置项已预留)
- 周报 / 月报
