# Pivot 用户管理体系 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Pivot 从「飞书扫码即账号」升级为带用户主数据、外部身份解耦、管理员审批治理、邀请码兜底登录的产品级用户管理体系。

**Architecture:** 新增 4 张表（`pivot_user` / `external_binding` / `join_application` / `invite`）作为身份层；现有 `users` 迁移到 `pivot_user` 后整张 drop；session 层由"读 user_open_id"改为"读 pivot_user_id"；废除硬编码 `X-Admin-Password`，改为基于 `pivot_user.role` 的角色鉴权。

**Tech Stack:** Python 3.12 + FastAPI + SQLite（标准库） + bcrypt（新增）+ React 18 + Vite + shadcn/ui + Tailwind。

**配套文档：**
- spec：`AI-docs/designs/2026-04-28-user-management-design.md`
- 改动地图：`AI-docs/designs/2026-04-28-user-management-impact-map.md`
- 假设验证：`AI-docs/designs/2026-04-28-user-management-assumptions-validation.md`

**已锁定的修订（覆盖 spec 原文，以本 plan 为准）：**
1. **pinyin 由用户手填**（A 方案）：邀请接受表单、ProfileSetup 都手填 + `PINYIN_RE` 校验；不引入 pypinyin
2. **`pivot_user.pinyin` 改为可空**：与现有 `users.pinyin` 行为对齐（首登后通过 ProfileSetup 填）
3. **ULID 改用 stdlib `uuid.uuid4()`**：避免新增依赖，可读性差异微不足道
4. **`/init` 路由守卫由 SPA 前端处理**：不写服务端 ASGI 中间件
5. **session 状态校验放在 `auth/deps.py` 的 user 解析层**：不写新中间件
6. **`Notifier` 新方法只通过 `_dm_many` 给绑了飞书的管理员发 DM**；未绑飞书的管理员靠后台未读角标自助看

---

## File Structure

### 新增后端

| 文件 | 职责 |
|---|---|
| `server/pivot_users.py` | `PivotUser` 实体 + `PivotUserRepo`（替代 `users.py`） |
| `server/external_bindings.py` | `ExternalBinding` 实体 + `ExternalBindingRepo` |
| `server/join_applications.py` | `JoinApplication` 实体 + `JoinApplicationRepo` + 同人匹配候选 |
| `server/invites.py` | `Invite` 实体 + `InviteRepo`（token 生成、bcrypt 密码） |
| `server/passwords.py` | bcrypt 密码哈希封装 |
| `server/api/init.py` | `/init/status` + `/init/complete` |
| `server/api/admin_applications.py` | 管理员审批接口 |
| `server/api/admin_users.py` | 管理员用户管理接口 |
| `server/api/admin_invites.py` | 管理员邀请管理接口 |
| `server/api/auth_invite.py` | 邀请加载与接受接口（公共） |
| `scripts/migrate_user_management.py` | 一次性迁移脚本 + `--dry-run` |

### 新增前端

| 文件 | 职责 |
|---|---|
| `web/src/pages/Init.tsx` | 初始化页（警示语 + 二选一登录） |
| `web/src/pages/PendingApproval.tsx` | "申请已提交"占位页 |
| `web/src/pages/InviteAccept.tsx` | 邀请接受页 |
| `web/src/pages/admin/AdminApplications.tsx` | 待审批列表 |
| `web/src/pages/admin/AdminUsers.tsx` | 用户列表 + 治理操作 |
| `web/src/pages/admin/AdminInvites.tsx` | 邀请管理 |
| `web/src/components/admin/MatchCandidates.tsx` | 同人匹配候选 chips |
| `web/src/components/admin/MergeUserDialog.tsx` | 合并到已有用户 dialog |
| `web/src/components/admin/UserStatusBadge.tsx` | 状态徽章 |
| `web/src/lib/displayUser.ts` | 按 status 渲染用户名工具 |

### 重写/重构后端

| 文件 | 改动 |
|---|---|
| `server/db.py` | 加 4 张新表 schema + 现有表新增 `pivot_user_id` 列（迁移用） |
| `server/auth/deps.py` | 新 `make_current_user` 返回 `PivotUser`；新 `require_admin_user`；status 校验内嵌 |
| `server/auth/session.py` | `Session.user_open_id` → `pivot_user_id`；表列同步 |
| `server/auth/routes.py` | `/auth/callback` 分流：已绑→入口 1，未绑→建 `join_application` |
| `server/auth/admin.py` | **删除**（迁移完成后） |
| `server/notify.py` | 新增 3 个 card builder + `Notifier` Protocol 新方法 |
| `server/mentions.py` | 新增 `resolve_display_info` 返回带 status 的完整信息 |
| `server/api/ai.py` / `server/api/contacts.py` / `server/api/workspace.py` | `Depends(require_admin)` → `Depends(require_admin_user)` |
| `server/users.py` | **保留为 stub**（向后兼容期），实际查询走 PivotUserRepo |
| `server/drafts.py` / `server/inbox.py` / `server/read_state.py` / `server/favorites.py` / `server/ai_conversations.py` / `server/api_tokens.py` | 字段重命名 `user_open_id` → `pivot_user_id` |
| `server/app.py` | 装配新 repos、新路由 |
| `pyproject.toml` | 加 `bcrypt>=4.0` |

### 重构前端

| 文件 | 改动 |
|---|---|
| `web/src/api.ts` | 移除 `X-Admin-Password`；新增 admin/applications/users/invites/init/invite 调用 |
| `web/src/pages/Login.tsx` | 加邮箱密码登录子表单 |
| `web/src/pages/AdminPage.tsx` | 删除密码输入；改为按 `me.role==='admin'` 守卫；改为侧栏导航 |
| `web/src/App.tsx` | app load 时调 `/init/status`，未初始化重定向 `/init`；非 active 用户强制登出 |
| `web/src/pages/MatterDetailPane.tsx` 等 | author 渲染改用 `lib/displayUser.ts` 工具 |

---

## Phase 0 · 准备

### Task 0: 创建新分支（实施起点）

> **必须在所有其它 Task 之前执行。** 实施工作必须基于 `main` 分支拉取最新代码后开新分支进行，避免把改动直接推到 `main` 或落在某条已有的 feature 分支上。

**Branch 命名约定：** `feat/user-management`（沿用项目现有 `feat/<feature-name>` 风格，参考 `feat/pivot-matter`、`feat/mcp-external-ai`）。

- [ ] **Step 1: 确认当前没有未提交改动**

Run: `git status`
Expected: `nothing to commit, working tree clean`
若有未提交改动 → 先 stash 或 commit 到对应分支，再继续。

- [ ] **Step 2: 切到 main 分支**

Run: `git checkout main`
Expected: `Switched to branch 'main'` 或已经在 main 上的提示

- [ ] **Step 3: 拉取最新远端代码**

Run: `git pull --ff-only origin main`
Expected: 输出 `Already up to date.` 或快进合并的统计信息
若 fast-forward 失败（分叉了）→ 停下来检查，不要强 merge / rebase；联系上下游对齐再说。

- [ ] **Step 4: 基于最新 main 创建新分支**

Run: `git checkout -b feat/user-management`
Expected: `Switched to a new branch 'feat/user-management'`

- [ ] **Step 5: 确认起点正确**

Run: `git log --oneline -1 && git status`
Expected: HEAD 指向最新 main 的同一 commit；working tree clean

完成后即可进入 Task 1。后续所有 Task 的 commit 都落在这条分支上。

### Task 1: 加 bcrypt 依赖

**Files:**
- Modify: `pyproject.toml:6-14`

- [ ] **Step 1: 在依赖列表加 bcrypt**

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "lark-oapi>=1.4",
    "itsdangerous>=2.2",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "mcp>=1.0",
    "bcrypt>=4.0",
]
```

- [ ] **Step 2: 同步依赖**

Run: `uv sync`
Expected: `bcrypt` 出现在 `Resolved N packages` 输出中

- [ ] **Step 3: 验证可导入**

Run: `uv run python -c "import bcrypt; print(bcrypt.__version__)"`
Expected: 打印一个 `4.x.x` 版本号

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add bcrypt for invite-code password hashing"
```

---

## Phase 1 · 数据模型

### Task 2: 在 db.py 加 4 张新表

**Files:**
- Modify: `server/db.py:8-82`（SCHEMA 常量末尾）

- [ ] **Step 1: 写测试，断言 4 张表存在**

Create: `server/tests/test_user_mgmt_schema.py`

```python
from __future__ import annotations
from server.db import Database


def test_pivot_user_table_exists(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('pivot_user','external_binding','join_application','invite')"
        ))
    assert {r[0] for r in rows} == {
        "pivot_user", "external_binding", "join_application", "invite"
    }


def test_pivot_user_columns(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pivot_user)")}
    expected = {
        "id", "display_name", "pinyin", "email", "avatar_url",
        "github_username", "role", "status", "status_note",
        "created_at", "updated_at", "last_login_at",
        "status_changed_at", "status_changed_by",
    }
    assert expected.issubset(cols)


def test_external_binding_unique_provider_external_id(tmp_path):
    db = Database(tmp_path / "test.db")
    with db.connect() as conn:
        # First insert OK
        conn.execute(
            "INSERT INTO pivot_user (id, display_name, pinyin, role, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("u1", "Alice", "alice", "member", "active", 1.0, 1.0),
        )
        conn.execute(
            "INSERT INTO external_binding (id, pivot_user_id, provider, external_id, bound_at)"
            " VALUES (?,?,?,?,?)",
            ("b1", "u1", "feishu", "ou_xxx", 1.0),
        )
        # Duplicate (provider, external_id) must raise
        import sqlite3
        try:
            conn.execute(
                "INSERT INTO external_binding (id, pivot_user_id, provider, external_id, bound_at)"
                " VALUES (?,?,?,?,?)",
                ("b2", "u1", "feishu", "ou_xxx", 2.0),
            )
            raise AssertionError("expected IntegrityError")
        except sqlite3.IntegrityError:
            pass
```

- [ ] **Step 2: 跑测试，确认全部 fail**

Run: `uv run pytest server/tests/test_user_mgmt_schema.py -v`
Expected: 3 个测试全 FAIL，因为表不存在

- [ ] **Step 3: 在 db.py 的 SCHEMA 末尾追加 4 张表 DDL**

Modify: `server/db.py:81`（在 `idx_api_tokens_user` 那行之后、闭合 `"""` 之前追加）

```sql
CREATE TABLE IF NOT EXISTS pivot_user (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pinyin TEXT,
    email TEXT UNIQUE,
    avatar_url TEXT NOT NULL DEFAULT '',
    github_username TEXT,
    role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
    status_note TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_login_at REAL,
    status_changed_at REAL,
    status_changed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pivot_user_role_status ON pivot_user(role, status);

CREATE TABLE IF NOT EXISTS external_binding (
    id TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL REFERENCES pivot_user(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT,
    password_hash TEXT,
    bound_at REAL NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_binding_user ON external_binding(pivot_user_id);

CREATE TABLE IF NOT EXISTS join_application (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT NOT NULL,
    suggested_match_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    applied_at REAL NOT NULL,
    reviewed_at REAL,
    reviewed_by TEXT,
    reject_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_join_app_pending_unique
    ON join_application(provider, external_id) WHERE status='pending';

CREATE TABLE IF NOT EXISTS invite (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    used_by_user_id TEXT
);
```

- [ ] **Step 4: 跑测试，确认全部 pass**

Run: `uv run pytest server/tests/test_user_mgmt_schema.py -v`
Expected: 3 个测试 PASS

- [ ] **Step 5: 跑全量回归确认未破坏现有 schema**

Run: `uv run pytest -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add server/db.py server/tests/test_user_mgmt_schema.py
git commit -m "feat(db): add pivot_user / external_binding / join_application / invite tables"
```

### Task 3: PivotUser 实体 + PivotUserRepo

**Files:**
- Create: `server/pivot_users.py`
- Test: `server/tests/test_pivot_users.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import pytest

from server.db import Database
from server.pivot_users import PivotUser, PivotUserRepo


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    return PivotUserRepo(db)


def test_create_user_returns_pivot_user(repo):
    u = repo.create(
        display_name="Alice",
        pinyin="alice",
        email="alice@example.com",
        avatar_url="",
        role="admin",
    )
    assert isinstance(u, PivotUser)
    assert u.id  # ULID/uuid generated
    assert u.display_name == "Alice"
    assert u.pinyin == "alice"
    assert u.role == "admin"
    assert u.status == "active"


def test_get_returns_none_when_missing(repo):
    assert repo.get("nonexistent") is None


def test_get_after_create(repo):
    u = repo.create(display_name="Bob", pinyin="bob", email=None, avatar_url="", role="member")
    fetched = repo.get(u.id)
    assert fetched is not None
    assert fetched.display_name == "Bob"


def test_update_status_records_who_when(repo):
    u = repo.create(display_name="Carol", pinyin="carol", email=None, avatar_url="", role="member")
    admin = repo.create(display_name="Admin", pinyin="admin", email=None, avatar_url="", role="admin")
    updated = repo.update_status(
        user_id=u.id, status="suspended", note="休假", changed_by=admin.id
    )
    assert updated.status == "suspended"
    assert updated.status_note == "休假"
    assert updated.status_changed_by == admin.id
    assert updated.status_changed_at is not None


def test_count_active_admins(repo):
    repo.create(display_name="A1", pinyin="a1", email=None, avatar_url="", role="admin")
    repo.create(display_name="A2", pinyin="a2", email=None, avatar_url="", role="admin")
    repo.create(display_name="M1", pinyin="m1", email=None, avatar_url="", role="member")
    assert repo.count_active_admins() == 2


def test_count_active_admins_excludes_suspended(repo):
    a1 = repo.create(display_name="A1", pinyin="a1", email=None, avatar_url="", role="admin")
    repo.create(display_name="A2", pinyin="a2", email=None, avatar_url="", role="admin")
    repo.update_status(user_id=a1.id, status="suspended", note=None, changed_by=a1.id)
    assert repo.count_active_admins() == 1


def test_update_role(repo):
    u = repo.create(display_name="X", pinyin="x", email=None, avatar_url="", role="member")
    promoted = repo.update_role(user_id=u.id, role="admin")
    assert promoted.role == "admin"


def test_touch_last_login(repo):
    u = repo.create(display_name="X", pinyin="x", email=None, avatar_url="", role="member")
    assert u.last_login_at is None
    repo.touch_last_login(u.id)
    fetched = repo.get(u.id)
    assert fetched.last_login_at is not None


def test_email_unique(repo):
    repo.create(display_name="A", pinyin="a", email="dup@example.com", avatar_url="", role="member")
    with pytest.raises(ValueError):
        repo.create(display_name="B", pinyin="b", email="dup@example.com", avatar_url="", role="member")


def test_list_for_admin_lists_all_with_filter(repo):
    repo.create(display_name="A", pinyin="a", email=None, avatar_url="", role="admin")
    m = repo.create(display_name="M", pinyin="m", email=None, avatar_url="", role="member")
    repo.update_status(user_id=m.id, status="suspended", note=None, changed_by=m.id)
    all_active_or_suspended = repo.list_for_admin(include_deleted=False)
    assert len(all_active_or_suspended) == 2
    deleted = repo.create(display_name="D", pinyin="d", email=None, avatar_url="", role="member")
    repo.update_status(user_id=deleted.id, status="deleted", note=None, changed_by=deleted.id)
    without_deleted = repo.list_for_admin(include_deleted=False)
    with_deleted = repo.list_for_admin(include_deleted=True)
    assert len(without_deleted) == 2
    assert len(with_deleted) == 3
```

- [ ] **Step 2: 跑测试，全部 fail（模块不存在）**

Run: `uv run pytest server/tests/test_pivot_users.py -v`
Expected: ImportError 或 ModuleNotFoundError

- [ ] **Step 3: 写实现**

```python
"""Pivot user master data — replaces server/users.py after migration."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, replace
from time import time
from typing import Iterable

from server.db import Database


@dataclass(frozen=True)
class PivotUser:
    id: str
    display_name: str
    pinyin: str | None
    email: str | None
    avatar_url: str
    github_username: str | None
    role: str
    status: str
    status_note: str | None
    created_at: float
    updated_at: float
    last_login_at: float | None
    status_changed_at: float | None
    status_changed_by: str | None

    @property
    def needs_setup(self) -> bool:
        return not self.pinyin

    @property
    def is_admin_active(self) -> bool:
        return self.role == "admin" and self.status == "active"


def _new_id() -> str:
    return uuid.uuid4().hex


def _row_to_user(row: sqlite3.Row) -> PivotUser:
    return PivotUser(
        id=row["id"],
        display_name=row["display_name"],
        pinyin=row["pinyin"],
        email=row["email"],
        avatar_url=row["avatar_url"] or "",
        github_username=row["github_username"],
        role=row["role"],
        status=row["status"],
        status_note=row["status_note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
        status_changed_at=row["status_changed_at"],
        status_changed_by=row["status_changed_by"],
    )


class PivotUserRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        display_name: str,
        pinyin: str | None,
        email: str | None,
        avatar_url: str,
        role: str = "member",
        github_username: str | None = None,
        id: str | None = None,
    ) -> PivotUser:
        now = time()
        new_id = id or _new_id()
        with self._db.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO pivot_user"
                    " (id, display_name, pinyin, email, avatar_url, github_username,"
                    "  role, status, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id, display_name, pinyin, email, avatar_url, github_username,
                     role, "active", now, now),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self.get(new_id)
        assert got is not None
        return got

    def get(self, user_id: str) -> PivotUser | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user WHERE id=?", (user_id,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> PivotUser | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pivot_user WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def update_profile(
        self,
        user_id: str,
        *,
        pinyin: str | None = None,
        github_username: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> PivotUser:
        updates: list[str] = []
        values: list[object] = []
        for col, val in [
            ("pinyin", pinyin),
            ("github_username", github_username),
            ("display_name", display_name),
            ("avatar_url", avatar_url),
        ]:
            if val is not None:
                updates.append(f"{col}=?")
                values.append(val)
        if not updates:
            got = self.get(user_id)
            assert got is not None
            return got
        updates.append("updated_at=?")
        values.append(time())
        values.append(user_id)
        with self._db.connect() as conn:
            try:
                conn.execute(
                    f"UPDATE pivot_user SET {','.join(updates)} WHERE id=?", values
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self.get(user_id)
        assert got is not None
        return got

    def update_status(
        self,
        *,
        user_id: str,
        status: str,
        note: str | None,
        changed_by: str,
    ) -> PivotUser:
        if status not in ("active", "suspended", "deleted"):
            raise ValueError(f"invalid status: {status}")
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET status=?, status_note=?, status_changed_at=?,"
                " status_changed_by=?, updated_at=? WHERE id=?",
                (status, note, now, changed_by, now, user_id),
            )
        got = self.get(user_id)
        assert got is not None
        return got

    def update_role(self, *, user_id: str, role: str) -> PivotUser:
        if role not in ("admin", "member"):
            raise ValueError(f"invalid role: {role}")
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET role=?, updated_at=? WHERE id=?",
                (role, time(), user_id),
            )
        got = self.get(user_id)
        assert got is not None
        return got

    def touch_last_login(self, user_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE pivot_user SET last_login_at=? WHERE id=?",
                (time(), user_id),
            )

    def count_active_admins(self) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM pivot_user"
                " WHERE role='admin' AND status='active'"
            ).fetchone()
        return int(row["n"])

    def list_for_admin(
        self,
        *,
        include_deleted: bool = False,
        search: str | None = None,
    ) -> list[PivotUser]:
        sql = "SELECT * FROM pivot_user WHERE 1=1"
        params: list[object] = []
        if not include_deleted:
            sql += " AND status != 'deleted'"
        if search:
            sql += " AND (display_name LIKE ? OR email LIKE ? OR pinyin LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])
        sql += " ORDER BY created_at ASC"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_user(r) for r in rows]
```

- [ ] **Step 4: 跑测试，全部 pass**

Run: `uv run pytest server/tests/test_pivot_users.py -v`
Expected: 9 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add server/pivot_users.py server/tests/test_pivot_users.py
git commit -m "feat(users): add PivotUser entity + PivotUserRepo"
```

### Task 4: ExternalBindingRepo

**Files:**
- Create: `server/external_bindings.py`
- Test: `server/tests/test_external_bindings.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import pytest

from server.db import Database
from server.external_bindings import ExternalBinding, ExternalBindingRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    user = users.create(display_name="Alice", pinyin="alice", email=None, avatar_url="", role="member")
    return users, bindings, user


def test_bind_creates_row(deps):
    _, bindings, user = deps
    b = bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id="on_xxx", raw_profile_json='{"name":"Alice"}',
    )
    assert isinstance(b, ExternalBinding)
    assert b.provider == "feishu"
    assert b.external_id == "ou_xxx"


def test_lookup_by_provider_external_id(deps):
    _, bindings, user = deps
    bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id=None, raw_profile_json=None,
    )
    found = bindings.lookup(provider="feishu", external_id="ou_xxx")
    assert found is not None
    assert found.pivot_user_id == user.id
    assert bindings.lookup(provider="feishu", external_id="nonexistent") is None


def test_user_already_bound_in_provider_rejected(deps):
    users, bindings, user = deps
    bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id=None, raw_profile_json=None,
    )
    with pytest.raises(ValueError):
        bindings.bind(
            pivot_user_id=user.id, provider="feishu", external_id="ou_yyy",
            external_union_id=None, raw_profile_json=None,
        )


def test_invite_password_storage(deps):
    _, bindings, user = deps
    b = bindings.bind(
        pivot_user_id=user.id, provider="invite", external_id="alice@example.com",
        external_union_id=None, raw_profile_json=None,
        password_hash="$2b$12$abc",
    )
    assert b.password_hash == "$2b$12$abc"
    found = bindings.lookup(provider="invite", external_id="alice@example.com")
    assert found.password_hash == "$2b$12$abc"


def test_list_bindings_for_user(deps):
    _, bindings, user = deps
    bindings.bind(pivot_user_id=user.id, provider="feishu", external_id="ou_x",
                  external_union_id=None, raw_profile_json=None)
    bindings.bind(pivot_user_id=user.id, provider="invite", external_id="a@x.com",
                  external_union_id=None, raw_profile_json=None,
                  password_hash="$2b$12$x")
    rows = bindings.list_for_user(user.id)
    assert {b.provider for b in rows} == {"feishu", "invite"}
```

- [ ] **Step 2: 跑测试，全部 fail**

Run: `uv run pytest server/tests/test_external_bindings.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 写实现**

```python
"""External identity binding (feishu open_id / invite email / etc) ↔ pivot_user."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class ExternalBinding:
    id: str
    pivot_user_id: str
    provider: str
    external_id: str
    external_union_id: str | None
    raw_profile_json: str | None
    password_hash: str | None
    bound_at: float


def _row_to_binding(row: sqlite3.Row) -> ExternalBinding:
    return ExternalBinding(
        id=row["id"],
        pivot_user_id=row["pivot_user_id"],
        provider=row["provider"],
        external_id=row["external_id"],
        external_union_id=row["external_union_id"],
        raw_profile_json=row["raw_profile"],
        password_hash=row["password_hash"],
        bound_at=row["bound_at"],
    )


class ExternalBindingRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def bind(
        self,
        *,
        pivot_user_id: str,
        provider: str,
        external_id: str,
        external_union_id: str | None,
        raw_profile_json: str | None,
        password_hash: str | None = None,
    ) -> ExternalBinding:
        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM external_binding"
                " WHERE pivot_user_id=? AND provider=?",
                (pivot_user_id, provider),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"user {pivot_user_id} already has a {provider} binding"
                )
            new_id = uuid.uuid4().hex
            try:
                conn.execute(
                    "INSERT INTO external_binding"
                    " (id, pivot_user_id, provider, external_id, external_union_id,"
                    "  raw_profile, password_hash, bound_at) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id, pivot_user_id, provider, external_id, external_union_id,
                     raw_profile_json, password_hash, time()),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(str(e)) from e
        got = self._get(new_id)
        assert got is not None
        return got

    def _get(self, binding_id: str) -> ExternalBinding | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM external_binding WHERE id=?", (binding_id,)
            ).fetchone()
        return _row_to_binding(row) if row else None

    def lookup(
        self, *, provider: str, external_id: str
    ) -> ExternalBinding | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM external_binding WHERE provider=? AND external_id=?",
                (provider, external_id),
            ).fetchone()
        return _row_to_binding(row) if row else None

    def list_for_user(self, pivot_user_id: str) -> list[ExternalBinding]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM external_binding WHERE pivot_user_id=?"
                " ORDER BY bound_at ASC",
                (pivot_user_id,),
            ).fetchall()
        return [_row_to_binding(r) for r in rows]

    def update_password(
        self, *, pivot_user_id: str, new_password_hash: str
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE external_binding SET password_hash=?"
                " WHERE pivot_user_id=? AND provider='invite'",
                (new_password_hash, pivot_user_id),
            )
```

- [ ] **Step 4: 跑测试，全部 pass**

Run: `uv run pytest server/tests/test_external_bindings.py -v`
Expected: 5 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add server/external_bindings.py server/tests/test_external_bindings.py
git commit -m "feat(auth): add ExternalBinding repo for multi-provider identity"
```

### Task 5: passwords.py（bcrypt 封装）

**Files:**
- Create: `server/passwords.py`
- Test: `server/tests/test_passwords.py`

- [ ] **Step 1: 写测试**

```python
from server.passwords import hash_password, verify_password


def test_hash_then_verify_succeeds():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)


def test_verify_wrong_password_fails():
    h = hash_password("hunter2")
    assert not verify_password("notthepw", h)


def test_hash_is_deterministic_within_same_salt_only():
    h1 = hash_password("x")
    h2 = hash_password("x")
    assert h1 != h2  # bcrypt salts random — must NOT match
    assert verify_password("x", h1)
    assert verify_password("x", h2)


def test_verify_handles_legacy_string_input():
    h = hash_password("x")
    # Hash returned as str so DB column TEXT works
    assert isinstance(h, str)
    assert verify_password("x", h)
```

- [ ] **Step 2: 跑，fail**

Run: `uv run pytest server/tests/test_passwords.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""bcrypt password hashing for invite-code users."""
from __future__ import annotations

import bcrypt

_ROUNDS = 12


def hash_password(plaintext: str) -> str:
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
```

- [ ] **Step 4: 跑，pass**

Run: `uv run pytest server/tests/test_passwords.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add server/passwords.py server/tests/test_passwords.py
git commit -m "feat(auth): add bcrypt password hashing"
```

### Task 6: JoinApplicationRepo + 同人匹配候选

**Files:**
- Create: `server/join_applications.py`
- Test: `server/tests/test_join_applications.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import json

import pytest

from server.db import Database
from server.join_applications import (
    JoinApplication,
    JoinApplicationRepo,
    MatchCandidate,
    compute_match_candidates,
)
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    apps = JoinApplicationRepo(db)
    return users, apps


def test_create_application(deps):
    _, apps = deps
    a = apps.create(
        provider="feishu",
        external_id="ou_xxx",
        external_union_id="on_xxx",
        raw_profile={"name": "李伟", "email": "li@example.com"},
        suggested_match_user_id=None,
    )
    assert isinstance(a, JoinApplication)
    assert a.status == "pending"
    assert a.raw_profile["name"] == "李伟"


def test_lookup_blocking_finds_pending_then_rejected(deps):
    _, apps = deps
    apps.create(provider="feishu", external_id="ou_a",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    blocker = apps.lookup_blocking("feishu", "ou_a")
    assert blocker is not None
    assert blocker.status == "pending"
    assert apps.lookup_blocking("feishu", "ou_nope") is None


def test_unique_pending_per_external_id(deps):
    _, apps = deps
    apps.create(provider="feishu", external_id="ou_a",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    with pytest.raises(ValueError):
        apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)


def test_approve_marks_status(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.approve(application_id=a.id, reviewed_by="admin1")
    fetched = apps.get(a.id)
    assert fetched.status == "approved"
    assert fetched.reviewed_by == "admin1"


def test_reject_with_reason(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin1", reason="not part of org")
    fetched = apps.get(a.id)
    assert fetched.status == "rejected"
    assert fetched.reject_reason == "not part of org"


def test_unblock_deletes_rejected(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin1", reason=None)
    apps.unblock(application_id=a.id)
    assert apps.lookup_blocking("feishu", "ou_a") is None


def test_list_pending(deps):
    _, apps = deps
    a = apps.create(provider="feishu", external_id="ou_a",
                    external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.create(provider="feishu", external_id="ou_b",
                external_union_id=None, raw_profile={}, suggested_match_user_id=None)
    apps.reject(application_id=a.id, reviewed_by="admin", reason=None)
    pending = apps.list_pending()
    assert len(pending) == 1
    assert pending[0].external_id == "ou_b"


def test_match_candidates_email_exact(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email="li@example.com", avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": "li@example.com"}
    )
    assert any(c.user_id == u.id and c.reason == "email_exact" for c in cands)


def test_match_candidates_display_name_exact(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email=None, avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": None}
    )
    assert any(c.user_id == u.id and c.reason == "name_exact" for c in cands)


def test_match_candidates_skip_non_active(deps):
    users, _ = deps
    u = users.create(display_name="李伟", pinyin="liwei",
                     email=None, avatar_url="", role="member")
    users.update_status(user_id=u.id, status="suspended", note=None, changed_by=u.id)
    cands = compute_match_candidates(
        users, raw_profile={"name": "李伟", "email": None}
    )
    assert all(c.user_id != u.id for c in cands)


def test_match_candidates_truncated_to_5(deps):
    users, _ = deps
    for i in range(10):
        users.create(display_name=f"User{i}", pinyin="dup", email=None, avatar_url="", role="member")
    cands = compute_match_candidates(
        users, raw_profile={"name": "Whatever", "email": None}
    )
    # 10 全拼匹配候选 → 截断到 5
    assert len(cands) <= 5
```

- [ ] **Step 2: 跑，fail**

Run: `uv run pytest server/tests/test_join_applications.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""Join applications & same-person match candidates.

Match candidate algorithm (per spec §5.2):
- email_exact: raw_profile.email matches a pivot_user.email (case-insensitive)
- name_exact: raw_profile.name matches a pivot_user.display_name (exact)
- pinyin_full: raw_profile.name → pinyin matches pivot_user.pinyin (skipped this
  iteration: pinyin auto-conversion deferred per plan revision A; if needed,
  callers can pass profile['pinyin'] explicitly)
- pinyin_initials: same source, first letters

Only matches against status='active' users. Capped at 5 candidates.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from time import time
from typing import Any

from server.db import Database
from server.pivot_users import PivotUserRepo


@dataclass(frozen=True)
class JoinApplication:
    id: str
    provider: str
    external_id: str
    external_union_id: str | None
    raw_profile: dict[str, Any]
    suggested_match_user_id: str | None
    status: str
    applied_at: float
    reviewed_at: float | None
    reviewed_by: str | None
    reject_reason: str | None


@dataclass(frozen=True)
class MatchCandidate:
    user_id: str
    display_name: str
    email: str | None
    avatar_url: str
    reason: str  # 'email_exact' | 'name_exact' | 'pinyin_full' | 'pinyin_initials'


def _row_to_app(row: sqlite3.Row) -> JoinApplication:
    return JoinApplication(
        id=row["id"],
        provider=row["provider"],
        external_id=row["external_id"],
        external_union_id=row["external_union_id"],
        raw_profile=json.loads(row["raw_profile"]) if row["raw_profile"] else {},
        suggested_match_user_id=row["suggested_match_user_id"],
        status=row["status"],
        applied_at=row["applied_at"],
        reviewed_at=row["reviewed_at"],
        reviewed_by=row["reviewed_by"],
        reject_reason=row["reject_reason"],
    )


class JoinApplicationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        provider: str,
        external_id: str,
        external_union_id: str | None,
        raw_profile: dict[str, Any],
        suggested_match_user_id: str | None,
    ) -> JoinApplication:
        new_id = uuid.uuid4().hex
        with self._db.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO join_application"
                    " (id, provider, external_id, external_union_id, raw_profile,"
                    "  suggested_match_user_id, status, applied_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (new_id, provider, external_id, external_union_id,
                     json.dumps(raw_profile, ensure_ascii=False),
                     suggested_match_user_id, "pending", time()),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(f"duplicate pending application: {e}") from e
        got = self.get(new_id)
        assert got is not None
        return got

    def get(self, application_id: str) -> JoinApplication | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM join_application WHERE id=?", (application_id,)
            ).fetchone()
        return _row_to_app(row) if row else None

    def lookup_blocking(
        self, provider: str, external_id: str
    ) -> JoinApplication | None:
        """Returns a pending or rejected application for (provider, external_id),
        or None. Used by login flow to decide whether to create new application."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM join_application"
                " WHERE provider=? AND external_id=?"
                " AND status IN ('pending','rejected')"
                " ORDER BY applied_at DESC LIMIT 1",
                (provider, external_id),
            ).fetchone()
        return _row_to_app(row) if row else None

    def list_pending(self) -> list[JoinApplication]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM join_application WHERE status='pending'"
                " ORDER BY applied_at ASC"
            ).fetchall()
        return [_row_to_app(r) for r in rows]

    def list_with_filter(self, status: str | None = None) -> list[JoinApplication]:
        sql = "SELECT * FROM join_application"
        params: list[object] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY applied_at DESC"
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_app(r) for r in rows]

    def approve(self, *, application_id: str, reviewed_by: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application"
                " SET status='approved', reviewed_at=?, reviewed_by=?"
                " WHERE id=?",
                (time(), reviewed_by, application_id),
            )

    def reject(
        self, *, application_id: str, reviewed_by: str, reason: str | None
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application"
                " SET status='rejected', reviewed_at=?, reviewed_by=?, reject_reason=?"
                " WHERE id=?",
                (time(), reviewed_by, reason, application_id),
            )

    def unblock(self, *, application_id: str) -> None:
        """Physical delete of a rejected row, freeing the (provider, external_id)
        for re-application. Per spec §5.4, this is the simplest implementation
        of "unblock" without adding new status enum values."""
        with self._db.connect() as conn:
            conn.execute(
                "DELETE FROM join_application WHERE id=? AND status='rejected'",
                (application_id,),
            )


def compute_match_candidates(
    users: PivotUserRepo,
    raw_profile: dict[str, Any],
    *,
    limit: int = 5,
) -> list[MatchCandidate]:
    """Compute same-person match candidates for an applicant.

    Matches only against status='active' users. Capped at `limit`.
    """
    name = (raw_profile.get("name") or "").strip()
    email = (raw_profile.get("email") or "").strip().lower()

    candidates: list[MatchCandidate] = []
    seen_ids: set[str] = set()

    actives = users.list_for_admin(include_deleted=False)
    actives = [u for u in actives if u.status == "active"]

    if email:
        for u in actives:
            if u.email and u.email.lower() == email and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="email_exact",
                ))
                seen_ids.add(u.id)

    if name:
        for u in actives:
            if u.display_name == name and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="name_exact",
                ))
                seen_ids.add(u.id)

    # Pinyin matches: only if applicant raw_profile carries an explicit pinyin
    # field (callers may pre-compute it from feishu open_user info or user input).
    applicant_pinyin = (raw_profile.get("pinyin") or "").strip().lower()
    if applicant_pinyin:
        for u in actives:
            if u.pinyin and u.pinyin.lower() == applicant_pinyin and u.id not in seen_ids:
                candidates.append(MatchCandidate(
                    user_id=u.id, display_name=u.display_name,
                    email=u.email, avatar_url=u.avatar_url, reason="pinyin_full",
                ))
                seen_ids.add(u.id)
        # Initials match
        applicant_initials = "".join(p[0] for p in applicant_pinyin.split() if p)
        if applicant_initials and len(applicant_initials) >= 2:
            for u in actives:
                if u.pinyin and u.id not in seen_ids:
                    user_initials = "".join(p[0] for p in u.pinyin.lower().split() if p)
                    if user_initials == applicant_initials:
                        candidates.append(MatchCandidate(
                            user_id=u.id, display_name=u.display_name,
                            email=u.email, avatar_url=u.avatar_url,
                            reason="pinyin_initials",
                        ))
                        seen_ids.add(u.id)

    return candidates[:limit]
```

- [ ] **Step 4: 跑，pass**

Run: `uv run pytest server/tests/test_join_applications.py -v`
Expected: 10 个测试 PASS

- [ ] **Step 5: Commit**

```bash
git add server/join_applications.py server/tests/test_join_applications.py
git commit -m "feat(auth): add JoinApplication repo + same-person match candidates"
```

### Task 7: InviteRepo

**Files:**
- Create: `server/invites.py`
- Test: `server/tests/test_invites.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import time as time_mod

import pytest

from server.db import Database
from server.invites import Invite, InviteRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    invites = InviteRepo(db)
    admin = users.create(display_name="Admin", pinyin="admin",
                         email=None, avatar_url="", role="admin")
    return users, invites, admin


def test_create_returns_token_plus_record(deps):
    _, invites, admin = deps
    token, record = invites.create(
        email="newcomer@example.com", display_name=None,
        created_by=admin.id, ttl_sec=86400 * 7,
    )
    assert token  # plaintext returned ONCE
    assert isinstance(record, Invite)
    assert record.email == "newcomer@example.com"
    assert record.used_at is None


def test_resolve_token_finds_active_invite(deps):
    _, invites, admin = deps
    token, _ = invites.create(
        email="x@example.com", display_name=None, created_by=admin.id, ttl_sec=3600,
    )
    found = invites.resolve_token(token)
    assert found is not None
    assert found.email == "x@example.com"


def test_resolve_invalid_token_returns_none(deps):
    _, invites, _ = deps
    assert invites.resolve_token("not-a-real-token") is None


def test_expired_invite_not_resolved(deps, monkeypatch):
    _, invites, admin = deps
    token, _ = invites.create(
        email="x@example.com", display_name=None, created_by=admin.id, ttl_sec=1,
    )
    # Force time to be after expiry
    real_time = time_mod.time
    monkeypatch.setattr("server.invites.time", lambda: real_time() + 10)
    assert invites.resolve_token(token) is None


def test_used_invite_not_resolved(deps):
    _, invites, admin = deps
    token, record = invites.create(
        email="x@example.com", display_name=None, created_by=admin.id, ttl_sec=3600,
    )
    invites.mark_used(invite_id=record.id, used_by_user_id="u-new")
    assert invites.resolve_token(token) is None


def test_revoke_invalidates_invite(deps):
    _, invites, admin = deps
    token, record = invites.create(
        email="x@example.com", display_name=None, created_by=admin.id, ttl_sec=3600,
    )
    invites.revoke(invite_id=record.id)
    assert invites.resolve_token(token) is None


def test_list_active_for_admin(deps):
    _, invites, admin = deps
    token1, r1 = invites.create(
        email="a@x.com", display_name=None, created_by=admin.id, ttl_sec=3600,
    )
    token2, r2 = invites.create(
        email="b@x.com", display_name=None, created_by=admin.id, ttl_sec=3600,
    )
    invites.mark_used(invite_id=r1.id, used_by_user_id="someone")
    listed = invites.list_for_admin(include_used=False)
    assert len(listed) == 1
    assert listed[0].id == r2.id
```

- [ ] **Step 2: 跑，fail**

Run: `uv run pytest server/tests/test_invites.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""Invite-code records for non-feishu users."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from time import time

from server.db import Database


@dataclass(frozen=True)
class Invite:
    id: str
    token_hash: str
    email: str
    display_name: str | None
    created_by: str
    created_at: float
    expires_at: float
    used_at: float | None
    used_by_user_id: str | None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_invite(row: sqlite3.Row) -> Invite:
    return Invite(
        id=row["id"],
        token_hash=row["token_hash"],
        email=row["email"],
        display_name=row["display_name"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        used_by_user_id=row["used_by_user_id"],
    )


class InviteRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        email: str,
        display_name: str | None,
        created_by: str,
        ttl_sec: int = 86400 * 7,
    ) -> tuple[str, Invite]:
        """Returns (plaintext_token, record). Plaintext is returned exactly
        once; only sha256 is persisted."""
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        new_id = uuid.uuid4().hex
        now = time()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO invite"
                " (id, token_hash, email, display_name, created_by,"
                "  created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (new_id, token_hash, email, display_name, created_by,
                 now, now + ttl_sec),
            )
            row = conn.execute(
                "SELECT * FROM invite WHERE id=?", (new_id,)
            ).fetchone()
        assert row is not None
        return token, _row_to_invite(row)

    def resolve_token(self, plaintext_token: str) -> Invite | None:
        token_hash = _hash_token(plaintext_token)
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM invite WHERE token_hash=?", (token_hash,)
            ).fetchone()
        if row is None:
            return None
        record = _row_to_invite(row)
        if record.used_at is not None:
            return None
        if record.expires_at < time():
            return None
        return record

    def mark_used(self, *, invite_id: str, used_by_user_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE invite SET used_at=?, used_by_user_id=? WHERE id=?",
                (time(), used_by_user_id, invite_id),
            )

    def revoke(self, *, invite_id: str) -> None:
        # "提前失效" by setting expires_at to past
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE invite SET expires_at=? WHERE id=?",
                (time() - 1, invite_id),
            )

    def list_for_admin(self, *, include_used: bool = True) -> list[Invite]:
        sql = "SELECT * FROM invite WHERE 1=1"
        if not include_used:
            sql += " AND used_at IS NULL"
        sql += " ORDER BY created_at DESC"
        with self._db.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [_row_to_invite(r) for r in rows]
```

- [ ] **Step 4: 跑，pass**

Run: `uv run pytest server/tests/test_invites.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add server/invites.py server/tests/test_invites.py
git commit -m "feat(auth): add InviteRepo for invite-code flow"
```

---

## Phase 2 · 迁移脚本

### Task 8: 迁移脚本（含 --dry-run）

**Files:**
- Create: `scripts/migrate_user_management.py`
- Test: `server/tests/test_migrate_user_management.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_user_management import migrate


def _seed_legacy_db(path: Path) -> None:
    """Build a v0 schema db with sample data."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            open_id TEXT PRIMARY KEY, union_id TEXT, name TEXT NOT NULL,
            avatar_url TEXT NOT NULL DEFAULT '',
            pinyin TEXT, github_username TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE drafts (id TEXT PRIMARY KEY, user_open_id TEXT NOT NULL, body TEXT);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, user_open_id TEXT NOT NULL,
            expires_at REAL NOT NULL, created_at REAL NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        ("ou_alice", "on_alice", "Alice", "", "alice", None, 1.0),
    )
    conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        ("ou_bob", "on_bob", "Bob", "", "bob", "bob_gh", 2.0),
    )
    conn.execute("INSERT INTO drafts VALUES (?,?,?)", ("d1", "ou_alice", "..."))
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                 ("s1", "ou_alice", 9999.0, 1.0))
    conn.commit()
    conn.close()


def test_dry_run_does_not_write(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=True)
    assert result.success
    # Verify no new tables created
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "pivot_user" not in tables


def test_full_migration_creates_tables_and_promotes_admin(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert result.success
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pivot_users = list(conn.execute("SELECT * FROM pivot_user"))
    assert len(pivot_users) == 2
    alice = conn.execute(
        "SELECT * FROM pivot_user WHERE pinyin='alice'"
    ).fetchone()
    assert alice["role"] == "admin"
    bob = conn.execute(
        "SELECT * FROM pivot_user WHERE pinyin='bob'"
    ).fetchone()
    assert bob["role"] == "member"
    bindings = list(conn.execute(
        "SELECT * FROM external_binding WHERE provider='feishu'"
    ))
    assert len(bindings) == 2
    # users table dropped
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "users" not in tables
    conn.close()


def test_initial_admin_no_match_aborts(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    result = migrate(db_path=db_path, initial_admin_pinyin="nobody", dry_run=False)
    assert not result.success
    assert "no user with pinyin" in result.error.lower()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "pivot_user" not in tables  # rolled back


def test_orphan_fk_aborts(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    # Insert orphan draft
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO drafts VALUES (?,?,?)", ("d2", "ou_ghost", "..."))
    conn.commit()
    conn.close()
    result = migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    assert not result.success
    assert "orphan" in result.error.lower()


def test_sessions_rewritten_not_cleared(tmp_path):
    db_path = tmp_path / "data.db"
    _seed_legacy_db(db_path)
    migrate(db_path=db_path, initial_admin_pinyin="alice", dry_run=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sessions = list(conn.execute("SELECT * FROM sessions"))
    conn.close()
    assert len(sessions) == 1  # still there
    # New column populated
    assert sessions[0]["pivot_user_id"] is not None
```

- [ ] **Step 2: 跑，fail**

Run: `uv run pytest server/tests/test_migrate_user_management.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现迁移脚本**

```python
#!/usr/bin/env python
"""User-management migration script (one-shot, single transaction).

See AI-docs/designs/2026-04-28-user-management-design.md §9.

Usage:
    uv run python scripts/migrate_user_management.py \
        --db var/data.db \
        --initial-admin <pinyin> \
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS pivot_user (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pinyin TEXT,
    email TEXT UNIQUE,
    avatar_url TEXT NOT NULL DEFAULT '',
    github_username TEXT,
    role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
    status_note TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_login_at REAL,
    status_changed_at REAL,
    status_changed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pivot_user_role_status ON pivot_user(role, status);

CREATE TABLE IF NOT EXISTS external_binding (
    id TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL REFERENCES pivot_user(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT,
    password_hash TEXT,
    bound_at REAL NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_binding_user ON external_binding(pivot_user_id);

CREATE TABLE IF NOT EXISTS join_application (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_union_id TEXT,
    raw_profile TEXT NOT NULL,
    suggested_match_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    applied_at REAL NOT NULL,
    reviewed_at REAL,
    reviewed_by TEXT,
    reject_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_join_app_pending_unique
    ON join_application(provider, external_id) WHERE status='pending';

CREATE TABLE IF NOT EXISTS invite (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    used_by_user_id TEXT
);
"""

_DOWNSTREAM_TABLES = (
    "drafts", "read_state", "favorites", "sessions",
    "ai_conversations", "api_tokens",
)


@dataclass
class MigrationResult:
    success: bool
    error: str = ""
    pivot_users_created: int = 0
    bindings_created: int = 0
    initial_admin_id: str | None = None


def _table_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def migrate(
    *,
    db_path: Path,
    initial_admin_pinyin: str,
    dry_run: bool,
) -> MigrationResult:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")

        # 1. New tables
        conn.executescript(_NEW_TABLES_SQL)

        # 2. Build mapping users.open_id → pivot_user.id and seed pivot_user
        users = list(conn.execute("SELECT * FROM users"))
        mapping: dict[str, str] = {}
        now = time()
        for u in users:
            new_id = uuid.uuid4().hex
            mapping[u["open_id"]] = new_id
            conn.execute(
                "INSERT INTO pivot_user"
                " (id, display_name, pinyin, email, avatar_url, github_username,"
                "  role, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id, u["name"], u["pinyin"], None, u["avatar_url"] or "",
                 u["github_username"], "member", "active",
                 u["created_at"], now),
            )
            raw_profile = json.dumps({
                "name": u["name"], "avatar_url": u["avatar_url"],
                "union_id": u["union_id"],
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO external_binding"
                " (id, pivot_user_id, provider, external_id, external_union_id,"
                "  raw_profile, bound_at) VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, new_id, "feishu", u["open_id"],
                 u["union_id"], raw_profile, u["created_at"]),
            )

        # 3. Add pivot_user_id column to downstream tables, populate, check orphans
        for table in _DOWNSTREAM_TABLES:
            if not _table_exists(conn, table):
                continue
            if not _table_has_column(conn, table, "user_open_id"):
                continue
            if not _table_has_column(conn, table, "pivot_user_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN pivot_user_id TEXT")
            conn.execute(
                f"UPDATE {table} SET pivot_user_id="
                " (SELECT id FROM pivot_user WHERE id IN ("
                "   SELECT pivot_user_id FROM external_binding"
                f"   WHERE provider='feishu' AND external_id={table}.user_open_id"
                " ))"
            )
            orphan_count = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
                " WHERE pivot_user_id IS NULL AND user_open_id IS NOT NULL"
            ).fetchone()["n"]
            if orphan_count > 0:
                raise _MigrationError(
                    f"orphan rows in {table}: {orphan_count} entries reference"
                    " open_id with no matching user"
                )

        # 4. Initial admin
        admin_row = conn.execute(
            "SELECT id FROM pivot_user WHERE pinyin=?",
            (initial_admin_pinyin,),
        ).fetchone()
        if admin_row is None:
            raise _MigrationError(
                f"no user with pinyin '{initial_admin_pinyin}'; cannot designate"
                " initial admin"
            )
        admin_matches = conn.execute(
            "SELECT COUNT(*) AS n FROM pivot_user WHERE pinyin=?",
            (initial_admin_pinyin,),
        ).fetchone()["n"]
        if admin_matches > 1:
            raise _MigrationError(
                f"pinyin '{initial_admin_pinyin}' matches {admin_matches} users"
                " — ambiguous; aborting"
            )
        admin_id = admin_row["id"]
        conn.execute(
            "UPDATE pivot_user SET role='admin' WHERE id=?", (admin_id,)
        )

        # 5. Drop legacy users table (only on real run)
        if not dry_run:
            conn.execute("DROP TABLE IF EXISTS users")

        if dry_run:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")

        return MigrationResult(
            success=True,
            pivot_users_created=len(users),
            bindings_created=len(users),
            initial_admin_id=admin_id,
        )
    except _MigrationError as e:
        conn.execute("ROLLBACK")
        return MigrationResult(success=False, error=str(e))
    except Exception as e:
        conn.execute("ROLLBACK")
        return MigrationResult(success=False, error=f"unexpected: {e}")
    finally:
        conn.close()


class _MigrationError(Exception):
    pass


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--initial-admin", type=str, required=True,
                        help="pinyin of the user to promote to admin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = migrate(
        db_path=args.db,
        initial_admin_pinyin=args.initial_admin,
        dry_run=args.dry_run,
    )
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    if result.success:
        print(f"[{mode}] OK")
        print(f"  pivot_user rows created: {result.pivot_users_created}")
        print(f"  feishu bindings created: {result.bindings_created}")
        print(f"  initial admin id: {result.initial_admin_id}")
        return 0
    else:
        print(f"[{mode}] FAILED: {result.error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: 跑测试**

Run: `uv run pytest server/tests/test_migrate_user_management.py -v`
Expected: 6 PASS

- [ ] **Step 5: 验证脚本可独立执行**

Run: `uv run python scripts/migrate_user_management.py --help`
Expected: 打印 usage 文档

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_user_management.py server/tests/test_migrate_user_management.py
git commit -m "feat(migration): add user-management migration script with --dry-run"
```

---

## Phase 3 · Auth 改造

### Task 9: 替换 deps.py：返回 PivotUser + 状态校验

**Files:**
- Modify: `server/auth/deps.py`（整体重写）
- Test: `server/tests/test_auth_deps.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user,
)
from server.auth.session import SessionStore
from server.db import Database
from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    sessions = SessionStore(db)
    api_tokens = ApiTokenRepo(db)
    bindings = ExternalBindingRepo(db)
    user = users.create(display_name="Alice", pinyin="alice",
                        email=None, avatar_url="", role="member")
    return users, sessions, api_tokens, bindings, user


def test_active_user_passes_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    result = dep(sid=sid, authorization=None)
    assert result.id == user.id


def test_suspended_user_blocked_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="suspended", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException) as exc:
        dep(sid=sid, authorization=None)
    assert exc.value.status_code == 401


def test_deleted_user_blocked_via_cookie(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="deleted", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException):
        dep(sid=sid, authorization=None)


def test_session_deleted_after_status_block(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    users.update_status(user_id=user.id, status="suspended", note=None, changed_by=user.id)
    dep = make_current_user(sessions, users, api_tokens)
    with pytest.raises(HTTPException):
        dep(sid=sid, authorization=None)
    assert sessions.get(sid) is None  # forced logout


def test_admin_user_passes_admin_dep(stack):
    users, sessions, api_tokens, _, user = stack
    users.update_role(user_id=user.id, role="admin")
    sid = sessions.create(pivot_user_id=user.id)
    user_dep = make_current_user(sessions, users, api_tokens)
    admin_dep = make_require_admin_user()
    fetched = user_dep(sid=sid, authorization=None)
    result = admin_dep(user=fetched)
    assert result.id == user.id


def test_member_blocked_by_admin_dep(stack):
    users, sessions, api_tokens, _, user = stack
    sid = sessions.create(pivot_user_id=user.id)
    user_dep = make_current_user(sessions, users, api_tokens)
    admin_dep = make_require_admin_user()
    fetched = user_dep(sid=sid, authorization=None)
    with pytest.raises(HTTPException) as exc:
        admin_dep(user=fetched)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: 跑，旧 deps 还存在所以会有冲突**

Run: `uv run pytest server/tests/test_auth_deps.py -v`
Expected: ImportError 或 fail（旧 deps.py 用 User，新 test 用 PivotUser）

- [ ] **Step 3: 重写 deps.py**

```python
"""Unified auth dependencies for /api/* routes (post-migration)."""
from __future__ import annotations

from typing import Callable

from fastapi import Cookie, Header, HTTPException

from server.api_tokens import ApiTokenRepo
from server.auth.session import SessionStore
from server.pivot_users import PivotUser, PivotUserRepo

BEARER_PREFIX = "Bearer "


def _resolve_user(user_id: str, users: PivotUserRepo,
                  on_block_cleanup: Callable[[], None]) -> PivotUser | None:
    u = users.get(user_id)
    if u is None:
        on_block_cleanup()
        return None
    if u.status != "active":
        on_block_cleanup()
        return None
    return u


def _user_from_session(
    sid: str | None, sessions: SessionStore, users: PivotUserRepo
) -> PivotUser | None:
    s = sessions.get(sid)
    if s is None:
        return None
    return _resolve_user(
        s.pivot_user_id, users,
        on_block_cleanup=lambda: sessions.delete(sid),
    )


def _user_from_bearer(
    authorization: str | None, tokens: ApiTokenRepo, users: PivotUserRepo,
) -> PivotUser | None:
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        return None
    token = authorization[len(BEARER_PREFIX):].strip()
    tok = tokens.lookup_by_plaintext(token)
    if tok is None:
        return None
    u = _resolve_user(tok.pivot_user_id, users, on_block_cleanup=lambda: None)
    if u is None:
        return None
    tokens.touch_last_used(tok.token_hash)
    return u


def make_current_user(
    sessions: SessionStore, users: PivotUserRepo, tokens: ApiTokenRepo,
) -> Callable:
    def current_user(
        sid: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> PivotUser:
        u = _user_from_session(sid, sessions, users)
        if u is None:
            u = _user_from_bearer(authorization, tokens, users)
        if u is None:
            raise HTTPException(status_code=401, detail="invalid_token")
        return u
    return current_user


def make_current_user_cookie_only(
    sessions: SessionStore, users: PivotUserRepo,
) -> Callable:
    def current_user_cookie(sid: str | None = Cookie(default=None)) -> PivotUser:
        u = _user_from_session(sid, sessions, users)
        if u is None:
            raise HTTPException(status_code=401, detail="not logged in")
        return u
    return current_user_cookie


def make_require_admin_user() -> Callable:
    """Returns a dependency that, given an already-resolved PivotUser
    (typically via Depends(current_user)), enforces role='admin'.
    Status is already guaranteed active by current_user resolution."""
    def require(user: PivotUser) -> PivotUser:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="admin_required")
        return user
    return require


def require_profile(user: PivotUser) -> PivotUser:
    if not user.pinyin:
        raise HTTPException(status_code=400, detail="profile setup required")
    return user
```

- [ ] **Step 4: 修改 SessionStore 字段名（task 10 完整做完，这里只对齐）**

确认 `server/auth/session.py` 的 `Session` dataclass 含 `pivot_user_id` 字段（暂时与 `user_open_id` 共存；最终 task 10 重命名）。这一步**先不做**——等 Task 10。

为让本 task 的测试通过，先在 `SessionStore.create()` 加一个临时形参：

修改 `server/auth/session.py`：
- `create(self, user_open_id, ...)` → `create(self, pivot_user_id=None, user_open_id=None, ...)` 接受任一参数
- `Session` 加 `pivot_user_id: str | None = None`

具体改动留到 Task 10。这一步先**跑测试看下哪些挂掉**：

Run: `uv run pytest server/tests/test_auth_deps.py -v`
Expected: 全部 fail（因为 SessionStore 还没有 pivot_user_id 概念）

**这一步暂停 Task 9，先做 Task 10 的 session 重命名，再回来收尾 Task 9。**

- [ ] **Step 5: （Task 10 完成后回来）跑 deps 测试，pass**

Run: `uv run pytest server/tests/test_auth_deps.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add server/auth/deps.py server/tests/test_auth_deps.py
git commit -m "feat(auth): deps.py returns PivotUser + status check + require_admin_user"
```

### Task 10: 重命名 session 字段 user_open_id → pivot_user_id

**Files:**
- Modify: `server/auth/session.py`
- Modify: `server/db.py:54-60`（schema）
- Modify: `server/api_tokens.py`（同等重命名）
- Modify: `server/db.py:73-81`（api_tokens schema）
- Modify: `server/mcp/auth.py`
- Modify: `server/api/tokens.py`
- Modify: `server/tests/test_session.py`
- Modify: `server/tests/test_api_tokens.py`
- Modify: `server/tests/test_mcp_auth.py`

- [ ] **Step 1: 在 SessionStore 加 `pivot_user_id` 字段，保留 `user_open_id` 兼容**

修改 `server/auth/session.py:14`（Session dataclass）：

```python
@dataclass
class Session:
    pivot_user_id: str
    expires_at: float
    user_access_token: str | None = None

    # Migration alias
    @property
    def user_open_id(self) -> str:
        return self.pivot_user_id
```

修改 `SessionStore.create()`:

```python
def create(
    self,
    pivot_user_id: str,
    *,
    user_access_token: str | None = None,
) -> str:
    sid = secrets.token_urlsafe(32)
    now = time()
    with self._db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions"
            " (id, pivot_user_id, expires_at, created_at, user_access_token)"
            " VALUES (?,?,?,?,?)",
            (sid, pivot_user_id, now + self._ttl, now, user_access_token),
        )
    return sid
```

修改 `SessionStore.get()`:

```python
def get(self, sid: str | None) -> Session | None:
    if not sid:
        return None
    with self._db.connect() as conn:
        row = conn.execute(
            "SELECT pivot_user_id, expires_at, user_access_token"
            " FROM sessions WHERE id=?", (sid,),
        ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < time():
        self.delete(sid)
        return None
    return Session(
        pivot_user_id=row["pivot_user_id"],
        expires_at=row["expires_at"],
        user_access_token=row["user_access_token"],
    )
```

- [ ] **Step 2: 修改 db.py 的 sessions 表 schema**

修改 `server/db.py:54-60`：

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
```

修改 `server/db.py:73-81`（api_tokens 表）：

```sql
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    pivot_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(pivot_user_id);
```

注意：`_migrate()` 函数里要加 ALTER 路径让旧库可以升级——但这个 plan 里我们靠 Phase 2 的迁移脚本处理生产库。dev 库直接删 `var/data.db` 重建（不管现有数据）：

```bash
rm var/data.db
```

- [ ] **Step 3: 改 `server/api_tokens.py`**

`ApiToken` dataclass 和 Repo 里 `user_open_id` 全部改名 `pivot_user_id`。所有 SQL 同步改。

- [ ] **Step 4: 改 `server/api/tokens.py` 和 `server/mcp/auth.py`**

调用 `api_tokens.lookup_by_plaintext` 等接口的 `tok.user_open_id` → `tok.pivot_user_id`，`users.get(tok.pivot_user_id)` 等。

- [ ] **Step 5: 修改对应单测文件**

`test_session.py` / `test_api_tokens.py` / `test_mcp_auth.py` 里所有 `user_open_id` 形参/字段名改 `pivot_user_id`。

- [ ] **Step 6: 跑测试**

Run: `uv run pytest server/tests/test_session.py server/tests/test_api_tokens.py server/tests/test_mcp_auth.py server/tests/test_auth_deps.py -v`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add server/auth/session.py server/api_tokens.py server/api/tokens.py server/mcp/auth.py server/db.py server/tests/test_session.py server/tests/test_api_tokens.py server/tests/test_mcp_auth.py server/tests/test_auth_deps.py
git commit -m "refactor(auth): rename session/api_tokens user_open_id to pivot_user_id"
```

### Task 11: /auth/callback 改造（飞书已绑 / 未绑分流）

**Files:**
- Modify: `server/auth/routes.py`
- Test: `server/tests/test_auth_routes.py`

- [ ] **Step 1: 写测试场景**

```python
# 增加在已有 test_routes.py / test_session.py 测试模块中，或新建：
from __future__ import annotations
import pytest

# 测试三个分支：
# - feishu open_id 已有 binding 且 user.status=active → 写 session，重定向首页
# - feishu open_id 已有 binding 但 user.status=suspended → 401 拦截，文案"账号已暂停"
# - feishu open_id 没有 binding 且没有 pending/rejected 申请 → 创建 join_application
# - feishu open_id 没有 binding 但有 pending → 显示"等待审批"
# - feishu open_id 没有 binding 但有 rejected → 阻断"已被拒绝"

# (具体测试写法见 test_routes.py 既有风格，用 TestClient + 模拟 OAuth callback)
```

详细测试代码因依赖现有 fixtures 工程量较大，**保持现有 `test_routes.py` 的 OAuth happy-path 测试，新增 3-4 个分支测试**。具体由实施者按现有风格补全。

- [ ] **Step 2: 改 build_router 函数签名加上新依赖**

修改 `server/auth/routes.py`：

```python
def build_router(
    oauth: FeishuOAuth,
    sessions: SessionStore,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    applications: JoinApplicationRepo,
    notifier: Notifier,
    contacts: ContactRepo,
    session_secret: str,
    post_login_redirect: str = "/",
    secure_cookie: bool = False,
) -> APIRouter:
    ...
```

- [ ] **Step 3: 重写 `/auth/callback` 处理函数**

替换 `server/auth/routes.py` 的 `callback()` 函数：

```python
@router.get("/auth/callback")
def callback(code: str, state: str) -> RedirectResponse:
    next_url = _verify_state(state)
    try:
        token = oauth.exchange_code(code)
        info = oauth.get_user_info(token.access_token)
    except FeishuOAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Always update contacts mirror — independent of binding state
    contacts.upsert_from_login(
        open_id=info.open_id, union_id=info.union_id,
        name=info.name, avatar_url=info.avatar_url or "",
    )

    binding = bindings.lookup(provider="feishu", external_id=info.open_id)
    if binding is not None:
        # Entry 1: existing user
        user = pivot_users.get(binding.pivot_user_id)
        if user is None:
            raise HTTPException(status_code=500, detail="binding_orphan")
        if user.status == "suspended":
            return RedirectResponse(
                f"{post_login_redirect}login?reason=suspended",
                status_code=302,
            )
        if user.status == "deleted":
            return RedirectResponse(
                f"{post_login_redirect}login?reason=deleted",
                status_code=302,
            )
        pivot_users.touch_last_login(user.id)
        sid = sessions.create(
            pivot_user_id=user.id, user_access_token=token.access_token
        )
        resp = RedirectResponse(next_url, status_code=302)
        resp.set_cookie(
            SESSION_COOKIE, sid,
            httponly=True, samesite=cookie_samesite,
            secure=secure_cookie, path="/",
        )
        return resp

    # Entry 2: not bound — check application history
    blocking = applications.lookup_blocking("feishu", info.open_id)
    if blocking is not None:
        if blocking.status == "pending":
            return RedirectResponse(
                f"{post_login_redirect}login?reason=pending_approval",
                status_code=302,
            )
        if blocking.status == "rejected":
            return RedirectResponse(
                f"{post_login_redirect}login?reason=rejected",
                status_code=302,
            )

    # Create new application
    raw_profile = {
        "name": info.name, "avatar_url": info.avatar_url,
        "union_id": info.union_id,
    }
    candidates = compute_match_candidates(pivot_users, raw_profile=raw_profile)
    suggested = candidates[0].user_id if candidates else None
    applications.create(
        provider="feishu", external_id=info.open_id,
        external_union_id=info.union_id,
        raw_profile=raw_profile, suggested_match_user_id=suggested,
    )
    # Notify all active admins
    admin_open_ids = _admin_feishu_open_ids(pivot_users, bindings)
    if admin_open_ids:
        notifier.notify_application_created(
            applicant_name=info.name, provider="feishu",
            admin_open_ids=admin_open_ids,
        )
    return RedirectResponse(
        f"{post_login_redirect}login?reason=submitted",
        status_code=302,
    )


def _admin_feishu_open_ids(
    pivot_users: PivotUserRepo, bindings: ExternalBindingRepo,
) -> list[str]:
    """Resolve all active admins' feishu open_ids for DM notification."""
    admins = [u for u in pivot_users.list_for_admin(include_deleted=False)
              if u.role == "admin" and u.status == "active"]
    open_ids: list[str] = []
    for a in admins:
        for b in bindings.list_for_user(a.id):
            if b.provider == "feishu":
                open_ids.append(b.external_id)
                break
    return open_ids
```

加 imports：
```python
from server.external_bindings import ExternalBindingRepo
from server.join_applications import JoinApplicationRepo, compute_match_candidates
from server.notify import Notifier
from server.pivot_users import PivotUserRepo
```

- [ ] **Step 4: 在 app.py 的 build_auth_router 调用处加新依赖**

修改 `server/app.py:119-128`：

```python
app.include_router(
    build_auth_router(
        oauth, sessions, pivot_users, bindings, applications, notifier,
        contacts, cfg.session_secret,
        post_login_redirect=cfg.web_dev_origin + "/",
        secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
    )
)
```

需要在 app.py 上面先实例化 `pivot_users`、`bindings`、`applications`、`invites`：

```python
from server.external_bindings import ExternalBindingRepo
from server.invites import InviteRepo
from server.join_applications import JoinApplicationRepo
from server.pivot_users import PivotUserRepo

pivot_users = PivotUserRepo(db)
bindings = ExternalBindingRepo(db)
applications = JoinApplicationRepo(db)
invites = InviteRepo(db)
```

`users = UserRepo(db)` 留着供 mentions.py 等模块过渡使用。

- [ ] **Step 5: 跑现有 test_routes.py，确认 OAuth happy path 还能通**

Run: `uv run pytest server/tests/test_routes.py -v`
Expected: 现有测试可能因为 `build_router` 签名变了而 fail——按 Step 3 的新签名调整 fixture，然后 PASS

- [ ] **Step 6: Commit**

```bash
git add server/auth/routes.py server/app.py server/tests/test_routes.py
git commit -m "feat(auth): /auth/callback dispatches by binding/application state"
```

### Task 12: /init 端点

**Files:**
- Create: `server/api/init.py`
- Test: `server/tests/test_init_api.py`

- [ ] **Step 1: 写测试**

```python
from __future__ import annotations

from fastapi.testclient import TestClient

# 测试场景：
# - 系统刚启动，无 admin → GET /init/status 返回 {needs_init: true}
# - POST /init/complete with feishu token → 创建 admin user + binding + 自动登录
# - POST /init/complete with email/password → 同上
# - 已有 admin 时 → GET /init/status 返回 {needs_init: false}, POST /init/complete 返 409

def test_init_status_when_no_admin(client_no_admin: TestClient):
    r = client_no_admin.get("/init/status")
    assert r.status_code == 200
    assert r.json() == {"needs_init": True}


def test_init_status_when_admin_exists(client_with_admin: TestClient):
    r = client_with_admin.get("/init/status")
    assert r.json() == {"needs_init": False}


def test_init_complete_email_password(client_no_admin: TestClient):
    payload = {
        "method": "email_password",
        "email": "first@example.com",
        "password": "hunter2",
        "display_name": "First Admin",
        "pinyin": "first",
    }
    r = client_no_admin.post("/init/complete", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["status"] == "active"
    # session cookie should be set
    assert "sid" in r.cookies


def test_init_complete_blocked_when_admin_exists(client_with_admin: TestClient):
    payload = {
        "method": "email_password",
        "email": "second@example.com",
        "password": "x", "display_name": "Late", "pinyin": "late",
    }
    r = client_with_admin.post("/init/complete", json=payload)
    assert r.status_code == 409
```

- [ ] **Step 2: 跑，fail**

Run: `uv run pytest server/tests/test_init_api.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: 实现 /init router**

```python
"""Initial-admin bootstrap endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PINYIN_RE_PATTERN, PivotUserRepo

SESSION_COOKIE = "sid"


class InitCompleteEmailPassword(BaseModel):
    method: str = Field(default="email_password")
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    pinyin: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9._-]*$")


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.get("/init/status")
    def status() -> JSONResponse:
        return JSONResponse({"needs_init": pivot_users.count_active_admins() == 0})

    @router.post("/init/complete")
    def complete(body: InitCompleteEmailPassword) -> JSONResponse:
        if pivot_users.count_active_admins() > 0:
            raise HTTPException(status_code=409, detail="admin_already_exists")
        # Currently only email/password method is implemented in this endpoint.
        # Feishu init goes through normal /auth/callback which checks count_active_admins
        # and bypasses join_application when zero (see Task 11 callback code path).
        if body.method != "email_password":
            raise HTTPException(status_code=400, detail="unsupported_method")
        try:
            user = pivot_users.create(
                display_name=body.display_name, pinyin=body.pinyin,
                email=body.email, avatar_url="", role="admin",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        bindings.bind(
            pivot_user_id=user.id, provider="invite", external_id=body.email,
            external_union_id=None, raw_profile_json=None,
            password_hash=hash_password(body.password),
        )
        sid = sessions.create(pivot_user_id=user.id)
        resp = JSONResponse({
            "user": {
                "id": user.id, "display_name": user.display_name,
                "role": user.role, "status": user.status,
            },
        })
        resp.set_cookie(
            SESSION_COOKIE, sid, httponly=True, samesite=samesite,
            secure=secure_cookie, path="/",
        )
        return resp

    return router
```

注意：`PINYIN_RE_PATTERN` 应改成正则字符串供 pydantic Field 使用——把 `users.py` 现有 PINYIN_RE 提取为字符串常量供复用。

修改 `server/users.py:10`（保留兼容）和 `server/pivot_users.py` 加：
```python
PINYIN_RE_PATTERN = r"^[a-z][a-z0-9._-]{1,39}$"
```

- [ ] **Step 4: 在 app.py 注册 init router**

`server/app.py`:
```python
from server.api.init import build_router as build_init_router

app.include_router(build_init_router(
    pivot_users, bindings, sessions,
    secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
))
```

- [ ] **Step 5: Update routes.py 的 /auth/callback：当无 admin 时直接 promote 飞书首登者**

修改 Task 11 写的 callback：在 "Entry 2 — not bound" 分支前加：

```python
if pivot_users.count_active_admins() == 0:
    # Bootstrap: first user → instant admin without going through application
    user = pivot_users.create(
        display_name=info.name, pinyin=None,  # filled at ProfileSetup
        email=None, avatar_url=info.avatar_url or "", role="admin",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id=info.open_id, external_union_id=info.union_id,
        raw_profile_json=json.dumps({"name": info.name, ...}),
    )
    sid = sessions.create(pivot_user_id=user.id, user_access_token=token.access_token)
    # ... set cookie + redirect ...
```

- [ ] **Step 6: 跑测试**

Run: `uv run pytest server/tests/test_init_api.py -v`
Expected: 4 PASS

- [ ] **Step 7: Commit**

```bash
git add server/api/init.py server/app.py server/auth/routes.py server/tests/test_init_api.py server/users.py server/pivot_users.py
git commit -m "feat(auth): add /init/status and /init/complete bootstrap endpoints"
```

### Task 13: 邮箱密码登录端点

**Files:**
- Create: `server/api/auth_email_password.py`
- Test: `server/tests/test_email_password_login.py`

- [ ] **Step 1: 写测试**

```python
def test_email_password_login_success(...):
    # setup: create invite user with bcrypt password
    # POST /auth/login_email_password {email, password}
    # → 200 + sid cookie set + body {"user": ...}
    pass


def test_email_password_login_wrong_password(...):
    # → 401
    pass


def test_email_password_login_suspended_user(...):
    # → 401
    pass


def test_email_password_login_no_such_email(...):
    # → 401
    pass
```

(具体测试代码 ~80 行，按 server/tests/conftest.py 现有 fixtures 风格写。)

- [ ] **Step 2: 跑，fail**

- [ ] **Step 3: 实现**

```python
"""Email + password login for invite-code users."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.passwords import verify_password
from server.pivot_users import PivotUserRepo

SESSION_COOKIE = "sid"


class EmailPasswordLogin(BaseModel):
    email: EmailStr
    password: str


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.post("/auth/login_email_password")
    def login(body: EmailPasswordLogin) -> JSONResponse:
        binding = bindings.lookup(provider="invite", external_id=body.email)
        if binding is None or binding.password_hash is None:
            raise HTTPException(status_code=401, detail="invalid_credentials")
        if not verify_password(body.password, binding.password_hash):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        user = pivot_users.get(binding.pivot_user_id)
        if user is None or user.status != "active":
            raise HTTPException(status_code=401, detail="invalid_credentials")
        pivot_users.touch_last_login(user.id)
        sid = sessions.create(pivot_user_id=user.id)
        resp = JSONResponse({
            "user": {
                "id": user.id, "display_name": user.display_name,
                "role": user.role, "status": user.status,
            },
        })
        resp.set_cookie(
            SESSION_COOKIE, sid, httponly=True, samesite=samesite,
            secure=secure_cookie, path="/",
        )
        return resp

    return router
```

- [ ] **Step 4: 注册到 app.py**

```python
from server.api.auth_email_password import build_router as build_email_login_router
app.include_router(build_email_login_router(pivot_users, bindings, sessions, secure_cookie=...))
```

- [ ] **Step 5: 跑测试，pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(auth): add email/password login for invite users"
```

### Task 14: 邀请加载 / 接受端点

**Files:**
- Create: `server/api/auth_invite.py`
- Test: `server/tests/test_invite_routes.py`

- [ ] **Step 1: 写测试**（4 个 case：load valid / load expired / accept happy path / accept reuse rejected）

- [ ] **Step 2: 跑，fail**

- [ ] **Step 3: 实现**

```python
"""Invite link load + accept endpoints (public)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from server.auth.session import SessionStore
from server.external_bindings import ExternalBindingRepo
from server.invites import InviteRepo
from server.passwords import hash_password
from server.pivot_users import PivotUserRepo

SESSION_COOKIE = "sid"


class InviteAcceptBody(BaseModel):
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    pinyin: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9._-]*$")


def build_router(
    invites: InviteRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.get("/invite/{token}")
    def load(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        return JSONResponse({
            "email": invite.email,
            "display_name": invite.display_name,
            "expires_at": invite.expires_at,
        })

    @router.post("/invite/{token}/accept")
    def accept(token: str, body: InviteAcceptBody) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        try:
            user = pivot_users.create(
                display_name=body.display_name, pinyin=body.pinyin,
                email=invite.email, avatar_url="", role="member",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        bindings.bind(
            pivot_user_id=user.id, provider="invite", external_id=invite.email,
            external_union_id=None, raw_profile_json=None,
            password_hash=hash_password(body.password),
        )
        invites.mark_used(invite_id=invite.id, used_by_user_id=user.id)
        sid = sessions.create(pivot_user_id=user.id)
        resp = JSONResponse({
            "user": {
                "id": user.id, "display_name": user.display_name,
                "role": user.role, "status": user.status,
            },
        })
        resp.set_cookie(
            SESSION_COOKIE, sid, httponly=True, samesite=samesite,
            secure=secure_cookie, path="/",
        )
        return resp

    return router
```

- [ ] **Step 4: 注册到 app.py**

- [ ] **Step 5: 跑测试，pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(auth): add invite link load + accept endpoints"
```

### Task 15: 替换 require_admin（3 个端点）+ 删除 admin.py

**Files:**
- Modify: `server/api/ai.py`
- Modify: `server/api/contacts.py`
- Modify: `server/api/workspace.py`
- Delete: `server/auth/admin.py`
- Update tests that previously sent `X-Admin-Password` header

- [ ] **Step 1: 在 app.py 准备 require_admin_user dep**

```python
from server.auth.deps import make_require_admin_user

require_admin_user_dep = make_require_admin_user()
```

- [ ] **Step 2: 修改 server/api/ai.py**

修改 `server/api/ai.py:21`：
- 删除 `from server.auth.admin import require_admin`
- 加 `from server.auth.deps import make_require_admin_user`
- 修改 `build_router` 签名加上 `require_admin: Callable`
- `@router.get(..., dependencies=[Depends(require_admin)])` → `dependencies=[Depends(require_admin)]`（这里参数名 require_admin 现在指 require_admin_user dep）

- [ ] **Step 3: 同样修改 contacts.py 和 workspace.py**

- [ ] **Step 4: 修改 app.py 把 require_admin_user_dep 传给 3 个 build_router**

```python
app.include_router(build_ai_router(
    workspace, settings, ai_conversations,
    current_user_dep, current_user_cookie_dep,
    require_admin=require_admin_user_dep,
))
# 类似改 contacts、workspace
```

需要把现在 ai/contacts/workspace 的 `current_user_dep` 链改成"先解析 user，再 require admin"——FastAPI dep 链式：

```python
admin_user_dep = lambda user=Depends(current_user_dep): require_admin_user_dep(user)
```

- [ ] **Step 5: 删除 server/auth/admin.py**

```bash
rm server/auth/admin.py
```

- [ ] **Step 6: 修改测试**

`server/tests/test_ai_api.py` / `test_workspace_api.py` / `test_contacts.py` 等里凡是 `headers={"X-Admin-Password": "000123"}` 的——改成用一个"已 promoted 为 admin 的 user 的 cookie 登录"。

- [ ] **Step 7: 跑全量回归**

Run: `uv run pytest -q`
Expected: 全绿

- [ ] **Step 8: Commit**

```bash
git add server/api/ai.py server/api/contacts.py server/api/workspace.py server/app.py server/tests/test_ai_api.py server/tests/test_contacts.py server/tests/test_workspace_api.py
git rm server/auth/admin.py
git commit -m "refactor(auth): replace X-Admin-Password with require_admin_user role check"
```

---

## Phase 4 · 管理员 API

### Task 16: /api/admin/applications

**Files:**
- Create: `server/api/admin_applications.py`
- Test: `server/tests/test_admin_applications_api.py`

- [ ] **Step 1: 写测试**（pending list、approve as new user、approve as merge、reject、unblock — 共 ~6 case）

- [ ] **Step 2: 跑，fail**

- [ ] **Step 3: 实现**

```python
"""Admin: join applications endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.external_bindings import ExternalBindingRepo
from server.join_applications import (
    JoinApplicationRepo,
    compute_match_candidates,
)
from server.notify import Notifier
from server.pivot_users import PivotUser, PivotUserRepo


class ApproveBody(BaseModel):
    target_pivot_user_id: str | None = None  # None = create new user


class RejectBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


def build_router(
    applications: JoinApplicationRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    notifier: Notifier,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/applications")

    @router.get("")
    def list_applications(
        status: str | None = None,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        if status:
            apps = applications.list_with_filter(status=status)
        else:
            apps = applications.list_pending()
        return JSONResponse({"items": [_app_dict(a) for a in apps]})

    @router.get("/{application_id}/match-candidates")
    def candidates(
        application_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None:
            raise HTTPException(status_code=404)
        cands = compute_match_candidates(pivot_users, raw_profile=a.raw_profile)
        return JSONResponse({
            "candidates": [
                {"user_id": c.user_id, "display_name": c.display_name,
                 "email": c.email, "avatar_url": c.avatar_url, "reason": c.reason}
                for c in cands
            ],
        })

    @router.post("/{application_id}/approve")
    def approve(
        application_id: str,
        body: ApproveBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None or a.status != "pending":
            raise HTTPException(status_code=404)

        if body.target_pivot_user_id is None:
            # Create new user
            user = pivot_users.create(
                display_name=a.raw_profile.get("name") or "Unknown",
                pinyin=None,
                email=a.raw_profile.get("email"),
                avatar_url=a.raw_profile.get("avatar_url") or "",
                role="member",
            )
            target_id = user.id
            merge = False
        else:
            target = pivot_users.get(body.target_pivot_user_id)
            if target is None or target.status != "active":
                raise HTTPException(status_code=400, detail="invalid_merge_target")
            target_id = target.id
            merge = True
        try:
            bindings.bind(
                pivot_user_id=target_id, provider=a.provider,
                external_id=a.external_id, external_union_id=a.external_union_id,
                raw_profile_json=str(a.raw_profile),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        applications.approve(application_id=application_id, reviewed_by=admin.id)

        notifier.notify_application_approved(
            applicant_open_id=a.external_id if a.provider == "feishu" else "",
            merged=merge,
        )
        return JSONResponse({"approved": True, "user_id": target_id})

    @router.post("/{application_id}/reject")
    def reject(
        application_id: str, body: RejectBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        a = applications.get(application_id)
        if a is None or a.status != "pending":
            raise HTTPException(status_code=404)
        applications.reject(
            application_id=application_id,
            reviewed_by=admin.id, reason=body.reason,
        )
        notifier.notify_application_rejected(
            applicant_open_id=a.external_id if a.provider == "feishu" else "",
        )
        return JSONResponse({"rejected": True})

    @router.post("/{application_id}/unblock")
    def unblock(
        application_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        applications.unblock(application_id=application_id)
        return JSONResponse({"unblocked": True})

    return router


def _app_dict(a) -> dict:
    return {
        "id": a.id, "provider": a.provider, "external_id": a.external_id,
        "raw_profile": a.raw_profile,
        "suggested_match_user_id": a.suggested_match_user_id,
        "status": a.status, "applied_at": a.applied_at,
        "reviewed_at": a.reviewed_at, "reviewed_by": a.reviewed_by,
        "reject_reason": a.reject_reason,
    }
```

- [ ] **Step 4: 注册到 app.py**

- [ ] **Step 5: 跑测试，pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(admin): add /api/admin/applications endpoints"
```

### Task 17: /api/admin/users

**Files:**
- Create: `server/api/admin_users.py`
- Test: `server/tests/test_admin_users_api.py`

- [ ] **Step 1: 写测试**（list、suspend、resume、mark-deleted、restore、role change、最少 1 admin 护栏 — 共 ~10 case）

- [ ] **Step 2: 实现**

```python
"""Admin: user management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.external_bindings import ExternalBindingRepo
from server.passwords import hash_password
from server.pivot_users import PivotUser, PivotUserRepo


class StatusChangeBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ConfirmedStatusChangeBody(StatusChangeBody):
    confirm_display_name: str


class RoleChangeBody(BaseModel):
    role: str  # 'admin' | 'member'


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


def build_router(
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    admin_user_dep,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/users")

    def _refuse_self(user_id: str, admin: PivotUser) -> None:
        if admin.id == user_id:
            raise HTTPException(
                status_code=422, detail="cannot_modify_self_state_or_role"
            )

    def _refuse_last_admin(target_id: str) -> None:
        target = pivot_users.get(target_id)
        if target is None:
            raise HTTPException(status_code=404)
        if target.role == "admin" and target.status == "active":
            if pivot_users.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=422, detail="last_active_admin_protected"
                )

    @router.get("")
    def list_users(
        include_deleted: bool = False, search: str | None = None,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        users = pivot_users.list_for_admin(
            include_deleted=include_deleted, search=search,
        )
        return JSONResponse({"items": [_user_dict(u, bindings) for u in users]})

    @router.post("/{user_id}/suspend")
    def suspend(
        user_id: str, body: StatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        _refuse_self(user_id, admin)
        _refuse_last_admin(user_id)
        u = pivot_users.update_status(
            user_id=user_id, status="suspended",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/resume")
    def resume(
        user_id: str, body: StatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        u = pivot_users.update_status(
            user_id=user_id, status="active",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/mark-deleted")
    def mark_deleted(
        user_id: str, body: ConfirmedStatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        _refuse_self(user_id, admin)
        _refuse_last_admin(user_id)
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        if body.confirm_display_name != target.display_name:
            raise HTTPException(status_code=422, detail="display_name_mismatch")
        u = pivot_users.update_status(
            user_id=user_id, status="deleted",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/restore")
    def restore(
        user_id: str, body: ConfirmedStatusChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        if body.confirm_display_name != target.display_name:
            raise HTTPException(status_code=422, detail="display_name_mismatch")
        u = pivot_users.update_status(
            user_id=user_id, status="active",
            note=body.note, changed_by=admin.id,
        )
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/role")
    def change_role(
        user_id: str, body: RoleChangeBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        if body.role not in ("admin", "member"):
            raise HTTPException(status_code=400, detail="invalid_role")
        if body.role == "member":
            _refuse_self(user_id, admin)
            _refuse_last_admin(user_id)
        u = pivot_users.update_role(user_id=user_id, role=body.role)
        return JSONResponse(_user_dict(u, bindings))

    @router.post("/{user_id}/reset-password")
    def reset_password(
        user_id: str, body: ResetPasswordBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        target = pivot_users.get(user_id)
        if target is None:
            raise HTTPException(status_code=404)
        bindings.update_password(
            pivot_user_id=user_id,
            new_password_hash=hash_password(body.new_password),
        )
        return JSONResponse({"reset": True})

    return router


def _user_dict(u: PivotUser, bindings: ExternalBindingRepo) -> dict:
    binding_list = bindings.list_for_user(u.id)
    return {
        "id": u.id, "display_name": u.display_name, "pinyin": u.pinyin,
        "email": u.email, "avatar_url": u.avatar_url,
        "role": u.role, "status": u.status, "status_note": u.status_note,
        "created_at": u.created_at, "last_login_at": u.last_login_at,
        "status_changed_at": u.status_changed_at,
        "providers": [b.provider for b in binding_list],
    }
```

- [ ] **Step 3: 注册到 app.py + 跑测试 + Commit**

```bash
git commit -m "feat(admin): add /api/admin/users endpoints with last-admin guard"
```

### Task 18: /api/admin/invites

**Files:**
- Create: `server/api/admin_invites.py`
- Test: `server/tests/test_admin_invites_api.py`

- [ ] **Step 1: 写测试** (create returns plaintext token; list excludes used by default; revoke invalidates)

- [ ] **Step 2: 实现**

```python
"""Admin: invite management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from server.invites import InviteRepo
from server.pivot_users import PivotUser


class CreateInviteBody(BaseModel):
    email: EmailStr
    display_name: str | None = None
    ttl_days: int = 7


def build_router(invites: InviteRepo, admin_user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/admin/invites")

    @router.get("")
    def list_invites(
        include_used: bool = False,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        items = invites.list_for_admin(include_used=include_used)
        return JSONResponse({
            "items": [{
                "id": i.id, "email": i.email, "display_name": i.display_name,
                "created_by": i.created_by, "created_at": i.created_at,
                "expires_at": i.expires_at, "used_at": i.used_at,
            } for i in items],
        })

    @router.post("")
    def create_invite(
        body: CreateInviteBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        token, record = invites.create(
            email=body.email, display_name=body.display_name,
            created_by=admin.id, ttl_sec=body.ttl_days * 86400,
        )
        return JSONResponse({
            "id": record.id,
            "email": record.email,
            "expires_at": record.expires_at,
            "token": token,  # plaintext — show ONCE
            "link_path": f"/invite/{token}",
        })

    @router.delete("/{invite_id}")
    def revoke(
        invite_id: str,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        invites.revoke(invite_id=invite_id)
        return JSONResponse({"revoked": True})

    return router
```

- [ ] **Step 3: 注册 + 测试 + Commit**

```bash
git commit -m "feat(admin): add /api/admin/invites endpoints"
```

---

## Phase 5 · 展示层

### Task 19: resolve_display_info（mentions.py 升级）

**Files:**
- Modify: `server/mentions.py`
- Test: `server/tests/test_mentions.py`

- [ ] **Step 1: 在 mentions.py 加新函数**

```python
from dataclasses import dataclass

from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo


@dataclass(frozen=True)
class DisplayInfo:
    display_name: str
    avatar_url: str
    status: str  # 'active' | 'suspended' | 'deleted' | 'unknown'


def resolve_display_info(
    open_id: str,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    contacts: ContactRepo | None = None,
) -> DisplayInfo:
    binding = bindings.lookup(provider="feishu", external_id=open_id)
    if binding is not None:
        u = pivot_users.get(binding.pivot_user_id)
        if u is not None:
            return DisplayInfo(
                display_name=u.display_name,
                avatar_url=u.avatar_url,
                status=u.status,
            )
    if contacts is not None:
        c = contacts.get_by_any_id(open_id)
        if c is not None:
            return DisplayInfo(
                display_name=c.name, avatar_url=c.avatar_url or "",
                status="unknown",
            )
    return DisplayInfo(display_name=open_id, avatar_url="", status="unknown")
```

- [ ] **Step 2: 把现有 resolve_id / resolve_avatar_url 改为内部调用 resolve_display_info**

```python
def resolve_id(value, pivot_users, bindings, contacts=None) -> str:
    if not value:
        return value
    return resolve_display_info(value, pivot_users, bindings, contacts).display_name


def resolve_avatar_url(value, pivot_users, bindings, contacts=None) -> str | None:
    if not value:
        return None
    info = resolve_display_info(value, pivot_users, bindings, contacts)
    return info.avatar_url or None
```

- [ ] **Step 3: 调用方批量改签名**

调用 `resolve_id` / `resolve_avatar_url` / `resolve_text` 的地方（grep 找到约 5-8 处）传入 `pivot_users` + `bindings` 而不是 `users` + `contacts`。

- [ ] **Step 4: 跑全量测试，pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(mentions): add resolve_display_info returning user status"
```

### Task 20: 在 API 响应中带上 status

**Files:**
- Modify: `server/api/discussions.py`、`server/api/matters.py`、`server/api/inbox.py`
- Modify: `server/auth/routes.py`（/me 响应）
- Test: 现有测试断言扩展

- [ ] **Step 1: 在 /me 响应里加 role + status**

`server/auth/routes.py` 的 `_user_dict()`：

```python
def _user_dict(u: PivotUser) -> dict:
    return {
        "id": u.id, "display_name": u.display_name, "pinyin": u.pinyin,
        "email": u.email, "avatar_url": u.avatar_url,
        "github_username": u.github_username,
        "role": u.role, "status": u.status,
        "needs_setup": u.needs_setup,
    }
```

- [ ] **Step 2: 在 posts/matters API 响应的 author 字段加 status**

每个 post 的 author 序列化器：

```python
def _author_view(open_id, pivot_users, bindings, contacts):
    info = resolve_display_info(open_id, pivot_users, bindings, contacts)
    return {
        "open_id": open_id,
        "display_name": info.display_name,
        "avatar_url": info.avatar_url,
        "status": info.status,
    }
```

- [ ] **Step 3: 现有测试断言里 author 字段类型升级**（适当处加 `assert "status" in author`）

- [ ] **Step 4: 跑全量回归，pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): include user status in author/me responses for display"
```

---

## Phase 6 · 通知

### Task 21: 新 card builders + Notifier 方法

**Files:**
- Modify: `server/notify.py`
- Test: `server/tests/test_notify.py`

- [ ] **Step 1: 在 Notifier Protocol 加 3 个新方法**

```python
class Notifier(Protocol):
    # ... 现有方法 ...

    def notify_application_created(
        self, *, applicant_name: str, provider: str,
        admin_open_ids: list[str],
    ) -> None: ...

    def notify_application_approved(
        self, *, applicant_open_id: str, merged: bool,
    ) -> None: ...

    def notify_application_rejected(
        self, *, applicant_open_id: str,
    ) -> None: ...
```

- [ ] **Step 2: NoOpNotifier 加 stub 实现**

```python
class NoOpNotifier:
    # ... 现有 ...
    def notify_application_created(self, **_): pass
    def notify_application_approved(self, **_): pass
    def notify_application_rejected(self, **_): pass
```

- [ ] **Step 3: 在 FeishuNotifier 加实现**

```python
def notify_application_created(self, *, applicant_name, provider, admin_open_ids):
    if not admin_open_ids:
        return
    card = build_application_card(
        title=f"📥 新加入申请：{applicant_name}",
        body=f"来源：{provider}",
        button_text="去后台审批",
        url=f"{self._web_base_url}/admin/applications",
        template="orange",
    )
    self._dm_many(admin_open_ids, card, event=f"application_created applicant={applicant_name}")


def notify_application_approved(self, *, applicant_open_id, merged):
    if not applicant_open_id:
        return
    text = "你的身份已并入现有账号" if merged else "你的加入申请已通过，欢迎使用 Pivot"
    card = build_application_card(
        title="✅ 加入申请通过",
        body=text,
        button_text="进入 Pivot",
        url=f"{self._web_base_url}/",
        template="green",
    )
    self._dm_many([applicant_open_id], card, event=f"application_approved")


def notify_application_rejected(self, *, applicant_open_id):
    if not applicant_open_id:
        return
    card = build_application_card(
        title="🚫 加入申请未通过",
        body="如有疑问请联系管理员",
        button_text="",
        url="",
        template="red",
    )
    self._dm_many([applicant_open_id], card, event=f"application_rejected")
```

- [ ] **Step 4: build_application_card helper**

```python
def build_application_card(*, title, body, button_text, url, template):
    elements = [{"tag": "markdown", "content": body}]
    if button_text and url:
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": button_text},
            "type": "primary",
            "multi_url": {"url": url, "pc_url": "", "android_url": "", "ios_url": ""},
        })
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "body": {"padding": "8px 16px 12px 16px", "elements": elements},
    }
```

- [ ] **Step 5: 单测每个新方法**（mock httpx 不真发请求）

- [ ] **Step 6: 跑测试，pass + Commit**

```bash
git commit -m "feat(notify): add application_created/approved/rejected card flows"
```

---

## Phase 7 · 前端

### Task 22: API 客户端扩展

**Files:**
- Modify: `web/src/api.ts`

- [ ] **Step 1: 移除 X-Admin-Password 相关代码**

把所有添加 `X-Admin-Password` header 的 helper 删除；改成普通 `fetch` 带 cookie。

- [ ] **Step 2: 加新调用**

```typescript
export async function getInitStatus() {
  return jsonGet<{ needs_init: boolean }>("/init/status");
}

export async function postInitComplete(body: {
  method: "email_password";
  email: string;
  password: string;
  display_name: string;
  pinyin: string;
}) {
  return jsonPost("/init/complete", body);
}

export async function postEmailPasswordLogin(body: { email: string; password: string }) {
  return jsonPost("/auth/login_email_password", body);
}

export async function getInvite(token: string) {
  return jsonGet<{ email: string; display_name: string | null; expires_at: number }>(
    `/invite/${token}`,
  );
}

export async function postInviteAccept(token: string, body: {
  password: string; display_name: string; pinyin: string;
}) {
  return jsonPost(`/invite/${token}/accept`, body);
}

// Admin
export async function listApplications(status?: string) {
  return jsonGet(`/api/admin/applications${status ? `?status=${status}` : ""}`);
}
export async function getMatchCandidates(applicationId: string) {
  return jsonGet(`/api/admin/applications/${applicationId}/match-candidates`);
}
export async function approveApplication(id: string, target_pivot_user_id?: string) {
  return jsonPost(`/api/admin/applications/${id}/approve`, { target_pivot_user_id });
}
export async function rejectApplication(id: string, reason?: string) {
  return jsonPost(`/api/admin/applications/${id}/reject`, { reason });
}
export async function unblockApplication(id: string) {
  return jsonPost(`/api/admin/applications/${id}/unblock`, {});
}

export async function listAdminUsers(opts?: { include_deleted?: boolean; search?: string }) {
  const q = new URLSearchParams();
  if (opts?.include_deleted) q.set("include_deleted", "true");
  if (opts?.search) q.set("search", opts.search);
  const qs = q.toString();
  return jsonGet(`/api/admin/users${qs ? `?${qs}` : ""}`);
}
export async function suspendUser(id: string, note?: string) {
  return jsonPost(`/api/admin/users/${id}/suspend`, { note });
}
export async function resumeUser(id: string, note?: string) {
  return jsonPost(`/api/admin/users/${id}/resume`, { note });
}
export async function markUserDeleted(id: string, note: string | undefined, confirm_display_name: string) {
  return jsonPost(`/api/admin/users/${id}/mark-deleted`, { note, confirm_display_name });
}
export async function restoreUser(id: string, note: string | undefined, confirm_display_name: string) {
  return jsonPost(`/api/admin/users/${id}/restore`, { note, confirm_display_name });
}
export async function changeUserRole(id: string, role: "admin" | "member") {
  return jsonPost(`/api/admin/users/${id}/role`, { role });
}
export async function resetUserPassword(id: string, new_password: string) {
  return jsonPost(`/api/admin/users/${id}/reset-password`, { new_password });
}

export async function listInvites(include_used = false) {
  return jsonGet(`/api/admin/invites${include_used ? "?include_used=true" : ""}`);
}
export async function createInvite(email: string, display_name?: string, ttl_days = 7) {
  return jsonPost(`/api/admin/invites`, { email, display_name, ttl_days });
}
export async function revokeInvite(id: string) {
  return jsonDelete(`/api/admin/invites/${id}`);
}
```

- [ ] **Step 2: 跑前端 typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(web): API client extensions for user management"
```

### Task 23: Init 页面

**Files:**
- Create: `web/src/pages/Init.tsx`
- Modify: `web/src/App.tsx`（加路由 + 守卫）

- [ ] **Step 1: 写 Init.tsx**

```typescript
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { postInitComplete } from "../api";

const WARNING = `如果你要初始化这个系统，你将成为当前 Pivot 的管理员。
请确认你有权限执行初始化操作后再继续。
否则请联系系统管理员或你的上级。`;

export default function Init() {
  const nav = useNavigate();
  const [confirmed, setConfirmed] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [pinyin, setPinyin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!confirmed) {
    return (
      <div className="max-w-xl mx-auto p-6 mt-12 border rounded">
        <h1 className="text-xl font-semibold mb-4">初始化 Pivot</h1>
        <pre className="whitespace-pre-wrap text-sm mb-6">{WARNING}</pre>
        <button
          className="bg-blue-600 text-white px-4 py-2 rounded"
          onClick={() => setConfirmed(true)}
        >
          我已确认权限，继续初始化
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto p-6 mt-12 border rounded">
      <h1 className="text-xl font-semibold mb-4">设置初始管理员</h1>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setSubmitting(true);
          setError(null);
          try {
            await postInitComplete({
              method: "email_password",
              email, password, display_name: displayName, pinyin,
            });
            nav("/");
          } catch (err: any) {
            setError(err?.message || "init_failed");
            setSubmitting(false);
          }
        }}
      >
        <input className="w-full border p-2 rounded" placeholder="邮箱"
               value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="w-full border p-2 rounded" placeholder="密码（≥6 位）"
               type="password" value={password}
               onChange={(e) => setPassword(e.target.value)} required />
        <input className="w-full border p-2 rounded" placeholder="显示名"
               value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        <input className="w-full border p-2 rounded"
               placeholder="拼音（如：zhangsan）"
               pattern="^[a-z][a-z0-9._-]+$"
               value={pinyin} onChange={(e) => setPinyin(e.target.value)} required />
        {error && <div className="text-red-600 text-sm">{error}</div>}
        <button className="w-full bg-blue-600 text-white py-2 rounded"
                disabled={submitting} type="submit">
          {submitting ? "初始化中..." : "完成初始化"}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: 在 App.tsx 加路由 + init 守卫**

```typescript
// 在 App 组件里：
const [needsInit, setNeedsInit] = useState<boolean | null>(null);

useEffect(() => {
  getInitStatus().then((r) => setNeedsInit(r.needs_init));
}, []);

if (needsInit === null) return <div>Loading...</div>;
if (needsInit && location.pathname !== "/init") {
  return <Navigate to="/init" replace />;
}

// 路由表：
<Route path="/init" element={<Init />} />
```

- [ ] **Step 3: 手动测试**

Run: `cd web && npm run dev` 同时跑 server，新开浏览器到 http://localhost:5173/
Expected: 自动重定向 /init，可以填表完成初始化，跳转回首页

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): add Init page + auto-redirect when no admin exists"
```

### Task 24: PendingApproval 页

**Files:**
- Create: `web/src/pages/PendingApproval.tsx`
- Modify: `web/src/pages/Login.tsx`（监听 ?reason= 显示对应提示）

- [ ] **Step 1: 写 PendingApproval.tsx**

```typescript
export default function PendingApproval({ reason }: { reason: string }) {
  const messages: Record<string, string> = {
    submitted: "你的加入申请已提交，请等待管理员审批。",
    pending_approval: "你的申请正在等待管理员审批。",
    rejected: "你的加入申请已被拒绝，如需复议请联系管理员。",
    suspended: "账号已暂停，请联系管理员。",
    deleted: "账号已停用，请联系管理员。",
  };
  return (
    <div className="max-w-md mx-auto p-6 mt-20 text-center">
      <h1 className="text-lg font-semibold mb-3">访问受限</h1>
      <p className="text-gray-700">{messages[reason] || "未授权"}</p>
    </div>
  );
}
```

- [ ] **Step 2: 修改 Login.tsx 读取 ?reason 显示对应消息**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(web): add PendingApproval page + reason messages on Login"
```

### Task 25: InviteAccept 页

**Files:**
- Create: `web/src/pages/InviteAccept.tsx`
- Modify: `web/src/App.tsx`（加 /invite/:token 路由）

- [ ] **Step 1: 写 InviteAccept.tsx**（form 类似 Init.tsx 但邮箱锁定）

- [ ] **Step 2: 路由注册**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(web): add InviteAccept page"
```

### Task 26: Login 页加邮箱密码 tab

**Files:**
- Modify: `web/src/pages/Login.tsx`

- [ ] **Step 1: 加邮箱密码登录子表单（tab/segmented control）**

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(web): add email/password login on Login page"
```

### Task 27: AdminApplications 页

**Files:**
- Create: `web/src/pages/admin/AdminApplications.tsx`
- Create: `web/src/components/admin/MatchCandidates.tsx`
- Create: `web/src/components/admin/MergeUserDialog.tsx`

- [ ] **Step 1: AdminApplications.tsx 列出 pending、每行可点 [同意为新用户][合并][拒绝]**

- [ ] **Step 2: 拒绝弹小窗输 reason；合并弹 dialog 选目标 user**

- [ ] **Step 3: 同人匹配候选 chip 显示在每行**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): add AdminApplications page with merge/approve/reject"
```

### Task 28: AdminUsers 页

**Files:**
- Create: `web/src/pages/admin/AdminUsers.tsx`
- Create: `web/src/components/admin/UserStatusBadge.tsx`

- [ ] **Step 1: 列表 + 筛选 + 每行操作下拉（暂停/恢复/标 deleted/撤销 deleted/升降级/重置密码）**

- [ ] **Step 2: 标 deleted / 撤销 deleted 弹强校验对话框（输入 display_name）**

- [ ] **Step 3: 不能对自己做的操作前端置灰**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): add AdminUsers page with full governance"
```

### Task 29: AdminInvites 页

**Files:**
- Create: `web/src/pages/admin/AdminInvites.tsx`

- [ ] **Step 1: 列表 + 创建按钮（弹邮箱填写）+ 创建后展示一次性 token**

- [ ] **Step 2: 撤销按钮**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(web): add AdminInvites page"
```

### Task 30: 用户名按 status 显示（灰色 deleted）

**Files:**
- Create: `web/src/lib/displayUser.ts`
- Modify: `web/src/components/MentionField.tsx`、`MatterDetailPane.tsx` 等

- [ ] **Step 1: 写 displayUser.ts**

```typescript
export type UserStatus = "active" | "suspended" | "deleted" | "unknown";

export interface DisplayInfo {
  display_name: string;
  avatar_url: string;
  status: UserStatus;
}

export function userClassName(status: UserStatus): string {
  switch (status) {
    case "deleted": return "text-gray-400";
    case "unknown": return "text-gray-400";
    default: return "";
  }
}

export function userTooltip(status: UserStatus): string | null {
  if (status === "deleted") return "该用户已停用";
  return null;
}
```

- [ ] **Step 2: 在所有渲染 author 的地方应用**

```typescript
<span className={userClassName(author.status)} title={userTooltip(author.status) ?? undefined}>
  {author.display_name}
</span>
```

涉及文件按 grep 找——约 5-6 处。

- [ ] **Step 3: 在 MentionField 候选下拉过滤掉 status≠'active'**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): style deleted/suspended users with gray + tooltip"
```

### Task 31: 移除 AdminPage 的密码门

**Files:**
- Modify: `web/src/pages/AdminPage.tsx`
- Modify: `web/src/App.tsx`（admin 路由按 me.role 守卫）

- [ ] **Step 1: 删除 AdminPage 的密码 input + storage**

- [ ] **Step 2: 改为按 `me.role==='admin'` 守卫；不是 admin 则 403 提示**

- [ ] **Step 3: AdminPage 改为侧栏导航 + 子路由（applications / users / invites / 现有 ai/workspace 配置）**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): replace AdminPage password gate with role-based guard"
```

---

## Phase 8 · 集成与清理

### Task 32: 强制登出已暂停 session

**Files:**
- Modify: `web/src/App.tsx` 或 `web/src/api.ts`

- [ ] **Step 1: 在通用 api 错误处理中：401 + detail='invalid_token' → 清前端用户态、跳 /login（已存在）**

- [ ] **Step 2: 增加：401 + reason 参数 → 跳 PendingApproval 显示对应文案**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(web): handle suspended/deleted session cleanup with reason routing"
```

### Task 33: 文档更新

**Files:**
- Modify: `AI-docs/pivot-memo.md`
- Modify: `README.md` 状态清单

- [ ] **Step 1: 更新 pivot-memo.md §4 鉴权层**——把 `X-Admin-Password` 章节改写为"基于 pivot_user.role 的角色鉴权"；增加邀请码、初始化流程描述

- [ ] **Step 2: 更新 §5 数据模型**——加 4 张新表的简要说明

- [ ] **Step 3: README.md 把"飞书 OAuth2 登录"改为"飞书 OAuth2 + 邀请码"；状态清单标记本期完成项**

- [ ] **Step 4: Commit**

```bash
git commit -m "docs: update memo + README for new user-management model"
```

### Task 34: 端到端 smoke test

**Files:**
- Create: `server/tests/test_e2e_user_management.py`

- [ ] **Step 1: 写一个长测试串联完整 happy path**

```python
def test_e2e_full_user_management_flow(client_blank_db: TestClient):
    # 1. /init/status → needs_init=true
    r = client_blank_db.get("/init/status")
    assert r.json()["needs_init"]

    # 2. /init/complete → 创建 admin
    r = client_blank_db.post("/init/complete", json={
        "method": "email_password",
        "email": "admin@example.com", "password": "admin123",
        "display_name": "Admin", "pinyin": "admin",
    })
    assert r.status_code == 200

    # 3. admin 创建 invite
    r = client_blank_db.post("/api/admin/invites", json={"email": "alice@example.com"})
    token = r.json()["token"]

    # 4. invite accept
    r = client_blank_db.post(f"/invite/{token}/accept", json={
        "password": "alice123", "display_name": "Alice", "pinyin": "alice",
    })
    assert r.json()["user"]["role"] == "member"

    # 5. admin 暂停 alice
    alice_id = r.json()["user"]["id"]
    r = client_blank_db.post(f"/api/admin/users/{alice_id}/suspend", json={"note": "测试"})
    assert r.status_code == 200

    # 6. alice 试登录被拒
    r = client_blank_db.post("/auth/login_email_password",
                              json={"email": "alice@example.com", "password": "alice123"})
    assert r.status_code == 401

    # 7. admin 恢复 alice
    r = client_blank_db.post(f"/api/admin/users/{alice_id}/resume", json={})

    # 8. alice 重新登录成功
    r = client_blank_db.post("/auth/login_email_password",
                              json={"email": "alice@example.com", "password": "alice123"})
    assert r.status_code == 200

    # 9. 试图取消唯一 admin → 422
    admin_id = ...  # 之前 init 时拿到
    r = client_blank_db.post(f"/api/admin/users/{admin_id}/role",
                              json={"role": "member"})
    assert r.status_code == 422
```

- [ ] **Step 2: 跑，pass**

- [ ] **Step 3: 跑全量回归**

```bash
uv run pytest -q
```

- [ ] **Step 4: 前端类型检查 + 构建**

```bash
cd web && npx tsc --noEmit
cd web && npm run build
```

Expected: 全绿

- [ ] **Step 5: 手动浏览器走一遍**
  - 清空 var/data.db → /init → 创建 admin → 进首页
  - admin 后台创建 invite → 复制链接 → 新隐身窗口接受 → 登录
  - admin 后台暂停 invite 用户 → 验证登录被拒
  - admin 后台恢复 → 验证可登录
  - admin 后台标 deleted → 验证显示规则（在某个有 author 的 post 上）

- [ ] **Step 6: Commit**

```bash
git commit -m "test(e2e): add full user-management lifecycle smoke test"
```

---

## 验收 checklist（全部 Phase 完成后）

- [ ] 现有飞书用户经过迁移脚本后能无感登录（sessions 不丢）
- [ ] 新飞书扫码用户走审批流程，被拒后再扫码被阻断
- [ ] 邀请码生成 / 接受 / 邮箱密码登录全链路通
- [ ] 暂停 / 恢复 / 标 deleted / 撤销 deleted 全部受护栏保护
- [ ] 最后一名 active admin 不能被暂停、降级、标 deleted
- [ ] deleted 用户的历史 post 显示灰名 + tooltip
- [ ] suspended 用户的状态对其他用户完全不可见
- [ ] `/admin/*` 路由对 admin 可见、对 member 403
- [ ] `X-Admin-Password` 在前后端代码里全部移除
- [ ] `--dry-run` 迁移不写入 DB
- [ ] `--initial-admin` 不传或不命中时迁移中止
- [ ] 全量 pytest 绿
- [ ] 前端 tsc + build 通过
