# ACT 卡片创建/发布交互时序

> 来源：`图片/act卡片.jpg`
> + 代码：`MatterDetailPane.tsx:generateSummaryViaChat`、`CreateFileDialog.tsx:CreateFileForm`（onGenerateSummary 路径）
> + 文档：`pivot-product.md` §三 §五 §九·1
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 001_xxx_think
  participant DC as 草稿卡 ACT
  participant AP as 右侧 AIPane
  participant CHAT as 后端 streamAIChat<br/>/api/ai/threads/:cat/:matter_id/chat
  participant API as 后端 /api/matters/:id

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing<br/>paused/finished/cancelled/reviewed 灰禁

  U->>FC: 点击 + act
  alt 已存在同 quote+act 草稿
    FC->>DC: 关闭草稿
  else 否则
    FC->>DC: 在下方追加草稿卡<br/>虚线框 + 绿色左色条<br/>quote=FileCard.file 自动只读
    DC-->>U: 渲染头部 ACT chip + 新增 基于 + AI 回复 按钮
    DC-->>U: 渲染表单 quote / owner 必填 / body 必填 / refer ≤4
    Note over DC: body 必填 提示<br/>发布时 AI 将基于此生成 summary
  end

  alt matter.current_status === planning
    DC-->>U: 渲染附加状态迁移 复选 正式进入执行 planning to executing
  else executing
    DC-->>U: 不渲染状态迁移控件
  end

  opt 需要 AI 协助起草
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>DC: 复制 AI 输出回填 body
  end

  U->>DC: 填 owner / body / refer / 是否勾 promote
  U->>DC: 点击 发布

  DC->>DC: 校验 body 必填 owner 必填
  alt 校验失败
    DC-->>U: toast 正文必填 / owner 必填
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>CHAT: streamAIChat<br/>messages = 内置提示词 + body<br/>reply_target = quote
    alt 流出错或超时
      CHAT-->>DC: error
      DC->>DC: stage=idle
      DC-->>U: toast 生成 summary 失败
    else 流成功
      CHAT-->>DC: SSE delta delta delta
      DC->>DC: 累加得到 summary

      alt summary 为空
        DC->>DC: stage=idle
        DC-->>U: toast AI 生成的 summary 为空
      else summary 有效
        DC->>DC: stage=publishing 按钮 发布中
        DC->>API: POST /files NewFileIn<br/>type=act + AI summary + body + owner + quote + refer + status_change
      end
    end
  end
```
