# Matter 实时刷新机制（SSE）· 实施计划

## Context

Pivot Web 当前是纯请求/响应模型，多人协作时 A 新建/回帖 B 不会感知，除非手动刷新。

目标：**不引入 WebSocket、不破坏现有数据模型**，加一层轻量级 SSE 变更通知——服务端只告诉前端"某个 matter 变了"，前端静默走现有 HTTP 接口刷新。要求列表/详情数据无变化时不重渲染、不闪烁、不重置滚动；后台/断连/移动端 WebView 暂停时回前台必定补刷一次。

## 关键事实（决定方案可行性）

- **已有事件总线** `server/events.py:33,46`（subscribe / emit），下面三个主题已经在写入路径上 emit 完毕，本期 SSE 只订阅、不改业务代码：
  - `TOPIC_MATTER_CREATED` —— `server/publish.py:405-411`（新建 matter）
  - `TOPIC_FILE_APPENDED` —— `server/publish.py:510`（回帖 / 追加文件）
  - `TOPIC_COMMENT_APPENDED` —— `server/publish.py:598-604`（追加评论）
- **未读由后端按文件名字典序算**（`server/inbox.py:217-241`）。前端只要 refetch `/api/matters`，未读自动正确，**不应自加**。
- **FastAPI 已用过 SSE**（`server/api/ai.py:309,504`），新端点直接复用 `StreamingResponse`。
- **详情页已有 visibility 兜底**（`MatterDetailPane.tsx:269-275`），本期把它抽到全局 Provider，详情页删掉本地监听。

## 事件协议（锁定）

端点 `GET /api/matters/events`，鉴权沿用 `current_user`。

```
event: matter.created
id: 1714110123456-1
data: {"matter_id":"abc","reason":"created","actor":"alice","ts":1714110123456}

event: matter.updated
id: 1714110125001-7
data: {"matter_id":"abc","reason":"file_appended","actor":"bob","ts":1714110125001}

: ping     # 每 25s 一帧，穿透代理空闲超时
```

`reason` 取值：`created` / `file_appended` / `comment_appended`。事件**不携带正文**——拿到 `matter_id` 后由前端走 `/api/matters` 或 `/api/matters/{id}` 取真相。

Topic 映射：

```
TOPIC_MATTER_CREATED   → matter.created  reason=created
TOPIC_FILE_APPENDED    → matter.updated  reason=file_appended
TOPIC_COMMENT_APPENDED → matter.updated  reason=comment_appended
```

不广播：`POST /api/matters/{id}/read`、`/favorite` 是本端动作，本端自己 refetch 即可。

## 服务端实现

新增 `server/api/matters_events.py`，注册到 `server/app.py`：

- 进程级 `deque(maxlen=512)` 作为最近事件 ring buffer，新连接带 `Last-Event-ID` 时回放该 id 之后的事件
- 每连接独立 `asyncio.Queue(maxsize=256)`；`put_nowait` 失败时丢弃，由前端 resume 兜底
- `subscribe()` × 3 在 handler 里组装 SSE 帧入队；`finally` 里 unsubscribe
- 主循环 `await asyncio.wait_for(queue.get(), timeout=25)`：拿到事件输出帧；超时输出 ping；`request.is_disconnected()` 退出
- Headers：`Cache-Control: no-cache`、`X-Accel-Buffering: no`（防 nginx 缓冲）

实施前先核对 `publish.py:405 / 510 / 598` 三处 emit payload 是否含 `matter_id` / `actor` / `ts`，缺啥补啥。

## 客户端实现

新增：

- `web/src/events/types.ts` —— `MatterEvent` 类型
- `web/src/events/MatterEventsProvider.tsx` —— Provider + `useMatterEvents` hook
- `web/src/events/scheduleRefresh.ts` —— 按 key 去抖（300ms）

Provider 做三件事：

1. `EventSource("/api/matters/events", { withCredentials: true })`，监听 `matter.created` / `matter.updated`
2. 监听 `visibilitychange`(visible) / `focus` / `pageshow`(persisted) → 派发 `{type:"resume"}`
3. `EventSource.onopen`（除首次外）也派发 `resume`，覆盖断线重连

挂载：`App.tsx` 最外层包一层 `<MatterEventsProvider>`。

### 列表页 `Dashboard.tsx`

- 现有 `fetchMatters` 包成 `refreshList`
- `sameMatters(prev, next)`：按 id 比较 `updated_at + unread_count + post_count + favorite` 指纹；相等返回 prev
- **不动 `isLoading`**——首屏 loading 走另一条路径
- `useMatterEvents(e => scheduleRefresh("matters-list", refreshList))`
- React key 用 `matter.id`

### 详情页 `MatterDetailPane.tsx`

- 删除 `:269-275` 处的本地 visibility 监听
- 现有 `load()` 拆为 `loadInitial()`（首次，显示 skeleton）和 `refreshDetail()`（静默）
- `sameDetail`：比较 post 数 + 最后一条 post 的 filename + 评论数指纹
- `useMatterEvents(e => { if (e.type==="resume" || e.matter_id===id) scheduleRefresh("detail:"+id, refreshDetail); })`
- React key 用 `post.filename`

防闪烁的本质：静默路径不动 isLoading、用稳定 key、`same*()` 相等返回旧引用、300ms 去抖合并多事件。

## 兜底机制

三种漏事件场景共用一个动作 = 派发 `resume` → 各订阅方静默 refetch：

| 场景 | 检测 |
|---|---|
| Tab 切回前台 / 窗口拿回焦点 | `visibilitychange` / `focus` |
| iOS BFCache 恢复 | `pageshow` 且 `event.persisted === true` |
| SSE 断后重连 / 飞书 WebView 解冻 | `EventSource.onopen` 第二次起 |

## 设计边界

- SSE 不承载业务真相，只发 `matter_id + reason + actor + ts`
- 不引入在线用户列表 / 房间 / 已送达回执 / WebSocket
- 不改 `server/inbox.py` 的未读计算
- 单进程事件总线即可，多副本部署再桥接 Redis pub/sub（事件协议不变）

## 实施阶段

```
Phase 0 ─┬─► Phase 1 (后端) ─┐
         └─► Phase 2 (前端骨架) ─┬─► Phase 3 (列表) ─┐
                                  └─► Phase 4 (详情) ─┴─► Phase 5 (联调)
```

Phase 1 与 2、Phase 3 与 4 可并行。

| Phase | 内容 | 工作量 |
|---|---|---|
| 0 | 切分支 `feat/matter-sse`；核对 emit payload 字段；缺啥补啥 | 30 min |
| 1 | 新建 `server/api/matters_events.py`，`app.py` 注册 router | 0.5 d |
| 2 | 新建 `web/src/events/{types,MatterEventsProvider,scheduleRefresh}`；`App.tsx` 挂 Provider | 0.5 d |
| 3 | `Dashboard.tsx` 接入 + `sameMatters` | 0.5 d |
| 4 | `MatterDetailPane.tsx` 接入 + `sameDetail` + 删除旧 visibility 监听 | 0.5 d |
| 5 | 桌面/移动/飞书 WebView 联调，验收标准全跑一遍 | 0.5 d |

合计约 **2.5 人日**。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | 双 Tab：A 新建 matter | B 列表 1s 内出现，无 skeleton 闪现 |
| 2 | A 在 matter X 回帖，B 在列表 | B 看到 X `unread_count` +1，无整页闪烁 |
| 3 | A 回帖时 B 停留在 X 详情页 | B 看到新帖追加在底部，滚动位置不变 |
| 4 | DevTools 关网 30s 再开 | 重连后 resume 触发，列表 + 详情各补刷一次 |
| 5 | iOS 锁屏 5min 解锁 / BFCache 前进后退 | 回前台 refetch 一次 |
| 6 | 飞书 WebView 后台冻结再解冻 | visibility + 重连去抖后 refetch 一次 |
| 7 | 同 matter 1s 内 5 条事件 | 只触发一次 refetch（Network 验证） |
| 8 | 数据无变化时（如重复标记已读） | `<MatterRow>` 不 commit（React DevTools Profiler 验证） |

## 风险与回滚

| 风险 | 对策 |
|---|---|
| 反代缓冲 SSE | Headers `X-Accel-Buffering: no`；Phase 5 在生产同款反代验证 |
| ring buffer 512 条不够 | resume 兜底覆盖；监控 `Last-Event-ID` 命中率 |
| `same*()` 漏字段导致漏更新 | Phase 5 显式覆盖未读 / favorite / 删除 case；指纹缺漏退化为 `JSON.stringify` 兜底 |
| 飞书 WebView 不支持 EventSource | EventSource 是 W3C 标准，飞书内核支持；如真不支持降级长轮询同一端点 |

**回滚**：删掉 `<MatterEventsProvider>` 包裹一行即关闭整个机制；后端端点保留无副作用。

## 交付清单

```
新增：
  server/api/matters_events.py
  web/src/events/MatterEventsProvider.tsx
  web/src/events/types.ts
  web/src/events/scheduleRefresh.ts

修改：
  server/app.py                              # +1 行注册
  web/src/App.tsx                            # +1 层 Provider
  web/src/pages/Dashboard.tsx                # 接入 + sameMatters
  web/src/pages/MatterDetailPane.tsx         # 接入 + sameDetail + 删除旧 visibility 监听
  server/publish.py                          # 仅当 Phase 0 发现 emit 字段缺失才改
```
