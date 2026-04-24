# 通用：AI 助手（草稿卡 → 右侧 AIPane）交互时序

> 来源：`图片/AI卡片.jpg` + `图片/think+ai组手总览图.jpg`
> + 代码：`MatterDetailPane.tsx`、`AIPane.tsx`、`server/api/ai.py`、`server/api/drafts.py`
>
> Endpoint：`/api/ai/matters/{matter_id}/...`

```mermaid
sequenceDiagram
  actor U as 用户
  participant DC as 草稿卡片
  participant AP as 右侧 AIPane
  participant AIAPI as 后端 /api/ai/matters
  participant DAPI as 后端 /api/drafts

  U->>DC: 点击 AI 回复
  DC->>AP: setAiOpen(true)
  AP->>AP: 顶部渲染 起点帖子<br/>timeline.find file === quote
  AP->>AIAPI: GET /:matter_id/conversation 拉历史
  AIAPI-->>AP: messages / reply_target / reference_files

  alt 历史为空
    AP-->>U: 渲染占位 可以先提问/总结/让 AI 帮你生成回复草稿
  else 有历史
    AP-->>U: 渲染消息列表
  end

  alt 用户输入提问后 发送
    U->>AP: 输入文本 点 发送
    AP->>AIAPI: POST /:matter_id/chat SSE
    AIAPI-->>AP: data delta x N
    AIAPI-->>AP: data DONE
    AP->>AIAPI: PUT /:matter_id/conversation 持久化整段
    U->>DC: 复制 或 参考 AI 输出 回填 summary / body
  else 用户点 生成草稿
    U->>AP: 点击 生成草稿
    Note over AP: 自动注入 GENERATE_REPLY_DRAFT 标签<br/>要求 AI 用 draft 标签包裹整篇正文

    alt 其它 matter 正在 streaming
      AP-->>U: 按钮禁用 提示当前活跃 matter
    else 可发起
      AP->>AIAPI: POST /:matter_id/chat SSE
      AIAPI-->>AP: data delta x N
      AIAPI-->>AP: data DONE
      AP->>AIAPI: PUT /:matter_id/conversation 持久化整段

      AP->>AP: 解析 AI 输出中的 draft 标签 取正文文本

      alt 解析到非空 draft 内容
        AP->>DC: onUseDraftAsReply(draftText)
        DC->>DC: 回填 form.body = draftText<br/>触发 textarea 受控更新
        DC->>DAPI: PATCH /api/drafts/:draft_id<br/>body_md = draftText<br/>(若无 draft_id 则 POST /api/drafts 新建)
        DAPI-->>DC: ok 返回 draft 记录
        DC-->>U: toast 已回填正文并保存草稿
      else 未解析到 draft 标签
        AP-->>U: toast AI 未按格式输出 请重试或手动复制
      end
    end
  end
```

---

## 关键约定

| 项 | 说明 |
|---|---|
| matter 维度 | 所有 matter 详情页 AI 都用 matter_id 作为唯一键；不同 matter 会话互相隔离 |
| 起点帖子 | 仅当 pendingCreate 存在（即草稿卡打开时）才渲染；从 timeline.find(t.file === quote) 取 |
| 生成草稿按钮 | 自动注入 GENERATE_REPLY_DRAFT 标签，要求 AI 输出用 draft 标签包裹完整正文 |
| 跨 matter 锁 | 全局 activeStream 单例：同一时间只允许一个 matter streaming |
| 会话持久化 | 流结束后一次性 PUT 整段；中途关闭页面会丢失最新流消息 |
| 回填 + 保存 | 生成草稿成功后：先回填到草稿卡 form.body，再 PATCH /api/drafts/:id 持久化；若卡片尚无 draft_id，先 POST 新建 |
| 生成 summary 链路 | act / verify 发布前的 streamAIChat 走 /api/ai/matters/:matter_id/chat，但只本地累加返回，不写 conversation |
