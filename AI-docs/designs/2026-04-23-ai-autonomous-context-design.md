# Web 端 AI 助手自主读取上下文：设计方案

**作者**：岳碧林
**日期**：2026-04-23
**状态**：draft，待评审
**依据**：Pivot 讨论《修改需求-Web端的AI助手增强和移动端UI改造》001、003 帖
**前置依赖**：index 重构先完成（见 `2026-04-23-index-refactor-design.md`），本文档直接基于新 schema 设计

---

## 一、目标

让 Web 端 AI 助手从"用户手工组装上下文"改为"自主按需读取上下文"：

- 用户在某篇帖子上点"AI 回复"后，AI 以这篇帖子为起点
- 当上下文不足时，AI 自主读取该文件所属 matter 的 timeline index
- 之后 AI 自主按需读取 timeline 上登记的相关文件（含 quote / refer 指向的跨 matter 文件）
- 全程无需用户手工选择 `reply_target` 或 `reference_files`
- 全程不走 GitHub，所有文件读取通过本地服务器 API
- 边界由服务端硬性把住：AI 只能读白名单内文件，白名单由 timeline 与 quote/refer 自动生成

本次明确**不做**：

- 移动端改造（已由主干代码覆盖）
- 用户手动追加 reference 的"逃生舱"入口
- 让 AI 扫仓库、或读任意路径文件

---

## 二、核心机制：tool-calling loop

### 2.1 为什么必须是 tool use

需求里的"AI 再自主读 index / 再自主读文件"**只能通过模型工具调用（tool use）实现**。其他选项（总把 index 附进 system prompt、按规则预拼上下文）都不是真正的"AI 自主"，而是"服务端代理"。

现状 `/api/ai/threads/{category}/{slug}/chat`（`server/api/ai.py:193` 起）是单轮 SSE：pre-baked system prompt + messages → LLM → 流式文本返回。本次改造把它升级为多轮 tool-calling loop。

### 2.2 整体流程

```
用户点"AI 回复" ─┐
                 │
                 ▼
   前端 POST /api/ai/matters/{matter_id}/chat
   body: { messages, target_file }
                 │
                 ▼
   后端起 chat 循环：
     1. 组装 system prompt（含工具描述、target_file 全文、读取边界说明）
     2. 调 LLM tool-calling API
     3. 若 LLM 返回 tool_calls：
           a. 校验工具名与参数
           b. 校验路径白名单（见 3.3）
           c. 执行 read_matter_index 或 read_file
           d. 把 tool_result 追加到 messages
           e. 回到步骤 2
     4. 若 LLM 返回文本：流式推送给前端，循环结束
                 │
                 ▼
        前端渲染消息 + 已读取文件列表
```

一轮会话里步骤 2-3 可能来回多次，直到模型不再调工具或达到预算上限。

---

## 三、工具定义

### 3.1 `read_matter_index(matter_id)`

**用途**：让 AI 获得当前 matter 的全局概览（timeline + 每篇文件的摘要、类型、引用关系），用来决定下一步读哪几篇全文。

**参数**：

- `matter_id` : string，必填。只允许等于当前会话的 `matter_id`（传别的直接拒绝）

**返回结构**（LLM 可读文本）：

```
# Matter: {title}  ({id})
Current status: {current_status}
Created: {created_at}  Last updated: {updated_at}

## Timeline

### {file path}
- type: think | act | verify | result | insight
- creator: xxx  owner: yyy
- created_at: ...
- summary: {一句话摘要}
- quote: {path or "(none)"}
- refer: [path1, path2, ...]
- status_change: {from -> to}  (仅在触发状态迁移时出现)
- verifications:                (仅 type=verify 时)
    - target: ...  judgement: passed|failed|cancelled  comment: ...

### {下一个 file}
...
```

返回体按 `MatterIndex.timeline` 序列化，不带 `comments` 字段（评论对 AI 选文件帮助小、占空间大；如需可通过 `read_file` 拿到文件本体时附带）。

**约束**：

- 只读，无副作用
- 返回体长度不计入 `MAX_CONTEXT_CHARS`（但计入 LLM 的 context window，截断策略见 5.3）
- 单次会话里该 tool 的调用次数计入总预算

### 3.2 `read_file(path)`

**用途**：按路径读取一篇文件全文。

**参数**：

- `path` : string，必填。形如 `discussions/{category}/{slug}/{filename}.md` 的绝对路径（相对于 workspace）

**返回结构**：

```
# {file path}
Type: {type}  Creator: {creator}  Owner: {owner}  Created: {created_at}

---

{文件正文}

---

## Comments on this file
- {author} @ {created_at}: {body} (mentions: @x @y)
- ...
```

正文体积上限沿用 `server/ai/context.py:MAX_CONTEXT_CHARS`。超长返回截断后的正文 + `[TRUNCATED]` 标记。

**约束**：

- 只读
- 路径必须通过 3.3 白名单检查
- 同一路径在同一会话内重复调用时返回缓存（避免反复读同一文件耗预算）

### 3.3 白名单算法

每次 `read_file(path)` 调用时，服务端计算当前允许读取集合：

```
Allowed(session) = {target_file}
                 ∪ { item.file for item in current_matter.timeline }
                 ∪ { item.quote for item in current_matter.timeline if item.quote }
                 ∪ { r for item in current_matter.timeline for r in item.refer }
```

即：当前 target、当前 matter timeline 上所有文件、它们 quote 指向的文件（通常同 matter，但若迁移后存在跨 matter quote 也允许）、refer 指向的所有跨 matter 文件。

**不允许的情况**：

- 路径不在 `Allowed(session)` 中
- 路径不通过基本合法性校验（不是三段式、不在 `discussions/` 下、文件不存在）

白名单在会话启动时一次性计算并缓存到会话上下文；若会话中间有文件被新增（目前本次会话中不会发生，因为 AI 只读不写），不重算。

---

## 四、chat 接口改造

### 4.1 请求

**新路径**：`POST /api/ai/matters/{matter_id}/chat`

旧路径 `POST /api/ai/threads/{category}/{slug}/chat` 保留为别名，内部转发到新 handler。

**请求体**：

```json
{
  "messages": [{"role": "user|assistant", "content": "..."}],
  "target_file": "discussions/Pivot/xxx/005_xxx.md"
}
```

**去掉** 旧字段 `reply_target`、`reference_files`。为向旧前端兼容，若请求体仍带 `reply_target`，后端把它当作 `target_file` 处理（灰度期）；`reference_files` 一律忽略并在响应 header 返回 `X-Deprecated-Field: reference_files`。

### 4.2 响应：SSE 事件协议扩展

当前 SSE 只有两类数据：`{delta: "..."}` 文本增量、`{error: "..."}` 错误。

新增三类事件：

```
data: {"type": "tool_call", "tool": "read_matter_index", "arguments": {...}, "call_id": "xyz"}

data: {"type": "tool_result", "call_id": "xyz", "ok": true, "bytes": 1823}

data: {"type": "tool_result", "call_id": "xyz", "ok": false, "error": "path not in allowed set"}
```

保留原有：

```
data: {"delta": "..."}     # 模型文本流
data: {"error": "..."}      # 终止性错误
data: [DONE]
```

前端消费 `tool_call / tool_result` 事件维护"AI 已读取哪些文件"的只读展示。**不**把 tool_result 的内容推到前端（避免把全部文件 body 发到浏览器）；前端只感知"读过哪些文件、成功/失败"。

### 4.3 chat 循环伪代码

```python
async def chat(matter_id, body):
    session = ChatSession(matter_id, body.target_file)
    session.messages = prepare_llm_messages(body.messages, system_prompt(matter_id, body.target_file))
    tool_calls_made = 0

    while tool_calls_made <= MAX_TOOL_CALLS_PER_SESSION:
        response = await llm_client.call_with_tools(
            messages=session.messages,
            tools=[READ_MATTER_INDEX, READ_FILE],
        )

        if response.finish_reason == "tool_calls":
            for tc in response.tool_calls:
                yield sse_event("tool_call", tool=tc.name, arguments=tc.arguments, call_id=tc.id)
                try:
                    result = execute_tool(session, tc)
                    yield sse_event("tool_result", call_id=tc.id, ok=True, bytes=len(result))
                    session.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                except ToolError as e:
                    yield sse_event("tool_result", call_id=tc.id, ok=False, error=str(e))
                    session.messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"ERROR: {e}"})
                tool_calls_made += 1
            continue

        # finish_reason == "stop": stream text
        async for delta in llm_client.stream_text_continuation(session.messages):
            yield sse_event_legacy(delta=delta)
        break

    if tool_calls_made > MAX_TOOL_CALLS_PER_SESSION:
        yield sse_event("error", error="工具调用次数已达上限，对话中止")

    yield "data: [DONE]\n\n"
```

### 4.4 system prompt

基础模板：

```
你是 Pivot 的 AI 助手。当前用户正在讨论 matter {matter_id}（{title}），
目标文件是 {target_file}。

以下是目标文件的全文：
<file path="{target_file}">
{target_file_content}
</file>

你可以调用下面两个工具来补充上下文：

- read_matter_index(matter_id): 返回当前 matter 的 timeline 与每篇文件的摘要、
  类型、引用关系。当目标文件本身信息不足、需要理解整个 matter 的脉络时调用。

- read_file(path): 按路径读取一篇文件全文。只能读取当前 matter timeline 上
  登记的文件，或它们 quote / refer 指向的文件。

调用原则：
1. 优先基于目标文件回答
2. 只在明确缺少信息时调用工具，不要为"以防万一"调用
3. 一次会话最多 {MAX_TOOL_CALLS_PER_SESSION} 次工具调用
4. 禁止请求白名单外的文件，错误只会返回同样的拒绝消息，请自行放弃
```

---

## 五、预算与频控（初版）

| 参数 | 初值 | 说明 |
|---|---|---|
| `MAX_TOOL_CALLS_PER_SESSION` | 6 | 单次会话累计工具调用次数上限 |
| `read_file` 单次体积上限 | 沿用 `MAX_CONTEXT_CHARS` | 超长截断 |
| `read_matter_index` 返回体上限 | 不设 | timeline 本身已是摘要，不会很大；若超 10K 字符前端 warn |
| tool_result 累计在 LLM context 的压缩阈值 | 当累计 tool_result 字节数 > `max_context_tokens * 3` | 触发 5.3 截断 |

### 5.1 重复调用去重

同一 `read_file(path)` 在同一会话内调用第二次时，直接返回缓存文本，**不计入** `MAX_TOOL_CALLS_PER_SESSION`。

### 5.2 错误不消耗预算

`read_file` 返回白名单错误或 `read_matter_index` 参数非法时，该次调用**计入**预算（否则模型可以用错误请求无限重试）。

### 5.3 context 截断策略

会话消息链路长度超限时：

- 保留 `system prompt`
- 保留最近 N 轮 `user / assistant` 消息（按 `min_rounds / max_rounds` 现有策略）
- 保留最后一次 `tool_result`
- 更早的 `tool_result` 压缩为形如 `"(previously read: 001_xxx.md, 003_xxx.md)"` 的单条 assistant 消息

这些初值上线后根据实际运行数据调整，可在 `/api/ai/settings` 追加字段暴露。

---

## 六、前端改造

### 6.1 `AIPane.tsx` 变化

**移除**：

- `replyTarget` 与 `referenceFiles` 两个 state 在用户可配置形态下的 UI 入口
- `FileTreeBrowser` 的 `mode="reply_target"` 与 `mode="reference"` 调用点
- 相关 `setReplyTarget / setReferenceFiles` 的 action

**新增**：

- "AI 已读取文件"只读展示区：订阅 SSE 的 `tool_call / tool_result` 事件，维护一个 `readFiles: { path: string, ok: boolean }[]` 列表，展示为折叠的小卡片
- 顶部显示当前 target 文件（不可编辑，由 `pendingReplyTarget` 机制自动填入，保留现有逻辑）

**保留**：

- `pendingReplyTarget` 注入机制（已经工作）
- `onUseDraftAsReply` 回调
- `GENERATE_REPLY_DRAFT` tag 的生成草稿流程

### 6.2 `FileTreeBrowser.tsx` 处置与相关清理

Grep 当前调用方：只在 `AIPane.tsx` 中被使用（`mode="reply_target"` 与 `mode="reference"`）。A 改造把两个调用点都移除后，该组件无其他消费方。

**本次直接删除**，不保留死代码：

- `web/src/components/FileTreeBrowser.tsx`（整文件）
- `web/src/api.ts` 中的 `fetchAIFiles` 函数与 `AIThreadFiles` type 定义
- `server/api/ai.py:120` 的 `list_ai_files` handler 与 `GET /api/ai/files` 路由
- `server/tests/test_ai_api.py` 中覆盖 `list_ai_files` 的测试用例

若评审阶段发现其他未知消费方，改为保留一个版本周期再删除，但当前代码搜索范围内没找到。

### 6.3 会话持久化

`ai_conversations` 表新增字段 `read_files: JSON`（字符串数组）。每次 `tool_result` 成功时追加文件路径；会话加载时前端用这个字段还原"AI 已读取文件"展示。

旧字段 `reply_target`、`reference_files` 在表里保留，新代码不写。

---

## 七、实施步骤

1. **M1：后端 tool 实现**
   - `server/ai/tools.py`（新增）：定义 `READ_MATTER_INDEX` / `READ_FILE` 的 JSON schema、执行函数、白名单算法
   - 单测覆盖：正常路径、白名单拒绝、参数非法、重复调用缓存、超额拦截

2. **M2：chat 循环改造**
   - `server/ai/client.py` 扩展 `stream_chat_with_tools`，对接 OpenRouter / OpenAI 兼容的 tool-calling API
     - **复杂度提示**：现行 `stream_chat` 只处理 `choices[0].delta.content` 简单流。OpenRouter tool-calling 流式响应里 `tool_calls` 分散在多个 chunk（每个 delta 带 `index` 与增量 `arguments` 字符串，需累积拼装到 finish_reason；工具名和 id 通常只在第一个 chunk 出现）。要实现：chunk 聚合器、finish_reason 判定、错误路径兜底。预计比 `stream_chat` 复杂 3-5 倍
     - 挑 2-3 个主流模型（Claude Sonnet / GPT-4 class / Gemini）实机跑通，兼容性差的加 warning
   - `server/api/ai.py` 的 `chat` handler 改为 4.3 节的循环结构
   - SSE 事件协议新增三类事件

3. **M3：API 路由切换**
   - 新增 `POST /api/ai/matters/{matter_id}/chat`
   - 保留 `POST /api/ai/threads/{category}/{slug}/chat` 作为别名
   - 请求体兼容逻辑（`reply_target` → `target_file`；`reference_files` 忽略）

4. **M4：前端改造**
   - `AIPane.tsx` 按 6.1 节改造
   - 新增 "已读取文件" 展示组件
   - SSE 事件消费扩展
   - 移除手工选文件的主流程入口

5. **M5：持久化**
   - 扩展 `ai_conversations` 表结构与 repo 方法
   - 加载会话时还原 read_files 展示

6. **M6：本地自测与联调**
   - 按需求原文六的要求：本地部署，跑通完整路径（读帖 → AI 讨论 → 生成草稿 → 修改 → 发布）
   - 核对验收标准（原文五）

7. **M7：部署**

本文档不列具体排期；开发进度见后续执行帖。

---

## 八、测试计划

### 8.1 单元测试

- `server/tests/test_ai_tools.py`（新增）
  - `read_matter_index` 正确返回 timeline
  - `read_file` 白名单校验、重复缓存、超长截断
  - 非法参数（matter_id 不匹配、路径越界）

- `server/tests/test_ai_chat_loop.py`（新增）
  - mock LLM 返回 tool_calls → 断言服务端执行 → tool_result 回塞 → 继续循环
  - 超过 `MAX_TOOL_CALLS_PER_SESSION` 时循环被中止
  - 工具返回错误时 assistant 收到错误消息而不是崩溃

- 现有 `server/tests/test_ai_chat.py`（如有）改为覆盖 SSE 新事件类型

### 8.2 前端测试

**前置**：假定 B 阶段已安装 vitest + @testing-library 测试栈（见 B 设计 7.1b）。若 A 先于 B 完成（不应发生，A 依赖 B 的新 schema），在 A 的 M4 里补装。

- `AIPane` 在 SSE 推 `tool_call / tool_result` 时正确渲染"已读取文件"列表
- 无手工选文件 UI
- `pendingReplyTarget` 注入后正确显示为只读 target 标签

### 8.3 联调验收（对齐需求原文五）

1. 点击某帖"AI 回复"，AI 先读该帖
2. 问 AI 一个需要更多上下文的问题，观察 SSE 出现 `read_matter_index` 调用
3. 观察 AI 继续调 `read_file` 读其他文件
4. 全程无用户手选
5. 全程流量只走本地 API
6. 断开 target 文件所在 matter，让 AI 尝试读外部文件，应被拒绝

---

## 九、风险

- **LLM 服务商 tool-calling 稳定性**：OpenRouter 上不同模型对 tool-calling 的遵循度差异较大。需要在 `server/ai/client.py` 里对返回结构做容错（模型偶尔把 tool_call 写在正文里等）。测试阶段挑 2-3 个主流模型都过一遍
- **预算 6 次是否够用**：真实场景下 AI 可能在一轮对话里需要多次读文件。初版 6 次偏保守，上线后按实际数据调
- **白名单对 AI 的解释成本**：如果模型反复请求白名单外文件，prompt 里要有更强的"放弃重试"引导，防止模型陷死循环
- **前端 SSE 断线重连**：tool_call 进行中连接断开时，前端如何恢复显示。初版简单处理：重连后从最后一次 DONE 之后的消息开始重放，tool_call 历史丢失可接受
- **跨 matter 白名单**：邓柯明确放弃了逃生舱，白名单只能靠 refer 字段。如果迁移后历史数据 refer 不全，会出现"AI 无法读到实际相关的跨 matter 文件"的遗憾。见 B 设计文档第九节风险，这里不重复兜

---

## 十、评审关注点

1. **预算 6 次是否合理**，还是上来就放到 10 次
2. **tool_result 内容不推前端**是否会让用户对 AI 的阅读过程不透明，需不需要让前端可点击查看读了什么
3. **旧请求体兼容期**（`reply_target` 被当作 `target_file`、`reference_files` 被忽略）保留多久
4. **生成草稿流程**（`[[GENERATE_REPLY_DRAFT]]` tag）是否也借这次机会改造为 tool（比如 `generate_draft(...)`），还是保持现有 tag-based 约定不动
