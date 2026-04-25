# Matter 迁移 · 非核心实现偏离记录

凡后端 P1 / P2 / P4 与前端 P3 的实现过程中，**非核心实现细节**未完全按 `pivot-product.md` / `pivot-interface.md` 落地的，按下格式登记。

核心变更（见 `matter-implementation-plan.md` "核心变更评审门"）必须先评审后动手，不在此处记录。

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

- **matter index `comments[].mentions` 字段格式：注册用户 pinyin / 未注册 open_id 兜底**
  - 原文档要求：`pivot-product.md §八.2` 示例里 `mentions: [liuyu]` —— 列在评论里的 mention 用 pinyin 形式
  - 实际实现：评论入 index 时 `_resolve_mentions_for_index` 把前端传入的 open_id 列表逐项解析：注册用户（`users` 表里有 pinyin）落 pinyin，与同文件里 `creator / owner` 同格式；解析不到 pinyin（仅在 contacts 表里、还未登录 Pivot 的飞书联系人）则保留 open_id 兜底。通知发送一侧仍用原始 open_id 调飞书 API，不受影响
  - 原因：spec 示例隐含"全员都有 pinyin"的简化前提；真实数据里 mention 目标可能是飞书通讯录里没登录过 Pivot 的人，他们没有 pinyin 可用，硬转换会丢身份。"已注册转 pinyin、未注册留 open_id" 是把"事实身份"诚实落到 yaml 上的折中——多数情况 AI 直读 pinyin 可读，少数兜底 open_id 不丢人

- **matter index `comments[].author` 字段在实现里有，spec §八.3 未列**
  - 原文档要求：`pivot-product.md §八.3` 评论字段说明只列 `created_at / body / mentions`
  - 实际实现：`matter_index._canonical_comment` 写入时把 `author = user.pinyin` 也落到每条评论上（C1 集成测试产物可见）
  - 原因：多人系统里评论必须可追溯到作者，spec 例子里隐含的"作者由上下文推断"在多人场景成立不了。`author` 由后端按当前登录用户兜底写入，前端无需传——属于 spec 文档疏漏，实现走的是事实上的正确路径。建议邓柯在 §八.3 补字段说明而非删字段

- **P4 `verify.verifications[].target` 跨 matter refer[] 白名单 fallback**
  - 原文档要求：`pivot-product.md §九.4` 规定 "verify 验证和评价行动"、每个 `act` 给出判断结果——即 target 语义上是"本事项内被验证的 act"；文档**未明示** target 可以跨 matter
  - 实际实现：`server/matter_validator.py::_validate_verify_shape` 对每条 `verifications[].target` 走两级判定——
    1. target 在本 matter timeline 存在且 `type=act` → 通过
    2. target 在当前 item 的 `refer[]` 里 → 通过（跨 matter 白名单，纯函数 validator 不读其他 matter 文件的 type，信任客户端主动声明）
    3. 否则拒绝（`verification_target_not_found` / `verification_target_not_act`）
  - 原因：支持"matter B 的 verify 覆盖 matter A 里某个 act 的完成情况"这类跨事项协作场景；`pivot-product.md §八.3` 的 `refer` 字段本身是"其他补充参考文件"的泛语义，并未排除 act；跨 matter 类型校验靠 refer[] 白名单交给客户端显式声明是合适的安全阀
  - 兼容面：本 matter 内的 verify 行为完全按 `pivot-product.md §九.4` 落；跨 matter 用法是严格受限的扩展路径——必须先把目标路径放进同一 item 的 `refer[]` 才能引用
