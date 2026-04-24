# INSIGHT 卡片创建/发布交互时序

> 来源：`图片/insight.jpg`
> + 代码：`MatterDetailPane.tsx`、`CreateFileDialog.tsx:CreateFileForm`（kind=page · type=insight）、`server/api/matters.py:append_file`
> + 文档：`pivot-product.md` §三（insight 类型）§五（finished/cancelled 只允许 insight）
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)
> 草稿、summary、AI 协助交互与 act 一致；insight 是**页面级**动作，无 quote、无 owner、无 verifications。

```mermaid
sequenceDiagram
  actor U as 用户
  participant PB as 页面顶部 生成 Insight 按钮
  participant DC as 草稿卡 INSIGHT
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over PB: 仅当 matter.current_status ∈ finished / cancelled 时显示<br/>planning / executing / paused / reviewed 不显示

  U->>PB: 点击 生成 Insight
  alt 已存在 INSIGHT 草稿
    PB->>DC: 关闭草稿
  else 否则
    PB->>DC: 在页面顶部追加草稿卡<br/>虚线框 + 灰色左色条<br/>页面级 无 quote
    DC-->>U: 渲染头部 INSIGHT chip + 页面级 · 无 quote + AI 助手 按钮
    DC-->>U: 渲染表单 body 必填 / refer ≤4 / 附加状态迁移 复选
    Note over DC: body 必填 提示 发布时 AI 将基于此生成 summary<br/>附加状态迁移: 同时推进到 reviewed (finished 或 cancelled to reviewed)
  end

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

---

## 与 act / verify / result 的核心差异

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
