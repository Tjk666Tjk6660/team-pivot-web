# Runbook：用户管理体系迁移

> 把一台 Pivot 部署的 SQLite 数据库从「user-management 之前」的形态，
> 升级到「pivot_user / external_binding 主导」的新形态。
> 只在每台部署上跑**一次**。

| | |
|---|---|
| 适用版本 | feat/user-management 合并到 main 之后的任意 commit |
| 主脚本 | `scripts/migrate_user_management_v2.py` |
| 维护窗口 | 10-15 分钟（含备份、自检、起服） |
| 数据规模假设 | 当前 ~10 人，单库 < 1MB；脚本本身秒级完成 |

---

## 1. 何时用 · 何时不用

**用**：
- 老 Pivot 部署还有 `users` 表（`open_id` 主键、`pinyin` 列），下游表（`drafts` / `sessions` / `read_state` 等）以 `user_open_id` 为外键
- 升级到 user-management 版本后**第一次**启动服务

**不用**：
- 全新部署（没有历史数据）—— 直接走 `/init/status` + `/init/complete` 创建首个 admin，跳过迁移
- 已经迁移过 —— 重复跑会被识别为 `database is already fully migrated; nothing to do`，不会破坏数据，但也没必要
- dev / 测试环境 —— 也用同一个脚本，但备份步骤可省

---

## 2. 前置决策（操作前先想好）

### 2.1 选 `--initial-admin <pinyin>`

迁移完成后，被指定的这位 pinyin 用户在 `pivot_user` 表里 `role='admin'`，其他人都是 `member`。**必须严格唯一命中**老 `users.pinyin`。

**怎么选**：通常是负责本次升级的人自己（也就是会进 `/admin` 后台继续配置的人）。

**先看候选**：
```bash
sqlite3 /var/lib/pivot/data.db \
    "SELECT pinyin, name FROM users ORDER BY pinyin"
```

如果有 NULL pinyin 或重复 pinyin，预检阶段会报错 —— 见 §6 故障排查。

### 2.2 备份保留时长

至少**保留 7 天**。万一第二天才发现问题，备份还在能直接 cp 回滚。

### 2.3 通知团队

迁移期间服务停止，依赖 Pivot 的所有人（飞书机器人通知、VS Code 客户端、CLI / MCP）都会断。提前在飞书群里发公告（建议提前 1-2 天），约定窗口时间。

---

## 3. 操作步骤

> **所有命令在服务器上跑**，路径以 `/var/lib/pivot/data.db` 为例。
> 你的实际 db 路径见 `.env` 或 systemd unit 里的 `--data-dir` 参数。

### 步骤 1 · 公告 + 停服

```bash
systemctl stop pivot-web
```

确认彻底停下：
```bash
systemctl status pivot-web | head -5
# Active: inactive (dead)
```

如果是手动 `uvicorn` 起的服务：`Ctrl+C` 关掉。

---

### 步骤 2 · 双重备份

```bash
TS=$(date +%Y%m%d-%H%M%S)
cp /var/lib/pivot/data.db /var/lib/pivot/data.db.before-mig-$TS
sqlite3 /var/lib/pivot/data.db ".backup '/var/lib/pivot/data.db.snapshot-$TS.db'"
ls -la /var/lib/pivot/data.db*
```

预期：能看到 3 个文件 —— 原 `data.db` + `data.db.before-mig-*` + `data.db.snapshot-*.db`。两个备份分别是文件级 cp 和 SQLite 内置 `.backup`，互为冗余。

---

### 步骤 3 · 预检（只读，不改库）

```bash
cd /opt/pivot   # Pivot 仓库 checkout 路径
uv run python scripts/audit_user_migration.py \
    --db /var/lib/pivot/data.db \
    --initial-admin <pinyin>
```

**预期看到**：

```
================================================================
结论
================================================================
  [ok] 未发现迁移阻塞项；可以按 spec §9 走
```

**任何 `[!]` 都要先解决再继续**。常见情形见 §6。

---

### 步骤 4 · Dry-run（事务里跑完整迁移再回滚）

```bash
uv run python scripts/migrate_user_management_v2.py \
    --db /var/lib/pivot/data.db \
    --initial-admin <pinyin> \
    --dry-run
```

**预期看到**：

```
[DRY-RUN] OK
  pivot_user rows created: <N>
  feishu bindings created: <N>
  initial admin id:        <32 位 hex>
  downstream tables rebuilt: 9
    - drafts
    - read_state
    - favorites
    - sessions
    - ai_conversations
    - api_tokens
    - file_reads
    - relevance_events
    - user_preferences
```

`<N>` 应等于老 `users` 表行数。**downstream tables rebuilt 必须是 9**，少一张说明哪张表 schema 异常。

---

### 步骤 5 · 真实迁移

```bash
uv run python scripts/migrate_user_management_v2.py \
    --db /var/lib/pivot/data.db \
    --initial-admin <pinyin>
```

**预期看到** `[APPLY] OK` + 同上 dry-run 的统计行。

**如果失败**（任何 `[APPLY] FAILED: ...`）：脚本已自动 ROLLBACK，db 还是迁移前状态。**不要重启服务、不要再跑脚本**，先看 §6 故障排查找出原因，修了再从步骤 3 重头。

---

### 步骤 6 · Schema 自检

```bash
# 应无输出（除了 'users' 自己 —— 它是空表，下个迭代再 drop）
sqlite3 /var/lib/pivot/data.db \
    "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%user_open_id%'"

# 4 张身份表必须都在
sqlite3 /var/lib/pivot/data.db \
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN \
     ('pivot_user','external_binding','join_application','invite')"

# initial admin 必须存在且 role=admin
sqlite3 /var/lib/pivot/data.db \
    "SELECT id, display_name, pinyin, role FROM pivot_user WHERE role='admin'"
```

**预期**：第一条无输出，第二条列出 4 张表，第三条列出 1 行 `role=admin` 的记录。

---

### 步骤 7 · 启服

```bash
systemctl start pivot-web
journalctl -u pivot-web -f
```

**关注启动日志**（前 10 秒内）：

| 看到 | 含义 |
|------|------|
| `workspace runtime ready` | git 仓库正常 |
| `notifier enabled (feishu)` | 飞书机器人配置加载 |
| `Application startup complete` | uvicorn 完成启动 |
| `IntegrityError` / `no such column` | **失败信号**，立即停服回滚（见 §5） |
| `Database still has legacy user_open_id column on: [...]` | 守卫触发，迁移没完成 |

确认日志干净后，`Ctrl+C` 退出 `journalctl`（不会停服）。

---

### 步骤 8 · 烟测

#### 8.1 后端层面

```bash
curl -s http://localhost:8000/init/status | jq
# 预期: {"needs_init": false}
```

#### 8.2 浏览器层面

打开服务地址，**用 initial admin 的飞书账号扫码登录**：

- 登录后能进首页（不会被踢去 `/init`）
- devtools → Network → `/me` 响应里有 `role: "admin"`、`status: "active"`、`display_name`、`email: null`
- 点进 `/admin/users` 列表，能看到所有老用户都迁过来了，迁来的是 `member`，只有 initial admin 是 `admin`
- 创建一条邀请、隐身窗口接受、暂停 / 恢复 —— 整套流程跑一遍

如果**老用户的 session cookie 还在浏览器里**，新版本会无感继续登录（迁移把 sessions 表的 `pivot_user_id` 也补上了）。**不需要让所有人重新登录**。

---

## 4. 验证 checklist（迁移完成后）

| 检查项 | 命令 / 操作 | 预期 |
|--------|-------------|------|
| 4 张身份表都建好 | `SELECT COUNT(*) FROM pivot_user` 等 | 行数符合预期 |
| `users` 表已空（不再写入） | `SELECT COUNT(*) FROM users` | 0 |
| 下游表无 `user_open_id` 列 | 见步骤 6 第 1 条 | 无输出 |
| Initial admin 唯一 | 见步骤 6 第 3 条 | 1 行 |
| 启动日志无 `IntegrityError` | journalctl | 无该字串 |
| 老 session 可继续用 | 浏览器刷新已登录页 | 不被踢登录 |
| `/admin/*` 对 admin 可见 | `/admin/users` | 列表显示 |
| `/admin/*` 对 member 403 | 用其他用户登录后访问 | 403 page |
| 飞书登录正常 | 退出后重新扫码 | 自动跳回首页 |

---

## 5. 回滚预案

迁移完成后**任何**重大异常（数据丢失、登录全断、关键 API 报 500）：

```bash
# 1. 停服
systemctl stop pivot-web

# 2. 恢复数据库
cp /var/lib/pivot/data.db.before-mig-<时间戳> /var/lib/pivot/data.db

# 3. 把代码回退到迁移之前的版本
cd /opt/pivot
git log --oneline | head -20    # 找 user-management 合并前的最后一个 commit
git checkout <pre-user-management-tag-or-commit>

# 4. 起服
systemctl start pivot-web
journalctl -u pivot-web -f      # 看启动是否正常
```

回滚后服务恢复到**迁移前的稳定状态**，老用户能继续用，但新功能（admin 后台、邀请码、申请审批）暂时不可用。

随后开 issue 复盘、修脚本，等下次维护窗口再尝试。

---

## 6. 故障排查

### 6.1 `audit_user_migration.py` 报 NULL pinyin

```
users 表概况
  pinyin 为空: <N>
    [ou_xxx, ou_yyy, ...]
```

**含义**：这几位用户老库里 `pinyin` 字段没填（一般是首登过但没走 ProfileSetup）。

**修法**：
```bash
# 进 SQLite 手动补
sqlite3 /var/lib/pivot/data.db \
    "UPDATE users SET pinyin='<合理的 pinyin>' WHERE open_id='ou_xxx'"
```

或者在迁移前临时启动老版本服务，让那位用户走一次 ProfileSetup 把 pinyin 填上。

补完重新跑步骤 3。

### 6.2 audit 报 pinyin 重复

```
pinyin 重复: 1 组
  'liuyu' x2 -> ['ou_a', 'ou_b']
```

**含义**：两个用户撞了同一个 pinyin。`pivot_user.pinyin` 没强制 UNIQUE 约束，但 `--initial-admin` 用 pinyin 选人会歧义。

**修法**：手动改其中一位的 pinyin（例如 `liuyu_z` / `liu.yu`），让两人 pinyin 不同。

### 6.3 audit 报 orphan_user_open_id

```
[!] sessions  rows=13  orphan_user_open_id=2
    未知 user_open_id: ou_zzz
```

**含义**：sessions 表里有 2 行引用了 `users` 表里**不存在**的 open_id（被 DELETE 用户后 sessions 没清干净，或者是垃圾数据）。

**修法**：
```bash
sqlite3 /var/lib/pivot/data.db \
    "DELETE FROM sessions WHERE user_open_id NOT IN (SELECT open_id FROM users)"
```

对其他下游表（drafts / favorites / read_state / file_reads 等）同理。

### 6.4 v2 脚本报 `--initial-admin '...' does not match any user`

**含义**：你输的 pinyin 不在 `users.pinyin` 里。

**修法**：先 `sqlite3 .. "SELECT pinyin FROM users"` 查现有 pinyin，挑一个填 `--initial-admin`，重跑。

### 6.5 启动后第一次写入撞 `NOT NULL constraint failed: sessions.user_open_id`

**含义**：迁移没跑完，`user_open_id` 列还在 + 是 NOT NULL，应用代码已经只写 `pivot_user_id`。

**修法**：v2 脚本应该已拒绝启动并报错。如果你看到这条，说明守卫绕过了（数据库被半迁移过），停服 → cp 备份回去 → 重新走步骤 3。

### 6.6 启动报 `Database still has legacy user_open_id column on: [...]`

**含义**：守卫触发，迁移没成功。

**修法**：去步骤 4-5 重跑 v2，看为什么没成功。

### 6.7 飞书登录后 `/me` 200 但 `/api/*` 全 401

**含义**：`server/app.py` 里 `current_user_dep` 接的是 legacy `UserRepo` 而不是 `PivotUserRepo`（这个 bug 我们 dev 上踩过，已修；如果生产上又出现说明 main 分支被 revert / merge 出问题了）。

**修法**：检查 `server/app.py` 第 119-120 行 `make_current_user(sessions, pivot_users, api_tokens)` 第 2 个参数必须是 `pivot_users`。不对就 git pull 最新代码、重启。

### 6.8 老用户 session 全失效，所有人需要重新登录

**含义**：sessions 表迁移时 orphan 检查失败 → 整个迁移 ROLLBACK，但服务起来时 sessions.pivot_user_id 没填。

实际上这种状态不应该出现 —— v2 在事务里要么全成要么全失。如果出现这条说明步骤 5 没真正成功但你没注意到，请看步骤 5 输出。

如果是已知影响范围，就让所有人重新登录一次（`/login` → 飞书 → 自动建新 session），影响仅是体验上的。

---

## 7. FAQ

**Q: 迁移完之后老 `users` 表为什么还在？**
A: 当前迭代 `db.py` SCHEMA 字符串保留 `CREATE TABLE IF NOT EXISTS users (...)`，启动时会建一个空壳。这个空壳无害（业务代码已不读 `users` 表）。下个迭代会清理。

**Q: 为什么 `pivot_user.email` 全是 NULL？**
A: 老 `users` 表没存 email（飞书 OAuth 不强制要邮箱）。新建的 admin 走 `/init/complete` 时填的 email 会进 `pivot_user.email`；邀请用户的 email 也是接受邀请时填的。迁过来的人想填 email 可以让 admin 在 `/admin/users` 重置（当前没有手动改 email 的端点，下个迭代加）。

**Q: 用户改名（`display_name`）怎么处理？**
A: 现在 `pivot_user.display_name` 是从老 `users.name` 复制过来的。要改名需要 admin 手动 `UPDATE pivot_user SET display_name=...`。下个迭代会加 `/admin/users/:id/rename` 端点。

**Q: 迁移失败了重跑安全吗？**
A: 安全。v2 脚本是 idempotent 的：识别 `legacy` / `mid` / `done` 三态，每态都不会破坏现有数据。但**还是建议先恢复到备份**再重跑，避免「半迁移状态」累积。

**Q: 迁移期间能手动写库吗？**
A: 不要。v2 脚本不加表锁（SQLite 是文件锁），但同时写会撞事务冲突。**严格停服 → 跑脚本 → 起服**。

**Q: 多台服务器共享同一 db 怎么办？**
A: 不应该这么用。Pivot 设计是单服务器 + 本地 SQLite，每台服务器独立一份 db。如果有多副本，需要逐一在每台上跑迁移（或停所有副本 + 一处迁移 + 同步 db 文件 + 都启）。

---

## 8. 参考

- 设计文档：`AI-docs/designs/2026-04-28-user-management-design.md`
- 实施计划：`AI-docs/plans/2026-04-28-user-management-plan.md`（已完成）
- 改动地图：`AI-docs/designs/2026-04-28-user-management-impact-map.md`
- 主脚本：`scripts/migrate_user_management_v2.py`
- 预检脚本：`scripts/audit_user_migration.py`
- 内容审计脚本：`scripts/audit_new_content_uses_ulid.py`（迁移上线后跑，验证新写入的 frontmatter 不再含 open_id；当前会有 leak，等 publish.py 切 ULID 后归零）

---

**最后更新**：2026-04-30（首次发布）
**维护者**：跟随 `feat/user-management` 分支演进；下次 schema 大改时一并更新本 runbook
