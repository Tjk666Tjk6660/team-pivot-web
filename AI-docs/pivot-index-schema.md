# Pivot Matter Index Schema(权威源)

> ⚠ **本文是 matter index 数据结构的单一权威源**(single source of truth)。
>
> - 任何 AI 应用读 index 给 LLM 看时,**应注入本文档作为字段语义说明**
>   (公司日报 / 个人日报 / AI 助手 chat / MCP tools / 未来新 AI 应用 都从这里读)
> - matter index 字段集若有变动(`server/matter_index.py` 的
>   `_ITEM_KEY_ORDER` / `_INVALIDATION_EVENT_KEY_ORDER` / `_OWNER_CHANGE_KEY_ORDER` /
>   `_MATTER_KEY_ORDER` 等常量),**必须同次 commit 更新本文档**;否则程序化测试
>   `server/tests/test_index_schema_doc.py` 会 fail
> - 本文档只描述"数据结构层"(字段集 + 字段语义 + 字段间关系);
>   "在某个具体场景下如何使用这些字段"由各 AI 应用自己的 prompt 写业务规则

## 一、Matter 顶层结构

每个 matter 对应一个 yaml 文件(`<matter_id>.index.yaml`),含两块:

```yaml
matter:                              # 顶层快照(高频读取)
  id: <string>                       # matter 唯一 ID(== slug == 文件名前缀)
  title: <string>                    # 业务标题
  current_status: <string>           # 6 状态机: planning / executing / paused / finished / cancelled / reviewed
  owner: <pinyin>                    # 当前 matter 责任人 pinyin
                                     # ⚠ 老 matter 可能无此字段(owner_change 功能上线前创建的)
  created_at: <ISO datetime>         # 创建时间
  updated_at: <ISO datetime>         # 最近一次有 file 追加 / 状态推进的时间
                                     # 注意: comments / 失效事件 / owner_change 不 bump 此字段

timeline:                            # matter 演进主结构
  - <entry 1>
  - <entry 2>
  ...
```

## 二、Timeline entry 三种形态

timeline 上有 3 种 entry 形态,**按 `type` 字段是否存在 + 取值识别**:

| 形态 | 识别方法 | 描述 |
|---|---|---|
| **文件项** | `type ∈ {think, act, verify, result, insight}` 且有 `file` 字段 | 一篇 md 文件被追加到 timeline,主体 |
| **owner_change 事件** | `type == "owner_change"` 且无 `file` 字段 | matter 责任人转交事件,无 md 落盘 |
| **失效/恢复事件** | **无 `type` 字段**,有 `reason ∈ {misposted, inaccurate, restored}` | 作者对自己已发布文档的失效/恢复声明,无 md 落盘 |

按 `created_at` 升序混排。

## 三、文件项字段(form 1)

```yaml
- file: discussions/<category>/<matter_id>/NNN_<creator>_<type>_<hash>.md   # 唯一身份
  created_at: <ISO datetime>
  creator: <pinyin>                  # 写这条文件的人
  owner: <pinyin>                    # 该文件责任人(可与 creator 不同 = 代写)
  type: think | act | verify | result | insight
  summary: <string>                  # 文件最小解释
  quote: <path>                      # 引用上一篇,形成因果链
  refer: [<path>, ...]               # 多个补充参考(最多 4 个)
  verifications:                     # 仅 verify 文件: 验证覆盖的 act + 判定结果
    - target: <act file path>
      judgement: passed | failed | partial
      comment: <string>
  verifications_received:            # 系统反写: 本文件被某 verify 覆盖时反写在此
    - verify_file: <verify path>
      verified_at: <ISO datetime>
      verified_by: <pinyin>
      judgement: passed | failed | partial
      comment: <string>
  invalidated: <bool>                # 系统反写: 文件当前是否失效
  invalidated_at: <ISO datetime>     # 系统反写: 最近一次失效时间
  invalidated_reason: misposted | inaccurate
  invalidated_by: <pinyin>
  outcome: finished | cancelled      # 仅 result 文件: matter 收尾的结论
  comments:                          # 评论流(独立于状态机)
    - created_at: <ISO datetime>
      author: <pinyin>
      body: <string>
      mentions: [<pinyin>, ...]
  status_change:                     # 仅触发状态迁移的文件出现此字段
    from: <state>
    to: <state>
```

### 关键字段语义

- **`creator` vs `owner`(文件项级)**:
  - `creator` = 写这条文件的人(实施者 / 评论者 / 验证者)
  - `owner` = 该文件的责任推进人,可与 creator 不同(代写场景)
  - 注意:**matter 顶层的 `owner`** 是事项级负责人,**file 项的 `owner`** 是文件级责任人,两者语义不同

- **5 类 file `type` 业务含义**:
  - `think` — 讨论 / 评审 / 提反提议
  - `act` — 实施 / 动手 / 合入
  - `verify` — 验收(`verifications[].judgement`: passed / failed / partial)
  - `result` — 事项收尾(`outcome`: finished / cancelled)
  - `insight` — 复盘 / 沉淀

- **`invalidated` 系列(系统反写,非作者声明)**:
  - **失效是声明式撤回,不是隐藏机制**。`invalidated: true` 表示作者已声明该文件失效,
    但**原文与元数据仍对所有有访问权限的用户和 AI 可见**,仅在 UI 渲染层标记"已失效"
  - **AI / LLM 应能看到 invalidated 元数据**,作为"已失效判断"的上下文(避免反复推已被
    撤回的方向);具体在某个 AI 应用里如何使用,由该应用的 prompt 业务规则定义
  - 若文件曾失效又被恢复 → `invalidated: false`,但
    `invalidated_at / invalidated_reason / invalidated_by` **保留作为审计痕迹**(下次失效时被新值覆盖)
  - 详见 `AI-docs/invalidate-self/product-design.md`

- **`status_change`**:
  - 6 状态机: planning / executing / paused / finished / cancelled / reviewed
  - 触发规则: 不同 file type 只能触发部分 transition
  - **失效不触发 `status_change`**(timeline 与状态机是两条独立事实链)

## 四、owner_change 事件项(form 2)

```yaml
- type: owner_change
  created_at: <ISO datetime>
  actor: <pinyin>                         # 操作人(转交者)
  from_owner: <pinyin>                    # 原 matter owner(可能为空,首次设置)
  to_owner: <pinyin>                      # 新 matter owner
  reason: <string>                        # 转交理由
  status_change: {from, to}               # 可选: 转交时也可推进状态
```

- 写 owner_change 后,**matter 顶层的 `owner` 字段被反写为 `to_owner`**

## 五、失效 / 恢复事件项(form 3)

```yaml
- creator: <pinyin>                # 失效/恢复操作人(必须 == 目标文件的 creator)
  created_at: <ISO datetime>
  quote: <被操作的目标文件 path>     # 必须指向同 matter 内的文件项
  reason: misposted | inaccurate | restored   # 同字段编码事件类型 + 具体原因
  summary: <string>                # 可选自由说明
```

- `reason ∈ {misposted, inaccurate}` → 失效事件,反写目标文件:
  `invalidated=true / invalidated_at=now / invalidated_reason=<reason> / invalidated_by=<creator>`
- `reason == "restored"` → 恢复事件,翻转目标文件 `invalidated=false`,**其他三个反写字段保留**

详细约束(6 条校验规则)见 `AI-docs/invalidate-self/product-design.md §三`。

## 六、字段间关系

- **`quote` 因果链**: 每个文件项的 `quote` 指向其回应的另一文件,形成"谁回应谁"的因果链
- **`refer` 补充参考**: 数组(≤ 4),语义弱于 quote
- **`verifications` ↔ `verifications_received`**: verify 文件写 `verifications` 表达"我验证了哪些 act",
  被覆盖的 act/result 文件反写 `verifications_received` 表达"我被哪些 verify 覆盖了"
- **失效事件 ↔ `invalidated_*` 反写**: 失效/恢复事件的影响通过反写函数同步到目标文件项的 4 字段
- **owner_change ↔ matter.owner**: owner_change 事件的 `to_owner` 反写到 matter 顶层 `owner`

## 七、状态机迁移触发规则(简表)

| 当前状态 | 允许 file type | 允许 transition |
|---|---|---|
| `planning` | think, act, verify | → `executing`(via act); → `paused`(via think) |
| `executing` | think, act, verify, result | → `paused`(via think); → `finished`(via result, outcome=finished); → `cancelled`(via result, outcome=cancelled) |
| `paused` | think | → `executing`(via think 重启 / via act resume) |
| `finished` / `cancelled` | insight | → `reviewed`(via insight) |
| `reviewed` | (终态) | 无 |

详细 status × type 矩阵见 `server/doc_types.py::ALLOWED_TYPES_BY_STATUS`,
状态机演进原则见 `pivot-product.md §九`。
