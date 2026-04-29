# Pivot 发布新 matter 和回复 matter 时使用 AI 助手的规则变化：方案设计

**作者**：lishuai
**日期**：2026-04-28
**状态**：待批准
**依据**：需求文档《Pivot 发布新 matter 和回复 matter 时使用 AI 助手的规则变化》（[001_dengke_think_7c71d4.md](https://pivot.enclaws.com/m/Pivot%E5%8F%91%E5%B8%83%E6%96%B0matter%E5%92%8C%E5%9B%9E%E5%A4%8Dmatter%E6%97%B6%E4%BD%BF%E7%94%A8AI%E5%8A%A9%E6%89%8B%E7%9A%84%E8%A7%84%E5%88%99%E5%8F%98%E5%8C%96/f/discussions%2FPivot%2FPivot%E5%8F%91%E5%B8%83%E6%96%B0matter%E5%92%8C%E5%9B%9E%E5%A4%8Dmatter%E6%97%B6%E4%BD%BF%E7%94%A8AI%E5%8A%A9%E6%89%8B%E7%9A%84%E8%A7%84%E5%88%99%E5%8F%98%E5%8C%96%2F001_dengke_think_7c71d4.md)）
**适用范围**：Pivot Web（同一份 React 代码响应式适配 PC + 窄屏；项目无独立 app / H5）

---

## 一、需求与现状

### 1. 需求一句话

统一「发布新 matter 第一篇文档」和「发布回复文档」的内容创建逻辑：

- 默认鼓励 AI 协作；
- 允许跳过 AI 直接输入；
- 未经 AI 协作的内容在发布前弹质量提示，提供「强行发布」与「发送给 AI 助手」两个出口。

### 2. 原文目标 → 方案对应

| 原文目标 | 方案对应 |
|----------|---------|
| 默认支持并鼓励用户先和 AI 助手讨论，再生成草稿 | NewMatter 改为左右两栏，AIPane **默认展开**；reply 侧 AIPane 入口保留现状 |
| 允许用户跳过 AI 助手，直接输入并发布内容 | 编辑器始终可手动输入；质量门**不阻塞**，"强行发布"永远可点 |
| 对未经当前 AI 助手协作生成的内容，在发布前进行明确质量提示 | 新增 `body_source` 标签 + 公用 `PublishQualityConfirmDialog`，发布前按需弹窗 |
| 允许用户在发布前，将当前草稿转交给 AI 助手继续讨论和整理 | 弹窗按钮"发送给 AI 助手" → `ai.setInput(body)` + 打开 AIPane，**不自动发送**，用户可继续追加说明 |

### 3. 关于"当前 AI 助手讨论后输出"的判定语义

需求原文的检测条件是：「不是由**当前 AI 助手和用户讨论后输出**的」。这里隐含两个语义：

1. **由 AI 输出**：内容来自 AI，而不是用户手打。
2. **当前 + 讨论后**：在草稿对应的 AI 会话里，由用户**主动触发**生成。

方案里这两条对应到现有机制：

- AI 受 system prompt 约束（[server/ai/prompts.py](../../server/ai/prompts.py)）**不会自发输出 `<draft>`**，必须用户点"生成草稿"按钮、注入 `[[GENERATE_REPLY_DRAFT]]` 才会输出 → 满足"讨论后触发"。
- 草稿与 AIPane 会话用 `threadKey` 一对一绑定 → 满足"当前会话"。
- 判定**只看 body 内容来源**（与最近一次 AI 产出的相似度），**不绑定对话是否还存活**——用户清空对话不影响判定，避免误伤。

### 4. 当前状态盘点

| 路径 | AI 入口 | 草稿持久化 | 发布前质量门 |
|------|--------|----------|-------------|
| 回复文档（reply / result / insight / verify） | 有，[AIPane](../../web/src/components/AIPane.tsx) + `<draft>` 协议 | 走 `useDraftAutosave` | **无** |
| 新 matter 第一篇文档 | **无**（[NewMatter.tsx](../../web/src/pages/NewMatter.tsx) 仅有 Textarea，AI 仅用于生成 summary） | 走 `useDraftAutosave` | **无** |
| 评论（comment） | 无 | 无 | **不在本次范围**（见 §四） |

两条不一致需要在本次抹平：**新 matter 缺 AI 入口**、**两条路径都缺质量门**。

---

## 二、核心设计

### 1. 两条路径流程图

**路径 A：AI 协作发布**

```
用户进入 NewMatter / 在某文件下点 "AI 回复"
        ↓
AIPane 已展开（NewMatter 默认展开 / reply 按钮触发）
        ↓
用户和 AI 自由讨论
        ↓
用户点【生成草稿】按钮（注入 [[GENERATE_REPLY_DRAFT]]）
        ↓
AI 返回 <draft>正文</draft> + <summary>...</summary> [+ <title>...</title>]
        ↓
内容自动落入草稿（reply: 草稿卡片 / new matter: NewMatter 表单 body）
body_source = "ai"，body_source_snapshot = AI 原文
        ↓
用户在草稿界面继续编辑（小改 < 50% 仍判 ai；大改 → manual）
        ↓
点【发布】→ body_source == "ai"：直接发，不弹窗
```

**路径 B：直接输入发布**

```
用户进入 NewMatter / 某文件下点 "+think/+act/..."
        ↓
直接在编辑器手打正文（body_source = "manual"）
        ↓
点【发布】→ body_source == "manual"：弹质量门
        ↓
   ┌─────────────────┬─────────────────────┐
   ↓                 ↓                     ↓
强行发布         发送给 AI 助手          取消
   ↓                 ↓                     ↓
原 publish     AIPane 打开              关弹窗
落盘 manual    setInput(currentBody)    （回到编辑器）
                不自动 send
                用户可追加说明 → 继续讨论
                → 回到路径 A
```

### 2. `body_source` ：内容来源标签

新增字段，写入 draft `matter_payload`、并随发布落到 post frontmatter：

```ts
body_source: "ai" | "manual"
body_source_snapshot?: string  // 上次 AI 产出的 body 原文（仅草稿层用，不进 frontmatter）
```

#### 状态机：**单向降级**，永不升级

需求原文的关键语义是"由 AI 助手和用户**讨论后输出**"——必须经过 AI 协议显式输出，而不是"碰巧和某次 AI 草稿很像"。所以 `body_source` 是单向状态机：

```
                 AI 通过 <draft> 协议写入
   manual  ──────────────────────────────►  ai
              （唯一升级通道：显式 AI 输出）
              
   ai      ──────────────────────────────►  manual
              （唯一降级通道：用户编辑且与 snapshot 偏离）

   manual  ──────────────────────────────►  manual
              （用户怎么改、粘贴什么，都还是 manual）
```

具体规则：

- **唯一升级路径**：[handleUseDraftAsReply](../../web/src/pages/MatterDetailPane.tsx#L585) 接收到 AI 的 `<draft>` 时，set `body_source = "ai"` + `snapshot = <draft>` 内容。
- **降级判定**（仅当当前是 `"ai"` 时执行）：用户编辑后用 LCS 与 snapshot 比，`sim < 0.5` 翻为 `"manual"`，`sim ≥ 0.5` 保持 `"ai"`。
- **`"manual"` 状态下**：用户做任何编辑（包括粘贴一大段恰好与某次 AI 草稿高度相似的外部文本）**都不会升级回 `"ai"`**。这是防"粘贴绕过质量门"的关键。
- **空 body**：发布按钮 disabled，不进入判定。

#### 相似度算法（仅用于 ai → manual 降级）

```
sim = LCS(current_body, snapshot) / max(len(current_body), len(snapshot))
```

- `sim ≥ 0.5` → 保持 `"ai"`
- `sim < 0.5` → 降级 `"manual"`
- `len(current_body) < len(snapshot) * 0.3` → 直接降级 `"manual"`（防"AI 写一大段、用户删剩两行新写"）

#### 性能与存储

- **LCS 只在用户点【发布】按钮时算一次**，不在 onChange 里实时算——避免长文本（>5000 字）的卡顿。
- **snapshot 存全文**，但天然受 Textarea `maxLength={50000}` 约束，单条草稿 payload 增量可控；不做截断（截断会丢精度）。
- autosave 已有 debounce（参考 [useDraftAutosave](../../web/src/hooks/useDraftAutosave.ts)），snapshot 字段共享同一节流，不会额外抖动写入。

### 3. 发布前质量门

新增公用组件 `PublishQualityConfirmDialog`，由一个 hook 包装：

```ts
const confirmPublishQuality = (body: string, source: "ai" | "manual") =>
  Promise<"go" | "send_to_ai" | "cancel">;
```

触发条件：用户点发布且 `source === "manual"`。

弹窗文案直接使用需求文档原文：

> 检测到这篇内容不是由当前 AI 助手和你讨论后输出的。
>
> 请确认这篇文档能够代表你的真实想法，并且足够清晰可读、有思考沉淀、有结构化表达，以便持续提高团队讨论质量。
>
> 对于低质量输入，后期我们会使用 AI 工具进行检测和评价。

按钮：
- **强行发布** → 关闭弹窗，继续原 publish 链路（包括 `body_source: "manual"` 落盘）。
- **发送给 AI 助手** → 关闭弹窗 + 打开/聚焦 AIPane + `ai.setInput(threadKey, currentBody)`，**不自动 send**，让用户追加说明再发。

#### 边界处理

| 场景 | 行为 |
|------|------|
| AI 流被其他 thread 占用（`blockedByOtherThread`） | 弹窗里"发送给 AI 助手"按钮文案动态切换为**"加入 AI 队列"**，副本提示"内容已填入输入框，等当前对话「xxx」完成后再发送"。点击后仍执行 setInput + open，但**不显示 streaming hint**——明确告诉用户当前是排队态 |
| 用户清空 AIPane 对话后又微改发布 | 仍按 body 与 snapshot 比对判定，不绑定对话存活 |
| AI 没聊一句直接点"生成草稿" | 算 AI 协作（用户主动触发，AI 看了上下文） |
| 用户拒绝弹窗（取消） | 关弹窗回到编辑器，**不阻塞**；用户随时可再点发布；体现原文"不会因为 AI 流程而失去直接发布的自由" |
| 紧急内容需要直接发 | 路径 B → 强行发布，一次确认即可，不需要先走 AI |

### 4. NewMatter 的 AIPane 接入

#### A. 布局

NewMatter 页改成左右两栏，AIPane **默认展开**，体现需求文档"默认鼓励"原则：

```
┌─────────────────────┬──────────────────┐
│ Category / Title /  │  AIPane          │
│ Type / Body 表单     │  （NewMatter 模式）│
│                      │                   │
└─────────────────────┴──────────────────┘
```

#### B. AIPane `mode` prop

新增 `mode: "reply" | "new-matter"`，差异：

| 项 | reply | new-matter |
|----|-------|-----------|
| "起点帖子"卡片 | 显示 | 隐藏 |
| `noTarget` disabled 判断 | 启用 | 关闭 |
| 空态文案 | "可以先提问、总结，或者让 AI 帮你生成回复草稿。" | "和 AI 说说你想发起的讨论吧，或者直接在右侧写正文。" |
| 输入框 placeholder | 同上 | 同上 |
| `[[GENERATE_REPLY_DRAFT]]` 后 prompt | 生成回复正文 | 生成 think 正文 + `<title>` + `<summary>` |

#### C. AI 工具集

**与 reply 路径完全一致**——NewMatter 模式 AI 同样获得 5 个工具：

| 工具 | 用途 |
|------|------|
| `list_thread_titles` | 列全部 matter / thread 标题 |
| `search_indexes` | 跨 matter 搜索 index |
| `read_thread_index` | 读某 thread 的 index |
| `read_matter_index` | 读某 matter 的 index |
| `read_post` | 读某篇 post 正文 |

理由：

- **产品一致性**：reply 路径强依赖这套工具——`AIPane` 专门做了 [tool 调用可视化](../../web/src/components/AIPane.tsx#L570)，"AI 总结"入口的预填 prompt 显式驱动 AI 调用 `read_matter_index + read_post`（[MatterDetailPane.tsx:233-250](../../web/src/pages/MatterDetailPane.tsx#L233)）。两条路径若工具集不一致，会形成"reply AI 比 NewMatter AI 强"的体感分裂。
- **真实价值**：用户在新建 matter 时可能会说"延续 #某 matter 讨论的方向"或"看看团队最近有没有在聊类似话题"——这些诉求自然落到 `search_indexes` / `read_matter_index` / `read_post` 上。
- **不强求查重**：工具开放 ≠ 产品要求 AI 查重。是否查重由 AI 根据用户意图自行判断；产品层不刻意鼓励、也不刻意阻止。
- **实现简化**：[server/ai/client.py](../../server/ai/client.py) 不需要按 mode 过滤工具集，两条路径共用同一份 `AITools(...).specs()`——只需 prompt 走 mode 分支即可。

**保留 mode 区分的部分**（在 prompt，不在工具）：
- 告诉模型"当前没有 matter 上下文，用户在新建 matter 阶段"；
- 收到 `[[GENERATE_REPLY_DRAFT]]` 时除了 `<draft>` / `<summary>`，多输出一个 `<title>` 标签。

#### D. 标题预填策略

AI 在 `<title>` 中给出建议时：

- 用户**未手动输入过**标题 → 直接预填到标题输入框，`body_source` 视同 `"ai"`；
- 用户**已手动输入过**标题 → **不覆盖**，在标题输入框下方出一行小字「AI 建议：xxx · 点击采用」。

#### E. 草稿持久化

NewMatter 已有 [useDraftAutosave](../../web/src/hooks/useDraftAutosave.ts)，沿用。AIPane 会话用虚拟 `threadKey = __newmatter__:${draftId}`，与草稿一对一绑定，刷新后对话仍在。

#### F. doc_type / category / status / summary

| 字段 | 由谁决定 | 备注 |
|------|---------|------|
| `title` | AI 给建议（`<title>`），用户可改/可拒 | 见 §D 预填策略 |
| `summary` | 路径 A：复用 AI 输出的 `<summary>`；路径 B：沿用旧逻辑——发布时再调一次 AI 基于 body 生成 | NewMatter.tsx 现有 [streamAIChat 调用](../../web/src/pages/NewMatter.tsx#L142) 在路径 A 下可跳过 |
| `body` | 用户写 / AI 生成 | 触发质量门的核心字段 |
| `category` | 用户手选 | AI 不动；查重也不做 |
| `doc_type` | 用户手选（think / act） | AI 默认按 think 输出 |
| `status` | 系统默认（`planning`） | AI 不参与；状态推进走原有 status_change 流 |

#### G. 窄屏响应式

项目用同一份 React 代码 + Tailwind 断点适配（参考 [Dashboard.tsx 现有 PC 双栏 / 窄屏单栏切换](../../web/src/pages/Dashboard.tsx)）。NewMatter 的左右两栏在窄屏下需切换为：

- **窄屏（< md 断点）**：左右栏堆叠为上下两段，**AIPane 默认收起**为顶部一个浮动按钮 + 角标提示"AI 助手 · 点开协作"——避免 AIPane 在小屏先于表单出现、用户看不到自己要填的字段；
- **PC（≥ md 断点）**：左右两栏，AIPane 默认展开。

**首次进入引导**（窄屏专属）：用户第一次在窄屏打开 NewMatter 时，在 body Textarea 上方显示一行 inline 引导条「💬 AI 助手可以帮你起草——点右上角展开」，**用户点击或滚动后自动消失**，并用 localStorage `pivot:newmatter:hint-dismissed` 记录，避免每次都出现。这是为了在"窄屏默认收起"和原文"默认鼓励"之间补回心智一致性，避免 AI 入口在小屏被埋没。

reply 路径（[MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx)）的 AIPane 现有窄屏处理（叠加在 timeline 上的浮层）保留，不动。

质量门 `PublishQualityConfirmDialog` 用现成的 [Dialog](../../web/src/components/ui/dialog.tsx) 组件，自带窄屏全屏适配，无额外工作。

---

### 5. AI 失败兜底（跨路径）

AI 流可能在多个环节失败，统一处理原则：**body 不变、不触发质量门、Toast 提示并保留重试入口**。

| 失败场景 | 行为 |
|---------|------|
| AI 流式连接错误（网络断、5xx、API key 失效） | 已写入的部分文本舍弃；body 不变；Toast「AI 暂时不可用：xxx，请稍后重试」；AIPane composer 立即解锁可重发 |
| AI 输出超时（>120s 无 token） | 同上，Toast 改为「AI 响应超时，请重试」 |
| AI 返回空 `<draft>` 或缺标签（路径 A） | 不写入 body；Toast「AI 没有给出可用草稿，请补充更多上下文后再试」；保留 AIPane 现有对话 |
| AI 在 NewMatter 模式下未给 `<title>` | 仅缺 `<title>` 不视作失败：标题保持用户已输入或留空，body 和 summary 正常落 |
| 用户中途停止（如关 AIPane / 切 thread） | 复用现有 abort 逻辑；body 不变；不触发质量门；不需要 Toast |

关键约束：**任何 AI 失败都不应该让 `body_source` 翻 `"ai"`**——只有完整收到 `<draft>` 且解析成功，才执行升级。

### 6. 发布后状态流转（跨路径）

**Reply 路径**：
- publish 成功 → 现有 `afterWrite()` 流程不变（refresh matter detail + reload sidebar）；
- 该草稿对应的 `pendingCreate` / `pendingDraftId` / `pendingInitial` / `body_source` / `snapshot` 全部 reset；
- **AIPane 对话保留**——按 thread 维度延续，用户接着同一 matter 写下一条回复时上下文还在（这是现有体感，不动）。

**NewMatter 路径**：
- publish 成功 → 沿用现有 `navigate(\`/m/${matter_id}\`)` 跳到详情页；
- 草稿删除后，对应的 `__newmatter__:${draftId}` 虚拟 threadKey 在 AI store 里成为孤儿；
- **AI store 在初始化时做一次孤儿清理**：扫描所有 `__newmatter__:` 前缀的 thread，对应的 draftId 已不在 `fetchDrafts()` 结果里就删掉；避免 store 里堆历史会话数据。

**质量门点击"取消"或拒绝**：
- 不做任何状态变更；保留草稿、保留 AIPane 对话；用户可继续编辑或再次点发布。

---

### 7. 对需求文档"交给实现同学思考的问题"的回答

需求文档结尾留了 3 个待决问题，逐一回答：

**Q1. 新 matter 的 AI 助手是否复用回复文档的助手逻辑，还是需要单独针对 matter 创建设计提示词和字段结构？**

A：**框架与工具集都复用，仅 prompt 单独**。

- 复用：AIPane 组件、`useDashboard().ai` store、`<draft>` / `<summary>` 协议、草稿写入回调、`AITools(...).specs()` 全部 5 个工具（详见 §二.4.C）。
- 单独：[server/ai/prompts.py](../../server/ai/prompts.py) 新增 `new-matter` 模式 system prompt（无 matter 上下文 / 增加 `<title>` 协议）。
- 字段结构：复用现有 draft `matter_payload`，仅追加 `body_source` / `body_source_snapshot` 两个公用字段。

**Q2. AI 生成新 matter 草稿时，是否需要同时整理 matter 的结构化字段（标题、分类、摘要、状态等）？**

A：**只整理标题和摘要**，分类/类型/状态不动。详见 §二.3.F。

- 标题：AI 给建议（`<title>`），用户没手输才预填，否则只提示。
- 摘要：路径 A 复用 AI 的 `<summary>`，路径 B 沿用旧的"发布时再调一次"逻辑。
- 分类（category）：用户主导组织习惯，AI 没足够信号；不让 AI 选。
- 类型（doc_type）：用户决策点，AI 默认按 think 输出。
- 状态（status）：系统默认 `planning`，AI 不干涉；和现有 status_change 解耦。

**Q3. 草稿保存机制是否需要和普通回复草稿保持一致，避免用户在讨论和编辑过程中丢失内容？**

A：**完全一致**，沿用 [useDraftAutosave](../../web/src/hooks/useDraftAutosave.ts)。

- NewMatter 已经在用同一套 hook（[NewMatter.tsx:101-119](../../web/src/pages/NewMatter.tsx#L101)），不引入第二套机制。
- AIPane 会话用虚拟 `threadKey = __newmatter__:${draftId}` 与草稿绑定，刷新/换设备恢复时对话和 body 一起回。
- `body_source` / `body_source_snapshot` 写进 `matter_payload`，跟着草稿活，跨刷新仍能正确判定质量门。

---

## 三、后端改动

### 1. 发布 API：post frontmatter 加 `body_source`

涉及 6 个发布入口（前端调用，后端落盘）：

| 入口 | 后端 |
|------|------|
| 新 matter 第一篇 | `POST /api/matters` |
| reply（think / act / verify） | `POST /api/matters/{id}/files` |

**result / insight 不写**：v1 跳过这两类，落盘时不带 `body_source` 字段，前端也不在 publish 前判定（详见 §四）。

后端在 [server/posts.py](../../server/posts.py)（或 publish 落盘处）把 `body_source` 当作可选 frontmatter 字段写入 markdown 头：

```yaml
---
type: think
author: dengke
created: '2026-04-28T...'
body_source: ai          # 或 manual；缺省按 manual 处理（兼容存量帖子）
---
```

**v1 不做 enforcement**：后端不会因为 `body_source: manual` 拒绝发布。这个字段只是为后续"AI 检测低质量输入"留下历史数据。

### 2. AI prompts：新增 NewMatter 模式

[server/ai/prompts.py](../../server/ai/prompts.py) 加一份 system prompt 变体（**仅 prompt 走分支，工具集不变**——详见 §二.4.C）：

- 告诉模型当前没有 matter 上下文，用户在新建 matter 阶段；
- 工具集与 reply 路径完全一致（5 个全开），AI 可按需调用 `search_indexes` / `read_matter_index` / `read_post` 等参考已有 matter；
- 收到 `[[GENERATE_REPLY_DRAFT]]` 时输出 `<draft type="think">` 正文 + `<summary>` + `<title>`，三段都必须有。

[server/ai/client.py](../../server/ai/client.py) 的 streamAIChat 新增 `mode` 参数路由 prompt（沿用现有 `_new_matter_` 占位 matter_id 也可以，二选一）。

### 3. 不改的部分

- 草稿 API（`/api/drafts`）不动，`matter_payload` 是自由 JSON。
- 现有 reply 路径的 `<draft>` / `<summary>` 协议不动。
- MCP 工具不动（外部 AI 走 MCP 通道，本次不涉及）。

---

## 四、范围确认

### 1. 范围内：质量门 + `body_source` 落 frontmatter

| 类型 | 入口 | 备注 |
|------|------|------|
| **新 matter 第一篇文档** | NewMatter | 需求原文明示 |
| **think 回复** | CreateFileDialog（卡片底部「+think」） | 需求原文"回复文档"明示 |
| **act 回复** | CreateFileDialog（卡片底部「+act」） | 同上 |
| **verify 回复** | CreateFileDialog（act 卡片底部「+verify」） | 同属"回复文档"——是"回复 + 验收 act"，仍是文档型回复 |

### 2. 不在本次范围（v1 不接入质量门）

| 项 | 原因 |
|----|------|
| **result（生成 Result）** | 阶段性收尾文档（推进 executing → finished/cancelled），需求原文"回复文档"按字面不含；触发场景固定（matter 完成时），AI 协作价值低于普通回复；v1 跳过，仍可走原 publish 路径，不写 `body_source` 字段。**仍允许**用户用 AI 起草，但发布时不弹门。v1.x 视用户反馈再决定接入 |
| **insight（生成 Insight）** | 同上——复盘归档文档（推进 finished/cancelled → reviewed），不在原文"回复文档"字面范围 |
| 评论（comment）的质量门 | 评论体量小、节奏快，加门破坏讨论流；需求文档措辞是"发布**文档**"，评论不在文义内 |
| 后端按 `body_source` enforce 拒绝低质量发布 | 需求文档明确"后期我们会使用 AI 工具进行检测和评价"，v1 只埋数据 |
| 强制 / 强引导 NewMatter 阶段查重 | 工具是开的（与 reply 一致），AI 可自行判断要不要查；产品不刻意推动，也不专门做"已存在相似 matter"的弹窗提示，留给 v1.1 |
| AI 帮忙决定 category / doc_type | 留给用户选择，暂时为不做 |
| 独立移动端 app / H5 | 项目本身就只有一份 Web 代码，没有原生 app 也没有独立 H5；窄屏由响应式适配（见 §二.4.G） |
| 已存在 post 的 frontmatter 回填 | 存量帖子缺字段时按 `manual` 处理，不批量回填 |

---

## 五、改动文件清单

| 文件 | 变动 | 说明 |
|------|------|------|
| `web/src/components/PublishQualityConfirmDialog.tsx` | **新增** | 公用质量门弹窗 |
| `web/src/hooks/useConfirmPublishQuality.ts` | **新增** | hook 包装弹窗 + 三态 promise |
| `web/src/lib/bodySource.ts` | **新增** | LCS 相似度算法 + 单向状态机 API：`applyAIDraft()`（唯一升级入口）、`onUserEdit()`（按需降级）、`computeAtPublish()`（发布前最终判定） |
| [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx) | 大改 | 改成左右两栏；接入 AIPane（new-matter 模式）；接入质量门；维护 `body_source` |
| [web/src/components/AIPane.tsx](../../web/src/components/AIPane.tsx) | 中改 | 新增 `mode` prop；隐藏起点帖子卡片；空态/placeholder 文案分支；GENERATE prompt 分支（new-matter 模式额外要求 `<title>`）。工具集不分支，与 reply 一致 |
| [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) | 小改 | 4 个发布入口（NewMatter + think/act/verify）前接入质量门；result / insight 仍走原 publish 链路、不写 `body_source`；`handleUseDraftAsReply` 写入 `body_source = "ai"` 与 snapshot |
| [web/src/components/matter/CreateFileDialog.tsx](../../web/src/components/matter/CreateFileDialog.tsx) | 小改 | Textarea onChange 时调用 `onUserEdit()` 更新 `body_source`；publish handler 按 `context.type` 分支——只对 think/act/verify 触发质量门，result/insight 跳过 |
| [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx) | 小改 | AI store 支持 `__newmatter__:` 前缀的虚拟 threadKey；启动时做一次孤儿清理（详见 §二.6） |
| [web/src/api.ts](../../web/src/api.ts) | 小改 | Draft / NewFileIn 类型加可选 `body_source` |
| [server/ai/prompts.py](../../server/ai/prompts.py) | 小改 | 新增 NewMatter 模式 system prompt（含 `<title>` 协议） |
| [server/api/ai.py](../../server/api/ai.py) | 小改 | chat_matter 接收 `mode` 参数（`reply` / `new-matter`），按 mode 选 system prompt；工具集仍用 `AITools(...).specs()` 不变 |
| [server/posts.py](../../server/posts.py) | 小改 | publish 时把 `body_source` 写入 frontmatter |
| [server/publish.py](../../server/publish.py) | 小改 | 同上，串通字段 |

---

## 六、测试计划

### 1. 单元测试

- `bodySource.ts`：
  - LCS 相似度边界（0.5 阈值附近、空字符串、中文字符、长文本截断）；
  - **状态机单向约束**：从 `"manual"` 状态出发，无论怎么 setBody（包括粘贴一段与 snapshot 100% 相同的文本），结果仍是 `"manual"`；只有 `applyAIDraft()` 才能升级到 `"ai"`。
- 后端 frontmatter writer：`body_source` 缺省时不写、有值时写。

### 2. 集成 / e2e（手测清单）

| 场景 | 期望 |
|------|------|
| NewMatter：默认进页，AIPane 已展开，无"起点帖子"卡片 | √ |
| NewMatter：和 AI 聊后点"生成草稿" → 正文/标题/summary 均预填 | √ |
| NewMatter：标题已手动输入时，AI 给出 title 不覆盖、出"AI 建议"提示 | √ |
| NewMatter：纯手打正文 → 点发布 → 弹质量门 | √ |
| NewMatter：质量门点"强行发布" → 创建成功，post frontmatter `body_source: manual` | √ |
| NewMatter：质量门点"发送给 AI 助手" → AIPane 输入框已填 body，未自动发送 | √ |
| Reply：AI 生成草稿不改 → 发布 → 不弹门，frontmatter `body_source: ai` | √ |
| Reply：AI 生成后小改（相似度 ≥ 0.5）→ 发布 → 不弹门，frontmatter `body_source: ai` | √ |
| Reply：AI 生成后大改（相似度 < 0.5）→ 发布 → 弹门 | √ |
| Reply：纯手打 → 发布 → 弹门 | √ |
| Reply：刷新页面后草稿恢复，`body_source` 状态正确 | √ |
| Comment：发评论 → **不弹门**（防回归） | √ |
| **result / insight 发布 → 不弹门**（防回归）；落盘 frontmatter **不含** `body_source` 字段 | √ |
| AI 流被其他 thread 占用时点"发送给 AI 助手" → 按钮文案变"加入 AI 队列" + setInput + open（不显 streaming hint） | √ |
| **粘贴绕过测试**：手动状态下把任意 AI 风格长文粘进 body → 仍为 manual → 仍弹门 | √ |
| AI 流式失败（断网模拟）→ body 不变、不弹门、Toast 重试入口可用 | √ |
| AI 返回空 `<draft>` → body 不变、不弹门、Toast 提示 | √ |
| NewMatter 模式 AI 未给 `<title>` → body/summary 正常落、标题保持原样 | √ |
| NewMatter 发布成功后跳转详情页 + 下次进入 NewMatter 时孤儿 `__newmatter__:` 会话已清理 | √ |
| Reply 发布成功后 AIPane 对话保留（同 thread 下次回复仍有上下文） | √ |
| 质量门点取消 → 不变更状态 / 草稿保留 / 可再次点发布 | √ |
| 窄屏首次进入 NewMatter → inline 引导出现 → 关闭后 localStorage 记住，下次不再出 | √ |

---

## 七、已确认决策清单

无待批准事项，开发可启动。

| 决策点 | 取值 | 落点 |
|--------|------|------|
| 相似度阈值 | **0.5**（仅用于 ai → manual 降级） | §二.2 |
| `body_source` 状态机 | **单向**：仅 AI `<draft>` 可升级；用户编辑只能降级 | §二.2 |
| 相似度计算时机 | **仅在点【发布】时算一次**，非 onChange 实时 | §二.2 |
| comment 是否纳入质量门 | **否**（豁免） | §四.2 |
| **result / insight 是否纳入质量门** | **否**（v1 跳过；落盘也不写 `body_source`；v1.x 视反馈再决定） | §四.2 |
| `body_source` 是否落 post frontmatter | **是**（仅 think/act/verify + 新 matter 第一篇） | §三.1 |
| NewMatter AI 工具集 | **与 reply 完全一致**（5 个全开） | §二.4.C |
| AI 是否决定 category / doc_type | **否**（用户手选） | §二.4.F |
| **`body_source: "ai"` 状态下编辑是否做视觉提示** | **否**（v1 不在编辑器加状态条；状态变化不抢用户视觉焦点，体感由"发布时不弹门"自然反馈） | — |
| 窄屏 NewMatter AIPane 默认状态 | **收起 + 首次进入显 inline 引导** | §二.4.G |
| 后端是否按 `body_source` enforce | **否**（v1 只埋数据） | §四.2 |

批准后转入实施计划文档（`AI-docs/plans/2026-04-28-publish-ai-rules-plan.md`，待写）。
