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
  - 原文档要求：`pivot-interface.md §Matter API 草案` 只列了 `/files` 和 `/result` 两个写入入口，未列评论端点
  - 实际实现：新增 `POST /api/matters/{matter_id}/comments`，请求体 `{target_file, body, mentions?}`；评论挂到 `timeline[i].comments[]`；不刷新 `matter.updated_at`；target 不存在返回 `404 comment_target_not_found`
  - 原因：`pivot-product.md §八` 示例规定 `comments[]` **嵌在每个 timeline item 下**（per-item），与 main 分支老 `POST /api/threads/{c}/{s}/mentions`（`server/api/discussions.py:199-218`）写到 thread INDEX **顶层 `timeline[]` 事件条目**的形态不兼容——
    - 数据位置：matter 写 `timeline[i].comments[]`（嵌套），thread 写顶层 `timeline[]`（flat log）
    - 调用时机：matter 任何时候都能给某篇文件加评论；thread `/mentions` 是"不新开帖子就 @ 别人"的特化场景
    - 必选 @ 人：thread `/mentions` 强制至少一个 `open_ids`（`if not mention_open_ids: raise`）；matter `comments` 的 `mentions` 可选
    - 三条都不同，无法复用老端点或老 `append_standalone_mention` 函数
  - 兼容面：老 `POST /api/threads/{c}/{s}/mentions` 在 feat/pivot-matter 分支上**完全不动**，thread 模型仍可调；matter 评论带 `mentions` 时复用既有 `notify_standalone_mention` 方法（不新增 notifier 方法）
  - P5 规划：`/api/threads/{c}/{s}/mentions` 属老 thread 接口，随"老 thread 接口统一下线"一并清理

- **P4.6 drafts 表新增 `matter_payload_json` 列**
  - 原文档要求：`pivot-interface.md §drafts` 请求体只列 `type / title / category / body_md / thread_key / mentions / reply_to / references`；`server/db.py SCHEMA` 里 drafts 表不含 matter 专属字段
  - 实际实现：`server/db.py::_migrate` 加一条幂等 `ALTER TABLE drafts ADD COLUMN matter_payload_json TEXT`；`Draft` / `DraftRepo` / `CreateDraftBody` / `UpdateDraftBody` / `_to_dict` 同步贯通；`pivot-interface.md` 已补接口字段
  - 原因：matter UI 要复用 main 分支的 autosave + publishDraft 规范，而 matter 结构化字段（`doc_type / summary / owner / quote / refer / verifications / outcome / status_change`）无处安放。选择单列 JSON：`type` 枚举不动（CHECK 不 drop、表不 rebuild、老数据零迁移）；矩阵查询路径不碰 JSON 内字段，索引效率无影响
  - 口径：`type` 仍 `proposal | reply`（语义：首篇 / 追加），matter 与老 thread 草稿共用 drafts 表，靠 `matter_payload_json` 是否非空判定

- **P4.6 `POST /api/drafts/{id}/publish` 契约收紧**
  - 原文档要求：`pivot-interface.md §POST /api/drafts/{id}/publish` 只说"发布草稿为正式 proposal 或 reply"
  - 实际实现：matter 迁移后，该接口**只服务 matter 发布路径**。`matter_payload` 为空直接 `400 matter_payload_required`，不再回落到 `publish_proposal / publish_reply`；`matter_payload` 非空按 `type=proposal|reply` 分发到 `publish_matter_create / publish_matter_append`
  - 原因：index 数据迁移后，老 `{slug}-discuss.index.yaml` 已不存在，继续走老分发会写半路废弃格式，造成新老割裂。历史 legacy 草稿由用户 PATCH 补全 `matter_payload` 后再重试
  - 兼容面：`POST /api/threads` / `POST /api/threads/{c}/{s}/posts` 直发接口不动，旧调用方仍可绕过草稿发老 thread（P5 再清理）；`pivot-interface.md` 已补错误码与新响应 shape 说明

- **P4.5 G 补遗：`_STATUS_LABEL` 替换为 matter 6 态 + `notify_status_change` 扩触发文件字段**
  - 原文档要求：P4.5 G 项目标是"复用现有 4 个 notifier 方法，补齐 matter 路径调用点"，当时没明确触发文件信息是否进卡片；`_STATUS_LABEL` 里还留着老 thread 5 态
  - 实际实现：
    1. `server/notify.py::_STATUS_LABEL` **替换**为 matter 6 态映射（`planning / executing / paused / finished / cancelled / reviewed` → 中文）。老 thread 5 态通过 `.get(k, k)` fallback 到原英文字符串（上线后老 thread 路径不会再调用，fallback 只是防御）
    2. `Notifier.notify_status_change` 协议扩可选参数 `trigger_type / trigger_summary / trigger_filename`；`FeishuNotifier` 在 matter 场景（`trigger_filename` 非空）下：正文多一行 `**触发**：<type> — <summary>`，按钮链接切到 `_matter_url(matter_id)` 走 `/m/<matter_id>`；老 thread 路径不传新参数，行为不变
    3. `publish.py::publish_matter_append` 在 status_change 触发时把 `item.type / item.summary / item.file` 透传
  - 原因：matter 的状态迁移本就由特定文件触发（`pivot-product.md §三 / §九`），触发文件的 type + summary 比老 thread 的 `reason` 字段密度高；老 `_STATUS_LABEL` 只覆盖 5 老态会让卡片显示半英文
  - 前端路由：P3 已用 `/m/:matter_id`（`web/src/App.tsx:33`），原 `_thread_url` 的 `/t/...` 路径在前端是 catch-all 归一到首页，matter 通知按钮必须走新 URL
