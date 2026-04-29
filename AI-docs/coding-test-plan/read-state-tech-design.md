# Pivot 已读状态 · 技术设计方案

| | |
|---|---|
| 状态 | 待评审 |
| 关联需求 | [`001_dengke_think_6520d6.md`](./001_dengke_think_6520d6.md) |
| 涉及组件 | `server/db.py` · `server/file_reads.py`（新增） · `server/api/matters.py` · `web/src/components/matter/FileCard.tsx` · `web/src/api.ts` |

---

## 一、需求背景

Pivot 当前是只读时间线模型：一个 matter 下挂着若干 markdown 文件，谁发的、什么时间发的、谁评论了，都靠 git 和 `matter-index.yaml` 记录。但有一件事现在系统不知道——**谁真正看过哪篇**。

对作者和管理者来说这是个实际痛点。某条 decision、某条 risk 发出去后，相关同事到底打开看了没有？现在只能去群里追问。飞书文档里那种"X 人已读"的轻量提示，正好能解决这个问题。

需求文档里强调了几条边界，是这次设计的硬约束：

- **不污染文档与索引**。已读是"用户和文档之间发生过一次阅读"的事实，不是文档自身的属性。如果写到 frontmatter 或 matter index 里，每个人读一次就要改一次文件，git 历史会被读已读行为塞满，时间线模型也就坏了。所以已读必须单独存。
- **基于真实展开行为**。Pivot 的 timeline 卡片默认收起，只露前几行；只有用户点了"展开全文"才算真读过。仅扫了一眼预览不算。
- **只记首次时间**。需求 v2 修正后明确：同一个用户读多次只保留第一次的时间，再读不更新。
- **本期只做"已读"，不做"未读"**。"未读"暗含"这个人本来应该读"的语义，目前 Pivot 还没有阅读分配机制，过早引入会造成误解。

仓库里现有的 `read_state` 表是 matter 级的"未读数高水位线"——每个 thread 记一个 `last_read_post_filename`，给收件箱算未读数用，跟本期的"按文件粒度记一次首次阅读"是两件事，不能混用，也不会被本设计改动。

## 二、目标

第一期上线后要满足：

1. 用户在 matter 详情页点击某篇文章的"展开全文"按钮，后端记一条该用户对该文件的首次阅读记录。
2. 如果文章本身够短（FileCard 里 `canExpand=false`，正文已经完整露出），用户滚动看到它时也算已读。
3. 在文件卡片底部显示"X 人已读"，hover/点击能看到名单（头像+姓名+首读时间）。
4. 已读记录不写入 markdown、frontmatter、matter index，只进 SQLite。
5. 同一用户对同一文件再触发一次，不更新时间，也不报错。

明确不做：

- 不做"未读"标识、不做"应读未读"提醒。
- 不做停留时长、滚动到底部之类的细粒度判定，本期就两条规则：点了展开 / 短文滚动可见。
- 不区分阅读来源（需求 v2 已删除该字段）。
- 不做实时推送已读事件（作者下次刷新看到即可）。

## 三、技术方案

### 3.1 数据模型

新增一张 SQLite 表，加在 `server/db.py` 的 `SCHEMA` 末尾：

```sql
CREATE TABLE IF NOT EXISTS file_reads (
    user_open_id TEXT NOT NULL,
    matter_id    TEXT NOT NULL,
    filename     TEXT NOT NULL,
    first_read_at REAL NOT NULL,
    PRIMARY KEY (user_open_id, matter_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_file_reads_matter
    ON file_reads(matter_id, filename);
```

几点说明：

- `filename` 存的是文件 basename（例如 `01-decision.md`），不存完整 `discussions/<cat>/<matter>/<filename>` 路径——matter_id 已经唯一定位到目录，basename 就够了，能省一截字符串。
- 主键 `(user_open_id, matter_id, filename)` 保证幂等，写入用 `INSERT OR IGNORE`，第二次及以后落地是 no-op，自然满足"只保留首次时间"。
- `idx_file_reads_matter` 是为了渲染详情页时能按 matter_id 一次性把所有文件的读者捞出来。
- `first_read_at` 用 unix 时间戳（float），跟现有 `read_state.updated_at`、`drafts.created_at` 保持一致；API 层再格式化成 ISO 8601。

`db.py` 现有的迁移逻辑是按列存在与否 ALTER TABLE，新增整张表用 `CREATE TABLE IF NOT EXISTS` 自然兼容老库。

### 3.2 后端 Repo 与 API

新增 `server/file_reads.py`，仿照 `server/read_state.py` 的写法：

```python
class FileReadRepo:
    def mark(self, user_open_id, matter_id, filename) -> bool:
        """返回 True 表示首次记录，False 表示已存在。"""

    def list_for_matter(self, matter_id) -> dict[str, list[ReaderEntry]]:
        """{filename: [ReaderEntry...]}, 按 first_read_at 升序。"""
```

`ReaderEntry` 是个简单 dataclass：`open_id / first_read_at`。姓名和头像在 API 层用 `UserRepo` 拼上去，不冗余存。

读者列表本期只通过详情接口聚合返回，不暴露独立的"按文件查读者"端点——前端首次加载、SSE 刷新、切前台 refetch 三条路径都走详情接口拿全量；mark 之后本地拼一条乐观记录就够，没有"只查单文件读者"的实际场景。等真有需要（比如未来的悬浮统计面板）再补一条 `GET /readers` 不迟。

API 端点放在 `server/api/matters.py`，本期只加一条：

```
POST /api/matters/{matter_id}/files/{filename}/read
  → 当前用户对该文件标记已读。幂等。
  → 200 {"matter_id", "filename", "first_read_at"}
  → 404 matter 不存在 / timeline 里没有这个 file
```

`mark` 之前要校验该 file 确实在 matter 的 timeline 里（防误触/伪造），校验靠读 `matter-index.yaml` 的 timeline，扫一遍 `file` 字段做 endsWith 匹配即可，没必要建索引。

详情接口 `GET /api/matters/{matter_id}` 顺手带上聚合后的读者列表。每个 timeline item 多两个字段：

```jsonc
{
  "file": "discussions/cat/m-x/01-decision.md",
  "type": "decision",
  ...,
  "readers_count": 3,
  "readers": [
    {"open_id": "ou_xxx", "name": "邓克", "avatar_url": "...", "first_read_at": "2026-04-28T10:22:03+08:00"},
    ...
  ]
}
```

`readers` 在团队规模可控的前提下直接全量返回；如果某天单 matter 出现几十人都读过的情况再做截断（比如保留最近 20 个 + count），现在不必提前防御。

### 3.3 前端触发与展示

FileCard 已经有 `expanded` 和 `canExpand` 两个状态（`web/src/components/matter/FileCard.tsx:81/101`）。基于这两个值能很自然地推出标记已读的两条规则，不需要新增更复杂的状态机。

**触发逻辑**：

- 长文（`canExpand === true`）：用户首次点击"展开全文 ↓"按钮时调用 mark API。
- 短文（`canExpand === false`，正文完整露出）：挂一个 IntersectionObserver，当卡片有一半进入视口时触发。
- 卡片内用 `useRef` 维护一个 `markedRef` 防抖标记，整个会话期内一篇文件只发一次请求。
- mark 接口的返回里有 `first_read_at`，前端再加上当前登录用户已知的姓名和头像，就够拼出一条 reader 记录。直接 append 到本地 `readers` 数组，UI 立刻把"X 人已读"加 1。
- 不要为了刷这一行去重新拉一遍详情接口——详情接口会重读这个 matter 下所有 markdown 正文，代价远大于"加一个头像"，而且整页重渲染容易让用户正在打字 / 滚动的位置抖动。
- 服务端对齐交给详情页本来就有的刷新触发点（SSE 推送、切回前台、页面前进后退）。这些时机会自动 refetch，到时候用服务端版本整体覆盖本地乐观状态即可，不需要专门写对齐逻辑。
- mark 失败时（matter 不存在 / file 不在 timeline / 网络断）回滚本地 readers，并把 `markedRef` 复位允许重试。

需要避免的坑：

- IntersectionObserver 必须只在 `canExpand === false` 时才挂，长文不挂——长文的"看到了卡头"≠"读了"。
- React StrictMode 双调用 effect 会导致 dev 环境打两次请求，幂等设计兜住，不需要额外处理。

**UI 展示**：

文件卡片底部加一行轻量信息，姓名前各跟一个小头像：

```
👁  2 人已读 · (Ⓒ) Captain  (Ⓣ) tank
```

具体规则：

- 每个 reader 渲染成"小头像 + 姓名"二元组，头像用 16~18px 圆形，复用现有 `resolve_avatar_url`（`server/mentions.py:25`）的解析口径，没有头像 URL 时退化成"姓名首字母 + 随机底色"圆形占位（跟 matter 列表里的 owner 头像同款组件）。
- 二元组之间留一个间隔（视觉密度参考飞书的"已读 N 人"行），不再用顿号分隔。
- 当人数较多（例如 ≥ 6）时，行内只展示最近 5 个的"头像 + 姓名"，第 6 个起折叠成"+N"圆形头像数字气泡，整组保持横向不换行；点开 popover 看完整名单。

点击 / hover 整行弹 popover，显示完整名单（更大头像 + 姓名 + 首读时间相对时间）。组件复用现有 `MentionField` / `Popover` 风格，不引入新设计语言。

如果 `readers_count === 0`，整行不渲染，避免给空 matter 显示一堆"0 人已读"造成视觉噪音。

详情接口的 `readers` 字段已经把 `name` 和 `avatar_url` 都拼好（参见 §3.2 JSON 示例），前端不用再额外拉一次用户表。


## 四、时序图

### 4.1 用户点击展开 → 标记已读

```
[用户 B 浏览器]              [Server]                     [SQLite]
    │                            │                            │
    │ 进入 matter X 详情页       │                            │
    │ GET /api/matters/X         │                            │
    │───────────────────────────►│                            │
    │                            │ 读 matter-index.yaml       │
    │                            │ list_for_matter(X) ───────►│
    │                            │◄──── readers per file ─────│
    │                            │ 拼装 timeline + readers    │
    │ ◄──── detail JSON ─────────│                            │
    │                            │                            │
    │ 渲染 FileCard, expanded=false                           │
    │                            │                            │
    │ 用户点击"展开全文 ↓"       │                            │
    │ markedRef = true           │                            │
    │ POST /matters/X/files/F/read                            │
    │───────────────────────────►│                            │
    │                            │ 校验 F ∈ timeline          │
    │                            │ INSERT OR IGNORE          │
    │                            │   into file_reads ────────►│
    │ ◄──── 200 {first_read_at} ─│                            │
    │                            │                            │
    │ 本地把自己拼到 readers     │                            │
    │ "3 人已读" → "4 人已读"    │                            │
```

### 4.2 短文章自动标记（IntersectionObserver）

```
[用户 B 浏览器]                                       [Server]
    │                                                     │
    │ 详情页渲染,某 FileCard:                            │
    │   canExpand = false  (正文 < 208px,无展开按钮)    │
    │   挂 IntersectionObserver(threshold=0.5)            │
    │                                                     │
    │ 用户向下滚动,卡片半数进入视口                      │
    │ observer.callback 触发                              │
    │ markedRef = true → disconnect()                     │
    │                                                     │
    │ POST /matters/X/files/F/read ──────────────────────►│
    │ ◄──── 200 ──────────────────────────────────────────│
    │                                                     │
    │ readers 本地 +1, UI 局部更新                        │
```

### 4.3 重复点击 / 重复进入

```
[用户 B 浏览器]                       [Server]              [SQLite]
    │                                     │                     │
    │ 第二次打开 matter X                 │                     │
    │ 同一篇文章再点展开                  │                     │
    │ POST /matters/X/files/F/read ──────►│                     │
    │                                     │ INSERT OR IGNORE ──►│
    │                                     │ ◄── 0 rows changed  │
    │                                     │ SELECT first_read_at│
    │ ◄──── 200 {first_read_at: 上次时间}─│                     │
    │ (UI 不变,because 该用户早就在 readers 里)                  │
```

## 五、实施分工

整体大概 1.5 人日，前后端可以并行。

| 阶段 | 内容 | 负责人 | 预估 |
|---|---|---|---|
| 切分支 | `feat/read-state` | 任一 | 0.1 h |
| 后端 1 | `db.py` 加 `file_reads` 表；新增 `server/file_reads.py` Repo + 单测 | 后端 | 2 h |
| 后端 2 | `server/api/matters.py` 加 mark / readers 路由；详情接口注入 `readers` 字段 | 后端 | 3 h |
| 后端 3 | `tests/test_file_reads.py` + `test_matters_api.py` 增量用例（首次/重复/不存在 file/不存在 matter） | 后端 | 1 h |
| 前端 1 | `api.ts` 加 `markFileRead` / `MatterDetail` 类型扩展 | 前端 | 0.5 h |
| 前端 2 | `FileCard.tsx` 接入触发逻辑 + 本地乐观更新 + readers 行渲染 | 前端 | 3 h |
| 前端 3 | Popover 完整名单（头像 + 时间）、空态处理 | 前端 | 1 h |
| 联调 | 多 tab 并发、刷新不丢数据、IntersectionObserver 在飞书 WebView 表现 | 前后端 | 1 h |

交付清单：

```
新增:
  server/file_reads.py
  server/tests/test_file_reads.py
  web/src/components/matter/ReadersRow.tsx     # 文件卡底部那行
  web/src/components/matter/ReadersPopover.tsx # 点开后的名单

修改:
  server/db.py                                 # SCHEMA 加 file_reads
  server/api/matters.py                        # 两条新路由 + 详情聚合
  server/tests/test_matters_api.py             # 详情含 readers / mark 路由
  web/src/api.ts                               # 类型 + markFileRead
  web/src/components/matter/FileCard.tsx       # 触发 + 渲染
```

风险点：

- **IntersectionObserver 兼容性**：飞书 WebView 当前内核 Chromium 108+，支持。手机端老版本飞书需要联调验证一下。
- **乐观更新与并发**：A B 同时第一次读同一篇，两边都把自己加进 readers 本地，等下次 refetch 服务端版本会修正，没有正确性问题。
- **大 matter 的 readers 膨胀**：一个 matter 50 篇 × 10 人 = 500 条 reader 记录，全量返回详情体积约几 KB，可接受。如果出现"全员读完"的极端情况再做截断。

## 六、后期扩展

按需求 v2 的"未读暂不实现"对齐，扩展方向已经写得很清楚，本设计为它们各自留了口子：

- **应读未读**：等 matter / 文件挂上 owner、关注人、@mention 应读人之类的语义信号后，把"应读集合 - 已读集合 = 未读"算出来。`file_reads` 表本身就是已读集合，到时候直接 join 应读列表即可。
- **催读**：在未读名单上挂一个 notify 入口，复用现有的 `server/notify.py` 飞书通知通道。
- **细粒度判定**：当前是"展开即读 / 短文进视口即读"的粗粒度，后续如果要做停留时长、滚动到底部等更严格的规则，加一个 `server/file_reads.py` 的策略层把判定逻辑收进去，前端只负责报告"看到了"事件，服务端决定是否落表。
- **实时已读推送**：如果作者关心"我的 decision 谁正在看"，给 `server/events.py` 加个 `TOPIC_FILE_READ`，`matters_events.py` 映射成 `matter.updated` 的新 reason，前端在详情页订阅同一 matter 的事件，看到 `file_read` 就把 readers 局部刷一下。这条是纯加法，不影响 v1 的接口。
- **跨设备聚合**：当前主键 `(user_open_id, matter_id, filename)` 已经按用户去重，跨设备无需特殊处理。
- **导出与统计**：文件级阅读率、读者扇出图等需求出现时，`file_reads` 是天然的事实表，加几个聚合视图就够。
