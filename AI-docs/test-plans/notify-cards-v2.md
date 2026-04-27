# 通知卡片测试用例

> 对应 merge commit `3008d08`，分支 `feature/notify-mention-migration-v2`。
> 覆盖 `server/notify.py`、`server/publish.py`、`server/tests/test_notify.py`、`web/src/pages/ThreadDetailPane.tsx`、`server/app.py`、`.gitignore`。

## 一、背景

`team-pivot-web` 是一个以 Git / Markdown 为后端的团队讨论工作台。当用户在 Web 端**发新讨论**、**回复**、或**单独 @ 某人**时，服务端通过飞书机器人把事件推送成**交互式卡片**到团队群里，并给被 @ 者另发一条私聊卡片，让团队不必回到浏览器就能看到讨论进展并一键跳转到具体帖子。

本次迭代的目标是让飞书群里的卡片成为**事件通知 + 内容预览 + 快速跳转**三合一的信息单元，最大化减少"必须点开 Web 才能判断要不要关注"的场景。

主要干系人：Web 端发布者、群里其他成员（阅读者）、被 @ 者。

## 二、本次涉及的卡片与关键行为

### 1. 新讨论群卡片（📨，蓝色）
- Header：`📨 来自 {作者} 的新讨论主题通知：{标题}`
- Body 6 字段（单段落、`<br>` 连接）：项目 / 主题（真实标题）/ 操作 / 文件 / 时间
- 可选 `**说明**：...` 行（**位于时间下方**，空白与换行折叠成单行）
- 可选 `**内容**：...` 行（正文前 200 字，剥离 markdown，超长以 `...` 结尾）
- 若有 @ 人：@at 标签置于最顶；群卡片下方同时给每个被 @ 者私聊 DM 卡片
- 折叠面板 `📂 讨论目录（N 篇帖子）`：列出本 thread 所有帖子，高亮当前新帖
- 按钮文本 `去 Web 查看`，URL 为**帖子级 deep link**（`?post=<anchor>#post-<anchor>`）

### 2. 回复群卡片（📩，绿色）
- Header：`📩 来自 {回复者} 的新回复通知：{所属 thread 标题}`
- Body、说明、内容、@ 规则与新讨论一致
- 按钮文本 `查看讨论`，URL 指向当前回复的 anchor

### 3. 独立 @ 群卡片（橙色）
- 用于单独给已存在的帖子补 @
- Header：`提及：{thread 标题}`
- Body：@at 行 + `{作者} 提及了以上成员` + 项目 / 主题 / 帖子 / 说明 / 时间 + `相关内容` 摘录
- 按钮文本 `查看该帖子`

### 4. @ 私聊 DM 卡片（橙色）
- Header：`有人 @ 了你`
- Body：`{作者} 在「{thread 标题}」的 {发起讨论 / 回复讨论 / 提及} 中 @ 了你`，附帖子、说明、相关内容
- 按钮跳转到帖子级 deep link

### 5. 视觉/结构约束
- `card.schema = "2.0"`，`wide_screen_mode = true`
- `body.padding = "4px 16px 12px 16px"`（顶部留白收紧）
- `body.elements` 顺序固定：`mar1kdown` → (可选 `collapsible_panel`) → `button`
- 卡片不应出现 `**作者**：`、`**摘要**：` 行
- 行间分隔只用 `<br>`，整块 markdown 不出现 `\n\n`（避免飞书渲染多段落）

---

## 三、前置条件

1. `team-pivot-web` 服务端运行于 `http://127.0.0.1:8000`
2. 飞书机器人在目标测试群、`FEISHU_APP_ID` / `APP_SECRET` 有效
3. 账号已完成 profile setup
4. `general` 分类存在

---

## 四、新讨论卡片用例（📨 / blue）

### TC-T01 · 基础新讨论，无 @、无说明、短正文

**输入**
- 分类：`general`　标题：`TC-T01 基础`　正文：`这是一段普通正文。`

**期望**
- Header：`📨 来自 {作者} 的新讨论主题通知：TC-T01 基础`
- 模板：蓝色
- Body：
  ```
  **项目**：general
  **主题**：TC-T01 基础
  **操作**：{作者} 发起了新讨论
  **文件**：001_xxx_proposal_xxxxxx.md
  **时间**：YYYY-MM-DD HH:MM
  **内容**：这是一段普通正文。
  ```
- 按钮文本 `去 Web 查看`，URL 含 `?post=001_..#post-001_..`

### TC-T02 · 正文含 markdown，预览应为纯文本

**输入正文**

````markdown
# 一级标题

**加粗** 和 *斜体* 与 `行内代码`，[链接](http://x)，![图片](http://y.png)。

- 列表项 1
- 列表项 2

> 引用

```python
print("代码块")
```
````

**期望 · 内容行**
- 不出现：`**`、`*`、`` ` ``、`#`、`[`、`]`、`(http`、`![`、`>`、代码块内文本 `print("代码块")`
- 出现：`加粗`、`斜体`、`行内代码`、`链接`、`图片`、`列表项 1`、`列表项 2`、`引用`
- 换行被压成空格

### TC-T03 · 正文超长，截断到 200 字 + `...`

**输入**：正文 300 个中文字符
**期望**：内容行形如 `**内容**：{200 字}...`，总长度 203

### TC-T04 · 空正文，省略内容行

**输入**：正文留空
**期望**：body 仅 5 行（项目/主题/操作/文件/时间），无 `**内容**：`

### TC-T05 · Header 只使用接口传入的标题

**输入**：标题 `我填写的标题`　正文 `# 正文自己的标题\n\n内容`
**期望**：Header = `📨 来自 {作者} 的新讨论主题通知：我填写的标题`（Header 直接使用 `title` 参数，不读正文 H1）

### TC-T06 · 新讨论 + @mention + 说明

**输入**：@ 1 人，说明填 `请这周回复`
**期望（群卡片）**
- Body 顺序：
  ```
  <at user_id="ou_xxx"></at>
  **项目**：general
  **主题**：…
  **操作**：…
  **文件**：…
  **时间**：…
  **说明**：请这周回复
  **内容**：…
  ```
- 说明出现在时间下方
- 被 @ 的人收到独立 DM 卡片（Header `有人 @ 了你`，lead 含 `发起讨论 中 @ 了你`）

### TC-T07 · 说明多行压缩为单行

**输入**：说明填 `请看\n\n\n   一下   \n重要事项`
**期望**：卡片内实际渲染 `**说明**：请看 一下 重要事项`（空白折叠，无段落断裂）

---

## 五、回复卡片用例（📩 / green）

### TC-R01 · 基础回复

**输入**：回复 `这是一条普通回复。`
**期望**
- Header：`📩 来自 {回复者} 的新回复通知：{所属 thread 标题}`
- 模板：绿色
- Body 6 行 + 内容行
- 按钮文本 `查看讨论`，URL 指向当前回复 anchor

### TC-R02 · 回复含 markdown 且超长

验证与 TC-T02、TC-T03 相同的剥离与截断规则

### TC-R03 · 回复 + @

同 TC-T06，说明位置在时间下方，DM lead 行含 `回复讨论 中 @ 了你`

---

## 六、讨论目录折叠面板

### TC-D01 · 多帖显示面板

**场景**：在已有 ≥ 2 篇帖子的讨论里再回复
**期望**
- `body.elements` 含 `collapsible_panel`，标题 `📂 讨论目录（N 篇帖子）`，默认折叠
- 展开后每条形如 `📄 **{filename}** · {author} · {YYYY-MM-DD}`
- 当前帖子一行 `<font color='blue'>🔷 …</font>`

### TC-D02 · 单帖也显示面板

首篇新讨论即出现面板，标题 `📂 讨论目录（1 篇帖子）`，唯一条目高亮

---

## 七、视觉 / 布局断言

| 断言点 | 期望值 |
|--------|--------|
| `card.schema` | `"2.0"` |
| `card.config.wide_screen_mode` | `true` |
| `card.body.padding` | `"4px 16px 12px 16px"` |
| `body.elements` 顺序 | `markdown` → (optional `collapsible_panel`) → `button` |
| 卡片中不应出现 | `**作者**：` / `**摘要**：` |
| 行间分隔 | `<br>` 单段落，不得出现 `\n\n` |

---

## 八、自动化测试覆盖（已就位，17 passed）

| 测试名 | 对应用例 |
|--------|----------|
| `test_thread_card_shape_6_fields` | TC-T01 |
| `test_reply_card_header_carries_author` | TC-R01 |
| `test_card_no_author_row` | 七、无 **作者** 行 |
| `test_card_omits_body_preview_when_no_body` | TC-T04 |
| `test_thread_card_body_preview_strips_markdown` | TC-T02 |
| `test_reply_card_body_preview_truncates_at_200` | TC-T03 / TC-R02 |
| `test_mention_comments_collapsed_to_single_line` | TC-T07 |
| `test_mention_comments_rendered_below_time_row` | TC-T06 行序 |
| `test_card_body_has_tight_top_padding` | 七、padding |
| `test_standalone_mention_card_structure` | 二、3 独立 @ 卡片 |
| `test_mention_dm_card_structure` | 二、4 DM 卡片 |
| `test_feishu_notifier_uses_auth_entry_thread_url` | URL 构造 |
| `test_feishu_notifier_post_url_carries_anchor` | 帖子级 deep link |
| `test_build_thread_directory_highlights_current_post` | TC-D01 / TC-D02 高亮 |
| `test_thread_card_includes_directory_panel` | TC-D01 |
| `test_thread_card_omits_directory_panel_when_empty` | 无 workspace 时省略面板 |
| `test_noop_notifier_silent` | NoOp 接口契约 |

```bash
python -m pytest server/tests/test_notify.py -q
```
