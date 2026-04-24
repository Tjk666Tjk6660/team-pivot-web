# 通用：AI 助手（草稿卡 → 右侧 AIPane）交互时序

> 来源：`图片/AI卡片.jpg` + `图片/think+ai组手总览图.jpg`
> + 代码：`MatterDetailPane.tsx`、`AIPane.tsx`、`api.ts:streamAIChat`、`server/api/ai.py`
>
> Endpoint：`/api/ai/threads/{category}/{matter_id}/...`（matter 复用 thread 命名空间）

```mermaid
sequenceDiagram
  actor U as 用户
  participant DC as 草稿卡片
  participant AP as 右侧 AIPane
  participant API as 后端 /api/ai/threads

  U->>DC: 点击 AI 回复
  DC->>AP: setAiOpen(true)
  AP->>AP: 顶部渲染 起点帖子<br/>timeline.find file === quote
  AP->>API: GET /:cat/:matter_id/conversation 拉历史
  API-->>AP: messages / reply_target / reference_files

  alt 历史为空
    AP-->>U: 渲染占位 可以先提问/总结/让 AI 帮你生成回复草稿
  else 有历史
    AP-->>U: 渲染消息列表
  end

  U->>AP: 输入提问 或 点 生成草稿
  Note over AP: 生成草稿会注入 GENERATE_REPLY_DRAFT 标签<br/>要求 AI 用 draft 标签包裹

  alt 其它 thread 正在 streaming
    AP-->>U: 按钮禁用 提示当前活跃 thread
  else 可发起
    AP->>API: POST /:cat/:matter_id/chat SSE
    API-->>AP: data delta x N
    API-->>AP: data DONE
    AP->>API: PUT /:cat/:matter_id/conversation 持久化整段
  end

  U->>DC: 复制 或 参考 AI 输出 回填 summary / body
```
