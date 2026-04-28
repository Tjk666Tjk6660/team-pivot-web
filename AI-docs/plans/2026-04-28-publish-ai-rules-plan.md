# Pivot 发布新 matter 和回复 matter 时使用 AI 助手的规则变化：实施计划

> **For agentic workers:** 用 checkbox（`- [ ]`）逐 Task / Step 推进。每个 Phase 末尾都有 Commit Checkpoint，**做完一个 Phase 再开下一个**，避免半截改动留在工作区。

**Goal:** 在 Pivot Web 上统一新 matter 第一篇文档与 reply 文档的 AI 协作能力——NewMatter 加 AIPane 双栏；新增"未经 AI 协作发布前弹质量门"机制；引入 `body_source` 内容来源单向状态机贯穿前端 + 草稿 + post frontmatter。

**Architecture:** 复用现有 [AIPane](../../web/src/components/AIPane.tsx) + `<draft>` / `<summary>` 协议；新增 `PublishQualityConfirmDialog` 公用组件 + `useConfirmPublishQuality` hook；新增 `web/src/lib/bodySource.ts` 实现单向状态机；后端 `chat_matter` 增加 `mode` 参数路由 prompt，工具集不变；后端发布路径把 `body_source` 当作可选 frontmatter 字段写入 markdown 头。

**Tech Stack:** React + TypeScript + shadcn/ui + Tailwind + sonner（前端）；Python 3.12 + FastAPI（后端）；pytest + Vitest（测试）。

**依据**：[AI-docs/designs/2026-04-28-publish-ai-rules-design.md](../designs/2026-04-28-publish-ai-rules-design.md)（已确认决策清单见 §七）

---

## 范围对照（与 design §四对齐）

**纳入质量门 + 写 `body_source`**：
- 新 matter 第一篇文档（NewMatter）
- think / act / verify 回复（CreateFileDialog）

**v1 不纳入**：
- result / insight（仍可用 AI 起草，但不弹门、不写 `body_source`）
- comment 评论
- 后端 enforcement

---

## 文件结构

### 前端新增

| 路径 | 职责 |
|------|------|
| `web/src/lib/bodySource.ts` | 单向状态机 API：`applyAIDraft()` / `onUserEdit()` / `computeAtPublish()` + LCS 相似度 |
| `web/src/components/PublishQualityConfirmDialog.tsx` | 公用质量门弹窗（强行发布 / 发送给 AI 助手 / 取消） |
| `web/src/hooks/useConfirmPublishQuality.ts` | 包装弹窗的 promise hook，返回 `"go" \| "send_to_ai" \| "cancel"` |

### 前端修改

| 路径 | 修改内容 |
|------|----------|
| [web/src/api.ts](../../web/src/api.ts) | `Draft.matter_payload` 类型扩展 `body_source` / `body_source_snapshot`；`NewFileIn` / `appendMatterFile` 等接受可选 `body_source` |
| [web/src/components/AIPane.tsx](../../web/src/components/AIPane.tsx) | 新增 `mode: "reply" \| "new-matter"` prop；隐藏起点帖子卡片；空态/placeholder 文案分支；GENERATE prompt 在 new-matter 模式下额外要求 `<title>` |
| [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx) | AI store 支持 `__newmatter__:` 前缀虚拟 threadKey；启动时做一次孤儿清理 |
| [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx) | 大改：左右两栏；接入 AIPane（new-matter mode）；标题预填策略；接入质量门；维护 body_source；窄屏 inline 引导 |
| [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) | `handleUseDraftAsReply` 调 `applyAIDraft` 写入 ai + snapshot；4 个 publish 入口前接入质量门；result / insight 入口跳过 |
| [web/src/components/matter/CreateFileDialog.tsx](../../web/src/components/matter/CreateFileDialog.tsx) | Textarea onChange 调 `onUserEdit()`；publish handler 按 `context.type` 跳过 result/insight；表单 props 加 `body_source` 透传 |

### 后端修改

| 路径 | 修改内容 |
|------|----------|
| [server/api/ai.py](../../server/api/ai.py) | `chat_matter` 接收可选 `mode: Literal["reply", "new-matter"] = "reply"`；按 mode 选 system prompt；工具集不变 |
| [server/ai/prompts.py](../../server/ai/prompts.py) | 新增 `build_new_matter_system_prompt()`，含 `<title>` 协议；reply 走原有 `build_system_prompt()` |
| [server/posts.py](../../server/posts.py) | post 写入时支持把 `body_source` 写进 frontmatter；缺省时不写 |
| [server/api/matters.py](../../server/api/matters.py)（或 publish 链路对应文件） | `POST /api/matters` 与 `POST /api/matters/{id}/files` 接收可选 `body_source`，串到 posts.py |

### 测试

| 路径 | 覆盖 |
|------|------|
| `web/src/lib/bodySource.test.ts` | 单向状态机 + LCS 边界 |
| `web/src/components/PublishQualityConfirmDialog.test.tsx`（可选 v1） | 三种 promise resolve |
| `server/tests/test_posts_body_source.py` | frontmatter 写入分支 |
| `server/tests/test_chat_matter_mode.py` | mode 参数路由 prompt |

### 不动

- 草稿 API（`/api/drafts`）：`matter_payload` 是自由 JSON，新字段直接落进去；
- 现有 reply 路径的 `<draft>` / `<summary>` 协议；
- MCP 工具与外部 AI 通道；
- 移动端独立代码（不存在；窄屏由 Tailwind 断点适配）。

---

## Phase 0：准备

### Task 0.1：确认工作分支

- [ ] **Step 1：从 main 切分支**

```bash
git checkout main
git pull --ff-only
git checkout -b feat/publish-ai-rules
```

- [ ] **Step 2：基线检查**

```bash
uv run pytest server/tests -q
cd web && npm run typecheck && npm run build
```

Expected：全部 PASS，建立干净基线。

---

## Phase 1：`bodySource.ts` 纯函数层（无 UI 依赖，可独立测试）

### Task 1.1：实现单向状态机 + LCS

**Files:**
- Create: `web/src/lib/bodySource.ts`
- Create: `web/src/lib/bodySource.test.ts`

- [ ] **Step 1：写 `bodySource.ts`**

API 形状（与 design §五一致）：

```ts
export type BodySource = "ai" | "manual";

export type BodySourceState = {
  body_source: BodySource;
  body_source_snapshot?: string;  // 仅 "ai" 状态下有意义
};

// 唯一升级入口：AI <draft> 协议显式写入
export function applyAIDraft(aiBody: string): BodySourceState;

// 用户编辑：当前 ai 时按 LCS 相似度决定是否降级；当前 manual 永远不变
export function onUserEdit(
  state: BodySourceState,
  newBody: string,
): BodySourceState;

// 发布前最终判定（仅做一次 LCS）；空 body 抛错由调用方处理
export function computeAtPublish(
  state: BodySourceState,
  currentBody: string,
): BodySource;

// 内部：LCS 相似度（导出供测试）
export function similarity(a: string, b: string): number;
```

实现要点（写进文件顶部 JSDoc，非每函数加注释）：

- LCS：标准 DP 实现，二维数组优化为一维滚动；空串相似度定义为 0；
- `similarity = LCS / max(len(a), len(b))`；
- 阈值常量 `SIM_THRESHOLD = 0.5`、`SHRINK_THRESHOLD = 0.3`；
- `onUserEdit` 仅当 `state.body_source === "ai"` 才计算；`manual` 直接返回原 state；
- `computeAtPublish`：先看 `body_source`；ai 状态下做最终 LCS（防 onUserEdit 跳过的极端漏判）；manual 直接返回 manual。

- [ ] **Step 2：写单元测试 `bodySource.test.ts`**

测试用例：

```ts
describe("similarity", () => {
  it("空字符串相似度为 0");
  it("完全相同字符串相似度为 1");
  it("中文字符按 code unit 计算");
  it("一长一短：'你好世界' vs '你好' → 0.5");
});

describe("applyAIDraft", () => {
  it("无论入参，结果固定为 ai + snapshot=入参");
});

describe("onUserEdit", () => {
  it("manual 状态下，无论 newBody 是什么（含与 snapshot 高度相似），仍为 manual");
  it("ai 状态下，sim ≥ 0.5 仍为 ai");
  it("ai 状态下，sim < 0.5 降为 manual");
  it("ai 状态下，len(new) < len(snapshot) * 0.3 直接降为 manual");
  it("ai 状态下清空 body → manual");
});

describe("computeAtPublish", () => {
  it("manual 状态返回 manual，不论相似度");
  it("ai 状态 + sim ≥ 0.5 返回 ai");
  it("ai 状态 + sim < 0.5 返回 manual");
});

describe("粘贴绕过场景（关键）", () => {
  it("从 manual 起步，粘入与某 AI 草稿 100% 相同的文本，仍为 manual");
});
```

- [ ] **Step 3：跑测试**

```bash
cd web && npx vitest run src/lib/bodySource.test.ts
```

Expected：全部 PASS。

- [ ] **Step 4：Commit**

```bash
git add web/src/lib/bodySource.ts web/src/lib/bodySource.test.ts
git commit -m "feat(web): bodySource state machine with one-way LCS gating"
```

---

## Phase 2：质量门 UI（弹窗 + hook）

### Task 2.1：`PublishQualityConfirmDialog` 组件

**Files:**
- Create: `web/src/components/PublishQualityConfirmDialog.tsx`

- [ ] **Step 1：实现弹窗**

复用 [`@/components/ui/dialog`](../../web/src/components/ui/dialog.tsx)。Props：

```ts
type Props = {
  open: boolean;
  blockedByAIBusy: boolean;     // AI 流被其他 thread 占用，影响"发送给 AI 助手"按钮文案
  busyTitle?: string;            // blocked 时显示的当前占用 thread 标题
  onForcePublish: () => void;
  onSendToAI: () => void;
  onCancel: () => void;
};
```

文案（直接照搬 design §二.3 / 需求文档原文）：

```
检测到这篇内容不是由当前 AI 助手和你讨论后输出的。

请确认这篇文档能够代表你的真实想法，并且足够清晰可读、有思考沉淀、
有结构化表达，以便持续提高团队讨论质量。

对于低质量输入，后期我们会使用 AI 工具进行检测和评价。
```

按钮：

| 状态 | "发送给 AI 助手"按钮 | "强行发布"按钮 |
|------|--------------------|--------------|
| 默认 | "发送给 AI 助手" | "强行发布" |
| `blockedByAIBusy === true` | "加入 AI 队列"，副本：「内容已填入，等当前对话「{busyTitle}」完成后再发送」 | 不变 |

- [ ] **Step 2：手测**

不必单测；起 `npm run dev` 临时把组件挂到任意页面上点一遍三个按钮，确认 onCancel/onForcePublish/onSendToAI 都触发；blocked 状态下文案切换正常。

- [ ] **Step 3：Commit**

```bash
git add web/src/components/PublishQualityConfirmDialog.tsx
git commit -m "feat(web): PublishQualityConfirmDialog with blocked-state copy"
```

---

### Task 2.2：`useConfirmPublishQuality` hook

**Files:**
- Create: `web/src/hooks/useConfirmPublishQuality.ts`

- [ ] **Step 1：实现 hook**

```ts
type GateResult = "go" | "send_to_ai" | "cancel";

export function useConfirmPublishQuality(): {
  dialog: React.ReactElement;          // 挂在页面里
  confirm: (args: {
    bodySource: BodySource;
    blockedByAIBusy: boolean;
    busyTitle?: string;
  }) => Promise<GateResult>;
};
```

约定：

- `bodySource === "ai"` → `confirm` 直接 resolve `"go"`，不弹窗；
- `bodySource === "manual"` → 弹窗，按用户点击 resolve `"go"` / `"send_to_ai"` / `"cancel"`；
- 同一时刻只允许一个弹窗存活（用 ref 守卫，避免页面同时调多次 confirm）。

- [ ] **Step 2：Commit**

```bash
git add web/src/hooks/useConfirmPublishQuality.ts
git commit -m "feat(web): useConfirmPublishQuality hook"
```

---

## Phase 3：API 类型扩展（前端 + 后端契约对齐）

### Task 3.1：前端 `api.ts` 扩展

**Files:**
- Modify: `web/src/api.ts`

- [ ] **Step 1：扩展 Draft / NewFileIn / CreateMatterIn 类型**

`Draft.matter_payload` 是自由 JSON，但本项目内有 TS 类型注解。在对应类型加：

```ts
matter_payload?: {
  // ... 既有字段
  body_source?: "ai" | "manual";
  body_source_snapshot?: string;
  // ...
};
```

`NewFileIn`（appendMatterFile / appendMatterResult / appendMatterInsight 接收）和 `CreateMatterIn` 加可选 `body_source?: "ai" | "manual"`。

- [ ] **Step 2：tsc 通过**

```bash
cd web && npm run typecheck
```

- [ ] **Step 3：Commit**

```bash
git add web/src/api.ts
git commit -m "feat(web): expose body_source on Draft / NewFileIn / CreateMatterIn types"
```

---

### Task 3.2：后端 `posts.py` 写入 frontmatter

**Files:**
- Modify: [server/posts.py](../../server/posts.py)
- Create: `server/tests/test_posts_body_source.py`

- [ ] **Step 1：增加可选字段**

找到 post frontmatter 写入函数（write/append post），把 `body_source: str | None = None` 加入参数；当且仅当传入非 None 时写 yaml 头里的 `body_source: <value>`。**缺省不写**（兼容存量 + 跳过 result/insight）。

- [ ] **Step 2：单元测试**

```python
def test_write_post_with_body_source(tmp_path):
    write_post(..., body_source="ai")
    # 读回 frontmatter，断言 body_source == "ai"

def test_write_post_without_body_source(tmp_path):
    write_post(...)  # 不传
    # 读回 frontmatter，断言不含 body_source 键

def test_write_post_body_source_manual(tmp_path):
    write_post(..., body_source="manual")
    # 读回断言 == "manual"
```

- [ ] **Step 3：跑测试**

```bash
uv run pytest server/tests/test_posts_body_source.py -q
```

- [ ] **Step 4：Commit**

```bash
git add server/posts.py server/tests/test_posts_body_source.py
git commit -m "feat(server): optional body_source in post frontmatter"
```

---

### Task 3.3：后端 publish 入口透传

**Files:**
- Modify: [server/api/matters.py](../../server/api/matters.py)（或对应路由文件）
- Modify: [server/publish.py](../../server/publish.py)（如果 publish 逻辑独立）

- [ ] **Step 1：定位 `POST /api/matters` 与 `POST /api/matters/{id}/files` 的请求模型**

```bash
```

用 Grep 找到对应 Pydantic 模型，加可选字段：

```python
class CreateMatterIn(BaseModel):
    # ...
    initial_file: InitialFileIn

class InitialFileIn(BaseModel):
    # ...
    body_source: Literal["ai", "manual"] | None = None

class AppendFileIn(BaseModel):
    # ...
    body_source: Literal["ai", "manual"] | None = None
```

`POST /api/matters/{id}/result` 和 `.../insight` **不加** `body_source` 参数（v1 跳过）。

- [ ] **Step 2：把字段透传到 `posts.py` 写入处**

publish 链路里调用 write_post 的地方加上 `body_source=in.body_source`。

- [ ] **Step 3：跑现有 matter API 测试**

```bash
uv run pytest server/tests/test_matters_api.py -q
```

Expected：现有测试不受影响（字段是可选）。

- [ ] **Step 4：Commit**

```bash
git add server/api/matters.py server/publish.py
git commit -m "feat(server): pipe body_source through create_matter / append_file"
```

---

## Phase 4：AIPane mode prop + new-matter 模式

### Task 4.1：后端 prompt 变体 + chat_matter mode 参数

**Files:**
- Modify: [server/ai/prompts.py](../../server/ai/prompts.py)
- Modify: [server/api/ai.py](../../server/api/ai.py)
- Create: `server/tests/test_chat_matter_mode.py`

- [ ] **Step 1：在 prompts.py 加 `build_new_matter_system_prompt()`**

复制现有 `build_system_prompt()` 的骨架（工具列表、`<draft>` 协议、禁止规则），改三处：

1. 移除 `starting_post` block（new matter 没有起点帖子）；
2. 改开场白："当前用户在新建 matter 阶段，没有 matter 上下文。你可以使用工具去 workspace 里查类似讨论作为参考，也可以直接基于用户输入起草。"；
3. `[[GENERATE_REPLY_DRAFT]]` 协议除了 `<draft type="think">` 和 `<summary>`，多要求一个 `<title>`：
   ```
   <title>matter 标题建议（一句话，不超过 30 字）</title>
   ```

- [ ] **Step 2：chat_matter 接收 mode**

[server/api/ai.py:180+](../../server/api/ai.py#L180) 的 `chat_matter` request body 加：

```python
class ChatMatterIn(BaseModel):
    # ...
    mode: Literal["reply", "new-matter"] = "reply"
    reply_target: str | None = None  # new-matter 模式可为空
```

handler 里：

```python
if body.mode == "new-matter":
    system_prompt = build_new_matter_system_prompt()
else:
    if not body.reply_target:
        raise HTTPException(400, "缺少起点帖子（reply_target）")
    starting_block = build_starting_post_block(...)
    system_prompt = build_system_prompt(starting_block)
```

工具集（`AITools(...).specs()`）**不分支**，两条路径共享。

- [ ] **Step 3：单元测试**

```python
def test_chat_matter_mode_reply_requires_target(client):
    # reply 模式不传 reply_target → 400

def test_chat_matter_mode_new_matter_no_target_ok(client, mock_openrouter):
    # new-matter 模式不传 reply_target → 200，system prompt 走 new_matter 分支

def test_chat_matter_default_mode_is_reply(client):
    # 不传 mode，行为与 mode=reply 一致（向后兼容）
```

- [ ] **Step 4：跑测试**

```bash
uv run pytest server/tests/test_chat_matter_mode.py -q
```

- [ ] **Step 5：Commit**

```bash
git add server/ai/prompts.py server/api/ai.py server/tests/test_chat_matter_mode.py
git commit -m "feat(server): chat_matter mode param + new-matter prompt with <title> protocol"
```

---

### Task 4.2：前端 `streamAIChat` 接受 mode

**Files:**
- Modify: [web/src/api.ts](../../web/src/api.ts)

- [ ] **Step 1：streamAIChat 增加可选 mode 参数**

```ts
export async function* streamAIChat(
  matter_id: string,
  messages: AIMsg[],
  reply_target: string | null,
  mode: "reply" | "new-matter" = "reply",
): AsyncIterable<...>
```

向 POST body 加 `mode`。reply 路径调用方不传 → 默认 `"reply"`，无回归。

- [ ] **Step 2：tsc + 现有调用方不变**

```bash
cd web && npm run typecheck
```

- [ ] **Step 3：Commit**

```bash
git add web/src/api.ts
git commit -m "feat(web): streamAIChat accepts optional mode parameter"
```

---

### Task 4.3：AIPane 增加 `mode` prop

**Files:**
- Modify: [web/src/components/AIPane.tsx](../../web/src/components/AIPane.tsx)

- [ ] **Step 1：加 prop**

```ts
type AIPaneProps = {
  // ... 既有
  mode?: "reply" | "new-matter";  // 默认 "reply"
};
```

- [ ] **Step 2：按 mode 分支**

| 项 | 改动位置 | reply | new-matter |
|----|---------|-------|-----------|
| "起点帖子"卡片 | line 178-196 块 | 显示 | 隐藏（`mode === "reply" && replyTarget && ...`）|
| `noTarget` disabled | line 145 | 启用 | 关闭（`const noTarget = mode === "reply" && !replyTarget;`）|
| 空态文案 | line 215-218 | 现状 | "和 AI 说说你想发起的讨论吧，或者直接在右侧写正文。" |
| placeholder | line 339-345 | 现状 | "和 AI 描述你想发起的讨论…" |
| GENERATE prompt | [line 139](../../web/src/components/AIPane.tsx#L139) | 现状 | 改为：`${GENERATE_TAG} 请根据以上对话，为这个新 matter 生成完整 think 正文（用 <draft type="think">...</draft> 包裹）+ 一句不超过 80 字的中文 <summary>...</summary> + 一句不超过 30 字的 <title>...</title>` |
| `streamAIChat` 调用 | 通过 ai store / Dashboard.tsx 传入 mode | 默认 reply | mode=new-matter |

- [ ] **Step 3：传 mode 给 streamAIChat**

`useDashboard().ai.sendMessage` 已经在 Dashboard.tsx 的 store 里。Task 5.1 会改 store 接收 mode；这里 AIPane 通过 sendMessage args 透传。

- [ ] **Step 4：Commit**

```bash
git add web/src/components/AIPane.tsx
git commit -m "feat(web): AIPane mode prop with new-matter UI/prompt branches"
```

---

## Phase 5：Dashboard AI store 支持虚拟 threadKey + mode 透传

### Task 5.1：扩展 `ai.sendMessage` 接收 mode

**Files:**
- Modify: [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx)

- [ ] **Step 1：sendMessage 加 mode 参数**

```ts
sendMessage({
  matter_id: string;
  threadKey: string;
  threadTitle: string;
  rawText: string;
  hasReplyDraft: boolean;
  onUseDraftAsReply: ...;
  mode?: "reply" | "new-matter";  // 默认 "reply"
}): Promise<void>;
```

- [ ] **Step 2：streamAIChat 调用透传**

把 mode 传到 [streamAIChat](../../web/src/api.ts) 调用处。

- [ ] **Step 3：处理 `<title>` 标签**

`DRAFT_RE` / `SUMMARY_RE` 旁边加 `TITLE_RE`：

```ts
const TITLE_RE = /<title>([\s\S]*?)<\/title>/i;
```

`extractDraft` 同时返回 `{ body, summary, title?, rest }`。`title` 通过 `onUseDraftAsReply` 的回调签名扩展（或 NewMatter 自己监听）传出去。

- [ ] **Step 4：孤儿 newmatter thread 清理**

在 ai store 初始化（构造 / Provider mount）时跑一次：

```ts
// 拉一次 drafts；找到所有 type === "proposal" && !thread_key 的草稿 id 集合 D；
// 扫 store 里所有 __newmatter__: 前缀的 threadKey；
// 抽出 draftId（threadKey.slice("__newmatter__:".length)），不在 D 里的 entry 删掉。
```

加到 Dashboard mount 的 useEffect 里，依赖空数组，只跑一次；fail-soft（失败仅 log，不阻断）。

- [ ] **Step 5：Commit**

```bash
git add web/src/pages/Dashboard.tsx
git commit -m "feat(web): ai store accepts mode + extracts <title> + cleans orphan newmatter threads"
```

---

## Phase 6：NewMatter 接入 AIPane 双栏

### Task 6.1：左右两栏布局 + AIPane

**Files:**
- Modify: [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx)

- [ ] **Step 1：布局重构**

把现有 `mx-auto max-w-4xl` 单栏改为 `md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,420px)] md:gap-6` 双栏；窄屏（< md）保持上下堆叠，AIPane 在下方。

- [ ] **Step 2：挂 AIPane**

```tsx
<AIPane
  mode="new-matter"
  matter_id="_new_matter_"
  threadKey={`__newmatter__:${draftId ?? "tmp"}`}
  threadTitle={title || "新讨论"}
  hasReplyDraft={false}
  onUseDraftAsReply={handleAIDraft}
/>
```

注意：`draftId` 在 useDraftAutosave 第一次保存前是 null，用 `"tmp"` 占位；首次保存后 setDraftId 触发 AIPane re-render，threadKey 切到正式值（store 里这两个 key 的对话不同——这是 corner case）。

**简化方案**：在 NewMatter 进入时就预先 `createDraft()` 拿到稳定 draftId，再渲染 AIPane。这样 threadKey 从一开始就稳定。增加一次 API 调用，但避免 corner case；推荐采用。

- [ ] **Step 3：handleAIDraft 实现**

```tsx
const handleAIDraft = async (
  content: string,
  _replyTo: string,
  summary?: string,
  aiTitle?: string,    // 新增（来自 <title>）
): Promise<boolean> => {
  setBody(content);
  setBodyState(applyAIDraft(content));
  if (summary) setBodySummary(summary);  // 路径 A 复用 AI summary，跳过发布时再调
  if (aiTitle) {
    if (!title.trim()) {
      setTitle(aiTitle.trim());          // 用户没输入过才直接预填
    } else {
      setAiTitleSuggestion(aiTitle.trim());  // 否则只挂建议
    }
  }
  return true;
};
```

- [ ] **Step 4：标题输入框下方加 AI 建议**

```tsx
{aiTitleSuggestion && aiTitleSuggestion !== title && (
  <button
    type="button"
    onClick={() => { setTitle(aiTitleSuggestion); setAiTitleSuggestion(null); }}
    className="text-xs text-[var(--text-mute)] hover:text-[var(--accent)]"
  >
    AI 建议：{aiTitleSuggestion} · 点击采用
  </button>
)}
```

- [ ] **Step 5：summary 处理分支**

修改 `submit` 函数：

```tsx
let summary = bodySummary;  // 路径 A：AI 已给 summary 直接用
if (!summary) {
  // 路径 B：沿用现有"发布时再调一次 AI 生成 summary"逻辑
  // ... 现有 streamAIChat 调用
}
```

- [ ] **Step 6：Commit**

```bash
git add web/src/pages/NewMatter.tsx
git commit -m "feat(web): NewMatter two-column layout with AIPane integration"
```

---

### Task 6.2：维护 body_source + 接入质量门

**Files:**
- Modify: `web/src/pages/NewMatter.tsx`

- [ ] **Step 1：body_source state**

```tsx
const [bodyState, setBodyState] = useState<BodySourceState>({
  body_source: "manual",
});
```

`handleAIDraft` 已在 Task 6.1.Step 3 中调 `applyAIDraft`。

- [ ] **Step 2：Textarea onChange 接 onUserEdit**

```tsx
<Textarea
  value={body}
  onChange={(e) => {
    const next = e.target.value;
    setBody(next);
    setBodyState((s) => onUserEdit(s, next));
  }}
/>
```

- [ ] **Step 3：autosave payload 加字段**

`useDraftAutosave` 的 payload 函数里 `matter_payload` 加：

```tsx
body_source: bodyState.body_source,
body_source_snapshot: bodyState.body_source_snapshot,
```

- [ ] **Step 4：草稿恢复时还原 bodyState**

`fetchDrafts` 回来命中 candidate 后：

```tsx
const bs = (payload.body_source as BodySource) ?? "manual";
const snap = typeof payload.body_source_snapshot === "string"
  ? payload.body_source_snapshot
  : undefined;
setBodyState({ body_source: bs, body_source_snapshot: snap });
```

- [ ] **Step 5：submit 前接质量门**

```tsx
const finalSource = computeAtPublish(bodyState, body);
const gate = await confirmPublishQuality({
  bodySource: finalSource,
  blockedByAIBusy: !!ai.activeStream,
  busyTitle: ai.activeStream?.title,
});
if (gate === "cancel") return;
if (gate === "send_to_ai") {
  ai.setInput(threadKey, body);
  // AIPane 已经在 NewMatter 双栏里展开/可见，无需额外 setAiOpen
  return;
}
// gate === "go" → 继续原 createMatter，并把 finalSource 传进 initial_file.body_source
```

- [ ] **Step 6：窄屏 inline 引导**

在 body Textarea 上方加：

```tsx
{showWideHint && (
  <div className="md:hidden rounded-md bg-[var(--accent-bg)] p-2 text-xs">
    💬 AI 助手可以帮你起草——点右上角展开
    <button onClick={dismissHint}>×</button>
  </div>
)}
```

`showWideHint` 初值 = `!localStorage.getItem("pivot:newmatter:hint-dismissed")`，dismissHint 写 localStorage 并 setShowWideHint(false)。

- [ ] **Step 7：Commit**

```bash
git add web/src/pages/NewMatter.tsx
git commit -m "feat(web): NewMatter quality gate + body_source state machine + narrow-screen hint"
```

---

## Phase 7：Reply 路径接入质量门 + body_source

### Task 7.1：handleUseDraftAsReply 写入 ai + snapshot

**Files:**
- Modify: [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx)

- [ ] **Step 1：写入状态**

[MatterDetailPane.tsx:585](../../web/src/pages/MatterDetailPane.tsx#L585) 的 `handleUseDraftAsReply` 内：

```ts
const aiState = applyAIDraft(content);
const matter_payload = buildMatterPayload(
  pendingCreate.type,
  pendingCreate.quote,
  {
    summary: nextInitial.summary ?? "",
    body: content,
    // ... 既有字段
    body_source: aiState.body_source,
    body_source_snapshot: aiState.body_source_snapshot,
  },
);
```

`buildMatterPayload` 函数也要相应支持新字段（找到定义处加进去）。

- [ ] **Step 2：Commit**

```bash
git add web/src/pages/MatterDetailPane.tsx
git commit -m "feat(web): mark AI-generated reply drafts with body_source"
```

---

### Task 7.2：CreateFileForm Textarea 接 onUserEdit + 跳过 result/insight

**Files:**
- Modify: [web/src/components/matter/CreateFileDialog.tsx](../../web/src/components/matter/CreateFileDialog.tsx)

- [ ] **Step 1：FormState 加 body_source**

```ts
type FormState = {
  // ... 既有
  body_source: BodySource;
  body_source_snapshot?: string;
};
```

`initialFormState` 从 `initial?.body_source / body_source_snapshot` 恢复，缺省 manual / undefined。

- [ ] **Step 2：Textarea onChange**

```tsx
onChange={(e) => {
  const next = e.target.value;
  setForm((f) => ({
    ...f,
    body: next,
    ...onUserEdit(
      { body_source: f.body_source, body_source_snapshot: f.body_source_snapshot },
      next,
    ),
  }));
}}
```

- [ ] **Step 3：autosave payload 加字段**

CreateFileForm 内部触发 onSubmit 时传给上层；上层 `MatterDetailPane.tsx` 里的 onSubmit handler 把 body_source 写进 `matter_payload` 与 NewFileIn。

- [ ] **Step 4：submit 前按 context.type 分支接质量门**

```tsx
const isQualityGated = context.kind === "card" 
  || (context.kind === "page" && false);  
  // page 类型对应 result / insight，v1 跳过

if (isQualityGated) {
  const finalSource = computeAtPublish(
    { body_source: form.body_source, body_source_snapshot: form.body_source_snapshot },
    form.body,
  );
  const gate = await confirmPublishQuality({
    bodySource: finalSource,
    blockedByAIBusy: !!ai.activeStream,
    busyTitle: ai.activeStream?.title,
  });
  if (gate === "cancel") return;
  if (gate === "send_to_ai") {
    ai.setInput(threadKey, form.body);
    setAiOpen(true);
    return;
  }
  // gate === "go"：继续原 publish；body_source 落 NewFileIn.body_source = finalSource
}
// result / insight：直接 publish，body_source 不传
```

`useConfirmPublishQuality` hook 在 `MatterDetailPane.tsx` 持有；CreateFileForm 通过 props 接收 `confirmPublishQuality` 函数注入。

- [ ] **Step 5：Commit**

```bash
git add web/src/components/matter/CreateFileDialog.tsx
git commit -m "feat(web): CreateFileForm tracks body_source + invokes quality gate (think/act/verify only)"
```

---

### Task 7.3：MatterDetailPane 4 个发布入口接入

**Files:**
- Modify: [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx)

- [ ] **Step 1：挂 hook + dialog**

```tsx
const { dialog: qualityDialog, confirm: confirmPublishQuality } =
  useConfirmPublishQuality();
// ...
return (
  <div ...>
    {/* 既有 */}
    {qualityDialog}
  </div>
);
```

- [ ] **Step 2：把 confirmPublishQuality 传给 CreateFileForm**

通过 prop 注入。

- [ ] **Step 3：result / insight 入口确认不接**

[MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) 里 result / insight 走的是 `appendMatterResult` 和对应 form。**这两条路径不调 confirmPublishQuality**，body_source 不传——保持 v1 跳过承诺。

- [ ] **Step 4：手测**

```bash
cd web && npm run dev
```

走一遍：
- 在 matter 里 + think → 手打 → 发布 → 看到弹门 ✓
- AI 生成 think → 不改 → 发布 → 不弹 ✓
- AI 生成 → 大改 → 发布 → 弹门 ✓
- 顶部"生成 Result" → 手打 → 发布 → **不弹门** ✓

- [ ] **Step 5：Commit**

```bash
git add web/src/pages/MatterDetailPane.tsx
git commit -m "feat(web): wire quality gate into 4 reply publish paths (skip result/insight)"
```

---

## Phase 8：AI 失败兜底

### Task 8.1：流错 / 超时 / 空 draft 的 UI 处理

**Files:**
- Modify: [web/src/components/AIPane.tsx](../../web/src/components/AIPane.tsx)（已有部分错误处理）
- Modify: [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx)（ai store 错误传播）

- [ ] **Step 1：定位现有错误处理**

`ai.sendMessage` 内部已经有 try/catch；找到对应位置，确认：

- 流错 → toast 现有逻辑保留；
- 解析 `<draft>` 时如果空 → **不**调 `onUseDraftAsReply`，toast「AI 没有给出可用草稿，请补充更多上下文后再试」；
- AI 中途断线 → 已写入的 partial body **不** persist 到 draft；body_source 不动。

- [ ] **Step 2：补充缺失的兜底**

按 design §二.5 五个场景对照逐个排查；缺哪个补哪个。重点：

- new-matter 模式 AI 返回 `<draft>` + `<summary>` 但缺 `<title>` → 仍调 `handleAIDraft(content, _, summary, undefined)`；NewMatter 不抢标题；
- AI 返回的 body 为空字符串 → 视作"空 draft"，不 apply。

- [ ] **Step 3：手测**

- 拔网线模拟流错；
- AI 返回故意填错（手动改 prompt 让 AI 不输出 `<draft>`）；
- 中途切到别的 thread 触发 abort。

- [ ] **Step 4：Commit**

```bash
git add web/src/pages/Dashboard.tsx web/src/components/AIPane.tsx
git commit -m "feat(web): AI failure fallback - body unchanged, no quality gate trigger"
```

---

## Phase 9：回归与端到端验证

### Task 9.1：测试矩阵（手测）

按 design §六.2 逐条跑。打勾下面 13 项：

- [ ] NewMatter：默认进页，AIPane 已展开（PC），无"起点帖子"卡片
- [ ] NewMatter：和 AI 聊后点"生成草稿" → 正文/标题/summary 均预填
- [ ] NewMatter：标题已手动输入时，AI 给出 title 不覆盖、出"AI 建议"提示
- [ ] NewMatter：纯手打正文 → 点发布 → 弹质量门
- [ ] NewMatter：质量门点"强行发布" → 创建成功，post frontmatter `body_source: manual`
- [ ] NewMatter：质量门点"发送给 AI 助手" → AIPane 输入框已填 body，未自动发送
- [ ] Reply（think）：AI 生成草稿不改 → 发布 → 不弹门，frontmatter `body_source: ai`
- [ ] Reply：AI 生成后小改（相似度 ≥ 0.5）→ 发布 → 不弹门，frontmatter `body_source: ai`
- [ ] Reply：AI 生成后大改（相似度 < 0.5）→ 发布 → 弹门
- [ ] Reply：纯手打 → 发布 → 弹门
- [ ] Reply：刷新页面后草稿恢复，body_source 状态正确
- [ ] **粘贴绕过**：手动状态下把任意 AI 风格长文粘进 body → 仍为 manual → 仍弹门
- [ ] Comment：发评论 → **不弹门**
- [ ] **result / insight**：发布 → **不弹门**；落盘 frontmatter **不含** body_source 字段
- [ ] AI 流被其他 thread 占用时点"发送给 AI 助手" → 按钮文案变"加入 AI 队列"
- [ ] AI 流式失败（断网模拟）→ body 不变、不弹门、Toast 提示
- [ ] AI 返回空 `<draft>` → body 不变、不弹门、Toast 提示
- [ ] NewMatter 模式 AI 未给 `<title>` → body/summary 正常落、标题保持原样
- [ ] NewMatter 发布成功后跳转详情页 + 下次进入 NewMatter 时孤儿 `__newmatter__:` 会话已清理
- [ ] 质量门点取消 → 不变更状态 / 草稿保留 / 可再次点发布
- [ ] 窄屏（DevTools < md）首次进入 NewMatter → inline 引导出现 → 关闭后下次不再出

### Task 9.2：自动化跑通

- [ ] **Step 1：后端测试全跑**

```bash
uv run pytest server/tests -q
```

- [ ] **Step 2：前端 typecheck + 单测**

```bash
cd web && npm run typecheck
cd web && npx vitest run
```

- [ ] **Step 3：build**

```bash
cd web && npm run build
```

任一失败即停下查根因，不绕过。

---

## Phase 10：合入

### Task 10.1：自查 + PR

- [ ] **Step 1：复审 commit 历史**

```bash
git log --oneline main..HEAD
```

期望看到约 12-15 条原子化 commit，每条对应一个 Task。

- [ ] **Step 2：rebase main 解冲突（如有）**

```bash
git fetch origin main
git rebase origin/main
```

- [ ] **Step 3：开 PR**

```bash
gh pr create --title "feat: publish AI rules - quality gate + NewMatter AI assistant" \
  --body "$(cat <<'EOF'
## Summary
- 新 matter 第一篇文档接入 AIPane（new-matter 模式 + 默认展开 / 窄屏收起带引导）
- 新增"未经 AI 协作发布前弹质量门"机制（公用 PublishQualityConfirmDialog + useConfirmPublishQuality hook）
- 引入 body_source 单向状态机（仅 AI <draft> 能升级；用户编辑只能降级）贯穿 draft + post frontmatter
- 范围：NewMatter + think/act/verify；result/insight/comment 不在 v1 范围
- 后端 chat_matter 增加 mode 参数路由 prompt（工具集不变）

## Test plan
- [ ] 后端 pytest 全绿
- [ ] 前端 vitest + typecheck + build 全绿
- [ ] design §六.2 手测矩阵全部打勾（21 项）

依据：AI-docs/designs/2026-04-28-publish-ai-rules-design.md
EOF
)"
```

---

## 附：实施期间易踩的坑

1. **AI store 的 threadKey 切换陷阱（Task 6.1.Step 2）**：建议进入 NewMatter 立即 `createDraft()` 拿稳定 draftId，避免 `tmp` → `actual` 切换时 AIPane 对话丢失。
2. **`<title>` 可选性**：AI 不一定输出 `<title>`，所有调用方必须按 `aiTitle ?? undefined` 处理；不要 require。
3. **bodyState 与 body 的同步**：所有改 body 的地方都要同时调 `applyAIDraft` 或 `onUserEdit`，否则状态机失真——优先用一个 `setBodyAndState(next, source)` 包装函数避免遗漏。
4. **post frontmatter 字段顺序**：[server/posts.py](../../server/posts.py) 里 yaml dump 默认按字典顺序排，`body_source` 字段会出现在 `author` / `created` 等中间。如果团队对 frontmatter 字段顺序敏感（git diff 可读性），考虑显式写 yaml key 顺序。
5. **AI 流错时 partial body 处理**：`ai.sendMessage` 当前会把已积累的 token 显示出来。流错时确保**不**调 `onUseDraftAsReply` 把这段 partial 写入草稿——只有 finish_reason === "stop" 且解析成功的 `<draft>` 才能 apply。
6. **`__newmatter__:` 孤儿清理时机**：必须在 Dashboard 首次 mount 时跑一次，而不是每次进 NewMatter 跑——后者会误删当前正在用的会话。
