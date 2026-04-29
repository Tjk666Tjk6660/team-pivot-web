# Pivot MCP 增加 create_matter 工具

| 项 | 值 |
|---|---|
| 文件 | `AI-docs/designs/2026-04-28-mcp-create-matter-design.md` |
| 创建日期 | 2026-04-28 |
| 状态 | 草案，待审核 |
| 范围 | 单一 PR，仅 MCP 层改动；后端无变更 |
| 关联 | Matter「新需求：Pivot MCP 应支持创建新 Matter」（dengke 提案） |

---

## 0. 需求概览

### 0.1 这次要做什么

Pivot MCP 当前已有 5 个工具（`resolve_context` / `list_matters` / `get_matter` / `read_files` / `create_file`），可以读 Matter、向已有 Matter 追加 timeline，但**缺一个创建新 Matter 的工具**。

这导致一个体验断点：外部 AI 终端可以协助用户讨论新需求、起草内容，但用户确认后 AI 不能通过 MCP 直接发布为新 Matter，只能让用户手动复制粘贴或绕到 HTTP API。

本期补这个工具，把"AI 协助起草 → 用户确认 → 直接发布为新 Matter"这条路径打通。

### 0.2 怎么做（解决方案主线）

- **不新增后端接口**：后端 `POST /api/matters` 已存在（Web 端创建 Matter 用的就是它），MCP 这一层只做薄适配
- **MCP 工具薄到极致**：HTTP 转发 + 错误码映射 + 拼装 `view_url` 与 `summary_for_ai`，与现有 `create_file` 同构
- **协议与 `create_file` 完全一致**：调用前 AI 必须把草稿展示给用户确认；调用后必须把 `summary_for_ai` 原样转述给用户
- **入参对外平铺、对内嵌套**：对外 AI 看到扁平 schema 易写对；MCP 内部组装成后端要求的嵌套形态

### 0.3 各部分在哪一章

| 主题 | 章节 |
|---|---|
| 决策一览 | §1 |
| 调用流程图 | §2 |
| 工具入参 / 出参字段表 | §3 |
| 用户确认协议 | §4 |
| 复用的后端接口 | §5 |
| 错误处理 | §6 |
| matter_id 与重名 | §7 |
| 不在范围内 | §8 |
| 验收 checklist | §9 |

---

## 1. 关键决策一览

| 项 | 决策 |
|---|---|
| 工具名 | `create_matter` |
| 后端接口 | 完全复用现有 `POST /api/matters`，不新增、不改动 |
| 入参形状 | MCP 对外平铺（`category` / `title` / `type` / `summary` / `body` / `owner`），内部转换为后端嵌套结构 |
| 用户确认 | 工具描述中明示"必须先在聊天窗口展示草稿、用户确认后再调"，与 `create_file` 协议一致 |
| 状态迁移 | 本工具**不**承担状态切换；新 Matter 默认进入 `planning`，要切 `executing` 等用户后续走 `create_file` + `status_change` |
| matter_id 冲突 | 后端 409 直透传，不在 MCP 做自动加后缀等 fallback |
| owner | 可选；为空时由后端按现有规则填（创建者拼音） |
| `summary_for_ai` | 必返回；AI 客户端按协议原样转述给用户 |
| 鉴权 | 沿用 MCP 现有 PAT 链路，无新增 |

---

## 2. 调用流程

```
   ┌────────────────────┐
   │ AI 起草新 Matter    │
   │ (title/summary/body)│
   └──────────┬─────────┘
              │
              ▼
   ┌──────────────────────────────────┐
   │ AI 在聊天窗口把草稿展示给用户：     │
   │ category + title + summary + body  │
   └──────────┬───────────────────────┘
              │
              ▼
       ┌──────────────┐    否    ┌──────────┐
       │ 用户确认?     │────────▶│ 不调用    │
       └──────┬───────┘          └──────────┘
              │ 是
              ▼
   ┌──────────────────────────────┐
   │ AI 调 MCP create_matter      │
   │ (此处会有第二层工具确认对话框) │
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ MCP 把扁平入参转嵌套，         │
   │ 转发给后端 POST /api/matters  │
   └──────────┬───────────────────┘
              │
       ┌──────┴───────┐
       │              │
     成功            错误
       │              │
       ▼              ▼
 ┌──────────────┐  ┌────────────────────────────┐
 │ MCP 拼装：    │  │ 按 §6 映射为 error / errors │
 │  view_url     │  │ AI 据此让用户改正后重试      │
 │  summary_for_ai│ └────────────────────────────┘
 └──────┬───────┘
        │
        ▼
 ┌──────────────────────────────┐
 │ AI 把 summary_for_ai 原样转   │
 │ 述给用户，附 view_url         │
 └──────────────────────────────┘
```

---

## 3. 工具入参 / 出参

### 3.1 入参（MCP 对外）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| category | 字符串 | 是 | Matter 所属类别，例如 `Pivot`；用于落盘到 `discussions/<category>/<slug>/` |
| title | 字符串 | 是 | Matter 标题（最长 200） |
| type | 字符串 | 是 | 第一篇 timeline 文件类型，建议默认 `think`，也可为 `act` / `result` 等已支持类型 |
| summary | 字符串 | 是 | 该 Matter 的摘要（最长 500），用于列表展示 |
| body | 字符串 | 是 | 第一篇文件正文（Markdown，最长 50000） |
| owner | 字符串 | 否 | 责任人；空缺时后端按现有规则填（默认创建者拼音） |

**形状取舍**：后端 `POST /api/matters` 实际接收的是嵌套结构（`{category, title, initial_file{type, summary, body, owner}}`），但对外部 AI 暴露平铺 schema 更易写对；MCP 内部完成扁平 → 嵌套的转换。

### 3.2 出参（成功）

| 字段 | 类型 | 说明 |
|---|---|---|
| matter_id | 字符串 | 后端生成的 Matter id |
| category | 字符串 | 回显入参 category |
| title | 字符串 | 回显入参 title |
| view_url | 字符串 | 形如 `https://pivot.enclaws.com/m/<matter_id>` 的 Web 详情页地址，已用 web_base_url 拼装 |
| first_file | 字符串 | 第一篇 timeline 文件的相对路径（如 `discussions/Pivot/<slug>/001_xxx_think_xxx.md`） |
| summary_for_ai | 字符串 | 适合 AI 原样转述给用户的确认文案，例如 "✅ 已创建 Matter「{title}」，点这里查看：{view_url}" |

### 3.3 出参（校验失败）

后端 422 不上抛为异常，作为数据返回，让 AI 拿到字段级错误信息后引导用户修正重试：

| 字段 | 类型 | 说明 |
|---|---|---|
| errors | 对象 | 字段级错误，含 `code` / `field` / `message`，与现有 `create_file` 422 处理形态一致 |

---

## 4. 用户确认协议

`create_matter` 与现有 `create_file` 共享同一套调用前协议，写在工具的 description 里，对外部 AI 起约束作用：

1. **调用前必须先展示草稿**：AI 必须在聊天窗口里以自然语言把 `category` / `title` / `summary` / `body` 完整展示给用户
2. **必须等用户明确同意**（"ok"、"go"、"发吧"等）后再调 `create_matter`
3. **工具调用对话框是最后一道确认**，不是第一道——不允许跳过聊天确认直接弹工具确认
4. **调用成功后必须原样转述** `summary_for_ai`，不要重写、不要省略 `view_url`

理由：`create_matter` 直接生成正式 Matter，覆盖面比 `create_file` 还大；用户确认环节不可省。

---

## 5. 用到的后端接口

### 5.1 复用接口

| 项 | 说明 |
|---|---|
| 接口大类 | "Matter 创建"——后端已有，Web 端创建 Matter 走的就是这个 |
| 鉴权 | 沿用调用方 PAT；与 MCP 入站请求所用 token 一致 |
| 入参类别 | category、title、initial_file（type / summary / body / owner / comments） |
| 返回类别 | matter（含 id / title / current_status / 时间戳）、initial_timeline_item、matter_id、file 路径 |
| 已实现的错误 | 401（未登录）、403（无权限）、409（matter 重名）、422（字段校验 / type 限制 / 状态机）|
| 落盘动作 | 创建 Matter 目录、生成 index、写入第一篇 timeline 文件、刷新 creator/owner/created_at/updated_at |

### 5.2 不新增任何后端接口

后端不动，所有写入逻辑共用同一条链路（Web / HTTP API / MCP 三入口数据模型一致）。

---

## 6. 错误处理

| 场景 | 后端来源 | MCP 表现 | AI 应该怎么做 |
|---|---|---|---|
| token 无效 / 已过期 | 401 | `error{401, invalid_token}` | 提示用户重登或换 PAT |
| 无创建权限 | 403 | `error{403, forbidden}` | 提示用户没有权限，停止重试 |
| Matter 标题重名 | 409 matter_already_exists | `error{409, matter_already_exists}` | 让用户改 title，重试 |
| category 不存在 / title 空 / body 空 / type 不合法 | 422 | `{errors: {code, field, message}}` | 按 field 引导用户修正后重试 |
| 网络 / 后端异常 | 5xx | `error{5xx, <detail>}` | 提示用户后端异常，建议稍后重试 |

**核心约束**：MCP 不向上透传底层 stack trace 字符串；所有错误必须落到上表中的某一格。

---

## 7. matter_id 与重名

- `matter_id` 完全由后端生成，规则与现有 Web 端创建一致（基于 title 的 slug）
- 重名时后端返回 409 `matter_already_exists`，MCP 直接透传
- **不在 MCP 层做 fallback**（如自动加 `-2` 后缀）：MCP 不创造命名规则，由 AI 拿到错误后引导用户改 title 重试
- 当前内部使用规模约 10 人，重名概率低，不需要防冲突的特殊设计

---

## 8. 不在范围内

| 不做项 | 原因 |
|---|---|
| 在 MCP 层重新实现 Matter 创建写入 | 与 dengke 提案一致：必须复用后端，三入口数据模型保持一致 |
| 改 `POST /api/matters` 的现有入参 / 出参形状 | 已在 Web 端用，改动会引入跨端协调成本；MCP 自己做扁平 ↔ 嵌套适配即可 |
| 改 `matter_id` 生成规则、加冲突 fallback | 见 §7；当前规模不需要 |
| 在 `create_matter` 里同时切状态 | 新 Matter 必然落 `planning`；后续切状态走 `create_file` + `status_change`，与现有协议一致 |
| 新工具 `create_matter` 之外，新增其他 MCP 工具 | 本期范围严格限定为补这一个工具 |

---

## 9. 验收 checklist

实现完成后逐项验证：

- [ ] MCP 工具列表中出现 `create_matter`，描述明确包含用户确认协议
- [ ] 外部 AI 终端可通过 MCP 创建 `category='Pivot'` 的新 Matter
- [ ] 入参支持 `title` / `summary` / `body` / `type` / `owner`，平铺形状
- [ ] 未指定 `owner` 时由后端按现有规则填充
- [ ] 创建成功后 Matter 列表中出现新 Matter，详情页可正常打开
- [ ] 新 Matter 的 index 与第一篇 timeline 文件均正确生成
- [ ] 返回 `matter_id` / `category` / `title` / `view_url` / `first_file` / `summary_for_ai`
- [ ] AI 客户端可把 `summary_for_ai` 原样转述
- [ ] title 重名时返回结构化 `error{409, matter_already_exists}`，AI 可据此引导用户重试
- [ ] body 空、title 空、category 非法等返回 `{errors: ...}`，AI 可据此修正
- [ ] 与现有 `create_file` 工具风格 / 错误协议一致
- [ ] 后端 `POST /api/matters` 与 Web 端行为完全一致（未做任何后端改动）
