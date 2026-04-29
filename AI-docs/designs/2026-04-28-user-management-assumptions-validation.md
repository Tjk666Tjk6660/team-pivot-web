# 用户管理体系 · spec 假设验证报告

| 项 | 值 |
|---|---|
| 文件 | `AI-docs/designs/2026-04-28-user-management-assumptions-validation.md` |
| 创建日期 | 2026-04-28 |
| 状态 | 调研产物（领导审核 spec 期间制作的 plan 输入） |
| 配套 spec | `2026-04-28-user-management-design.md` |

---

## 摘要

针对 spec 里 5 个"基于直觉给出的假设"逐条对照现有代码，验证它们是否真能落地。

| 假设 | 涉及 spec 章节 | 验证结果 |
|---|---|---|
| `notify.py` 支持向一组管理员广播飞书 DM | §10 | ✅ 已支持（`_dm_many` 现成可用） |
| 名字解析的 users→contacts 回退链已存在 | §7.1 | ✅ 已存在（`mentions.py`），改造比新建省一半工作 |
| `bcrypt` / `pypinyin` / `ulid` 等依赖现状 | §3, §4 | ⚠ `bcrypt`、`pypinyin` 都不在依赖里，要加 |
| session 状态校验有地方挂 | §6.3 | ✅ 现有 `_user_from_session` 加 1 行即可 |
| `/init` 路由守卫的实现方式 | §4.4 | ✅ 不需要服务端中间件，SPA 处理 |

**关键意外发现：现有 `pinyin` 字段是用户手填**（profile setup 页面有正则校验），**不是后端自动生成**——pypinyin 不是依赖。spec §4.3 写的"中文 display_name 用 pypinyin 算 pinyin"需要新引入这个依赖，或者改为"邀请接受表单也要求用户手填 pinyin（与现有飞书首登一致）"。这是个产品决策点，见 §6。

---

## 1. notify.py 广播能力

### 现状（`server/notify.py:267` 起）

`FeishuNotifier` 已有两条发送路径：

| 方法 | 用途 | 入参 |
|---|---|---|
| `_broadcast(card, event)` | 给 bot 所在的所有群发卡片 | bot 加入的群组 chat_id 列表（自动拉取） |
| `_dm_many(open_ids, card, event)` | 给一组用户私信卡片 | open_id 列表 |

`_dm_many` 已经在 `notify_new_thread` / `notify_new_reply` 的 mention DM 场景里用了——传一组被 @ 的 open_id，每人单独发一份。

### spec §10 对接

新加 3 个 card builder + 3 个 notifier 方法：

| 通知场景 | 用 `_broadcast` 还是 `_dm_many` |
|---|---|
| 新加入申请 → 通知所有管理员 | `_dm_many(admin_open_ids, card)` |
| 申请被同意（通知申请人） | `_dm_many([applicant_open_id], card)` |
| 申请被拒绝（通知申请人） | `_dm_many([applicant_open_id], card)` |

**结论：spec §10 没有任何技术阻塞。** `Notifier` Protocol 加几个 `notify_application_*` 方法、`FeishuNotifier` 实现里复用 `_dm_many`。

### 但有一个 plan 阶段要明确的小决策

`_dm_many` 按 **open_id**（飞书）发。如果某管理员是邀请码用户、**没绑飞书**，他就收不到这条 DM。两种处理：

- **A. 仅给绑了飞书的管理员发 DM**——简单；后续如果有非飞书管理员，他们靠后台轮询看待审批
- **B. 在管理员后台搞一个"未读审批"角标**——所有管理员都能看到待审批数量，不依赖 IM 通知

我建议 **A + B 同时做**：B 是治理设计本身就该有的（管理员第一次进后台就能看到未审批清单），A 锦上添花给绑飞书的管理员一个推送。这个细节 spec 没明说，plan 阶段补上。

---

## 2. mentions.py 现有名字解析

### 现状（`server/mentions.py`）

已有 3 个函数，回退链 = users → contacts → 原始值：

```python
resolve_id(value, users, contacts)         # → name 字符串
resolve_avatar_url(value, users, contacts) # → 头像 URL
resolve_text(text, users, contacts)        # → 把 body 里的 ou_xxx 替换成 @name
```

### spec §7.1 对比

spec 要的 `resolve_user_for_display` 返回 `{display_name, avatar_url, status}`。差别：

| 维度 | 现有 | spec 要的 |
|---|---|---|
| 回退链 | users → contacts → 原始值 | external_binding → contacts → frontmatter |
| 返回 | 单个值（name 或 url） | 完整 DisplayInfo（含 status） |
| 谁用 | 后端 post 渲染时 mention 替换 | 后端所有展示用户名的地方 + 前端通过 API 拿 status |

### 改造路径

1. `users` 这个数据源升级为 `pivot_users`（迁移完成后）
2. 加一个新函数 `resolve_display_info(provider, external_id, ...)` 返回完整 DisplayInfo
3. 现有 `resolve_id` / `resolve_avatar_url` / `resolve_text` 继续保留，内部改为调用 `resolve_display_info` 取需要的字段——业务层调用方零改动
4. 前端拿到的 API 响应（`/me`、posts 列表的 author 字段、mention 命名等）扩展为带 `status`

**结论：现有有相似实现，工作量约为绿地新建的一半。** spec §7.1 的"统一入口"在概念上和现状一致；不会推翻现有代码。

---

## 3. 现有依赖（pyproject.toml）

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "lark-oapi>=1.4",
    "itsdangerous>=2.2",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "mcp>=1.0",
]
```

### spec 引入但**不在**依赖里

| 包 | 用途 | 来源 spec 章节 | 优先级 |
|---|---|---|---|
| `bcrypt` | 邀请码用户密码哈希 | §3 / §4.3 | 必加 |
| `pypinyin` | 邀请接受表单：中文 display_name → pinyin | §4.3 | **见下** |
| `ulid-py`（可选） | `pivot_user.id` 主键生成 | §3 | 可用 stdlib uuid4 替代 |

### 关键意外发现：现有 pinyin 是用户手填的

读 `server/users.py` + `server/auth/routes.py:158`：

```python
PINYIN_RE = re.compile(r"^[a-z][a-z0-9._-]{1,39}$")

@router.post("/me/profile")
def update_profile(body: ProfileUpdate, sid: str | None = Cookie(default=None)):
    user = _current_user(sid)
    updated = users.update_profile(user.open_id, pinyin=body.pinyin, ...)
```

意味着：**现有飞书首登流程，pinyin 是 ProfileSetup 页面用户手填的**（带 PINYIN_RE 校验），不是后端用 pypinyin 自动算的。

这个事实让 spec §4.3 邀请接受流程出现一个产品决策叉路：

- **A. 邀请接受表单也让用户手填 pinyin**——和现有飞书首登一致，**不引入 pypinyin**，统一交互
- **B. 邀请接受表单后端自动算 pinyin**——和现有不一致；要引入 pypinyin；但被邀人少一步操作

我倾向 **A**——一致性更强，且邀请用户大多是英文姓名（外部协作者），手填 pinyin 反而比 pypinyin 算英文小写化更合理；同时引入 pypinyin 还需要考虑多音字、姓的特殊读法等问题。spec §4.3 我会改成 A。

---

## 4. Session 状态校验位置

### 现状（`server/auth/deps.py:21`）

```python
def _user_from_session(sid, sessions, users):
    s = sessions.get(sid)               # 1. 查 session
    if s is None:
        return None
    u = users.get(s.user_open_id)        # 2. 查 user
    if u is None:
        sessions.delete(sid)             # 3. 用户不存在 → 清 session
        return None
    return u
```

### spec §6.3 要求

"已有 session 接下来的请求 → 中间件检测后强制登出"

### 落地

只需在 `_user_from_session` 和 `_user_from_bearer` 的 `users.get(...)` 之后加一行：

```python
if u.status != 'active':
    sessions.delete(sid)
    return None
```

性能上**无新增 DB 查询**——`users.get(...)` 本来就要做，只是从 row 多读一个字段。

**结论：不需要新写 ASGI 中间件**；spec §6.3 描述的"中间件检测"实际是 deps 层的检测，措辞要更精确一点。

---

## 5. `/init` 路由守卫

### 现状（`server/app.py:111`）

FastAPI app 只挂了 `CORSMiddleware`，没有其他全局 ASGI 中间件。鉴权全部走 per-route dependency（`Depends(current_user)`）。

### spec §4.4 描述

"其它路由（除 /login /auth/*）一律 302 → /init"

### 落地分析

这听起来像需要服务端中间件，但实际**不需要**——因为 Pivot 是 SPA：

1. 前端 React Router 在 app load 时调 `GET /init/status` 公开接口
2. 返回 `{ needs_init: true }` → 前端跳 `/init` 页面
3. 返回 `{ needs_init: false }` → 前端按现有逻辑（已登录 → 主页 / 未登录 → /login）

服务端只需提供：

- `GET /init/status` — 公开（不依赖 current_user dep）
- `POST /init/complete` — 公开 + 服务端事务里再次确认"无在线管理员"才执行
- 现有所有 `/api/*` 仍按原 dep 校验——未登录用户照常 401，前端按 401 + init/status 决定去哪

**结论：spec §4.4 描述的"路由守卫"是前端 React Router 行为，不是 ASGI 中间件。** spec 措辞要明确这一点，避免实施时往中间件方向走偏。

---

## 6. 应反馈到 spec 的修订

下面这些是验证后发现的描述不够精确或要小调的地方。等领导反馈一回来，我会一并修：

| spec 章节 | 当前描述 | 修订为 |
|---|---|---|
| §4.3 邀请接受 | "中文 display_name 用 pypinyin 算 pinyin；非中文则取小写化形态" | "由用户手填 pinyin，与现有飞书首登一致；后端按 PINYIN_RE 校验。**不引入 pypinyin**" |
| §4.4 /init 路由守卫 | "其它路由（除 /login /auth/*）一律 302 → /init" | 补一句"由 SPA 前端 React Router 实现守卫，不在服务端做 ASGI 中间件" |
| §6.3 强制登出 | "中间件检测后强制登出" | "由 `auth/deps.py` 的 user 解析层在每次请求时检测；非 active 状态直接清 session 返 401" |
| §7.1 名字解析 | （新写实现） | 补一行"基于现有 `server/mentions.py` 的回退链改造，不绿地重写" |
| §10 通知 | "新加入申请创建 → 所有 admin" | 补一句"仅发飞书 DM 给绑了飞书的管理员；未绑飞书的管理员靠 `/admin/applications` 后台未读角标自助查看" |

每条都是小调，不影响整体设计；领导反馈定盘后顺手做。

---

## 7. 其它发现（不影响 spec，仅作 plan 阶段提醒）

1. **`Notifier` Protocol** 已经定义在 `notify.py` 顶部，`NoOpNotifier` 是测试用的空实现。新增 `notify_application_*` 方法时要同步更新两个类——单测不会自动报错，要靠 mypy 或 pytest 覆盖。
2. **`SessionStore.user_open_id` 字段重命名** 涉及 `auth/session.py:14`、`server/db.py` schema、`server/api/tokens.py`、`server/mcp/auth.py`——共 5 处需要同步。
3. **现有 `users.update_profile` 接收 `pinyin` 参数** 用 PINYIN_RE 校验——邀请接受流程可以**直接复用**这个校验逻辑，pinyin 校验不必单独实现。
4. **`_FEISHU_ID_RE`**（`server/mentions.py:8`）匹配 `ou_xxx` / `on_xxx` 飞书 ID 格式。如果未来加邀请码或钉钉用户，他们的 mention 用什么格式？plan 阶段需要明确——本期先继续只支持飞书 mention（与现有一致）。
