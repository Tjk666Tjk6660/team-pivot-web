# Matter 迁移 · 非核心实现偏离记录

凡后端 P1 / P2 / P4 与前端 P3 的实现过程中，**非核心实现细节**未完全按 `pivot-product.md` / `pivot-interface.md` 落地的，按下格式登记。

核心变更（见 `matter-migration-plan.md` "核心变更评审门"）必须先评审后动手，不在此处记录。

## 格式

```
- <阶段-任务> | 原文档要求: ... | 实际实现: ... | 原因: ...
```

## 记录

- **P1 status×type 矩阵 / `executing + result`**
  - 原文档要求：`pivot-product.md §五` — `executing` 下 `result` "只在事项准备正式结束时才允许创建"
  - 实际实现：executing 状态下随时允许创建 result（创建 result 即作为终态触发信号）
  - 原因：程序无法判定"准不准备结束"；result 本身就是终态信号，再加一道"准备度"校验既无法自动化也不增价值

- **P1 status×type 矩阵 / `reviewed`**
  - 原文档要求：`pivot-product.md §五` — reviewed "原则上不再新增任何文件"
  - 实际实现：reviewed 严格禁止任何新文件创建（writer 一律拒绝）
  - 原因："原则上"作为软约束对代码无指导意义；选择严格禁保证终态干净，如有补写诉求后续再评审放开

- **P2 `POST /api/matters` 请求体新增 `category`**
  - 原文档要求：`pivot-interface.md §POST /api/matters` 请求体只列 `title + initial_file`
  - 实际实现：请求体新增 `category`（与 `POST /api/threads` 同规则：支持中文、最长 20 字符、禁止路径危险字符）
  - 原因：磁盘布局仍为 `discussions/<category>/<slug>/`，创建 matter 时必须知道 category 才能落 MD。category 在 matter 模型里只作为磁盘分组标签，不参与语义

- **P2 `POST /api/matters` 响应新增 `matter_id` + `file` 便利字段**
  - 原文档要求：`pivot-interface.md §POST /api/matters` 返回只列 `matter` + `initial_timeline_item`
  - 实际实现：响应额外返回 `matter_id`（= `matter.id`）与 `file`（首个 timeline item 的完整路径）
  - 原因：前端直接使用，避免从 `matter.id` 和 `initial_timeline_item.file` 再抽一次

- **P2 新增 `POST /api/matters/{matter_id}/comments` 端点**
  - 原文档要求：`pivot-interface.md` 未列出独立评论端点
  - 实际实现：新增 `POST /api/matters/{matter_id}/comments`，请求体 `{target_file, body, mentions?}`，挂到 timeline item 的 `comments[]`；不刷新 `matter.updated_at`；target 不存在返回 `404 comment_target_not_found`
  - 原因：§八 示例里 `comments[]` 附着在每个 timeline item 上，需要一个独立入口追加；不新增端点就要把评论塞进 `/files` 语义，反而更混乱
