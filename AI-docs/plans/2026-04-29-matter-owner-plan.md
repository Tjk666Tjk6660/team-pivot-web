# Matter Owner 责任人机制：实施计划

> **For agentic workers:** 用 checkbox（`- [ ]`）逐 Task / Step 推进。每个 Phase 末尾都有 Commit Checkpoint，**做完一个 Phase 再开下一个**，避免半截改动留在工作区。

**Goal:** 给 Matter 增加 matter 级 owner 字段（与既有 file 级 owner 并行不冲突），支持创建时指定、转交（带 reason），转交可选合并 `planning → executing` 状态推进；列表与详情卡片展示 owner 头像 + 姓名；timeline 增加 `owner_change` 事件以保留变更历史。

**Architecture:** 复用现有 timeline 架构 —— `owner_change` 作为新 timeline entry type 与既有文件型 entry 并列；`matter.{}` block 加 `owner` 字段；`matter_validator` 入口按 type ∈ FILE / EVENT 分流；display / avatar 全部走 render 层即时解析（mirror 既有 `creator` 三件套）。新增一个 API 端点 `POST /api/matters/{id}/owner`，复用既有 `_atomic_write_yaml` + write_session + emit。

**Tech Stack:** Python 3.12 + FastAPI（后端）；React + TypeScript + shadcn/ui + Tailwind（前端）；pytest + Vitest（测试）。

**依据**：[AI-docs/designs/2026-04-29-matter-owner-design.md](../designs/2026-04-29-matter-owner-design.md)（已确认决策清单见 §四.1，边界值清单见 §六）

---

## 范围对照（与 design §二 + §六 对齐）

**纳入 v1**：

- matter index 增加 `matter.owner`（与 creator 同格式：注册用户 = pinyin，未注册 = open_id）
- timeline 增加 `type: owner_change` entry（含 actor / from_owner / to_owner / reason / 可选 status_change）
- `POST /api/matters` 接受可选 `owner_open_id`（缺省 = 创建者）
- `POST /api/matters/{id}/owner` 端点
- 列表 / 详情卡片 / timeline 三处 UI 展示
- 转交合并 status_change 仅支持 `planning → executing`
- 历史 matter 缺 owner 的回填脚本 + 运行时兜底

**v1 不做**：

- 权限限制（开放协作，需求 §8）
- 撤销 / undo 链路（用"再发一条 owner_change 转回去"自然解决）
- 通知功能（§2.7 设计稿讨论过 IM 通知 + 软提醒，但未决；本期先纯打通基础链路）
- co-owner（一个 matter 始终至多 1 个 owner）

---

## 文件结构

### 后端新增

| 路径 | 职责 |
|------|------|
| `server/scripts/backfill_matter_owner.py` | 一次性脚本：扫所有 `*.index.yaml`，缺 `matter.owner` 时用 `timeline[0].creator` 填入；幂等 |
| `server/tests/test_matters_owner.py` | API 端点 + 状态合并的集成测试 |
| `server/tests/test_matter_validator_owner.py` | validator owner_change 分支的纯函数测试 |
| `server/tests/test_matter_status_event_triggers.py` | EVENT_TRIGGERS_BY_TRANSITION 测试 |

### 后端修改

| 路径 | 修改内容 |
|------|---------|
| [server/doc_types.py](../../server/doc_types.py) | 新增 `VALID_EVENT_TYPES = frozenset({"owner_change"})`；`VALID_DOC_TYPES` 不动 |
| [server/matter_status.py](../../server/matter_status.py) | 新增 `EVENT_TRIGGERS_BY_TRANSITION` + `can_event_type_trigger()` helper |
| [server/matter_validator.py](../../server/matter_validator.py) | `validate_append` 入口按 type 分流；新增 `_validate_owner_change_shape` |
| [server/matter_index.py](../../server/matter_index.py) | `_normalize_item` 增加 owner_change 分支 + 独立 key 顺序；`create_matter_index` 接受 `matter_owner` 参数；新增 `apply_owner_change(...)` |
| [server/publish.py](../../server/publish.py) | `publish_matter_create` 接受可选 `matter_owner_pinyin`；新增 `publish_matter_owner_change(...)` |
| [server/api/matters.py](../../server/api/matters.py) | `NewMatterBody` 加 `owner_open_id`；新增 `OwnerChangeBody` + `POST /api/matters/{id}/owner`；`_summarize_matter` / `_render_matter_detail` 输出 owner 三件套；`_render_item` 走 owner_change 分支 |
| `server/events.py`（或对应 topics 文件） | 新增 `TOPIC_MATTER_OWNER_CHANGED` |
| [server/recovery.py](../../server/recovery.py) | 启动期检测 matter.owner 缺失 → log warning |
| [server/mcp/schemas.py](../../server/mcp/schemas.py) | timeline entry schema 加 `owner_change` 到 type enum |

### 前端新增

| 路径 | 职责 |
|------|------|
| `web/src/components/matter/OwnerChip.tsx` | 列表用：头像 + 姓名 + 截断 + unassigned 占位 |
| `web/src/components/matter/OwnerBadge.tsx` | 详情顶部用：稍大版 OwnerChip |
| `web/src/components/matter/TransferOwnerDialog.tsx` | OwnerPicker + reason textarea + 可选"同时推进至 executing"复选框 |
| `web/src/components/matter/OwnerChangeRow.tsx` | timeline 内的轻量事件条；带 status_change 时再渲染一行 status 视觉条 |

### 前端修改

| 路径 | 修改内容 |
|------|---------|
| [web/src/api.ts](../../web/src/api.ts) | `MatterSummary` / `MatterMeta` 加 `owner / owner_display / owner_avatar_url`；`TimelineItem` 改成 union（含 `TimelineOwnerChangeItem`）；`createMatter` 入参增 `owner_open_id`；新增 `transferMatterOwner(matter_id, to_owner, reason, status_change?)` |
| [web/src/components/ThreadListPane.tsx](../../web/src/components/ThreadListPane.tsx) | `MatterRow` meta 行加 OwnerChip；shrink-0 占位 |
| [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx) | 顶部 matter 卡片加 OwnerBadge + 转交按钮；接 TransferOwnerDialog；timeline 渲染层在 owner_change 分支调 OwnerChangeRow |
| [web/src/components/matter/TimelineStrip.tsx](../../web/src/components/matter/TimelineStrip.tsx) | 节点渲染按 type 分形（owner_change = 小菱形 / 灰色） |
| [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx) | classic form 加"责任人（可选 · 默认你自己）"OwnerPicker；与既有 act-file owner 文案分明 |
| [web/src/pages/NewMatterGuidedFlow.tsx](../../web/src/pages/NewMatterGuidedFlow.tsx) | 新增"指定责任人"步骤（mentions 之前），原 6 步 → 7 步 |
| [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx) | SSE 监听现有 `matter.updated` 事件，按 `reason: "owner_changed"` invalidate 该 matter 缓存 |

### 测试

| 路径 | 覆盖 |
|------|------|
| `server/tests/test_matter_status_event_triggers.py` | EVENT_TRIGGERS_BY_TRANSITION 仅含 planning→executing |
| `server/tests/test_matter_validator_owner.py` | owner_change 分支：reason 必填、from_owner 校验、to_owner ≠ from_owner、status_change 校验 |
| `server/tests/test_matters_owner.py` | API 集成：转交成功 / reason 空 / owner_unknown / owner_unchanged / owner_stale / status 合并 / 未分配状态转交 / SSE event |
| `server/tests/test_backfill_matter_owner.py` | 脚本幂等 / 异常 corner |
| `web/src/components/matter/OwnerChip.test.tsx` | unassigned 占位 / 名字超长截断 |
| `web/src/components/matter/TransferOwnerDialog.test.tsx` | reason 必填 / new ≠ current / 提交调 API |

### 不动

- 现有 `timeline[i].owner`（文件级）一行不改；matter 级与文件级两层语义并存
- `creator` / `_resolve_owner_for_index` 现有兜底逻辑
- 前端 reply 路径（`MatterDetailPane` 的回复入口、`AIPane` 等）
- MCP 工具实现层（`server/mcp/tools.py` 不需改 —— `read_matter_index` 自然返回 owner_change）

---

## Phase 0：准备

### Task 0.1：分支 + 基线

- [ ] **Step 1：从 main 切分支**

```bash
git checkout main
git pull --ff-only
git checkout -b feat/matter-owner
```

- [ ] **Step 2：基线检查**

```bash
uv run pytest server/tests -q
cd web && npm run typecheck && npm run build
cd web && npx vitest run
```

Expected：全部 PASS，建立干净基线。

---

## Phase 1：后端纯逻辑层（status / validator / doc_types）

### Task 1.1：doc_types + matter_status 扩展

**Files:**
- Modify: [server/doc_types.py](../../server/doc_types.py)
- Modify: [server/matter_status.py](../../server/matter_status.py)
- Create: `server/tests/test_matter_status_event_triggers.py`

- [ ] **Step 1：doc_types.py 加 VALID_EVENT_TYPES**

```python
VALID_EVENT_TYPES = frozenset({"owner_change"})
# VALID_DOC_TYPES 不动
```

- [ ] **Step 2：matter_status.py 加 EVENT_TRIGGERS + helper**

```python
EVENT_TRIGGERS_BY_TRANSITION: dict[tuple[str, str], frozenset[str]] = {
    ("planning", "executing"): frozenset({"owner_change"}),
}

def can_event_type_trigger(event_type: str, from_state: str, to_state: str) -> bool:
    return event_type in EVENT_TRIGGERS_BY_TRANSITION.get((from_state, to_state), frozenset())
```

- [ ] **Step 3：写测试**

```python
def test_can_event_type_trigger_planning_to_executing():
    assert can_event_type_trigger("owner_change", "planning", "executing")

def test_can_event_type_trigger_other_transitions_disallowed():
    for from_, to in [
        ("planning", "paused"), ("executing", "finished"),
        ("paused", "executing"), ("finished", "reviewed"),
    ]:
        assert not can_event_type_trigger("owner_change", from_, to)

def test_can_event_type_trigger_unknown_event():
    assert not can_event_type_trigger("status_change", "planning", "executing")
```

- [ ] **Step 4：跑测试**

```bash
uv run pytest server/tests/test_matter_status_event_triggers.py -q
```

### Task 1.2：matter_validator owner_change 分支

**Files:**
- Modify: [server/matter_validator.py](../../server/matter_validator.py)
- Create: `server/tests/test_matter_validator_owner.py`

- [ ] **Step 1：validate_append 入口按 type 分流**

```python
from server.doc_types import VALID_DOC_TYPES, VALID_EVENT_TYPES

def validate_append(index_data: dict, item: dict) -> ValidationResult:
    doc_type = item.get("type")
    if not doc_type:
        return _fail("type_missing", "type", "type is required")
    if doc_type in VALID_EVENT_TYPES:
        return _validate_owner_change_shape(index_data, item)
    if doc_type not in VALID_DOC_TYPES:
        return _fail("unknown_type", "type", f"unknown type: {doc_type!r}")
    # 既有文件型分支保持不动
    ...
```

- [ ] **Step 2：实现 _validate_owner_change_shape**

```python
def _validate_owner_change_shape(index_data: dict, item: dict) -> ValidationResult:
    matter = index_data.get("matter") or {}

    # reason 必填
    reason = item.get("reason")
    if not reason or not str(reason).strip():
        return _fail("reason_required", "reason", "reason is required")
    if len(str(reason)) > 200:
        return _fail("reason_too_long", "reason", "reason exceeds 200 chars")

    # from_owner 必须 == matter.owner（None == None 视为相等）
    current_owner = matter.get("owner")
    from_owner = item.get("from_owner")
    if from_owner != current_owner:
        return _fail(
            "owner_stale",
            "from_owner",
            f"from_owner {from_owner!r} does not match current matter.owner {current_owner!r}",
        )

    # to_owner 必填且 ≠ from_owner
    to_owner = item.get("to_owner")
    if not to_owner:
        return _fail("to_owner_required", "to_owner", "to_owner is required")
    if to_owner == from_owner:
        return _fail("owner_unchanged", "to_owner", "to_owner equals from_owner")

    # 可选 status_change：走 EVENT_TRIGGERS 校验
    sc = item.get("status_change")
    if sc:
        from_state = sc.get("from")
        to_state = sc.get("to")
        if from_state != matter.get("current_status"):
            return _fail(
                "status_stale",
                "status_change.from",
                f"status_change.from {from_state!r} does not match current {matter.get('current_status')!r}",
            )
        from server.matter_status import can_transition, can_event_type_trigger
        if not can_transition(from_state, to_state):
            return _fail("status_change_not_allowed", "status_change",
                         f"transition {from_state!r} → {to_state!r} not allowed")
        if not can_event_type_trigger("owner_change", from_state, to_state):
            return _fail(
                "status_change_not_allowed_by_event",
                "status_change",
                f"owner_change cannot trigger {from_state!r} → {to_state!r}",
            )

    return OK
```

- [ ] **Step 3：测试矩阵（覆盖 design §六）**

```python
# 基础
def test_owner_change_reason_required()
def test_owner_change_reason_too_long_201()
def test_owner_change_to_owner_required()
def test_owner_change_to_owner_equals_from_owner()
def test_owner_change_from_owner_mismatch_stale()

# 未分配（design §6.1）
def test_owner_change_from_null_when_matter_owner_null_ok()
def test_owner_change_from_null_when_matter_owner_set_stale()

# 状态合并（design §6.2 / §2.5）
def test_owner_change_with_status_planning_to_executing_ok()
def test_owner_change_with_status_executing_to_paused_rejected()
def test_owner_change_with_status_finished_to_reviewed_rejected()
def test_owner_change_with_status_from_mismatch_stale()
def test_owner_change_in_reviewed_state_without_status_change_ok()
```

- [ ] **Step 4：跑测试**

```bash
uv run pytest server/tests/test_matter_validator_owner.py -q
```

### Task 1.3：Commit Checkpoint

- [ ] **Commit**

```bash
git add server/doc_types.py server/matter_status.py server/matter_validator.py \
  server/tests/test_matter_status_event_triggers.py \
  server/tests/test_matter_validator_owner.py
git commit -m "feat(server): owner_change event type + status-merge validator (planning→executing only)"
```

- [ ] **跑既有 server 测试，确认无回归**

```bash
uv run pytest server/tests -q
```

Expected：原有用例全绿。

---

## Phase 2：后端 matter_index 扩展

### Task 2.1：_normalize_item + key 顺序分支

**Files:**
- Modify: [server/matter_index.py](../../server/matter_index.py)

- [ ] **Step 1：加 owner_change 专属 key 顺序常量**

```python
_OWNER_CHANGE_KEY_ORDER = (
    "type",
    "created_at",
    "actor",
    "from_owner",
    "to_owner",
    "reason",
    "status_change",
)
```

- [ ] **Step 2：_normalize_item 按 type 分流**

```python
def _normalize_item(item: dict, *, now_iso: str) -> dict:
    out = dict(item)
    out.setdefault("created_at", now_iso)
    if out.get("type") == "owner_change":
        # 不要 fallback owner=creator——event 没有 creator 概念
        return _reorder(out, _OWNER_CHANGE_KEY_ORDER)
    # 既有文件型分支保持不动
    creator = out.get("creator")
    if creator and not out.get("owner"):
        out["owner"] = creator
    if out.get("comments"):
        out["comments"] = [_canonical_comment(c) for c in out["comments"]]
    return _reorder(out, _ITEM_KEY_ORDER)
```

### Task 2.2：create_matter_index 接受 matter_owner

- [ ] **Step 1：扩展函数签名**

```python
def create_matter_index(
    path: Path,
    *,
    matter_id: str,
    title: str,
    initial_item: dict[str, Any],
    now_iso: str,
    matter_owner: str | None = None,    # ← 新增
) -> None:
    ...
    index: dict[str, Any] = {
        "version": VERSION,
        "matter": {
            "id": matter_id,
            "title": title,
            "current_status": "planning",
            **({"owner": matter_owner} if matter_owner else {}),  # ← 新增
            "created_at": now_iso,
            "updated_at": now_iso,
        },
        "timeline": [],
    }
    ...
```

匹配 yaml 里 owner 字段位置在 `current_status` 之后、`created_at` 之前（与示例一致）。

### Task 2.3：apply_owner_change 写入函数

- [x] **Step 1：实现**

```python
def apply_owner_change(
    path: Path,
    *,
    item: dict[str, Any],
    now_iso: str,
) -> None:
    """Append an owner_change timeline item; update matter.owner +
    optionally matter.current_status; bump matter.updated_at.
    All in a single _atomic_write_yaml call."""
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    normalized = _normalize_item(item, now_iso=now_iso)
    result = validate_append(data, normalized)
    if not result.ok:
        raise ValidationError(result)
    data.setdefault("timeline", []).append(normalized)
    # 同步 matter.owner
    matter = data.setdefault("matter", {})
    matter["owner"] = normalized.get("to_owner")
    # 同步 matter.current_status（若 entry 携带 status_change）
    _apply_status_change(data, normalized)
    matter["updated_at"] = now_iso
    _atomic_write_yaml(p, data)
```

- [ ] **Step 2：测试矩阵**

```python
def test_apply_owner_change_updates_matter_owner()
def test_apply_owner_change_with_status_change_updates_both()
def test_apply_owner_change_normalizes_key_order()
def test_apply_owner_change_invalid_raises_validation_error()
def test_apply_owner_change_unknown_matter_raises_filenotfound()
```

加到 `server/tests/test_matter_index.py` 现有文件里。

- [ ] **Step 3：跑测试**

```bash
uv run pytest server/tests/test_matter_index.py -q
```

### Task 2.4：Commit Checkpoint

- [ ] **Commit**

```bash
git add server/matter_index.py server/tests/test_matter_index.py
git commit -m "feat(server): matter_index supports owner_change entry + matter.owner field"
```

---

## Phase 3：后端 publish + API + events

### Task 3.1：events 主题

**Files:**
- Modify: 现有 events / topics 文件（grep 找）

- [ ] **Step 1：定位现有 emit topics 定义位置**

```bash
```

Grep `TOPIC_MATTER_CREATED` 找到。

- [ ] **Step 2：加新 topic**

```python
TOPIC_MATTER_OWNER_CHANGED = "matter.owner_changed"
```

说明：这是服务端内部 event bus topic；SSE 对外沿用既有 `matter.updated` event，并在 payload 中携带 `reason: "owner_changed"`，与 `file_appended` / `comment_appended` 的刷新机制保持一致。

### Task 3.2：publish.py 扩展

**Files:**
- Modify: [server/publish.py](../../server/publish.py)

- [ ] **Step 1：publish_matter_create 接收 matter_owner_pinyin**

```python
def publish_matter_create(
    workspace, user, *,
    category, title, initial_item,
    matter_owner_open_id: str | None = None,    # ← 新增
    contacts=None, notifier=None, users=None,
):
    ...
    matter_owner_pinyin = (
        _resolve_owner_for_index(matter_owner_open_id, users)
        if matter_owner_open_id
        else user.pinyin
    )
    ...
    create_matter_index(
        index_path,
        matter_id=matter_id,
        title=title,
        initial_item=item,
        now_iso=now,
        matter_owner=matter_owner_pinyin,    # ← 新增
    )
```

- [ ] **Step 2：新增 publish_matter_owner_change**

```python
def publish_matter_owner_change(
    workspace,
    user,
    *,
    matter_id: str,
    to_owner_open_id: str,
    reason: str,
    status_change: dict | None = None,
    contacts=None,
    notifier=None,
    users=None,
) -> dict:
    if not user.pinyin:
        raise PublishError("profile setup required")
    index_path = matter_index_path(workspace.index_dir, matter_id)
    data = read_matter_index(index_path)
    if data is None:
        raise MatterNotFoundError(matter_id)

    matter = data.get("matter") or {}
    from_owner = matter.get("owner")
    to_owner = _resolve_owner_for_index(to_owner_open_id, users)
    if not to_owner:
        raise PublishError(f"owner not found: {to_owner_open_id}")

    now = _now_iso()
    item = {
        "type": "owner_change",
        "actor": user.pinyin,
        "from_owner": from_owner,
        "to_owner": to_owner,
        "reason": reason,
    }
    if status_change is not None:
        item["status_change"] = dict(status_change)

    with workspace.write_session(
        message=f"chore: owner change on {matter_id}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        apply_owner_change(index_path, item=item, now_iso=now)

    matter_snapshot = read_matter_index(index_path) or {}
    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id=matter_id,
        actor=user.pinyin,
        at=now,
        payload={
            "from_owner": from_owner,
            "to_owner": to_owner,
            "reason": reason,
            "status_change": status_change,
        },
    )
    return {
        "matter": matter_snapshot.get("matter", {}),
        "item": item,
    }
```

### Task 3.3：API 路由 + Pydantic

**Files:**
- Modify: [server/api/matters.py](../../server/api/matters.py)

- [ ] **Step 1：NewMatterBody 加 owner_open_id**

```python
class NewMatterBody(BaseModel):
    category: str = ...
    title: str = ...
    owner_open_id: str | None = Field(default=None, max_length=50)    # ← 新增
    initial_file: InitialFileIn
```

create_matter 路由内：

```python
result = publish_matter_create(
    workspace, user,
    category=body.category,
    title=body.title,
    initial_item=initial,
    matter_owner_open_id=body.owner_open_id,    # ← 新增
    ...
)
```

- [ ] **Step 2：OwnerChangeBody + 路由**

```python
class StatusChangeIn(BaseModel):
    from_: str = Field(alias="from", min_length=1, max_length=20)
    to: str = Field(min_length=1, max_length=20)

    class Config:
        populate_by_name = True


class OwnerChangeBody(BaseModel):
    to_owner: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=200)
    status_change: StatusChangeIn | None = None


@router.post("/matters/{matter_id}/owner")
def transfer_owner(
    matter_id: str,
    body: OwnerChangeBody,
    user: User = Depends(current_user),
):
    require_profile(user)

    # to_owner 解析
    resolved_user = users.get_by_any_id(body.to_owner)
    if resolved_user is None:
        # 联系人也算合法（沿用 _resolve_owner_for_index 的兜底）—— 但这里要确认 open_id 实际存在
        contact = contacts.get(body.to_owner) if contacts else None
        if contact is None:
            raise HTTPException(status_code=422, detail={"code": "owner_unknown"})

    sc_dict = (
        {"from": body.status_change.from_, "to": body.status_change.to}
        if body.status_change
        else None
    )

    try:
        result = publish_matter_owner_change(
            workspace, user,
            matter_id=matter_id,
            to_owner_open_id=body.to_owner,
            reason=body.reason,
            status_change=sc_dict,
            contacts=contacts,
            notifier=notifier,
            users=users,
        )
    except MatterNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "matter_not_found"})
    except ValidationError as e:
        # validator 422 错误码（owner_unchanged / owner_stale / status_change_not_allowed_by_event 等）
        raise HTTPException(
            status_code=409 if e.result.code in ("owner_stale", "status_stale") else 422,
            detail={"code": e.result.code, "field": e.result.field, "message": e.result.message},
        )
    except PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # render owner display + avatar 后返回
    return {
        "matter": _render_matter_block(result["matter"], users, contacts),
        "item": _render_owner_change_item(result["item"], users, contacts),
    }
```

`_render_matter_block` / `_render_owner_change_item` 见 Phase 4 Task 4.1。

### Task 3.4：测试

**Files:**
- Create: `server/tests/test_matters_owner.py`

- [ ] **Step 1：测试矩阵**

按 design §7.1 + §六 边界覆盖：

```python
# 转交基础
def test_transfer_owner_success()
def test_transfer_owner_reason_empty_422()
def test_transfer_owner_reason_too_long_422()
def test_transfer_owner_to_owner_unknown_422()
def test_transfer_owner_to_owner_equals_current_422()
def test_transfer_owner_concurrent_stale_409()

# 创建
def test_create_matter_default_owner_is_creator()
def test_create_matter_with_owner_open_id_to_other()
def test_create_matter_owner_open_id_unknown_422()
def test_create_matter_matter_owner_independent_from_file_owner()

# 未分配（design §6.1）
def test_transfer_when_matter_owner_unassigned_ok()
def test_transfer_after_unassigned_chain()

# 状态合并（design §6.2）
def test_transfer_with_status_planning_to_executing_ok()
def test_transfer_with_status_other_transitions_rejected_422()
def test_transfer_unassigned_with_status_to_executing_ok()

# reviewed
def test_transfer_in_reviewed_state_ok()
def test_transfer_in_reviewed_with_status_change_rejected()

# SSE
def test_transfer_emits_matter_owner_changed_event()

# 历史 matter 兜底
def test_get_matter_returns_owner_display_fallback_to_creator_when_owner_missing()
```

- [ ] **Step 2：跑测试**

```bash
uv run pytest server/tests/test_matters_owner.py -q
```

### Task 3.5：Commit Checkpoint

- [ ] **Commit**

```bash
git add server/publish.py server/api/matters.py server/events.py \
  server/tests/test_matters_owner.py
git commit -m "feat(server): POST /api/matters/{id}/owner + publish_matter_owner_change"
```

---

## Phase 4：后端 render 层 owner display + avatar

### Task 4.1：_summarize_matter / _render_matter_detail / _render_item

**Files:**
- Modify: [server/api/matters.py](../../server/api/matters.py)

- [ ] **Step 1：_summarize_matter 输出 owner 三件套**

```python
def _summarize_matter(data, users=None, contacts=None) -> dict:
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []
    out = { ... 既有字段 ... }
    if users is not None:
        # 既有 creator 三件套
        out["creator"] = ...
        out["creator_display"] = ...
        out["creator_avatar_url"] = ...
        # 新增 owner 三件套
        owner = matter.get("owner")
        # 兜底：matter.owner 缺失时 fallback 到 timeline[0].creator
        if not owner and timeline:
            owner = timeline[0].get("creator")
        out["owner"] = owner
        out["owner_display"] = resolve_id(owner, users, contacts) if owner else None
        out["owner_avatar_url"] = resolve_avatar_url(owner, users, contacts) if owner else None
    return out
```

- [ ] **Step 2：_render_matter_detail 同步**

`matter` block 里加 owner 三件套（同上）。

- [ ] **Step 3：_render_item 走 owner_change 分支**

```python
def _render_item(workspace, item, users, contacts) -> dict:
    if item.get("type") == "owner_change":
        return _render_owner_change_item(item, users, contacts)
    # 既有文件型分支保持不动
    ...

def _render_owner_change_item(item, users, contacts) -> dict:
    out = dict(item)
    actor = out.get("actor")
    out["actor_display"] = resolve_id(actor, users, contacts)
    out["actor_avatar_url"] = resolve_avatar_url(actor, users, contacts)
    from_owner = out.get("from_owner")
    out["from_owner_display"] = resolve_id(from_owner, users, contacts) if from_owner else None
    out["from_owner_avatar_url"] = resolve_avatar_url(from_owner, users, contacts) if from_owner else None
    to_owner = out.get("to_owner")
    out["to_owner_display"] = resolve_id(to_owner, users, contacts)
    out["to_owner_avatar_url"] = resolve_avatar_url(to_owner, users, contacts)
    # 不要 expanded / body / comments / readers —— event 没有这些概念
    return out
```

- [ ] **Step 4：测试**

```python
def test_summarize_matter_includes_owner_three_fields()
def test_summarize_matter_owner_fallback_to_creator_when_missing()
def test_render_owner_change_item_resolves_displays()
def test_render_owner_change_item_from_null_renders_null_displays()
```

加到现有 `server/tests/test_matters_api.py`。

- [ ] **Step 5：跑测试**

```bash
uv run pytest server/tests/test_matters_api.py -q
```

### Task 4.2：Commit Checkpoint

- [ ] **Commit**

```bash
git add server/api/matters.py server/tests/test_matters_api.py
git commit -m "feat(server): render matter.owner display+avatar via existing creator path"
```

---

## Phase 5：MCP schema 兼容（design §6.4 P0）

### Task 5.1：schema 加 owner_change 到 type enum

**Files:**
- Modify: [server/mcp/schemas.py](../../server/mcp/schemas.py)

- [ ] **Step 1：定位 timeline entry schema**

```bash
```

Grep `read_matter_index` 找其响应 schema。

- [ ] **Step 2：扩展 type enum + description**

```python
timeline_item_schema = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["think", "act", "verify", "result", "insight", "owner_change"],
        },
        # owner_change 字段集（与文件型互斥）
        "actor": {"type": "string"},
        "from_owner": {"type": ["string", "null"]},
        "to_owner": {"type": "string"},
        "reason": {"type": "string"},
        # ... 既有字段
    },
    "additionalProperties": True,    # display / avatar 后端动态加
}
```

工具描述里加一段：

> timeline 包含两类 entry：文件型（type ∈ {think, act, verify, result, insight}，带 file 字段）和事件型（type == owner_change，没有 file，记录责任人变更）。

- [ ] **Step 3：测试**

```python
def test_mcp_read_matter_index_owner_change_passes_schema()
```

加到现有 mcp 测试。

- [ ] **Step 4：跑测试**

```bash
uv run pytest server/tests/test_mcp_e2e.py server/tests/test_mcp_tools.py -q
```

### Task 5.2：Commit Checkpoint

- [ ] **Commit**

```bash
git add server/mcp/schemas.py server/tests/
git commit -m "feat(mcp): timeline schema accepts owner_change type"
```

---

## Phase 6：前端 api.ts 类型扩展

### Task 6.1：MatterSummary / MatterMeta / MatterDetail.matter

**Files:**
- Modify: [web/src/api.ts](../../web/src/api.ts)

- [ ] **Step 1：MatterSummary / MatterMeta 加 owner 三件套**

```ts
export type MatterSummary = {
  // ... 既有
  creator?: string;                  // 已隐式存在，显式声明
  creator_display?: string;
  creator_avatar_url?: string | null;
  owner: string | null;              // ← 新增
  owner_display: string | null;      // ← 新增
  owner_avatar_url: string | null;   // ← 新增
};
```

`MatterMeta` 别名跟着改。

### Task 6.2：TimelineItem 改 union

- [ ] **Step 1：拆 file vs owner_change**

```ts
export type TimelineFileItem = {
  // 既有 TimelineItem 内容
  file: string;
  type: DocType;
  // ...
};

export type TimelineOwnerChangeItem = {
  type: "owner_change";
  created_at: string;
  actor: string;
  actor_display: string;
  actor_avatar_url: string | null;
  from_owner: string | null;
  from_owner_display: string | null;
  from_owner_avatar_url: string | null;
  to_owner: string;
  to_owner_display: string;
  to_owner_avatar_url: string | null;
  reason: string;
  status_change?: { from: MatterStatus; to: MatterStatus } | null;
};

export type TimelineItem = TimelineFileItem | TimelineOwnerChangeItem;
```

- [ ] **Step 2：消费侧的 `item.type === "owner_change"` narrow**

[TimelineStrip.tsx](../../web/src/components/matter/TimelineStrip.tsx) 等地方按 type 分支。Phase 7 / 9 会修。

### Task 6.3：API 函数

- [ ] **Step 1：createMatter 入参增 owner_open_id**

```ts
export async function createMatter(input: {
  category: string;
  title: string;
  owner_open_id?: string;            // ← 新增
  initial_file: InitialFileIn;
}): Promise<...>
```

- [ ] **Step 2：transferMatterOwner**

```ts
export async function transferMatterOwner(
  matter_id: string,
  body: {
    to_owner: string;
    reason: string;
    status_change?: { from: MatterStatus; to: MatterStatus };
  },
): Promise<{ matter: MatterMeta; item: TimelineOwnerChangeItem }> {
  const r = await fetch(`/api/matters/${encodeURIComponent(matter_id)}/owner`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail?.message || d.detail?.code || `transfer failed: ${r.status}`);
  }
  return r.json();
}
```

- [ ] **Step 3：tsc 通过**

```bash
cd web && npm run typecheck
```

会有大量 type 错误（TimelineItem 改 union 后所有消费点都要 narrow）。**先记下**所有错误位置，Phase 7 / 9 集中修。如果错误量太大，可以临时回退 union 改用 `& Partial<...>` 同 shape，等 Phase 9 再细化。

### Task 6.4：Commit Checkpoint

- [ ] **Commit**

```bash
git add web/src/api.ts
git commit -m "feat(web): MatterSummary owner three-field + TimelineItem union + transferMatterOwner"
```

---

## Phase 7：前端共享组件

### Task 7.1：OwnerChip / OwnerBadge

**Files:**
- Create: `web/src/components/matter/OwnerChip.tsx`

- [x] **Step 1：实现**

```tsx
export function OwnerChip({
  name,
  avatarUrl,
  unassigned,
  size = "sm",
}: {
  name: string | null;
  avatarUrl: string | null;
  unassigned: boolean;
  size?: "sm" | "md";
}) {
  const display = unassigned ? "未分配" : (name ?? "未分配");
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full",
        size === "sm" ? "h-5 max-w-[7rem] pr-2" : "h-6 max-w-[9rem] pr-2.5",
        unassigned ? "bg-[var(--surface-mute)] text-[var(--text-mute)]" : "bg-[var(--surface-alt)]",
      )}
      title={display}
    >
      <Avatar src={avatarUrl} fallback={display.slice(0, 1)} size={size === "sm" ? 16 : 20} />
      <span className="truncate text-xs leading-none">{display}</span>
    </span>
  );
}
```

`OwnerBadge` 用 `<OwnerChip size="md" />` 别名即可。

- [ ] **Step 2：测试**

```tsx
test('OwnerChip renders unassigned when name is null')
test('OwnerChip truncates long name at max-w')
test('OwnerChip falls back to placeholder avatar when avatarUrl is null')
```

- [ ] **Step 3：跑测试**

```bash
cd web && npx vitest run src/components/matter/OwnerChip.test.tsx
```

### Task 7.2：TransferOwnerDialog

**Files:**
- Create: `web/src/components/matter/TransferOwnerDialog.tsx`

- [x] **Step 1：实现**

```tsx
export function TransferOwnerDialog({
  open,
  matter,
  onClose,
  onTransferred,
}: {
  open: boolean;
  matter: MatterMeta;
  onClose: () => void;
  onTransferred: (next: MatterMeta) => void;
}) {
  const [toOwner, setToOwner] = useState<{ openId: string; name: string } | null>(null);
  const [reason, setReason] = useState("");
  const [withStatusChange, setWithStatusChange] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const showStatusToggle = matter.current_status === "planning";
  const canSubmit =
    !!toOwner &&
    toOwner.openId !== matter.owner &&
    reason.trim().length > 0 &&
    !submitting;

  const submit = async () => {
    if (!canSubmit || !toOwner) return;
    setSubmitting(true);
    try {
      const r = await transferMatterOwner(matter.id, {
        to_owner: toOwner.openId,
        reason: reason.trim(),
        status_change: withStatusChange
          ? { from: "planning", to: "executing" }
          : undefined,
      });
      toast.success("转交成功");
      onTransferred(r.matter);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogTitle>转交负责人</DialogTitle>
        <div className="space-y-3 py-2">
          <div>
            <Label>当前 Owner</Label>
            <div className="mt-1 text-sm text-[var(--text-mute)]">
              {matter.owner_display ?? "未分配"}
            </div>
          </div>
          <div>
            <Label>新 Owner</Label>
            <OwnerPicker value={toOwner?.openId ?? ""} onChange={(id, name) => setToOwner({ openId: id, name })} />
          </div>
          <div>
            <Label>变更原因 *</Label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={200}
              rows={2}
              placeholder="为什么转交？例如：李四正式接手执行"
            />
          </div>
          {showStatusToggle && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={withStatusChange}
                onChange={(e) => setWithStatusChange(e.target.checked)}
              />
              同时推进至 executing
            </label>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {submitting ? "转交中…" : "确认转交"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2：测试**

```tsx
test('TransferOwnerDialog disables submit when reason is empty')
test('TransferOwnerDialog disables submit when toOwner equals current owner')
test('TransferOwnerDialog hides status toggle when status != planning')
test('TransferOwnerDialog calls transferMatterOwner with status_change when toggle on')
```

### Task 7.3：OwnerChangeRow（timeline 内事件条）

**Files:**
- Create: `web/src/components/matter/OwnerChangeRow.tsx`

- [x] **Step 1：实现**

```tsx
export function OwnerChangeRow({ item }: { item: TimelineOwnerChangeItem }) {
  return (
    <>
      <div className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm">
        <UserCog className="h-4 w-4 text-[var(--text-mute)]" />
        <span>
          <strong>{item.actor_display}</strong>{" "}
          将 Owner 从 <strong>{item.from_owner_display ?? "未分配"}</strong>{" "}
          → <strong>{item.to_owner_display}</strong>
        </span>
        <span className="ml-auto text-xs text-[var(--text-mute)]">
          {relativeTime(item.created_at)}
        </span>
      </div>
      {item.reason && (
        <div className="mt-1 px-3 text-xs text-[var(--text-mute)]">
          原因：{item.reason}
        </div>
      )}
      {item.status_change && (
        <div className="mt-2 flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface-alt)] px-3 py-2 text-sm">
          <ArrowRight className="h-4 w-4 text-[var(--text-mute)]" />
          状态：{item.status_change.from} → {item.status_change.to}
        </div>
      )}
    </>
  );
}
```

### Task 7.4：Commit Checkpoint

- [ ] **Commit**

```bash
git add web/src/components/matter/OwnerChip.tsx \
  web/src/components/matter/OwnerChip.test.tsx \
  web/src/components/matter/TransferOwnerDialog.tsx \
  web/src/components/matter/TransferOwnerDialog.test.tsx \
  web/src/components/matter/OwnerChangeRow.tsx
git commit -m "feat(web): OwnerChip + TransferOwnerDialog + OwnerChangeRow components"
```

---

## Phase 8：前端列表 + 详情接入

### Task 8.1：ThreadListPane MatterRow 接 OwnerChip

**Files:**
- Modify: [web/src/components/ThreadListPane.tsx](../../web/src/components/ThreadListPane.tsx)

- [x] **Step 1：MatterRow meta 行加 OwnerChip**

```tsx
<div className="mt-1 flex items-center gap-2">
  <OwnerChip
    name={matter.owner_display}
    avatarUrl={matter.owner_avatar_url}
    unassigned={!matter.owner}
  />
  <div className="min-w-0 flex-1 truncate text-[10px] ...">{meta}</div>
  <StatusBadge ... />
</div>
```

布局稳定性：OwnerChip 已带 `shrink-0 max-w-[7rem]`，不抖动。

### Task 8.2：MatterDetailPane 顶部卡片 + 转交入口 + timeline 渲染

**Files:**
- Modify: [web/src/pages/MatterDetailPane.tsx](../../web/src/pages/MatterDetailPane.tsx)

- [x] **Step 1：顶部 matter 卡片加 OwnerBadge + 按钮**

```tsx
const [transferOpen, setTransferOpen] = useState(false);

// 在 status badge 旁
<div className="flex items-center gap-3">
  <OwnerChip
    name={detail.matter.owner_display}
    avatarUrl={detail.matter.owner_avatar_url}
    unassigned={!detail.matter.owner}
    size="md"
  />
  <button
    onClick={() => setTransferOpen(true)}
    className="text-xs text-[var(--text-mute)] hover:text-[var(--accent)]"
  >
    转交负责人
  </button>
</div>

<TransferOwnerDialog
  open={transferOpen}
  matter={detail.matter}
  onClose={() => setTransferOpen(false)}
  onTransferred={(next) => {
    setDetail((prev) => prev && { ...prev, matter: { ...prev.matter, ...next } });
    // 列表缓存也要刷 —— 让 Dashboard 的 SSE 监听器接管，或这里手动 invalidate
  }}
/>
```

- [x] **Step 2：timeline 渲染按 type 分流**

```tsx
{detail.timeline.map((item) =>
  item.type === "owner_change" ? (
    <OwnerChangeRow key={`oc-${item.created_at}`} item={item} />
  ) : (
    <FileCard key={item.file} item={item} ... />
  ),
)}
```

key 用 `created_at`（owner_change 没有 file）或 `${idx}-${created_at}`。

### Task 8.3：TimelineStrip 节点按 type 分形

**Files:**
- Modify: [web/src/components/matter/TimelineStrip.tsx](../../web/src/components/matter/TimelineStrip.tsx)

- [x] **Step 1：节点形状分支**

```tsx
{items.map((item, i) =>
  item.type === "owner_change" ? (
    <DiamondNode key={i} ... />
  ) : (
    <CircleNode key={i} ... />
  ),
)}
```

DiamondNode 灰色 + 比 CircleNode 略小，体现"事件"vs"文件"的视觉重量差。

### Task 8.4：手测

- [ ] **Step 1：跑前端 dev 服务**

```bash
cd web && npm run dev
```

走一遍：

- 列表 OwnerChip 出现，名字超长不抖
- 详情顶部 OwnerBadge 出现 + 按钮可点
- 转交弹窗：reason 必填、与当前 owner 相同时按钮 disabled
- 转交成功后顶部 OwnerBadge 即时刷新
- timeline 看到 owner_change 行 + reason
- planning 状态下勾"同时推进至 executing"提交 → matter status 变 executing + timeline 多一行 status 行
- executing 状态下 dialog 不显示 status toggle

### Task 8.5：Commit Checkpoint

- [ ] **Commit**

```bash
git add web/src/components/ThreadListPane.tsx \
  web/src/pages/MatterDetailPane.tsx \
  web/src/components/matter/TimelineStrip.tsx
git commit -m "feat(web): list + detail show matter owner; timeline renders owner_change"
```

---

## Phase 9：前端 NewMatter owner picker（design §6.5）

### Task 9.1：classic form 加"责任人"OwnerPicker

**Files:**
- Modify: [web/src/pages/NewMatter.tsx](../../web/src/pages/NewMatter.tsx)

- [x] **Step 1：增加 matterOwner state + UI**

放在 title 输入框下方、initialType 之前：

```tsx
const [matterOwner, setMatterOwner] = useState<{ openId: string; name: string }>({
  openId: me.open_id,
  name: me.name,
});

<div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
  <div className="space-y-2">
    <div className="section-kicker">责任人</div>
    <p className="text-sm leading-6 text-[var(--text-mute)]">
      推进这件事的人，可选 · 默认你自己。
    </p>
  </div>
  <OwnerPicker
    value={matterOwner.openId}
    onChange={(openId, name) => setMatterOwner({ openId, name })}
    sessionOpenId={me.open_id}
    sessionName={me.name}
    displayName={matterOwner.name}
  />
</div>
```

文件级 owner（act 的 OwnerPicker）保持现有位置，文案保持"Owner（执行人 · 默认你自己）"——视觉上分明。

- [x] **Step 2：createMatter 调用透传**

```tsx
await createMatter({
  category, title,
  owner_open_id: matterOwner.openId !== me.open_id ? matterOwner.openId : undefined,
  initial_file: { ... },
});
```

`!== me.open_id` 是 design §6.7 的优化（指向自己等价于不传）。

### Task 9.2：guided flow 加"指定责任人"步骤

**Files:**
- Modify: [web/src/pages/NewMatterGuidedFlow.tsx](../../web/src/pages/NewMatterGuidedFlow.tsx)

- [x] **Step 1：扩展 Phase + StepData**

```ts
type Phase = "topic" | "type" | "category" | "title" | "owner" | "mentions" | "drafting" | "review";

const PHASE_ORDER: Phase[] = ["topic", "type", "category", "title", "owner", "mentions", "drafting", "review"];

const PHASE_LABEL: Record<Phase, string> = {
  topic: "话题", type: "类型", category: "种类", title: "标题",
  owner: "责任人",  // ← 新增
  mentions: "圈人", drafting: "AI 起草", review: "确认发布",
};
```

`StepData` 加 `matterOwner: { openId: string; name: string }` 字段，初始值 = 当前用户。

- [x] **Step 2：OwnerStep 子组件**

类似 MentionsStep 的形态，OwnerPicker + "跳过（默认你自己）"按钮。

- [x] **Step 3：phaseDisplayIndex 适配**

原 6 步 → 7 步。`phaseDisplayIndex` 计算改：

```ts
const phaseDisplayIndex = phase === "review" ? 7 : phaseIndex + 1;
const totalSteps = 7;  // 显示"第 X / 7 步"
```

bridge 入口（hasBridge）的 phase 仍直接跳到 drafting，但 data.matterOwner 从 bridge 取（新增字段）。

- [x] **Step 4：publish 透传**

```ts
await createMatter({
  category: data.category,
  title: data.title,
  owner_open_id: data.matterOwner.openId !== me.open_id ? data.matterOwner.openId : undefined,
  initial_file: { ... },
});
```

### Task 9.3：bridge 类型扩展

**Files:**
- Modify: [web/src/pages/NewMatterGuidedFlow.tsx](../../web/src/pages/NewMatterGuidedFlow.tsx)

- [x] **Step 1：ClassicBridgeSnapshot 加 matterOwner**

```ts
export type ClassicBridgeSnapshot = {
  body: string;
  title: string;
  category: string;
  docType: DocType;
  mentions: MentionBlock;
  matterOwner: { openId: string; name: string };  // ← 新增
};
```

[NewMatter.tsx](../../web/src/pages/NewMatter.tsx) 的 classic form `onSwitchToGuidedWithSnapshot` 调用处把 matterOwner 也带过去。

### Task 9.4：手测

走一遍：

- classic form：选他人为责任人 → 创建后详情卡片 owner = 他人；timeline 没有 owner_change
- classic form：默认（自己）→ 创建后详情卡片 owner = 自己
- guided flow：第 5 步 OwnerStep 出现；选择 + 继续 / 跳过都正常
- bridge 路径：classic → 引导流时 matterOwner 也带过去

### Task 9.5：Commit Checkpoint

- [ ] **Commit**

```bash
git add web/src/pages/NewMatter.tsx web/src/pages/NewMatterGuidedFlow.tsx
git commit -m "feat(web): NewMatter classic + guided flow expose matter-level owner picker"
```

---

## Phase 10：Dashboard SSE 监听 + 一致性

### Task 10.1：监听 owner_changed 更新原因

**Files:**
- Modify: [web/src/pages/Dashboard.tsx](../../web/src/pages/Dashboard.tsx)

- [x] **Step 1：定位现有 SSE 订阅位置**

```bash
```

Grep `matter_created` 找到既有 SSE 订阅 effect。

- [x] **Step 2：加新 topic handler**

```ts
es.addEventListener("matter.updated", (e) => {
  const data = JSON.parse(e.data);
  if (data.reason !== "owner_changed") return;
  // refresh matters list （触发 fetchMatters() 刷新缓存）
  void load();
  // 如果当前打开的就是该 matter，让 MatterDetailPane 也刷
  if (location.pathname.startsWith(`/m/${encodeURIComponent(data.matter_id)}`)) {
    // 通过 useDashboard().refreshDetail(matter_id) 之类的接口
  }
});
```

具体接 API 视当前 SSE / store 实现而定。

实现备注：当前 `Dashboard` 已通过 `useMatterEvents` 对 `resume / matter.created / matter.updated` 统一触发 `matters-list` 防抖刷新；`matter.updated` 携带 `reason: "owner_changed"` 时无需新增独立 EventSource handler，也会走同一刷新路径。

### Task 10.2：Commit

- [ ] **Commit**

```bash
git add web/src/pages/Dashboard.tsx
git commit -m "feat(web): SSE owner_changed refresh invalidates cache"
```

---

## Phase 11：迁移脚本 + recovery warning（design §五 / §6.边界）

### Task 11.1：backfill_matter_owner.py

**Files:**
- Create: `server/scripts/backfill_matter_owner.py`
- Create: `server/tests/test_backfill_matter_owner.py`

- [x] **Step 1：脚本实现**

```python
"""Backfill matter.owner for legacy index files.

Idempotent: skips files that already have matter.owner.
Defensive: warns and skips on missing timeline / missing creator / unexpected first item type.
Run once after deploy; safe to re-run.
"""

from pathlib import Path
import sys
import logging

import yaml
from server.matter_index import _atomic_write_yaml, read_matter_index

log = logging.getLogger(__name__)


def backfill(index_dir: Path) -> dict:
    stats = {"total": 0, "filled": 0, "skipped_already": 0, "skipped_corner": 0}
    for path in index_dir.glob("*.index.yaml"):
        stats["total"] += 1
        data = read_matter_index(path)
        if data is None:
            log.warning("skip unreadable: %s", path)
            stats["skipped_corner"] += 1
            continue
        matter = data.get("matter") or {}
        if matter.get("owner"):
            stats["skipped_already"] += 1
            continue
        timeline = data.get("timeline") or []
        if not timeline:
            log.warning("skip empty timeline: %s", path)
            stats["skipped_corner"] += 1
            continue
        first = timeline[0]
        if first.get("type") == "owner_change":
            log.warning("skip first-item-is-event: %s", path)
            stats["skipped_corner"] += 1
            continue
        creator = first.get("creator")
        if not creator:
            log.warning("skip missing creator: %s", path)
            stats["skipped_corner"] += 1
            continue
        # 幂等：matter.owner 不存在才写
        matter["owner"] = creator
        data["matter"] = matter
        _atomic_write_yaml(path, data)
        stats["filled"] += 1
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("usage: backfill_matter_owner.py <index_dir>")
        sys.exit(1)
    stats = backfill(Path(sys.argv[1]))
    print(stats)
```

- [x] **Step 2：测试矩阵（design §5.1 边界表）**

```python
def test_backfill_fills_when_missing()
def test_backfill_idempotent_skip_when_already_set()
def test_backfill_skip_empty_timeline_warn()
def test_backfill_skip_first_is_owner_change_warn()
def test_backfill_skip_missing_creator_warn()
def test_backfill_handles_unreadable_yaml()
```

- [x] **Step 3：跑测试**

```bash
uv run pytest server/tests/test_backfill_matter_owner.py -q
```

### Task 11.2：recovery warning

**Files:**
- Modify: [server/recovery.py](../../server/recovery.py)

- [x] **Step 1：启动期检测 missing matter.owner**

定位现有 recovery 函数，加：

```python
def warn_missing_matter_owners(index_dir: Path) -> int:
    """Log warning for indexes lacking matter.owner. Returns count."""
    count = 0
    for path in Path(index_dir).glob("*.index.yaml"):
        data = read_matter_index(path)
        if data and not (data.get("matter") or {}).get("owner"):
            log.warning("matter %s lacks matter.owner; run backfill_matter_owner.py", path.stem)
            count += 1
    return count
```

在 startup 钩子调用。**不**自动回填——让运维主动跑脚本（design §五 决策）。

### Task 11.3：Commit

- [ ] **Commit**

```bash
git add server/scripts/backfill_matter_owner.py \
  server/tests/test_backfill_matter_owner.py \
  server/recovery.py
git commit -m "feat(server): backfill_matter_owner script + recovery warning"
```

---

## Phase 12：边界值 e2e + 完整测试矩阵

### Task 12.1：自动化全跑

- [x] **Step 1：后端 pytest**

```bash
uv run pytest server/tests -q
```

- [x] **Step 2：前端 typecheck + vitest + build**

```bash
cd web && npm run typecheck
cd web && npx vitest run
cd web && npm run build
```

任一失败停下查根因，**不绕过**。

实现备注：`web/package.json` 没有独立 `typecheck` script；已通过 `npm run build` 中的 `tsc -b` 覆盖类型检查，并额外跑 `npm test`。

### Task 12.2：手测矩阵（按 design §7.2）

逐项打勾：

#### 创建路径

- [ ] 不指定 owner 创建 → 详情卡片 owner = 自己
- [ ] 指定他人创建 → 详情卡片 owner = 他人；timeline 无 owner_change
- [ ] 指定 owner_open_id 不存在 → 422
- [ ] matter 级 owner = A，文件级 `initial_file.owner` = B → 落盘 matter.owner=A，timeline[0].owner=B

#### 列表 / 详情 / 转交

- [ ] 列表展示 owner 头像 + 姓名；名字超长不抖
- [ ] 详情顶部 OwnerBadge 出现
- [ ] 转交弹窗：reason 空 → 按钮 disabled
- [ ] 转交弹窗：to_owner == 当前 → 按钮 disabled
- [ ] 转交后 OwnerBadge 即时刷新（不刷页）
- [ ] timeline 出现 "X 将 Owner 从 A → B · 原因：..."
- [ ] 用 `read_matter_index`（MCP / API）读出 actor / from_owner / to_owner / reason / created_at 齐全

#### 状态合并

- [ ] planning 状态下勾"同时推进至 executing" → matter status 变 + timeline 上 owner 行下方紧邻 status 行
- [ ] executing 状态下 dialog 不显示 status toggle
- [ ] 强行调 API 在 executing 上带 status_change → 422 status_change_not_allowed_by_event

#### 边界（design §六）

- [ ] §6.1 未分配状态转交：matter.owner=null + 不传 from_owner → 200，落盘 from_owner: null
- [ ] §6.1 未分配后再转交：第二次 from_owner 必须 = 第一次的 to_owner 否则 409
- [ ] §6.2 接手未分配 + 启动 executing 一次完成
- [ ] §6.3 timeline 顺序：写入顺序 = 显示顺序
- [ ] §6.4 MCP read_matter_index 含 owner_change 不报 schema 错
- [ ] §6.6 owner = 不存在的 ou_xxx → owner_display = 截断字符串、avatar = null
- [ ] §6.7 owner_open_id = 自己 → 等价于不传，matter.owner = creator.pinyin
- [ ] §6.8 yaml key 顺序：type → created_at → actor → from_owner → to_owner → reason → status_change?

#### reviewed / 兜底 / 撤销

- [ ] reviewed 状态转交（不带 status_change）→ 200
- [ ] 历史 matter（matter.owner 缺失，没跑回填）→ owner_display fallback to creator
- [ ] 误转交后再发一条转回去（reason 注明纠错）→ timeline 留两条邻接 entry
- [ ] 跑 backfill 脚本一遍 → 所有 index 有 matter.owner
- [ ] 第二次跑脚本（幂等）→ 不改任何文件

---

## Phase 13：合入

### Task 13.1：自查 + PR

- [ ] **Step 1：复审 commit 历史**

```bash
git log --oneline main..HEAD
```

期望约 13–16 条原子 commit，每条对应一个 Task。

- [ ] **Step 2：rebase main 解冲突（如有）**

```bash
git fetch origin main
git rebase origin/main
```

- [ ] **Step 3：开 PR**

```bash
gh pr create --title "feat: matter owner mechanism (assign / transfer / timeline)" \
  --body "$(cat <<'EOF'
## Summary
- 新增 matter 级 owner 字段（与现有 file 级 owner 并行不冲突）
- 创建时可指定他人为 owner（默认创建者）
- 详情页支持转交（必填 reason），可选合并 planning → executing 状态推进
- timeline 增加 owner_change 事件以保留变更历史
- 列表 / 详情卡片展示 owner 头像 + 姓名（未分配时显"未分配"）
- 后端内部发 `matter.owner_changed`，SSE 对外推 `matter.updated` + `reason: "owner_changed"`；前端订阅刷新缓存
- 历史 matter 缺 owner 的回填脚本 + 启动期 warning

依据：AI-docs/designs/2026-04-29-matter-owner-design.md

## Test plan
- [ ] 后端 pytest 全绿（含 owner_change validator + API 集成 + backfill 脚本）
- [ ] 前端 vitest + typecheck + build 全绿
- [ ] design §7.2 手测矩阵全部打勾
- [ ] design §六 边界值矩阵全部打勾
- [ ] 在 staging 跑一遍 backfill 脚本，验证幂等

## Decisions（design §4.1）
- 转交可与 status_change 合并到一次操作，仅限 planning → executing
- 创建时可指定他人为 owner（不生成 owner_change 事件）
- owner 变更全员可见，开放协作（无审批 / 无权限灰显）
- reason 长度上限 200 字
- owner_change 在 reviewed / cancelled 状态下也允许
- 历史 matter 缺 owner：显式跑脚本回填 + UI"未分配"占位
EOF
)"
```

---

## 附：实施期易踩的坑

1. **两个 owner 不能混（design §6.5）**：classic form 同框出现 matter 级 OwnerPicker 和文件级 OwnerPicker（act 类型），用户极易选错。**文案分明** + **位置分开**（matter 级在 title 旁；文件级在 act 表单内）必须做到。
2. **未分配 from_owner 处理（design §6.1）**：validator 比较 `from_owner == matter.owner`，两个 None 必须视为相等。如果用 `if from_owner != current_owner` 这种 truthy 比较会出错——必须用 `!=` 显式比较 None。
3. **timeline 顺序契约（design §6.3）**：前端千万不要按 created_at 重排——matter_index 是 append-only，写入顺序就是事实顺序。如果误用 `sort((a,b) => a.created_at.localeCompare(b.created_at))` 会让 owner_change 错位插到文件 entry 之前。
4. **owner_change yaml key 顺序（design §6.8）**：`_normalize_item` 必须按 type 分流走不同 key 顺序常量，否则 owner_change 字段会被既有 `_ITEM_KEY_ORDER` 牵连，落盘看起来很乱。
5. **`_resolve_owner_for_index` 失败兜底（design §6.6）**：`to_owner` 解析失败时落盘的是原 open_id（如 `ou_abc123`），response 阶段 `resolve_id` 找不到也会 fallback 显原值——验收时确认 UI 不会出现 undefined / 空白。
6. **MCP schema 严格 enum（design §6.4）**：上 owner_change 之前必须先扩 enum，否则外部 MCP 客户端拿到响应后 schema validation fail。先 Phase 5 再 Phase 11——发布顺序不能错。
7. **回填脚本必须幂等**：第二次运行不应改任何文件。`if matter.get("owner"):` 的早返回是关键。
8. **bridge 类型同步**：classic → guided 的 ClassicBridgeSnapshot 加 matterOwner 后，所有调用 / 接收点都要同步——否则 ts 通过但运行时 bridge 字段缺失。
