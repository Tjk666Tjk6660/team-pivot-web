# 五类卡片创建/发布交互时序合集

## ① THINK 卡片

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard
  participant DC as 草稿卡 THINK
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: 仅 planning / executing / paused 显示 + think

  U->>FC: 点击 + think
  FC->>DC: 追加草稿卡 (蓝色左色条) · quote = FileCard.file 只读
  DC-->>U: 渲染 quote / body 必填 / refer ≤4

  opt 已有 (think, quote) 草稿
    DC-->>U: draftFromPayload 回填表单
  end

  alt planning 或 executing
    DC-->>U: 状态迁移单选: 不切换 / 同时暂停 → paused
  else paused
    DC-->>U: 状态迁移单选: 不切换 / 恢复 planning / 恢复 executing
  end

  opt AI 协助
    U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
  end

  U->>DC: 填表 + 点击 发布
  Note over DC,API: 走公共发布流程（见末尾）
  DC->>API: POST /api/matters/:id/files<br/>type=think + AI summary + body + quote + refer + status_change
```

> [!IMPORTANT]
> **⚠️ 特别提醒 · 触发状态变更的参数：状态迁移单选组**
> - `不切换状态` (默认) → matter 状态不变
> - `同时暂停` → planning / executing → **paused**
> - `恢复为 planning` → paused → **planning**
> - `恢复为 executing` → paused → **executing**
>
> （think 是 paused 进出的唯一通道）

---

## ② ACT 卡片

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard
  participant DC as 草稿卡 ACT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: 仅 planning / executing 显示 + act

  U->>FC: 点击 + act
  FC->>DC: 追加草稿卡 (绿色左色条) · quote = FileCard.file 只读
  DC-->>U: 渲染 quote / owner 必填 / body 必填 / refer ≤4

  opt 已有 (act, quote) 草稿
    DC-->>U: draftFromPayload 回填表单
  end

  alt planning
    DC-->>U: 复选 正式进入执行 (planning → executing)
  else executing
    DC-->>U: 不渲染状态迁移控件
  end

  opt AI 协助
    U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
  end

  U->>DC: 填表 + 点击 发布
  Note over DC,API: 走公共发布流程（见末尾）
  DC->>API: POST /api/matters/:id/files<br/>type=act + AI summary + body + owner + quote + refer + status_change
```

> [!IMPORTANT]
> **⚠️ 特别提醒 · 触发状态变更的参数：复选 `正式进入执行`**（仅 planning 状态时显示）
> - 勾选 → planning → **executing**
> - 不勾 → matter 状态不变

---

## ③ VERIFY 卡片

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard
  participant DC as 草稿卡 VERIFY
  participant VE as VerificationsEditor
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: 仅 planning / executing 且本 matter 已有 ≥1 条 act

  U->>FC: 点击 + verify
  FC->>DC: 追加草稿卡 (黄色左色条) · quote = FileCard.file 只读
  DC-->>U: 渲染 quote / owner 必填 / body 必填 / verifications 必填 (无 refer)

  opt 已有 (verify, quote) 草稿
    DC-->>U: draftFromPayload 回填表单
  end

  alt 源 FileCard.type === act 且属本 matter
    DC->>VE: 预填一行 target=quote / passed / 空 comment
  else
    DC->>VE: verifications 为空
  end

  loop 编辑 verifications 行
    U->>VE: 选 target / 选 judgement / 填 comment / 增删行
  end

  opt AI 协助
    U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
  end

  U->>DC: 填表 + 点击 发布
  Note over DC,API: 走公共发布流程（见末尾）<br/>额外校验: verifications.length ≥ 1 且每条 comment 必填
  DC->>API: POST /api/matters/:id/files<br/>type=verify + AI summary + body + owner + quote + verifications
```

> [!NOTE]
> **状态变更说明**：verify 不携带 status_change，**任何参数都不会触发状态变更**，matter 状态保持 executing。

---

## ④ RESULT 卡片（页面级）

```mermaid
sequenceDiagram
  actor U as 用户
  participant PB as 页面顶部 生成 Result 按钮
  participant DC as 草稿卡 RESULT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over PB: 仅 executing 显示

  U->>PB: 点击 生成 Result
  PB->>DC: 追加草稿卡 (紫色左色条) · 页面级 无 quote
  DC-->>U: 渲染 outcome 必填 / body 必填

  opt 已有 RESULT 草稿
    DC-->>U: draftFromPayload 回填表单
  end

  opt AI 协助
    U->>AP: 点 AI 助手 → 生成草稿 → 回填 body
  end

  U->>DC: 选 outcome (finished/cancelled) + 填 body + 点击 发布
  Note over DC,API: 走公共发布流程（见末尾）<br/>reply_target = 空 (无 quote)
  DC->>API: POST /api/matters/:id/result<br/>outcome + AI summary + body<br/>(后端隐式追加 status_change)
```

> [!WARNING]
> **⚠️ 特别提醒 · 触发状态变更的参数：`outcome` 单选**（必填 · **发布即必然触发**）
> - `finished` → executing → **finished**
> - `cancelled` → executing → **cancelled**
>
> status_change 由后端 `append_result` 隐式追加，前端不组装；result 是 matter 收口动作，落盘后不可撤回。

---

## ⑤ INSIGHT 卡片（页面级）

```mermaid
sequenceDiagram
  actor U as 用户
  participant PB as 页面顶部 生成 Insight 按钮
  participant DC as 草稿卡 INSIGHT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over PB: 仅 finished / cancelled 显示

  U->>PB: 点击 生成 Insight
  PB->>DC: 追加草稿卡 (灰色左色条) · 页面级 无 quote
  DC-->>U: 渲染 body 必填 / refer ≤4 / 复选 同时推进到 reviewed

  opt 已有 INSIGHT 草稿
    DC-->>U: draftFromPayload 回填表单
  end

  opt AI 协助
    U->>AP: 点 AI 助手 → 生成草稿 → 回填 body
  end

  U->>DC: 填表 + 点击 发布
  Note over DC,API: 走公共发布流程（见末尾）<br/>reply_target = 空 (无 quote)<br/>若勾 reviewed 额外校验状态 ∈ finished / cancelled
  DC->>API: POST /api/matters/:id/files<br/>type=insight + AI summary + body + refer + status_change (若勾)
```

> [!WARNING]
> **⚠️ 特别提醒 · 触发状态变更的参数：复选 `同时推进到 reviewed`**
> - 勾选 → finished / cancelled → **reviewed**（终态，**不可逆**）
> - 不勾 → matter 状态不变

---

## 公共发布流程（点 `发布` 后五段执行）

1. **前端校验**必填字段；任一不通过 → toast 错误，停在草稿卡
2. `stage = generating`，按钮显示 **AI 生成中**
3. `streamAIChat` → `POST /api/ai/matters/:matter_id/chat`（SSE）
   - 流出错 / 超时 → toast 失败、`stage = idle`
   - SSE delta 累加得到 summary
   - summary 为空 → toast 失败、`stage = idle`
4. `stage = publishing`，按钮显示 **发布中**
5. POST 落盘
   - think / act / verify / insight → `POST /api/matters/:id/files`
   - result → `POST /api/matters/:id/result`
6. 成功 → toast 成功、清理 pendingCreate / pendingDraftId / pendingInitial、`fetchMatter` 刷新时间轴

---

## 五类速查表

| 维度 | think | act | verify | result | insight |
|---|---|---|---|---|---|
| 入口位置 | FileCard 卡级 | FileCard 卡级 | FileCard 卡级 | 页面顶部 | 页面顶部 |
| quote | FileCard.file | FileCard.file | FileCard.file | 无 | 无 |
| owner | — | 必填 | 必填 | — | — |
| refer | ≤4 | ≤4 | — | — | ≤4 |
| 专属字段 | 状态迁移单选 | promote 复选 | verifications | outcome | 推进 reviewed 复选 |
| 状态前置 | planning / executing / paused | planning / executing | planning / executing 且有 act | 仅 executing | 仅 finished / cancelled |
| 落盘 endpoint | `/files` | `/files` | `/files` | `/result` | `/files` |
| 状态后置 | 不变 / paused 进出 | 不变 / → executing | 不变 | → finished/cancelled | 不变 / → reviewed |

---

## ⑥ AI 助手（通用 · 触发自所有草稿卡的 `AI 回复` / `AI 助手` 按钮）

```mermaid
sequenceDiagram
  actor U as 用户
  participant DC as 草稿卡
  participant AP as 右侧 AIPane
  participant API as 后端 API

  U->>DC: 点击 AI 回复 / AI 助手
  DC->>AP: setAiOpen(true)
  AP->>AP: 渲染起点帖子 (timeline.find file === quote)
  AP->>API: GET /api/ai/matters/:matter_id/conversation 拉历史
  API-->>AP: messages / reply_target / reference_files

  alt 用户输入提问 + 发送
    U->>AP: 输入文本 + 发送
    AP->>API: POST /api/ai/matters/:matter_id/chat (SSE)
    API-->>AP: SSE delta x N · DONE
    AP->>API: PUT .../conversation 持久化整段
    U->>DC: 参考 AI 输出 手动回填 summary / body
  else 用户点 生成草稿
    U->>AP: 点击 生成草稿
    Note over AP: 注入 GENERATE_REPLY_DRAFT 标签<br/>要求 AI 用 draft 标签包裹整篇正文
    AP->>API: POST /api/ai/matters/:matter_id/chat (SSE)
    API-->>AP: SSE delta x N · DONE
    AP->>API: PUT .../conversation 持久化整段
    AP->>AP: 解析 AI 输出中的 draft 标签

    alt 解析到非空 draft
      AP->>DC: onUseDraftAsReply(draftText)
      DC->>DC: 回填 form.body = draftText
      DC->>API: PATCH /api/drafts/:draft_id (body_md)<br/>无 draft_id 则 POST /api/drafts 新建
      DC-->>U: toast 已回填正文并保存草稿
    else 未解析到 draft
      AP-->>U: toast AI 未按格式输出 请重试或手动复制
    end
  end
```

### 约定速查

| 项 | 说明 |
|---|---|
| matter 维度 | 用 matter_id 作为唯一键；不同 matter 会话互相隔离 |
| 跨 matter 锁 | 前端单例 `activeStream`：同一时间只允许一个 matter streaming（后端无锁） |
| 生成 summary 链路 | 公共发布流程里的 streamAIChat 与本图共用 endpoint，但**不写 conversation**，只本地累加返回 |
