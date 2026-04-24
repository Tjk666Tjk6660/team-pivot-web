# 五类卡片创建/发布交互时序合集

## ① THINK 卡片创建/发布交互时序

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 005_xxx_verify
  participant DC as 草稿卡 THINK
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing / paused<br/>finished/cancelled/reviewed 灰禁

  U->>FC: 点击 + think
  FC->>DC: 在下方追加草稿卡<br/>虚线框 + 蓝色左色条<br/>quote=FileCard.file 自动只读
  DC-->>U: 渲染头部 THINK chip + 新增 基于 + AI 回复 按钮
  DC-->>U: 渲染表单 quote / body 必填 / refer ≤4
  opt 命中 matterDrafts 中已存在同 (type, quote) 草稿
    DC-->>U: 用已有草稿 draftFromPayload 回填表单
  end
  Note over DC: body 必填 提示<br/>发布时 AI 将基于此生成 summary

  alt matter.current_status === planning 或 executing
    DC-->>U: 渲染附加状态迁移 单选组<br/>不切换 默认 / 同时暂停 status to paused
  else paused
    DC-->>U: 渲染附加状态迁移 单选组<br/>不切换 默认 / 恢复为 planning / 恢复为 executing
  end

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>AP: 点击 生成草稿 按钮<br/>AI 输出 draft 自动回填卡片body body<br/>详见 flow-ai-assistant 的 生成草稿 分支
  end

  U->>DC: 填 body / refer / 选状态迁移
  U->>DC: 点击 发布

  DC->>DC: 校验 body 必填
  alt 校验失败
    DC-->>U: toast body必填
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>API: POST /api/ai/matters/:matter_id/chat (SSE)<br/>streamAIChat · messages = 内置提示词 + body<br/>reply_target = quote
    alt 流出错或超时
      API-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      API-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /api/matters/:id/files NewFileIn<br/>type=think + AI summary + body + quote + refer + status_change
      end
    end
  end
```

---

## ② ACT 卡片创建/发布交互时序

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 001_xxx_think
  participant DC as 草稿卡 ACT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing<br/>paused/finished/cancelled/reviewed 灰禁

  U->>FC: 点击 + act
  FC->>DC: 在下方追加草稿卡<br/>虚线框 + 绿色左色条<br/>quote=FileCard.file 自动只读
  DC-->>U: 渲染头部 ACT chip + 新增 基于 + AI 回复 按钮
  DC-->>U: 渲染表单 quote / owner 必填 / body 必填 / refer ≤4
  opt 命中 matterDrafts 中已存在同 (type, quote) 草稿
    DC-->>U: 用已有草稿 draftFromPayload 回填表单
  end
  Note over DC: body 必填 提示<br/>发布时 AI 将基于此生成 summary

  alt matter.current_status === planning
    DC-->>U: 渲染附加状态迁移 复选 正式进入执行 planning to executing
  else executing
    DC-->>U: 不渲染状态迁移控件
  end

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>AP: 点击 生成草稿 按钮<br/>AI 输出 draft 自动回填卡片body body<br/>详见 flow-ai-assistant 的 生成草稿 分支
  end

  U->>DC: 填 owner / body / refer / 是否勾 promote
  U->>DC: 点击 发布

  DC->>DC: 校验 body 必填 owner 必填
  alt 校验失败
    DC-->>U: toast body必填 / owner 必填
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>API: POST /api/ai/matters/:matter_id/chat (SSE)<br/>streamAIChat · messages = 内置提示词 + body<br/>reply_target = quote
    alt 流出错或超时
      API-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      API-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /api/matters/:id/files NewFileIn<br/>type=act + AI summary + body + owner + quote + refer + status_change
      end
    end
  end
```

---

## ③ VERIFY 卡片创建/发布交互时序

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 003_xxx_act
  participant DC as 草稿卡 VERIFY
  participant VE as VerificationsEditor
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing<br/>且本 matter 必须有 ≥1 条 act<br/>paused/finished/cancelled/reviewed 灰禁

  U->>FC: 点击 + verify
  alt 已存在同 quote+verify 草稿
    FC->>DC: 关闭草稿
  else 否则
    FC->>DC: 在下方追加草稿卡<br/>虚线框 + 黄色左色条<br/>quote=FileCard.file 自动只读
    DC-->>U: 渲染头部 VERIFY chip + 新增 基于 + AI 回复 按钮
    DC-->>U: 渲染表单 quote / owner 必填 / body 必填 / verifications 必填<br/>注意 不出现 refer 字段
    opt 命中 matterDrafts 中已存在同 (type, quote) 草稿
      DC-->>U: 用已有草稿 draftFromPayload 回填表单
    end
    Note over DC: body 必填 提示<br/>发布时 AI 将基于此生成 summary

    alt 源 FileCard.type === act 且属本 matter
      DC->>VE: 预填一行 target=quote judgement=passed comment 空
    else
      DC->>VE: verifications 为空
    end
  end

  Note over VE: VerificationsEditor 行操作<br/>每行 target 下拉 必须属本 matter actFiles<br/>judgement 下拉 passed/failed/cancelled<br/>comment 必填

  loop 多条 verification 行
    U->>VE: 选 target / 选 judgement / 填 comment
    opt 增加行
      U->>VE: 点击 追加 target<br/>新行默认 target=actFiles[0] / passed / 空
    end
    opt 删除行
      U->>VE: 点击 移除按钮
    end
  end

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>AP: 点击 生成草稿 按钮<br/>AI 输出 draft 自动回填卡片body body<br/>详见 flow-ai-assistant 的 生成草稿 分支
  end

  U->>DC: 填 owner / body / 调整 verifications
  U->>DC: 点击 发布

  DC->>DC: 校验 body 必填 owner 必填 verifications.length>=1 每条 comment 必填
  alt 校验失败
    DC-->>U: toast 错误信息
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>API: POST /api/ai/matters/:matter_id/chat (SSE)<br/>streamAIChat · messages = 内置提示词 + body<br/>reply_target = quote
    alt 流出错或超时
      API-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      API-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /api/matters/:id/files NewFileIn<br/>type=verify + AI summary + body + owner + quote + verifications<br/>不带 refer
      end
    end
  end
```

---

## ④ RESULT 卡片创建/发布交互时序

```mermaid
sequenceDiagram
  actor U as 用户
  participant PB as 页面顶部 生成 Result 按钮
  participant DC as 草稿卡 RESULT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over PB: 仅当 matter.current_status === executing 时显示<br/>planning / paused / finished / cancelled / reviewed 不显示

  U->>PB: 点击 生成 Result
  PB->>DC: 在页面顶部追加草稿卡<br/>虚线框 + 紫色左色条<br/>页面级 无 quote
  DC-->>U: 渲染头部 RESULT chip + 页面级 · 无 quote + AI 助手 按钮
  DC-->>U: 渲染表单 outcome 必填 / body 必填
  opt 命中 matterDrafts 中已存在 RESULT 草稿
    DC-->>U: 用已有草稿 draftFromPayload 回填表单
  end
  Note over DC: outcome 单选: 完成 finished 默认 / 取消 cancelled<br/>body 必填 提示 发布时 AI 将基于此生成 summary

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 助手
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>AP: 点击 生成草稿 按钮<br/>AI 输出 draft 自动回填卡片正文 body<br/>详见 flow-ai-assistant 的 生成草稿 分支
  end

  U->>DC: 选 outcome / 填 body
  U->>DC: 点击 发布

  DC->>DC: 校验 outcome 必填 body 必填
  alt 校验失败
    DC-->>U: toast outcome 必选 / 正文必填
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>API: POST /api/ai/matters/:matter_id/chat (SSE)<br/>streamAIChat · messages = 内置提示词 + body<br/>reply_target = 空（页面级 无 quote）
    alt 流出错或超时
      API-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      API-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /api/matters/:id/result NewResultBody<br/>outcome + AI summary + body<br/>后端隐式追加 status_change executing to outcome
      end
    end
  end
```

### 与 act / verify 的核心差异

| 维度 | act / verify | result |
|---|---|---|
| 入口位置 | FileCard 底部按钮（卡级） | 页面顶部按钮（页面级） |
| quote | 自动带入 = FileCard.file | **无**（result 对象就是 matter 本身） |
| owner | 必填 | 无 |
| refer | act 可选 / verify 无 | 无 |
| 类型专属字段 | act: actPromote 复选；verify: verifications | **outcome 单选 finished/cancelled** |
| status_change | 由前端组装 | **后端 `append_result` 隐式追加** `{from: current_status, to: outcome}` |
| 落盘 endpoint | `POST /api/matters/:id/files` | `POST /api/matters/:id/result` |
| 状态前置 | planning / executing | **仅 executing** |
| 后置语义 | 可重复追加 | **唯一**：一个 matter 只允许一篇有效 result（pivot-product §九·4） |

---

## ⑤ INSIGHT 卡片创建/发布交互时序

```mermaid
sequenceDiagram
  actor U as 用户
  participant PB as 页面顶部 生成 Insight 按钮
  participant DC as 草稿卡 INSIGHT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over PB: 仅当 matter.current_status ∈ finished / cancelled 时显示<br/>planning / executing / paused / reviewed 不显示

  U->>PB: 点击 生成 Insight
  PB->>DC: 在页面顶部追加草稿卡<br/>虚线框 + 灰色左色条<br/>页面级 无 quote
  DC-->>U: 渲染头部 INSIGHT chip + 页面级 · 无 quote + AI 助手 按钮
  DC-->>U: 渲染表单 body 必填 / refer ≤4 / 附加状态迁移 复选
  opt 命中 matterDrafts 中已存在 INSIGHT 草稿
    DC-->>U: 用已有草稿 draftFromPayload 回填表单
  end
  Note over DC: body 必填 提示 发布时 AI 将基于此生成 summary<br/>附加状态迁移: 同时推进到 reviewed (finished 或 cancelled to reviewed)

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 助手
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>AP: 点击 生成草稿 按钮<br/>AI 输出 draft 自动回填卡片正文 body<br/>详见 flow-ai-assistant 的 生成草稿 分支
  end

  U->>DC: 填 body / refer / 是否勾 推进 reviewed
  U->>DC: 点击 发布

  DC->>DC: 校验 body 必填<br/>若勾 reviewed 再校验当前状态 ∈ finished / cancelled
  alt 校验失败
    DC-->>U: toast 错误信息
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>API: POST /api/ai/matters/:matter_id/chat (SSE)<br/>streamAIChat · messages = 内置提示词 + body<br/>reply_target = 空（页面级 无 quote）
    alt 流出错或超时
      API-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      API-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /api/matters/:id/files NewFileIn<br/>type=insight + AI summary + body + refer<br/>+ status_change finished/cancelled to reviewed (若勾)
      end
    end
  end
```

### 与 act / verify / result 的核心差异

| 维度 | act / verify | result | insight |
|---|---|---|---|
| 入口位置 | FileCard 底部按钮（卡级） | 页面顶部按钮（页面级） | 页面顶部按钮（页面级） |
| quote | 自动带入 | 无 | 无 |
| owner | 必填 | 无 | 无 |
| refer | act 可选 / verify 无 | 无 | **可选 ≤4** |
| 类型专属字段 | act: actPromote / verify: verifications | outcome 单选 | **附加状态迁移 复选: 同时推进到 reviewed** |
| 落盘 endpoint | `POST /api/matters/:id/files` | `POST /api/matters/:id/result` | `POST /api/matters/:id/files` |
| 状态前置 | planning / executing | 仅 executing | **仅 finished / cancelled** |
| 后置语义 | 可重复追加 | 唯一 | 可重复，可选触发 reviewed 收口 |
