# THINK 卡片创建/发布交互时序

> 来源：`图片/think卡片.jpg` + `图片/think+ai组手总览图.jpg`
> + 代码：`MatterDetailPane.tsx:generateSummaryViaChat`、`CreateFileDialog.tsx:CreateFileForm`（onGenerateSummary 路径）
> + 文档：`pivot-product.md` §三 §五 §1.2
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)
> summary 由 AI 基于 body 自动生成，与 act / verify 一致。

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 005_xxx_verify
  participant DC as 草稿卡 THINK
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing / paused<br/>finished/cancelled/reviewed 灰禁

  U->>FC: 点击 + think
  alt 已存在同 quote+think 草稿
    FC->>DC: 关闭草稿
  else 否则
    FC->>DC: 在下方追加草稿卡<br/>虚线框 + 蓝色左色条<br/>quote=FileCard.file 自动只读
    DC-->>U: 渲染头部 THINK chip + 新增 基于 + AI 回复 按钮
    DC-->>U: 渲染表单 quote / body 必填 / refer ≤4
    Note over DC: body 必填 提示<br/>发布时 AI 将基于此生成 summary
  end

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
