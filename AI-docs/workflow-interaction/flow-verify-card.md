# VERIFY 卡片创建/发布交互时序

> 来源：`图片/verfiy卡片.jpg`
> + 代码：`MatterDetailPane.tsx:generateSummaryViaChat`、`CreateFileDialog.tsx:CreateFileForm`（verify 分支 + VerificationsEditor）
> + 文档：`pivot-product.md` §三 §五 §九
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)
> summary 由 AI 基于 body 自动生成，与 think / act 一致。

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
