# Pivot 日报 · 产品设计

---

## 〇、设计主轴

- **只读 Pivot matter 数据**,**不接入** git 代码仓库
- **不做** commit 统计、**不做**任何评分(团队/个人都不做)
- 核心是 **AI 因果叙事**(讲清楚事项在干什么、推进到哪、有什么新变化、下一步关注什么),而不是结构化统计表
- 输出包含 **matter / 个人 / 公司**三层视角
- 实现上采用**分层阅读**:程序负责扫描 index 和筛选候选 matter,AI 负责判断 summary 是否足够、必要时自主读取原文,然后生成叙事

---

## 一、项目背景

Pivot 已经把团队工作活动结构化为 matter 模型 —— 每件事一条 timeline,事项的状态、推进、参与人、讨论都沉淀在 index 里。

团队负责人需要每天对所有 matter 的进展心中有数,以便识别风险、调配资源、决定下一步关注点。但 matter 数量上去之后,逐个翻 timeline 的成本会越来越高。

日报就是把这份沉淀数据每天定时整理成一份**事项推进叙事**:matter 时间线上发生了什么、谁推动了什么、目前处于什么状态、哪里需要关注 —— 推到飞书群 / 个人会话,让管理层不必逐个翻 matter 也能掌握全局。

**产品定位:独立通知服务**。日报不在 Pivot 站内承载页面,而是作为独立的消息推送管道,把每日摘要送进管理层既有的 IM 信息流。Pivot 负责生产事项数据,日报负责消费数据并推送 —— 两者解耦,互不依赖,也不与未来的调度台(scheduler)在站内功能上重叠。

---

## 二、目标

日报回答 4 个问题,全部由 AI 用**叙事**方式回答,不出统计表:

1. 团队整体在往哪些方向发力?
2. 哪些事项有实质推进?
3. 哪里需要关注?(风险 / 阻塞 / 长期无进展)
4. 谁最近一天无输入输出?(透明,不评价)

### 不是目标

| 不做 | 原因 |
|---|---|
| 不做绩效考核 / 个人排名 | 重点是说明事项推进,不是给人排名或做绩效评价 |
| 不做 todo list | 不是日报职责 |
| 不承载交互(评论 / 回复 / 跳转操作) | 日报是只读推送 |
| 不接入代码仓库 / commit 统计 | 工作分布在多个 repo,单仓库会偏 |

---

## 三、数据源(只一处)

**Pivot 数据仓库 matter index**(`/opt/team-pivot-web/var/git/<repo>/index/*.index.yaml`),只读访问。

### 3.1 matter 视角的读取范围:不做 24h 时间过滤

为了让"无推进概括""风险标注""整体定性"这些判断有完整依据,**程序在数据准备阶段读取 matter 全集**(所有还活着的 matter,而不是只读 24h 内动过的)。是否把每条都喂给 LLM 是另一回事,见 §3.5.2 的硬过滤。

程序的读取策略:

- 读取**所有非终态 matter**,即 `current_status ∈ { planning, executing, paused }`
- 加上窗口内**新进入终态**的 matter,即 `current_status ∈ { finished, cancelled, reviewed }` 且最近一次 `status_change` 落在 24h 内的(代表"今日完成 / 终止"事件,需要进叙事)
- 已经在 24h 之前就终态的 matter 一律不读(无需再次叙述历史完成项)

每条 matter 在交给下游(LLM 或程序合成)之前,程序附加**派生标签**:

| 标签 | 含义 |
|---|---|
| `has_window_activity: bool` | 24h 内 timeline 是否有任何新文件 / 评论 / 状态变更 |
| `last_activity_at: datetime` | 最近一次 timeline 项的时间(用于"已停滞 N 天") |
| `days_since_last_activity: int` | 距今天数,辅助识别长期无进展 |
| `risk_flag: string \| null` | 程序按硬规则识别的风险类型(`long_idle` / `failed_unhandled` / `paused_overdue` 等),无风险则 `null` |

派生标签是程序硬过滤(§3.5.2)的判定依据:`has_window_activity = true` 或 `risk_flag != null` 的 matter 才会喂 LLM,其余只参与计数。

### 3.2 读取的 index 字段

- `matter.current_status` — 事项当前阶段
- `matter.updated_at` — 排序参考(不做窗口过滤)
- `timeline[].file / type / creator / owner / created_at / summary` — 文件级动态
- `timeline[].status_change` — 状态迁移事件(`{from, to}`)
- `timeline[].verifications` — 验收结论(`judgement: passed/failed/...`)
- `timeline[].comments[]` — 评论 / @mention 协作信号
- `timeline[].quote` — 引用关系,辅助 AI 推断因果链

读取 `users` 表(SQLite,`mode=ro`)做 pinyin → 中文名展示,以及个人维度聚合。

### 3.3 个人视角:24 小时活动窗口,全员覆盖

脚本每天定时启动(默认 09:00),**按过去 24 小时**聚合每位成员的活动:

- 程序遍历 `users` 表全员,**不在程序层按"是否活跃"过滤掉任何成员**
- 对每位成员,按 24 小时窗口聚合 timeline 上的输入和输出(分类规则见下表)
- 24 小时内有活动 → AI 生成一行叙事:今日的输入 / 输出 + 涉及 matter
- 24 小时内无活动 → 该成员**不单独占行**,渲染层合并到一行(见 §4.1 / §5),内容固定为"**最近一天无输入输出**",不写模糊话术

**时间窗口仅在个人视角生效**,matter 视角和公司视角不按 24 小时过滤(详见 §3.1)。

#### 输入 / 输出分类规则(程序数据准备层就打好,不让 LLM 推断)

| 类别 | 包含 |
|---|---|
| **输入(被动 / 参与型)** | 自己写的 think;在他人 matter 下的评论;**被他人 mention**(自己出现在他人 comments[].mentions[]);收到的 verify 判断针对的是自己的 act |
| **输出(主动 / 产出型)** | 自己创建的 act / verify / result / insight;由自己触发的 status_change;**主动 mention 别人**(自己评论里 @ 了别人);**对其他 matter 的关键贡献**(在 owner / creator 都不是自己的 matter 上,做了写文件 / 写 verify 的动作) |

注:think 默认归"输入"(规划 / 思考类),与 act 起跑型输出区分;但若 think 触发了 status_change(例:planning → executing),那条 status_change 进"输出"。

**不读** `team-pivot-web` 代码仓库,**不读**任何 commit history,默认**不读** matter 文件正文(详见下方分层阅读)。

### 3.4 分层阅读策略

正常流程下 AI 只看 index:summary、timeline 摘要、状态变化、评论摘要。

当 AI 判断 summary 信息密度不足以做出可靠的因果叙事时(例如 summary 过短、状态变化原因不明、可能产生误判),**自主决定读取相关文件原文**(对应 markdown 正文)。规则:

- AI 只在判断必要时读,**不**默认读所有
- 单次日报生成有总读取量上限(代码内默认值)
- 每次记录读取次数 / 涉及文件数 / 额外 token 消耗 / 总耗时,作为后续策略调整依据

### 3.5 AI 调用编排

#### 3.5.1 三次调用,每层视角独立

为了降低 LLM 单次理解负担、提升输出质量,**三层视角拆成三次独立调用**,而不是一次性吃下所有数据产出整张日报:

| 调用 | 输入 | 输出 |
|---|---|---|
| **call A · matter 视角** | 有活动 matter + 风险候选 matter(各自带派生标签) | `matter_progress[]` + `attention[]` |
| **call B · 个人视角** | 全员 24 小时内的输入 / 输出条目(含 0 活动占位) | `personal_dynamics[]` |
| **call C · 公司视角** | A、B 的输出 + 整体计数(N 个有活动 / M 个无推进 / K 个风险) | `company_overview { summary, tone }` |

A、B 可并行;**C 必须在 A、B 之后串行执行**,基于前两次的事实合成整体定性,避免 LLM 凭空给出"积极 / 平稳 / 偏停滞"。

#### 3.5.2 程序层硬过滤:无推进 matter 不喂 LLM

数据预筛阶段就做切分,LLM 只看值得叙事的 matter:

| matter 类型(程序按派生标签判定) | 处理 |
|---|---|
| 24h 内 timeline 有活动 | **喂 call A**(进"关键进展"段) |
| 24h 无活动,但命中风险硬规则(long_idle / failed_unhandled / paused_overdue 等) | **喂 call A**(进"需要关注"段) |
| 24h 无活动,且无风险 | **不喂 LLM** — 程序直接计数生成 `"另有 N 个 matter 无推进"` 一句话,合并到 matter 视角清单尾部 |

理由:无活动且无风险的 matter **没有事实可叙**。让 LLM 写"无更新 / 保持现状 / 持续推进"这类话只是话术污染,且浪费 token。程序按计数直接出结论即可。

#### 3.5.3 工具调用:summary 不足时返读正文

**call A 内** LLM 默认只看 index 字段(`current_status` / `timeline` 摘要 / `status_change` / `verifications` / `comments` / `quote`)。当 summary 信息密度不足以判断推进或风险时(例:summary 过短、状态变化原因不明、可能产生误判),**允许 LLM 主动调用工具读取 markdown 正文**:

```
tool: read_matter_file
input:  { matter_id: string, file_path: string }
output: { content: string, truncated: bool }
```

回路约束:

- **仅在 call A 内可用**;call B(个人视角)/ call C(公司视角)不开放此工具
- 单次日报生成的总读取次数有**代码内默认上限**;超出则工具返回 `{ error: "read budget exhausted" }`,LLM 必须基于已有 index 信息继续
- LLM 读完正文后基于内容继续生成,无需二次确认
- 每次调用记录:`matter_id` / `file_path` / 返回字符数 / 是否截断 / token 消耗,作为后续上限调整依据

#### 3.5.4 关键提示词(系统侧硬约束)

三次调用共享的硬约束:

- **角色定位**:Pivot 日报生成器,只生成 matter 推进事实的因果叙事,**不打分、不评价个人产出**
- **禁止臆造**:任何陈述必须基于输入字段(或 call A 通过工具读到的正文)。不允许编造未发生的动作、不存在的人、不存在的状态迁移
- **不输出技术细节**:不引用文件路径、commit hash、issue 号、内部 ID
- **禁止 markdown 链接 / emoji**(emoji 由渲染层注入)
- **禁止换行符以外的控制字符**
- **总篇幅 200-400 字**(三次调用各自的 narrative / summary 字段加总后,程序拼出的卡片正文落在该区间;**暂时设置,调试阶段根据实际生成质量调优**)。三次调用按比例分配:call A 占大头(约 60%),call B 次之(约 25%),call C 最少(约 15%)

各调用的额外约束:

- **call A(matter 视角)**:清单逐条输出,**不允许把多个 matter 合并到一段**;每条一段因果叙事;`status_transition` 仅在确实发生迁移时填,否则 `null`
- **call B(个人视角)**:**全员都出现**,顺序与 `users` 表一致;`personal_dynamics[]` 仍按"每人一条"输出(LLM 不做合并),`has_activity = false` 的条目 `narrative` **固定为空字符串 `""`** —— 合并行由**渲染层**统一处理,LLM 不输出"最近一天无输入输出"这个串(避免 LLM 凭空给无活动者编理由);**禁止使用任何模糊话术**(如"暂未活跃" / "仍在持续推进" / "保持关注")
- **call C(公司视角)**:`tone` 必须从 `active` / `steady` / `stalled` 三选一;`summary` 是 2-3 句叙事段落,**基于 A、B 的事实合成,不允许引入新 matter 或新人**

#### 3.5.5 输出结构约束(JSON Schema)

三次调用各输出一个独立 JSON,程序合并后渲染卡片。任一字段缺失或类型不符 → 触发 §4.4 降级流程。

```json
// call A 输出
{
  "matter_progress": [
    {
      "matter_id": "string",
      "title": "string",
      "current_status": "planning | executing | paused | finished | cancelled | reviewed",
      "status_transition": "string | null",
      "narrative": "string"
    }
  ],
  "attention": [
    {
      "matter_id": "string",
      "title": "string",
      "risk_type": "string",
      "owner": "string",
      "advice": "string"
    }
  ]
}

// call B 输出
{
  "personal_dynamics": [
    {
      "user": "string",
      "has_activity": "boolean",
      "narrative": "string"
    }
  ]
}

// call C 输出
{
  "company_overview": {
    "summary": "string",
    "tone": "active | steady | stalled"
  }
}
```

字段约束:

- `matter_progress` 排序:有 `status_transition` 的优先,其次按 `last_activity_at` 倒序
- `attention` 为空时 `[]`,不允许 `null`
- `personal_dynamics` 必须**覆盖 `users` 表全员**;`has_activity=false` 时 `narrative === ""`(空字符串,合并行展示由渲染层处理)
- `matter_no_progress_summary`(无推进 matter 概括)**由程序在调用前计数生成**,不进入任何一次 LLM 调用;渲染时拼到 matter 视角清单尾部

### 3.6 资源访问表

| 资源 | 位置 | 读 / 写 |
|---|---|---|
| matter index | `/opt/team-pivot-web/var/git/<repo>/index/*.index.yaml` | 只读 |
| matter 文件正文(按需) | `/opt/team-pivot-web/var/git/<repo>/discussions/...` | 只读 |
| 用户表 | `var/data.db` (SQLite,`mode=ro`) | 只读 |
| 系统配置 | `data.db.settings` 表 | 只读 |
| AI 模型 | OpenAI 兼容端点 | 出站 HTTPS |
| 飞书 IM | 飞书 API(沿用 `FeishuTokenManager`) | 出站 HTTPS |
| 日报运行日志 | `var/log/daily-report.log` | append |

### 3.7 进程隔离

- 日报脚本是**独立一次性进程**(systemd timer 调起),与 Pivot 主服务在同一台机器但不共用进程
- 主服务挂掉不影响日报触发;日报崩掉不会拖累主服务
- 数据仓库 git 工作树**只读使用**,不与主服务的 `Workspace.write_session` 写路径竞争锁

---

## 四、产出形式

### 4.1 三层叙事视角

三层视角各自的输出形态不同,**matter 和个人是清单化输出(逐条列出)**,**只有公司视角是叙事段落**。三者不能混在一起,也不允许"一段话塞满所有 matter / 所有人"的写法。

#### 第一层:matter 视角(清单化输出)

**输出形态:逐个 matter 列出,每个 matter 一段因果叙事**,不允许把多个 matter 合并到一段里。

对**有推动**(timeline 有新文件 / 新评论 / 状态变化)的每个 matter,各自一条:

> 这个 matter 在干什么 → 之前进展到哪里 → 谁做了什么输入或行动 → 使它发生了什么变化 → 现在处于什么状态 → 下一步应该关注什么

对**没有推动**的 matter,**不**逐个展开,而是用一段话宏观概括(这一段独立于上面的清单,放在清单尾部):

- 哪些 matter 处于停滞 / paused
- 是否有明显风险(长时间没动 / 阻塞下游)
- 是否需要 owner 跟进

#### 第二层:个人视角(清单化输出 + 无活动合并行)

**输出形态**:

- **有活动者**:每人独占一行,逐个列出。绝不允许把多个有活动者的动作糅进一段叙述
- **无活动者**:**合并到清单末尾的一行**,所有人名顿号串联,固定模板:`最近一天无输入输出: dengke、liuyu、huangshengli、…`
- 这样既满足 dengke #005"明确点名、不用模糊话术"的要求,又避免团队成员多时(>20 人)无活动者占满整张卡片、把活跃成员动态挤出屏幕

输入 / 输出的字段分类规则见 §3.3 表(由程序数据准备层打好,不让 LLM 推断)。

**所有团队成员都要被覆盖**,要么在有活动者清单里、要么在合并行里 —— 不允许遗漏。这是给管理层做团队动态透明用的,**不是评价个人产出**。

#### 第三层:公司视角(叙事段落)

**输出形态:一段连贯文字**,站在整个公司或团队管理者视角总结整体都在干什么:

- 主要推进了哪些方向
- 哪些事项有实质进展
- 哪些事项还在讨论
- 哪些事项卡住了
- 整体推进状态:**积极 / 平稳 / 偏停滞**(三选一定性,不打分)

回答 §二 那 4 个问题,**用叙述,不用统计表**。

### 4.2 异常识别

matter 视角"需要关注"段的异常类型由**程序按硬规则识别**(不依赖 LLM 判断"是不是异常"),写入派生标签 `risk_flag`,再由 call A LLM 基于这些候选生成 `attention[]` 中的 `advice`:

| `risk_flag` 值 | 硬规则 |
|---|---|
| `long_idle` | `current_status ∈ { planning, executing }` 且 `days_since_last_activity` 超过阈值(代码内默认 7 天) |
| `failed_unhandled` | 最近一条 `verifications.judgement = failed` 后,超过阈值未出现新 timeline 项(默认 2 天) |
| `paused_overdue` | `current_status = paused` 且 `days_since_last_activity` 超过阈值(默认 14 天) |
| `overdue` | matter 自身有 `due_at` 且已过期 |

阈值是代码内默认值,**不进 §六 后台配置**(总开关之外的内容上线跑稳两周后再评估是否暴露)。LLM 在 call A 中只决定 `advice` 文案,不决定"算不算异常"。

### 4.3 推送链路

```
每日定时触发
   │
   ▼
聚合程序读取所有非终态 matter + 窗口内新终态 matter
→ 给每个 matter 打派生标签(has_window_activity / risk_flag / days_since_last_activity ...)
→ 按 users 表全员聚合个人 24h 输入 / 输出(含 0 活动占位)
   │
   ▼
程序硬过滤(§3.5.2):
  · 24h 有活动 / 风险候选 → 喂 LLM
  · 24h 无活动且无风险 → 程序计数生成 "另有 N 个 matter 无推进"
   │
   ├─► call A · matter 视角 LLM → matter_progress[] + attention[]
   │     (call A 内 LLM 可调用 read_matter_file 工具按需读正文)
   │
   ├─► call B · 个人视角 LLM → personal_dynamics[]
   │
   ▼
   call C · 公司视角 LLM(以 A、B 输出 + 整体计数为输入)→ company_overview
   │
   ▼
程序合并三段 JSON + "无推进"概括 → 渲染飞书卡片 → 团队 Channel
```

A、B 可并行;C 必须在 A、B 之后。只生成一份日报,只推送到团队 Channel,不为个人单独再发一份。

### 4.4 异常 / 降级行为

- **AI 调用失败**:仍出一份**纯结构化卡片**(列出活跃 matter 名称 + 状态、列出有活动的成员名单),不带叙事,卡片明显标注"AI 生成失败,请管理员检查"。退出码 1(让 systemd 显示 failed,触发监控)
- **数据仓库读取失败**:退出码 2,日志 ERROR
- **飞书发送失败**:退出码 1
- **`daily_report.enabled = "0"`**:退出码 0,跳过执行(让管理员可临时停推但不让 timer 报警)
- **当天团队全员 0 活动**:仍发卡(标注"今日团队无活动"),让管理层确认脚本活着

---

## 五、日报格式

**只生成一份日报**,内含三层视角(matter / 个人 / 公司),不为个人单独再发独立日报。

**总篇幅控制在 200-400 字**(暂时设置,调试阶段根据实际生成质量调优),管理层一屏可读完,信息密度优先,叙事不堆砌。四个区块对应三层视角,**输出形态严格区分**:公司视角是段落,matter / 个人视角是清单。

**区块一 · 公司视角(全局概览)** — 段落形式
2-3 句话宏观判断 + 整体阶段定性。

**区块二 · matter 视角(关键进展)** — **清单形式,逐条列出**
有推动的 matter 一条一条列,**不允许合并到一段**。无推动的 matter 在清单结尾以一句话概括(例:"另有 N 个 matter 处于停滞,无明显风险")。每条结构:

- matter 名称 + 当前状态(有迁移则 `[from → to]`)
- 一段叙事(谁做了什么 → 使它发生了什么变化)
- 状态展望(可省略)

**区块三 · matter 视角(需要关注)** — **清单形式,逐条列出**
异常事项一条一条列,每条:事项名 + 风险类型 + 简要建议。无异常时显式写"当前无需特别关注的事项"。

**区块四 · 个人视角(团队成员动态)** — **清单形式 + 无活动合并行**
所有团队成员逐个覆盖,**不允许把多个有活动者的动作糅进一段叙述**:

- 有活动者:每人独占一行,概括今天的输入 / 输出 + 涉及 matter
- 无活动者:**合并到清单末尾一行**,顿号串联,固定模板 `· 最近一天无输入输出:xxx、yyy、zzz`(平实表述,不评价)

### 卡片样例

> **📊 日报 · 4-26**
>
> **🌐 整体方向**
> 团队聚焦于登录链路收口和权限体系方案分析,8 个 matter 有动作,核心参与人 dengke / liuyu / huangshengli。整体处于平稳推进期。权限体系方案讨论较多但尚未进入 act 阶段,值得继续观察是否需要管理层介入推一把。
>
> **📌 关键进展**
> ● **登录链路改造** [executing]
> liuyu 创建了 verify,判定主链路 act 为 passed。dengke 跟进收尾 result,事项接近闭环,下一步关注 e2e 测试覆盖。
>
> ● **数据迁移方案** [executing → finished]
> dengke 创建了 result,正式完成。技术风险已通过 verify 链验收,后续观察生产数据稳定性。
>
> **⚠️ 需要关注**
> ⚠️ 支付对账优化 — act 已数日无人验收(owner: wangwu)
> 　→ 建议:确认 wangwu 是否仍在跟进,或考虑指定替代验收人
>
> **👥 团队动态**
> · **dengke**:推进登录链路收口,完成 1 篇 verify、1 篇 result;在权限体系评论中补充了多租户隔离的视角
> · **liuyu**:负责验收推进,完成 2 篇 verify;在权限体系给出技术意见
> · **terry.tao**:在新需求-日报推送补充 v0.2 PRD,推进设计评审
> · 最近一天无输入输出:huangshengli、zhangbo、佘耀君、wangwu、yuebilin、tangkun

---

## 六、后台管理配置

最少必要配置(避免过度设计 / 阈值待实测后再加):

| 配置项 | 默认值 | 用途 |
|---|---|---|
| `daily_report.enabled` | `"1"` | 总开关。`"0"` 时 runner 退出码 0 跳过执行 |

只保留这一项总开关,其余(AI 正文读取上限、异常阈值、推送时间、目标 Channel 等)统一作为代码内默认值,**待上线跑稳两周后**再根据实际反馈决定是否暴露到后台,而不是评审会议上预先想象。

---

## 七、与现有模块的关系

### 7.1 与主服务的关系

- 日报是独立 systemd timer 调起的一次性进程,与 Pivot 主服务进程隔离
- 互不依赖:主服务挂不影响日报、日报挂不影响主服务

### 7.2 与 matter index 的关系

日报**始终是消费者**,不写入、不修改 index 或任何 matter 数据。即使 AI 读取正文,也不触发任何 commit / push / index 更新。

---

## 八、关键用户链路

### 场景 1:管理者早上看日报

1. 系统按定时聚合 matter 数据
2. AI 生成日报,推送到飞书群
3. 管理者 1 分钟读完整体方向 / 关键进展 / 风险事项 / 团队动态
4. 看到风险提示,在群里 @ owner 安排对齐
5. 看到某成员最近一天无输入输出,记下 1:1 时确认是否在外部任务

### 场景 2:员工在群里看到自己的动态

1. 日报推送到团队 Channel
2. 员工在团队动态区块看到自己今天的输入 / 输出概括
3. 发现某个 matter 的 think 还没有 act 跟进,主动回 Pivot 推进

### 场景 3:管理员临时停推

1. 团队反馈日报内容需要打磨
2. 管理员到 `/admin` 把 `daily_report.enabled` 设为 `"0"`
3. 后续 timer 触发都直接 skip,不再发卡

---

## 九、验收标准

| 验收项 | 标准 |
|---|---|
| 定时推送 | 配置时间点准时推送 |
| 内容准确性 | 日报中事项状态 / 干系人 / 摘要与 index 数据一致,无臆造 |
| 三层视角覆盖 | matter / 个人 / 公司三层均出现,缺一即不通过 |
| 个人无活动表达 | 无活动成员明确写"最近一天无输入输出",不用模糊话术 |
| 因果叙事质量 | matter 叙事能讲清楚因果链,而非堆砌字段 |
| 篇幅控制 | 日报 200-400 字,超出视为不通过(管理层不需要长文,信息密度优先);该范围**暂时设置,调试阶段根据实际生成质量调优** |
| 静默规则 | 团队无活动仍推送(注明"今日团队无活动") |
| AI 降级 | AI 调用失败时仍出一份纯结构化卡片(无叙事),并明显标注"AI 生成失败" |
| 后台开关生效 | 管理员改 `daily_report.enabled` 后,下次推送即按新值执行 |

---

## 十、本期不包含

- 接入代码仓库 / commit 统计 / 评分(后续视反馈决定是否引入)
- 周报 / 月报
- 多 IM 平台(钉钉 / Slack / 企业微信)
- 日报站内存档与历史查看
- 日报模板自定义
- 跨团队 / 部门日报路由
