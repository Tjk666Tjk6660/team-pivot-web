# Matter 生命周期总流程交互设计

> 把 think → act → verify → result → insight 五阶段串成一条 matter 完整生命周期的交互链路。
>
> 每段落只画"入口 → 草稿卡 → 发布 → 落盘 → 状态变化"主干；表单细节、校验、AI summary 三段式 stage（idle / generating / publishing）、回填已有草稿等公共模式见各 `flow-*-card.md` 单图。
>
> AI 助手部分见 [`flow-ai-assistant.md`](./flow-ai-assistant.md)

---

```mermaid
sequenceDiagram
  actor U as 用户
  participant FC as 入口 (FileCard / 页面顶部按钮)
  participant DC as 草稿卡
  participant AP as 右侧 AIPane
  participant API as 后端 API

  Note over U,API: 共同模式 · 点击 发布 后:<br/>1) 前端校验必填<br/>2) stage=generating · streamAIChat 生成 summary<br/>3) stage=publishing · POST 落盘<br/>详见 flow-{type}-card.md

  rect rgba(147, 197, 253, 0.18)
    Note over U,API: 阶段一 · status = planning · 创建 THINK
    U->>FC: 在某 FileCard 点 + think
    FC->>DC: 追加 THINK 草稿卡 (蓝色左色条)
    Note over DC: 表单 quote / body / refer / 状态迁移单选组
    opt AI 协助
      U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
    end
    U->>DC: 填表 + 发布
    DC->>API: POST /api/matters/:id/files<br/>type=think + AI summary
    Note over API: status 维持 planning<br/>think 是 paused 进出的唯一通道
  end

  rect rgba(110, 231, 183, 0.20)
    Note over U,API: 阶段二 · planning → executing · 创建 ACT
    U->>FC: 在某 FileCard 点 + act
    FC->>DC: 追加 ACT 草稿卡 (绿色左色条)
    Note over DC: 表单 owner / body / refer + 复选 正式进入执行
    opt AI 协助
      U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
    end
    U->>DC: 填表 + 发布
    DC->>API: POST /api/matters/:id/files<br/>type=act + AI summary + status_change (若勾 promote)
    Note over API: 若勾 promote · status → executing
  end

  rect rgba(252, 211, 77, 0.18)
    Note over U,API: 阶段三 · status = executing · 创建 VERIFY
    U->>FC: 在某 ACT FileCard 点 + verify
    FC->>DC: 追加 VERIFY 草稿卡 (黄色左色条)
    Note over DC: 表单 owner / body / verifications · 不出现 refer
    opt AI 协助
      U->>AP: 点 AI 回复 → 生成草稿 → 回填 body
    end
    U->>DC: 填表 (≥1 条 verification) + 发布
    DC->>API: POST /api/matters/:id/files<br/>type=verify + AI summary + verifications
    Note over API: status 维持 executing
  end

  rect rgba(196, 181, 253, 0.22)
    Note over U,API: 阶段四 · executing → finished / cancelled · 生成 RESULT
    U->>FC: 点击 页面顶部 生成 Result (仅 executing 显示)
    FC->>DC: 追加 RESULT 草稿卡 (紫色左色条) · 页面级 无 quote
    Note over DC: 表单 outcome 单选 (finished / cancelled) + body
    opt AI 协助
      U->>AP: 点 AI 助手 → 生成草稿 → 回填 body
    end
    U->>DC: 选 outcome + 填 body + 发布
    DC->>API: POST /api/matters/:id/result<br/>outcome + AI summary
    Note over API: 后端隐式追加 status_change<br/>status → finished 或 cancelled
  end

  rect rgba(203, 213, 225, 0.25)
    Note over U,API: 阶段五 · finished / cancelled → reviewed · 生成 INSIGHT
    U->>FC: 点击 页面顶部 生成 Insight (仅 finished / cancelled 显示)
    FC->>DC: 追加 INSIGHT 草稿卡 (灰色左色条) · 页面级 无 quote
    Note over DC: 表单 body / refer + 复选 同时推进到 reviewed
    opt AI 协助
      U->>AP: 点 AI 助手 → 生成草稿 → 回填 body
    end
    U->>DC: 填表 + 发布
    DC->>API: POST /api/matters/:id/files<br/>type=insight + AI summary + status_change (若勾)
    Note over API: 若勾推进 · status → reviewed (终态)
  end

  Note over U,API: matter 生命周期已 reviewed<br/>不再新增任何文件
```

---

## 五阶段速查表

| 阶段 | 入口 | 状态前置 | type | 专属字段 | 落盘 endpoint | 状态后置 |
|---|---|---|---|---|---|---|
| ① think   | FileCard 卡级 | planning / executing / paused | think   | 状态迁移单选组（含 paused 进出） | POST /files | 不变 或 paused 进出 |
| ② act     | FileCard 卡级 | planning / executing | act     | 复选 正式进入执行（仅 planning） | POST /files | planning → executing（若勾） |
| ③ verify  | FileCard 卡级（须有 act） | planning / executing | verify  | verifications 编辑器 ≥1 条 | POST /files | 不变 |
| ④ result  | 页面顶部 | executing | result  | outcome 单选（finished / cancelled） | POST /result | executing → outcome |
| ⑤ insight | 页面顶部 | finished / cancelled | insight | 复选 同时推进到 reviewed | POST /files | 不变 或 → reviewed |
