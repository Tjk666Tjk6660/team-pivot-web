# 失效文档需求 — 设计方案 v2

> 本文是 matter「新需求-作者在pivot中失效自己的文档」的设计方案 v2 评审稿,基于 dengke 001 需求 + liuyu 003 反馈整理。源自 timeline file `004_huangshengli_think_ce750f.md`。

## 修订摘要(相比 002 v1)

- **sensitive 从失效理由中移除**:失效语义收敛为"声明式撤回",不承担访问控制职责。sensitive 归入未来「帖子权限」项目;在权限体系上线前,误粘贴密钥/PII 走 admin 应急 redact 路径(独立紧急通道,不混入失效流程)。
- **可见性从三态简化为单一视图**:失效不参与可见性判断,所有对 matter 有访问权限的用户和 AI 均可见原文 + 失效元数据,仅 UI 渲染层标记"已失效(理由)"。访问权限由「帖子权限」单独控制。

底层概念调整:**失效是"声明式撤回",不是"删除式撤回"**。

## 一、设计原则

保持 Pivot timeline 不可篡改的核心前提下,提供"作者本人将自己已发布文档标记为已撤回"的能力。

**三条不变量:**

- 原文件不删除、不修改、不抹除
- 失效操作本身作为 timeline 上的可审计事件,与文件具有同等的不可篡改性
- 失效不影响 matter 状态机(`current_status` / `status_change` 历史)

**关键定位**:失效是声明式标签,不是隐藏机制;访问控制由「帖子权限」单独承接。

## 二、数据结构

### 2.1 文件项新增反写字段(4 个)

```yaml
- file: discussions/Pivot/xxx/003_dengke_act_abc.md
  type: act
  creator: dengke
  ...   # 原有字段不变
  # ↓ 反写字段
  invalidated: bool                              # 当前是否失效(权威)
  invalidated_at: <iso datetime>                 # 最近一次失效时间
  invalidated_reason: misposted | inaccurate     # 失效理由(2 值)
  invalidated_by: <pinyin>                       # 最近一次失效操作人
```

恢复后保留 `invalidated_at` / `invalidated_reason` / `invalidated_by`,仅翻转 `invalidated: true → false`。这三个字段含义变成"最近一次失效的元数据",再次失效时被新值覆盖。

### 2.2 失效 / 恢复事件项(新增 timeline entry 形态)

事件项是 timeline 上的一种**非文件型记录**,沿用现有 timeline event 的字段约定,但不在 `type` 枚举中:

```yaml
- creator: dengke                                  # 必填
  created_at: 2026-04-26T10:00:00+08:00            # 必填
  quote: <被操作文件 path>                         # 必填
  reason: misposted | inaccurate | restored        # 必填(3 值)
  summary: "误发,撤回此文档"                       # 可选自由说明
```

**reason 枚举共用,单字段同时编码"事件类型 + 具体原因":**

| reason 值 | 事件类型 | 系统反写 |
|---|---|---|
| `misposted` | 失效 | invalidated=true, invalidated_at=now, invalidated_reason=misposted, invalidated_by=creator |
| `inaccurate` | 失效 | 同上,reason=inaccurate |
| `restored` | 恢复 | invalidated=false(仅翻转 bool,其他三个字段保留) |

### 2.3 完整数据结构示例

下面是一个 matter index 完整示例,展示文件项、失效事件、恢复事件三者在 timeline 上的共存形态:

```yaml
matter_id: 示例-某 matter
title: 示例-某 matter
current_status: planning
created_at: 2026-04-25T21:00:00+08:00
updated_at: 2026-04-27T15:00:00+08:00

timeline:
  # ── 文件项 #1: 普通的 think,从未被失效 ─────────────────
  - file: discussions/Pivot/xxx/001_dengke_think_aaa.md
    type: think
    creator: dengke
    owner: dengke
    created_at: 2026-04-25T21:00:00+08:00
    summary: "初始想法"
    quote: null
    refer: []
    comments: []

  # ── 文件项 #2: 一度被失效又恢复的 act ───────────────────
  - file: discussions/Pivot/xxx/003_dengke_act_bbb.md
    type: act
    creator: dengke
    owner: dengke
    created_at: 2026-04-25T22:00:00+08:00
    summary: "推进登录回跳"
    quote: null
    refer: []
    # ↓ 反写字段:当前 invalidated=false,但保留最近一次失效的元数据
    invalidated: false
    invalidated_at: 2026-04-26T10:00:00+08:00
    invalidated_reason: misposted
    invalidated_by: dengke
    comments: []

  # ── 事件项 #1: 2026-04-26 dengke 失效了 003 ─────────────
  - creator: dengke
    created_at: 2026-04-26T10:00:00+08:00
    quote: discussions/Pivot/xxx/003_dengke_act_bbb.md
    reason: misposted
    summary: "误发,撤回此文档"

  # ── 事件项 #2: 2026-04-27 dengke 恢复了 003 ─────────────
  - creator: dengke
    created_at: 2026-04-27T15:00:00+08:00
    quote: discussions/Pivot/xxx/003_dengke_act_bbb.md
    reason: restored
    # 无 summary,无文字补充
```

要点说明:

- 文件项通过 `type` 字段在枚举中(think/act/...)标识自己,事件项**没有 `type`**,通过其有 `reason` 而无 `type` 自然区分
- 文件项 #1 没有任何 invalidated 相关字段(向前兼容,旧数据不需要 migration)
- 文件项 #2 当前 `invalidated: false`(可正常展示),但保留了之前失效时的时间戳、理由、操作人——这是"曾经失效过"的审计痕迹,timeline 上配合事件项 #1 + #2 形成完整故事
- 事件项之间按 `created_at` 排序,与文件项混在同一 timeline 中

### 2.4 timeline 形态约束

文件项与事件项通过"是否有 `type` 字段"自然区分,不引入显式判别字段:

- **文件项**:保留 `file` 字段指向自身 md 文件,所有现有约束不变
- **事件项**:不带 `file` 字段,靠 `quote` 引用被操作的目标文件

## 三、校验规则(matter_validator)

新增 6 条规则:

1. 事件项 `creator` 必须等于 `quote` 指向文件的 `creator`(v1 作者本人限定)
2. 已失效(`invalidated == true`)文件不能再发失效事件,必须先恢复
3. 未失效(`invalidated != true`)文件不能发恢复事件
4. 事件项的 `quote` 不能指向另一条事件项(失效不能套娃)
5. 事件项的 `quote` 必须指向同一 matter 内的文件(不允许跨 matter)
6. comment 不能被失效(comment 不在失效能力范围)

## 四、可见性规则

失效是声明式撤回,不是隐藏机制。**所有对该 matter 有访问权限的用户和 AI 均可见失效文档的原文与失效元数据,仅 UI 渲染层标记"已失效(理由)"。**

| 角色 | 失效文档可见性 |
|---|---|
| 对 matter 有访问权限的所有用户 | ✅ 可见,UI 标"已失效(理由)",原文可展开 |
| AI / 外部 agent(`server/ai/tools.py` / `server/mcp/`) | ✅ 可见,沿 timeline 读取原文 + 失效元数据,作为"已被撤回的判断"上下文输入 |
| 作者本人 | 同上,附带"恢复"入口 |

设计依据:

- **失效是 timeline 演进的一部分**:团队需要看到"曾有过这个判断、后来被作者撤回"——这是 matter 故事不可或缺的一段
- **AI 协作必要性**:AI 在出方案、做评估时必须知道哪些方向已被作者主动否掉,否则会反复推已撤回的建议,降低协作效率
- **职责拆分**:谁能访问该 matter / 该文件,由「帖子权限」单独控制,失效不替它承担

**实现层影响:**

- 不需要 `is_visible_to` 辅助函数
- 后端读路径(GET / SSE / 搜索 / AI tool / MCP)不需要按"是否失效"做过滤
- 前端只在 timeline 渲染层根据 `invalidated: true` 加徽标 + 显示理由文本即可

## 五、衍生行为

### 5.1 实时推送

- 失效 / 恢复事件触发 SSE 推送,新主题 `matter.invalidated` / `matter.restored`
- `MatterEventsProvider` 收到后刷新对应 matter 的时间线视图

### 5.2 通知

- 失效 / 恢复事件触发飞书卡片广播(同等于新文件的通知级别)
- 卡片需要清晰展示"作者已撤回某条内容",让团队知晓

### 5.3 引用阻断

- 已失效文件不能被新的 `quote` / `refer` 引用(基于"撤回声明"语义,不依赖可见性收紧)
- 校验器在文件创建路径阻断(不在写盘后才发现)

### 5.4 用户私有状态

- 已失效文件的 `read_state` / `favorites` / `drafts` 引用保留(历史不动)
- 但 unread 计数减 1(不再贡献"待读")

### 5.5 状态机解耦

- 失效不触发任何 `status_change`
- 即使被失效的是 result 文件且曾把 matter 推到 finished,matter 状态依然 finished
- 这是有意为之:保持 timeline 与状态机的两条独立事实链

## 六、v2 延展(本期不做)

| 议题 | v2 方向 |
|---|---|
| 离职员工兜底失效 | admin override 路径,写入时 `invalidated_by ≠ creator`。当前 schema 已能容纳(`invalidated_by` 字段已存在) |
| verification 链联动失效 | 事件项加 `cascade: true` 字段(额外可选字段)。当前 schema 易扩展 |
| 系统 AI 大脑扫描 | 待该能力上线时再设计权限模型;现阶段不与现有 AI tool 混淆 |
| 「帖子权限」项目 | 承接访问控制需求,包括 sensitive 类型内容隐藏。失效与帖子权限是正交关系——失效管"撤回声明",权限管"谁能看见" |
| admin 应急 redact 通道 | 在「帖子权限」上线前,误粘贴密钥/PII 走 admin 介入的紧急 redact 路径,作为独立紧急通道,不混入 v1 失效流程 |

## 七、本期不在范围

- comment 失效能力(明确剥离)
- sensitive 失效理由(归入未来「帖子权限」项目)
- 失效操作的撤销窗口(操作即生效,靠"恢复事件"实现"反悔")

## 八、涉及代码改动点

| 模块 | 改动 |
|---|---|
| `server/matter_index.py` | `_normalize_item` canonical key 顺序扩展;新增 `_reverse_write_invalidations` |
| `server/matter_validator.py` | 6 条新校验规则 |
| `server/doc_types.py` | 新增 reason 枚举:文件项 `invalidated_reason` 取 {misposted, inaccurate};事件项 `reason` 取 {misposted, inaccurate, restored} |
| `server/api/matters.py` | 新 endpoint 处理失效/恢复事件;读路径不需要可见性过滤 |
| `server/api/matters_events.py` | 新 SSE 主题 `matter.invalidated` / `matter.restored` |
| `server/notify.py` | 新飞书卡片模板 |
| `server/ai/tools.py` + `server/mcp/` | 不需要可见性过滤(失效不再是过滤维度,直接返回带 invalidated 元数据的内容) |
| `web/src/pages/MatterDetailPane.tsx` | 时间线渲染分支(事件项 vs 文件项)+ 已失效徽标(渲染层标记,内容仍展示) |
| `web/src/components/matter/` | 新失效/恢复操作 UI(按钮 + 理由选择 dialog,理由 2 选 1) |
| `AI-docs/pivot-product.md` | 同步更新 schema 规范(per CLAUDE.md 约束) |
| `AI-docs/pivot-interface.md` | 同步更新 API 文档(per CLAUDE.md 约束) |
