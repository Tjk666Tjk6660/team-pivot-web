# RESULT 卡片创建/发布交互时序

> 来源：`图片/result卡片.jpg`
> + 代码：`MatterDetailPane.tsx`、`ResultConfirmDialog.tsx`、`appendMatterResult`、`server/api/matters.py:append_result`
> + 文档：`pivot-product.md` §三 §九·4 §十三（"生成 Result" 页面级动作）
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)
> 草稿、summary、AI 协助交互与 act 一致；result 是**页面级**动作，无 quote、无 owner、无 refer。

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

---

## 与 act / verify 的核心差异

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
