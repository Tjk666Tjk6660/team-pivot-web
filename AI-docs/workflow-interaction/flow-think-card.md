# THINK 卡片创建/发布交互时序

> 来源：`图片/think卡片.jpg` + `图片/think+ai组手总览图.jpg`
> + 代码：`MatterDetailPane.tsx`、`CreateFileDialog.tsx:CreateFileForm`、`timeline-config.ts`
> + 文档：`pivot-product.md` §三 §五 §1.2
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as FileCard 005_xxx_verify
  participant DC as 草稿卡 THINK
  participant AP as 右侧 AIPane
  participant API as 后端 /api/matters/:id

  Note over FC: matter.current_status<br/>必须 ∈ planning / executing / paused<br/>否则 + think 灰禁

  U->>FC: 点击 + think
  alt 已存在同 quote+think 草稿
    FC->>DC: 关闭草稿 setPendingCreate=null
  else 否则
    FC->>DC: 在下方追加草稿卡<br/>article 虚线框 + 蓝色左色条<br/>quote=FileCard.file 自动只读
    DC-->>U: 渲染头部 THINK chip + 新增 基于 005_xxx + AI 回复 按钮
    DC-->>U: 渲染表单 quote / summary 必填 / body 可选 / refer ≤4 / 状态迁移单选组
  end

  Note over DC: 状态迁移选项随 matterStatus 变<br/>planning 或 executing: 不切换 / 同时暂停<br/>paused: 不切换 / 恢复 planning / 恢复 executing

  opt 需要 AI 协助
    U->>DC: 点击 AI 回复
    DC->>AP: setAiOpen(true) 见 flow-ai-assistant
    AP-->>U: 起点帖子 + 对话面板
    U->>DC: 复制 AI 输出回填 summary / body
  end

  U->>DC: 填 summary / body / refer / 选状态迁移
  U->>DC: 点击 发布

  DC->>DC: 校验 summary 必填
  alt summary 为空
    DC-->>U: toast summary 必填
  else 校验通过
    DC->>API: POST /files NewFileIn<br/>type=think + summary + body + quote + refer + status_change
  end
```
