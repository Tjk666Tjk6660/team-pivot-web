# VERIFY 卡片创建/发布交互时序

> 来源：`图片/verfiy卡片.jpg`
> + 代码：`MatterDetailPane.tsx:generateSummaryViaChat`、`CreateFileDialog.tsx:CreateFileForm`（verify 分支 + VerificationsEditor）
> + 文档：`pivot-product.md` §三 §五 §九
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 003_xxx_act
  participant DC as 草稿卡 VERIFY
  participant VE as VerificationsEditor
  participant AP as 右侧 AIPane
  participant CHAT as 后端 streamAIChat<br/>/api/ai/matters/:matter_id/chat
  participant API as 后端 /api/matters/:id

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing<br/>且本 matter 必须有 ≥1 条 act

  U->>FC: 点击 + verify
  alt 已存在同 quote+verify 草稿
    FC->>DC: 关闭草稿
  else 否则
    FC->>DC: 在下方追加草稿卡<br/>虚线框 + 黄色左色条<br/>quote=FileCard.file 自动只读
    DC-->>U: 渲染头部 VERIFY chip + 新增 基于 + AI 回复 按钮
    DC-->>U: 渲染表单 quote / owner 必填 / body 必填 / verifications 必填<br/>注意 不出现 refer 字段

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

  opt 需要 AI 协助
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    U->>DC: 复制 AI 输出回填 body
  end

  U->>DC: 填 owner / body / 调整 verifications
  U->>DC: 点击 发布

  DC->>DC: 校验 body / owner / verifications.length>=1 / 每条 comment 必填
  alt 校验失败
    DC-->>U: toast 错误信息
  else 校验通过
    DC->>DC: stage=generating 按钮 AI 生成中

    DC->>CHAT: streamAIChat<br/>messages = 内置提示词 + body<br/>reply_target = quote
    alt 流出错
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
        DC->>API: POST /files NewFileIn<br/>type=verify + AI summary + body + owner + quote + verifications<br/>不带 refer
      end
    end
  end
```
