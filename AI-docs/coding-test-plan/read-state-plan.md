# Pivot 已读状态 · 实施计划

## Context

Pivot 当前没法回答"谁看过这篇 decision / risk"。需要在 matter 详情页文件卡底部加一行"X 人已读 + 名单"，触发口径是**真实展开行为**：长文点"展开全文"、短文进视口即记。

硬约束：
- 已读不写入 markdown / frontmatter / matter-index，只进 SQLite —— 否则每人读一次都要改文件，git 历史会被淹掉。
- 同一用户对同一文件只记**首次时间**，再读不更新。
- 现有 `read_state` 表（matter 级未读高水位线，`server/db.py:30-36`）与本期"按文件粒度记一次首读"完全是两件事，**不混用、不改动**。
- 本期只做"已读"，不做"未读"/"应读未读"。

## 关键事实（决定方案可行性）

- **DB 迁移天然兼容**：`server/db.py` 用 `CREATE TABLE IF NOT EXISTS` 装载 `SCHEMA`，新表直接追加到 SCHEMA 末尾即可，无需写迁移脚本。
- **Repo 模板已存在**：`server/read_state.py` 的 `ReadStateRepo` 是连接管理 + dataclass + `INSERT ... ON CONFLICT` 的标准写法，新 Repo 仿之即可。
- **FileCard 已具备触发所需状态**：`web/src/components/matter/FileCard.tsx:87-88` 的 `expanded` / `canExpand` 两个 state 直接对应"长文/短文"两条触发规则，不需要新状态机。
- **详情接口是聚合 readers 的天然位置**：前端首次加载、SSE 刷新（`matter.updated`）、切前台 refetch 三条路径都已经走详情接口，把 readers 注到 timeline item 上即可一并刷新。
- **UserRepo 已能按 open_id 取姓名/头像**：API 层拼装 ReaderEntry 时直接复用，不冗余存到 `file_reads` 表。

## 数据契约（锁定）

### SQLite 表

加在 `server/db.py` 的 `SCHEMA` 末尾：

```sql
CREATE TABLE IF NOT EXISTS file_reads (
    user_open_id  TEXT NOT NULL,
    matter_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    first_read_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, matter_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_file_reads_matter
    ON file_reads(matter_id, filename);
```

- `filename` 存 basename（如 `01-decision.md`），matter_id 已唯一定位目录。
- `INSERT OR IGNORE` 写入，主键冲突即 no-op，自然满足"只记首次"。

### HTTP 端点

```
POST /api/matters/{matter_id}/files/{filename}/read
  → 200 {"matter_id","filename","first_read_at": "2026-04-28T10:22:03+08:00"}
  → 404 matter 不存在 / file 不在该 matter 的 timeline
```

幂等：第二次调用返回的 `first_read_at` = 第一次入库时间。

### 详情接口扩展

`GET /api/matters/{matter_id}` 的每个 timeline item 增加：

```jsonc
{
  "file": "discussions/cat/m-x/01-decision.md",
  ...,
  "readers_count": 3,
  "readers": [
    {"open_id":"ou_xxx","name":"邓克","avatar_url":"...","first_read_at":"2026-04-28T10:22:03+08:00"},
    ...
  ]
}
```

`readers` 按 `first_read_at` 升序，本期不做截断。

## 服务端实现

新增 `server/file_reads.py`，仿 `server/read_state.py`：

```python
@dataclass(frozen=True)
class ReaderEntry:
    open_id: str
    first_read_at: float

class FileReadRepo:
    def mark(self, user_open_id, matter_id, filename) -> ReaderEntry:
        # INSERT OR IGNORE; 之后 SELECT 拿回真正的 first_read_at（首次=now，重复=旧值）
    def list_for_matter(self, matter_id) -> dict[str, list[ReaderEntry]]:
        # 单 SQL 一次性捞全 matter，按 (filename, first_read_at) 排序，Python 侧 group by
```

`server/api/matters.py` 改两处：

1. **新增** `POST /api/matters/{matter_id}/files/{filename}/read` 处理函数：
   - 取 `current_user`。
   - 读 `matter-index.yaml`（详情接口里已有这步骤，复用同一个 helper）。
   - 校验 `filename` 出现在该 matter 的 timeline `file` 字段中（endsWith 匹配 basename）—— 不在则 404。
   - `FileReadRepo.mark()` → 拼 ReaderEntry → 加上当前用户的 name/avatar_url → ISO 化 → 返回。
2. **改** 详情接口（`GET /api/matters/{matter_id}` 的 handler）：在装配 timeline 那段，调用 `FileReadRepo.list_for_matter(matter_id)` 拿到 `{filename: [ReaderEntry...]}`，给每个 item 注入 `readers_count` 与 `readers`（用 `UserRepo` 把 open_id 拼成 name + avatar_url）。

`server/app.py` 在依赖装配处补一行 `FileReadRepo(db)` 注入到路由（参照 `ReadStateRepo` 的注入方式）。

## 客户端实现

### 类型与 API 调用

`web/src/api.ts` 新增：

```ts
export type Reader = {
  open_id: string;
  name: string;
  avatar_url: string;
  first_read_at: string;
};
// MatterDetail.timeline[i] 扩展：readers_count?: number; readers?: Reader[]
export async function markFileRead(matterId: string, filename: string): Promise<{first_read_at: string}>;
```

### 触发逻辑（FileCard.tsx）

利用已有的 `expanded` / `canExpand` 两个 state，加一个 `markedRef = useRef(false)` 整会话级防抖：

- **长文路径**（`canExpand === true`）：在"展开全文 ↓"按钮的 onClick 里，`markedRef.current === false` 时调 `markFileRead`，置 true，乐观更新本地 readers。
- **短文路径**（`canExpand === false`）：用 effect 挂 IntersectionObserver(threshold=0.5)，回调里同上；`markedRef` 翻 true 后立即 `observer.disconnect()`。
- **切换文件 reset**：`useEffect(() => { markedRef.current = false; }, [item.file])`，跟现有 `setExpanded(false)` effect 同生命周期。
- **失败回滚**：mark 失败时回退 readers 本地数组、复位 `markedRef` 允许重试。

**显式不做**：mark 成功后不重拉详情（重拉会触发整页 markdown 重渲染）。服务端对齐交给详情页本来就有的刷新触发点（SSE 推送 / 切前台 / pageshow），到时候服务端版本整体覆盖本地乐观状态即可。

### UI 展示

- 新组件 `web/src/components/matter/ReadersRow.tsx`：渲染"👁 X 人已读 · 名字、名字、名字"那行。`readers_count === 0` 时返回 null（不渲染空态）。
- 新组件 `web/src/components/matter/ReadersPopover.tsx`：点击或 hover 弹出完整名单（头像 + 姓名 + 相对时间）。复用现有 Popover 风格，不引入新组件库。
- FileCard 在卡片底部（actions 行下方）插入 `<ReadersRow readers={item.readers ?? []} count={item.readers_count ?? 0} />`。

## 设计边界

- 触发口径只有两条：长文点展开 / 短文进视口。**不做**停留时长、滚动到底、阅读来源等细粒度判定。
- mark 接口不广播 SSE 事件 —— 作者下次 refetch（切前台 / 收到该 matter 其他事件）看到即可。如未来要做"实时推送已读"，按 `read-state-tech-design.md` §六留下的口子加 `TOPIC_FILE_READ` 即可，不影响 v1 接口。
- 不暴露独立的"按文件查读者"端点，所有读者数据走详情接口聚合。
- `MAX_READERS_PER_FILE` 截断**不做**：50 篇 × 10 人 ≈ 几 KB，可接受。

## 实施阶段

```
Phase 0 ─┬─► Phase 1 (后端 DB+Repo) ─┐
         ├─► Phase 2 (后端 API)       ├─► Phase 5 (联调验收)
         └─► Phase 3 (前端 API+类型) ─┤
              └─► Phase 4 (前端 UI)  ─┘
```

Phase 1 / 2 / 3 可并行启动；Phase 4 依赖 Phase 3；Phase 5 等所有合并后跑。

| Phase | 内容 | 工作量 |
|---|---|---|
| 0 | 切分支 `feat/file-reads`；本地 sanity check（确认 `server/db.py` SCHEMA 末尾、`server/read_state.py` 模板、`FileCard.tsx` 状态位置） | 0.2 h |
| 1 | `server/db.py` 加 `file_reads` 表；新建 `server/file_reads.py`（`ReaderEntry` + `FileReadRepo.mark` / `list_for_matter`）；`server/tests/test_file_reads.py`（首次/重复/多用户/跨 matter） | 2 h |
| 2 | `server/api/matters.py` 加 `POST /matters/{id}/files/{name}/read` 路由 + 详情接口注入 `readers`；`server/app.py` 注入 Repo；`server/tests/test_matters_api.py` 增量用例（mark 成功/重复/file 不存在/matter 不存在；详情含 readers） | 3 h |
| 3 | `web/src/api.ts` 加 `Reader` 类型 + `MatterDetail` timeline 扩展 + `markFileRead` | 0.5 h |
| 4 | `FileCard.tsx` 接入触发 + 乐观更新；新建 `ReadersRow.tsx` / `ReadersPopover.tsx`；空态处理 | 3 h |
| 5 | 联调：多 tab 并发、刷新后服务端覆盖本地乐观状态、IntersectionObserver 在飞书 WebView 表现、StrictMode 双调用幂等 | 1 h |

合计约 **1.5 人日**，前后端可并行。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | 短文（`canExpand=false`）滚动至半数进入视口 | 1s 内 POST 一次 mark；ReadersRow 出现并 +1 |
| 2 | 长文首次点"展开全文 ↓" | 立即 POST 一次 mark；ReadersRow +1 |
| 3 | 长文点开后再合上、再点开 | 整会话只 POST 一次（Network 验证） |
| 4 | 同一用户刷新页面再次展开 | POST 仍发出（前端 ref 已重置），后端 `INSERT OR IGNORE` 保留首次时间，readers 顺序不变 |
| 5 | A、B 两人同时第一次读同一篇 | 两边本地都 +1；任一方触发 refetch 后服务端版本整体覆盖，readers 不重复 |
| 6 | 删除该文件所在 matter 后再次 mark | 返回 404 |
| 7 | mark 不存在的 filename | 返回 404；前端不出现"已读" |
| 8 | `readers_count === 0` 的卡片 | 不渲染 ReadersRow（无空态噪音） |
| 9 | React StrictMode dev 环境双 effect | 仅产生一条记录，readers 无重复（DB 主键兜底） |
| 10 | 详情页打开多个 matter 切换 | 切回时 readers 来自服务端，无残留 |

## 风险与回滚

| 风险 | 对策 |
|---|---|
| IntersectionObserver 在老飞书 WebView 不可用 | 飞书 WebView 内核 Chromium 108+，原生支持；Phase 5 在飞书桌面 + 移动端各跑一次。极端兜底：`canExpand=false` 时退化为"挂载即标"（仍然只首次） |
| 乐观更新导致 readers 顺序与服务端不一致 | 下一次 refetch（SSE / 切前台）服务端版本整体覆盖；本期不强同步 |
| `filename` 校验靠 endsWith 误判（同名跨 matter） | matter_id 已经定位目录；endsWith 匹配仅在该 matter 的 timeline 内做，不存在跨 matter 干扰 |
| 旧版本前端命中新字段 | timeline item 加字段是纯加法；`readers` / `readers_count` 缺失时旧版本忽略，行为不变 |
| 大 matter 全员读完 readers 膨胀 | 50 篇 × 10 人 ≈ 几 KB，不防御。监控详情接口体积，超阈值再做"最近 20 + 总数"截断 |

**回滚**：详情接口注入 `readers` 字段是纯加法 —— 删掉前端 ReadersRow 渲染、停掉 mark 调用即可静默关闭；后端表与端点保留无副作用。

## 交付清单

```
新增：
  server/file_reads.py
  server/tests/test_file_reads.py
  web/src/components/matter/ReadersRow.tsx
  web/src/components/matter/ReadersPopover.tsx

修改：
  server/db.py                                   # SCHEMA 末尾加 file_reads 表 + 索引
  server/api/matters.py                          # mark 路由 + 详情接口注入 readers
  server/app.py                                  # 注入 FileReadRepo
  server/tests/test_matters_api.py               # 新增 mark / readers 用例
  web/src/api.ts                                 # Reader 类型 + MatterDetail 扩展 + markFileRead
  web/src/components/matter/FileCard.tsx         # 触发 + 乐观更新 + ReadersRow 渲染
```

## 后期扩展（不在本期）

按 `read-state-tech-design.md` §六对齐：

- **应读未读**：等 owner / 关注人 / @mention 应读人语义信号补齐后，"应读集合 - 已读集合" 即可。`file_reads` 是天然的已读事实表。
- **催读**：复用 `server/notify.py` 飞书通道，对未读名单挂 notify 入口。
- **细粒度判定**：在 `server/file_reads.py` 加策略层；前端只报告"看到了"事件，落表与否由服务端决定。
- **实时已读推送**：加 `TOPIC_FILE_READ` → `matters_events.py` 映射成 `matter.updated` 新 reason，纯加法不影响 v1。
- **导出与统计**：`file_reads` 是天然事实表，加聚合视图即可。
