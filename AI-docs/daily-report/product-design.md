# Pivot 日报 · 产品设计

> v0.2 已落地。基于 matter「新需求-日报推送」中 dengke #005 / #013 + terry #008 + huangshengli #009 的讨论收敛。

---

## 〇、设计主轴

- **只读 Pivot matter 数据**,**不接入** git 代码仓库 / 不做 commit 统计
- **两份独立报告**:公司视角 + 个人视角,**共享底层事实数据,不共享 LLM 中间结果**(dengke #013 决议)
- **不做评分**(团队 / 个人都不做),只做事项推进叙事 + 整体节奏定性(active / steady / stalled)
- **进程内调度**:FastAPI lifespan 内挂 asyncio scheduler,不依赖 systemd timer
- **配置驱动**:管理员通过 `/admin` UI 调整开关 / 时间 / 频率;手动触发也走同一 UI

---

## 一、项目背景

Pivot 已经把团队工作活动结构化为 matter 模型 —— 每件事一条 timeline,事项的状态、推进、参与人、讨论都沉淀在 index 里。

团队负责人需要每天对所有 matter 的进展心中有数,以便识别风险、调配资源、决定下一步关注点。但 matter 数量上去之后,逐个翻 timeline 的成本会越来越高。

日报就是把这份沉淀数据每天定时整理成一份**事项推进叙事**:matter 时间线上发生了什么、谁推动了什么、目前处于什么状态 —— 推到飞书群,让管理层不必逐个翻 matter 也能掌握全局。

**产品定位:独立通知服务**。日报是 Pivot 向外输出的一条信息管道,在 IM 流量里触达管理层,不在 Pivot 站内承载页面。

---

## 二、目标

日报由两份独立 LLM 生成的报告组成:

### 2.1 公司视角报告

**回答 3 个问题**(由 LLM 用一段叙事一并回答):

1. 整体推进了什么?(file_type 分布 + verify 判定)
2. 哪个 matter 今天最活跃?(top_active_matters 强度话术)
3. 整体节奏如何?(active / steady / stalled 三选一定性)

### 2.2 个人视角报告

**逐人**生成一行叙述,涵盖每人当日的输入(think / 评论 / 被 mention 等)和输出(act / verify / result / insight / 状态推进等)。

**所有团队成员都要覆盖**,无活动者合并到一行 `最近一天无输入输出: A、B、C`(避免团队规模大时 N 行重复句撑爆篇幅,但仍明确点名)。

### 2.3 不是目标

| 不做 | 原因 |
|---|---|
| 不做绩效考核 / 个人排名 | 日报重点是事项推进,不是给人排名(dengke 原话) |
| 不做 todo list | 不是日报职责 |
| 不承载交互(评论 / 跳转) | 日报是只读推送 |
| 不接入代码仓库 / commit 统计 | 工作分布在多个 repo,单仓库会偏(dengke #005) |
| 不做 matter 视角逐个叙事 | dengke #013:第一版不做基于 matter 的逐事项报告 |

---

## 三、数据源(只一处)

**Pivot 数据仓库 matter index**(`/opt/team-pivot-web/var/git/<repo>/index/*.index.yaml`),只读访问。

读取的字段:

- `matter.current_status` / `matter.updated_at` / `matter.title`
- `timeline[].file / type / creator / owner / created_at / summary`
- `timeline[].status_change` / `verifications[]` / `comments[]`

读取 `users` 表(SQLite,`mode=ro`)做 pinyin → 中文名展示和个人维度聚合。

**不读** 代码仓库,**不读** commit history,**默认不读** matter 文件正文(v0.3 可能加 AI 下钻读正文,未实现)。

---

## 四、共享事实层 + 派生指标

dengke #013 强调"程序层统一提供同一份事实数据"。`shared_facts.py` 一次性算好所有派生指标,两份 LLM 调用各取所需:

| 字段 | 含义 | 给谁用 |
|---|---|---|
| `matter_events` | 24h 内的 timeline 事件清单 | 个人视角(按用户聚合) |
| `user_activities` | 全员(含 0 活动)的 input/output 聚合 | 个人视角 |
| `summary` | 窗口级总计数 | 公司视角 |
| `matter_status_breakdown` | `current_status → 触动 matter 数` | 公司视角 |
| `file_type_breakdown` | think / act / verify / result / insight 各几篇 | 公司视角("整体推进了什么") |
| `verify_judgements` | passed / failed / partial 各几次 | 公司视角("实质推进"信号) |
| `top_active_matters[]` | 按 activity_score 降序的 top N | 公司视角("最活跃 matter") |

`MatterActivityMetrics` 单条结构:

```
{
  path: "Pivot/数据迁移方案",      ← category/slug 引用 token,不是自然语言 title
  current_status: "finished",
  file_count: 3,
  file_types: { verify: 1, result: 1 },
  status_change: { from: "executing", to: "finished" },
  verify_judgements: { passed: 1 },
  comments_count: 2,
  activity_score: 16
}
```

**activity_score 公式**:`file_count + (5 if status_change else 0) + (3 if has result) + verify_passed*2 + verify_failed*2 + comments/2`。weights 是粗略经验值,实测调整。

---

## 五、LLM 调用契约

### 5.1 两次独立调用

| 调用 | 输入 | 输出 |
|---|---|---|
| **call C · 公司视角** | window + team_stats + matter_status_breakdown + top_active_matters | `{ summary, tone }` |
| **call P · 个人视角** | 全员 input/output 聚合(只活跃用户喂 LLM) | `{ entries: [{ pinyin, narrative }] }` |

两次调用**独立运行,互不依赖中间结果**(dengke #013)。共享底层 SharedFacts,但 LLM prompt / 输出 schema 不共享。

### 5.2 公司视角 prompt 关键约束

- summary 必须是 2-4 句中文叙事段落,**不切分子区块,不用 markdown**
- 必须给 tone:`active / steady / stalled` 三选一
- 描述"实质推进"必须基于 verify_judgements 数据(passed / failed 数字)
- top_active_matters 用**强度话术**("讨论最激烈" / "落地最快" / "评论密度最高"),**禁止描述 matter 内容**(prompt 里没 summary 数据)
- matter 引用必须用 path 原文(`Pivot/xxx`),不要改名 / 翻译 / 缩写
- **不要把 path 中的 category 当方向归类** —— 防止 LLM 把"Pivot""enclaws"自由聚类成虚构产品方向
- 末尾不绝对(用"整体""主要""可能",不用"完成""确定")

### 5.3 个人视角 prompt 关键约束

- 只为活跃成员生成 narrative,**无活动者由程序填固定字符串**"今天没有任何输入和输出"(避免 LLM 给无活动者编理由 / 模糊话术)
- 单条叙述 1-2 句,中文,直接陈述事实
- 反绩效化:不打分 / 不排名 / 不对比
- 防御:LLM 漏返回 → 程序 stub;LLM 多返回不存在用户 → 忽略

### 5.4 LLM 失败兜底

任一调用 schema 不合格 / 异常 / 超时 → 该报告进 fallback 模式:卡片用 wathet 模板,内容退化为统计性兜底文案(公司:数字陈述;个人:全员 stub)。**另一份报告不受影响**。

---

## 六、产出形式

两张独立飞书卡,推到所有 bot 在的群。

### 6.1 公司日报卡(示意)

```
📊 公司日报 · 4-28
📅 覆盖窗口:2026-04-28 09:00 → 2026-04-29 09:00

📈 团队总览
matter 事件 55 篇 · 状态推进 13 次 · 评论 20 条 · 涉及 matter 19 个 · 活跃成员 11 人

🚀 整体节奏:积极推进
今日团队产出 40 篇 think + 10 篇 act + 12 篇 verify + 1 篇 result,
verify 判定 8 passed / 2 failed,显示多任务线进入实质验证。今日交互
密度最高的是 enclaws/OPC-数字员工服务台-产品规划,9 篇文件 + 集中
评论形成高热度讨论区;落地最快的是 Pivot/支持SSE刷新...

本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论。
```

### 6.2 个人日报卡(示意)

```
👥 个人日报 · 4-28
📅 覆盖窗口:2026-04-28 09:00 → 2026-04-29 09:00

👥 团队动态
· dengke:推进登录链路收口,完成 1 篇 verify、1 篇 result;在权限体系
  评论中补充了多租户隔离的视角
· liuyu:负责验收推进,完成 2 篇 verify;在权限体系给出技术意见
· terry.tao:在新需求-日报推送补充 v0.2 PRD,推进设计评审
· 最近一天无输入输出: 史宏伟、高勇

本日报由 AI 基于 Pivot matter 数据生成,仅供管理参考,不作为最终结论;不用于绩效评价。
```

模板色:`blue`(AI 成功)/ `wathet`(fallback / no_active_users)。

---

## 七、调度 + 触发

### 7.1 进程内 asyncio scheduler

主服务 FastAPI lifespan 启动时挂 `DailyReportScheduler` 后台任务:

1. 算下一个推送时刻(当前 push_time + push_freq:weekdays 跳过 Sat/Sun)
2. `asyncio.wait_for(stop_event.wait(), timeout=sleep_secs)`
3. 时间到 → 检查 `daily_report.enabled` → 开 → 在新 thread 跑 runner(LLM 慢调用不能阻塞 asyncio loop)
4. 回到 1

主服务停止时优雅取消调度循环,但**正在跑的 LLM 线程让它跑完**(LLM 调用不能安全 abort)。

### 7.2 手动触发

`/admin` 管理面板 → 日报配置卡片 → "立即触发"按钮:

1. POST `/api/admin/daily-report/trigger` { dry_run, no_ai }
2. 后端 200 + run_id 立即返回
3. 后台 thread 跑 runner,结果存模块级 `_last_run` dict
4. 前端轮询 `GET /last-run` 直到 `finished_at` 非空(默认 3s 间隔)
5. toast 提示成功 / 失败

---

## 八、配置项 (admin UI 可调)

存 SQLite `settings` 表,**懒初始化**(没行用代码默认值,首次保存才写 DB):

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `daily_report.enabled` | bool | true | 总开关,关闭后调度和手动触发都跳过 |
| `daily_report.company_enabled` | bool | true | 公司视角报告开关 |
| `daily_report.personal_enabled` | bool | true | 个人视角报告开关 |
| `daily_report.time_window_hours` | int | 24 | 统计时间窗口,1-168 |
| `daily_report.push_time` | str | "09:30" | 每日推送时刻(HH:MM,Asia/Shanghai) |
| `daily_report.push_freq` | str | "weekdays" | 推送频率:`daily` 或 `weekdays`(跳过 Sat/Sun) |

UI 布局(3×2 对称网格):

```
┌──────────────┬──────────────┐
│ 总开关        │ 仅工作日推送   │
├──────────────┼──────────────┤
│ 公司视角报告  │ 个人视角报告   │
├──────────────┼──────────────┤
│ 统计时间窗口  │ 每日推送时刻   │
└──────────────┴──────────────┘
```

---

## 九、关键用户链路

### 场景 1:管理者每日通过定时报告了解全局

1. 09:30(由 `push_time` 控制)scheduler 自动触发
2. runner 读 matter index + users 表,聚合 SharedFacts
3. 公司视角 LLM(120s 超时)生成段落 + tone
4. 个人视角 LLM(180s 超时)生成全员 narratives
5. 渲染两张卡片,飞书 SDK 广播到所有 bot 在的群
6. 管理者打开飞书群,1 分钟读完两张卡

### 场景 2:管理员临时停推日报

`/admin` → 日报配置 → 关闭"总开关"→ 保存。下次调度 fire 时检查到 `enabled=0`,直接跳过(loop 不停,可随时再开)。

### 场景 3:管理员手动补跑

`/admin` → 日报配置 → "立即触发"按钮(可选 dry-run / no-AI)→ 后台 thread 跑 → UI 轮询 last-run 状态 → toast 提示结果。

---

## 十、降级 + 鲁棒性

| 失败类型 | 行为 |
|---|---|
| 全员 0 活动 | 公司视角进 `no_activity` 状态(固定文案 + tone=stalled);个人视角全部固定"无活动"行 |
| AI 调用失败 / 超时 | 该报告 fallback 模板,**另一份不受影响** |
| AI 返回非 JSON / schema 错 | 同上 |
| 飞书 SSL 抖动 | `notify._http_get/post_with_retry` 一次性重试(实测 80%+ 抖动靠这条吃掉) |
| 数据仓库读取失败 | runner 退出码 2,日志 ERROR,不发卡 |
| 主服务进程崩溃 / 重启 | 调度器随主服务一起停;下次启动后等到下个 push_time 再跑(**不补跑**;管理员可手动触发补一次) |

---

## 十一、本期不包含

- 接入代码仓库 / commit 统计 / 评分
- matter 视角(逐 matter 因果叙事)
- AI 正文读取下钻(`tools/read_matter_file` 等待 v0.3)
- 个人日报推到个人 IM 会话(目前统一发到 bot 群,dengke #012 暂定)
- 多 worker 锁(scheduler 单 worker 假设)
- 不补跑(主服务挂过夜恢复后等下个 push_time)
- 多 IM 平台(钉钉 / Slack / 企业微信)
- 日报站内存档与历史查看
- 周报 / 月报

---

## 十二、与 dengke / terry / huangshengli 讨论的对应

本设计是这条讨论链的最终落地版:

| 帖号 | 作者 | 关键贡献 |
|---|---|---|
| #001 - #002 | terry | 独立通知服务定位 |
| #005 | dengke | 收窄数据源到 matter only,提出三层叙事 |
| #006 | terry | PRD v0.2,决策辅助定位 + AI 读正文 + 后台配置 |
| #008 | terry | PRD v0.3,接受 dengke 三层叙事方向 |
| #009 | huangshengli | 替代方案:推送形态、风险呈现、合并行、AI 调用编排、push_freq |
| **#012 - #013** | **dengke** | **决议:第一版不做 matter 视角;只做公司 + 个人两份独立报告;独立运行;统一推送到飞书机器人群;行动优先** |

最终落地以 #013 为准。
