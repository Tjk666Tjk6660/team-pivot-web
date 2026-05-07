n# IM-Binding-Required Invite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完全替换现有 email/password 邀请流——admin 创建 TTL-only 链接，受邀人打开后跳飞书 OAuth，回调写入 application 队列（标记 `via_invite_id`），admin 审核通过后系统自动用 pypinyin 从飞书 name 转拼音落 PivotUser。

**Architecture:** 复用现有飞书 OAuth + JoinApplication 审核管线，只在两端加挂钩——前端着陆页改成"飞书登录"按钮、后端在 OAuth callback 解 invite_token 把 application 标记为"邀请来"。`invite` 表精简（drop email/display_name），`join_application` 表加 `via_invite_id` 列。

**Tech Stack:** FastAPI / pydantic / SQLite / pypinyin（已在 deps）/ React + TypeScript

**Spec:** `AI-docs/plans/2026-05-06-im-binding-required-invite-design.md`

---

## File Structure

| 文件 | 改动类型 | 责任 |
|---|---|---|
| `server/db.py` | Modify | `_migrate()` 加 invite 表重建 + join_application 加 via_invite_id |
| `server/invites.py` | Modify | `Invite` dataclass 删 email/display_name；`InviteRepo.create` 同步精简 |
| `server/join_applications.py` | Modify | 新增 `via_invite_id` 字段；`create()`/`get()`/list 都带它 |
| `server/auth/invite_state.py` | Create | HMAC 签名/验签 invite_token 用作 OAuth state |
| `server/auth/auto_pinyin.py` | Create | 用 `name_to_pinyin` + 冲突检测 + fallback 生成可用 pinyin |
| `server/api/admin_invites.py` | Modify | 入参从 `{email, display_name?, ttl_days?}` 改 `{ttl_days?}`；输出加 `provider` |
| `server/api/auth_invite.py` | Modify | 删 `POST /accept`；`GET /` 输出删 email/display_name 加 provider；新加 `POST /start` |
| `server/auth/routes.py` | Modify | 飞书 callback 加分支：state 含 invite_token → 解出 → 写 application 时带 via_invite_id + mark invite used |
| `server/api/admin_applications.py` | Modify | approve 用 auto_pinyin；list/get 返回 via_invite 元数据 |
| `web/src/api.ts` | Modify | type `AdminInvite`/`CreatedInvite`/`InvitePreview` 删 email/display_name 加 provider；新增 `startInvite` 函数 |
| `web/src/pages/admin/AdminInvites.tsx` | Modify | Dialog 删 email/display_name 输入；行删 email、加 provider badge |
| `web/src/pages/InviteAccept.tsx` | Modify | 整页重写为着陆页 + "飞书登录"按钮 + 跳转 |
| `web/src/pages/admin/AdminApplications.tsx` | Modify | 列表行加 "邀请来源：\<admin\>" badge |

---

## Task 1: HMAC-signed invite state

**Files:**
- Create: `server/auth/invite_state.py`
- Test: `server/tests/test_invite_state.py`

State 字段嵌入 invite_token，用 HMAC-SHA256 签名防伪造；放在 Feishu OAuth `state` 参数里。Server 重启 secret 不变（从 settings 读）。

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_invite_state.py`:

```python
import pytest

from server.auth.invite_state import (
    InviteStateError,
    decode_invite_state,
    encode_invite_state,
)


SECRET = "test-secret"


def test_encode_decode_roundtrip():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    assert decode_invite_state(encoded, secret=SECRET) == "tok_123"


def test_decode_rejects_tampered_payload():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    head, sig = encoded.rsplit(".", 1)
    tampered = head.replace("tok_123", "tok_xxx") + "." + sig
    with pytest.raises(InviteStateError):
        decode_invite_state(tampered, secret=SECRET)


def test_decode_rejects_bad_signature():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    head, _sig = encoded.rsplit(".", 1)
    forged = head + ".aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with pytest.raises(InviteStateError):
        decode_invite_state(forged, secret=SECRET)


def test_decode_rejects_wrong_secret():
    encoded = encode_invite_state(invite_token="tok_123", secret=SECRET)
    with pytest.raises(InviteStateError):
        decode_invite_state(encoded, secret="other-secret")


def test_decode_rejects_malformed():
    with pytest.raises(InviteStateError):
        decode_invite_state("not-a-valid-state", secret=SECRET)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_invite_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'server.auth.invite_state'`.

- [ ] **Step 3: Create `server/auth/invite_state.py`**

```python
"""HMAC-signed state envelope for the invite-bearing Feishu OAuth flow.

The Feishu OAuth `state` parameter is the only place the server can stash
context across the redirect. We sign it so the callback can trust the
invite_token came from our /api/invite/{token}/start handler — not from
a forged URL someone crafted to skip invite validation."""
from __future__ import annotations

import base64
import hashlib
import hmac

_PREFIX = "v1"
_SEP = "."


class InviteStateError(ValueError):
    """Raised when an OAuth state envelope fails decode / signature checks."""


def encode_invite_state(*, invite_token: str, secret: str) -> str:
    if not invite_token:
        raise ValueError("invite_token must be non-empty")
    payload = f"{_PREFIX}{_SEP}{invite_token}"
    sig = _sign(payload, secret)
    return f"{payload}{_SEP}{sig}"


def decode_invite_state(state: str, *, secret: str) -> str:
    parts = state.split(_SEP)
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise InviteStateError("malformed invite state envelope")
    prefix, invite_token, sig = parts
    payload = f"{prefix}{_SEP}{invite_token}"
    expected = _sign(payload, secret)
    if not hmac.compare_digest(expected, sig):
        raise InviteStateError("invite state signature mismatch")
    return invite_token


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest server/tests/test_invite_state.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/auth/invite_state.py server/tests/test_invite_state.py
git commit -m "$(cat <<'EOF'
feat(auth): HMAC-signed invite state for Feishu OAuth handoff

Envelope format: v1.<invite_token>.<sig>. Used as the OAuth `state`
parameter so the Feishu callback can extract the originating invite
without trusting raw URL data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Auto-pinyin assignment helper

**Files:**
- Create: `server/auth/auto_pinyin.py`
- Test: `server/tests/test_auto_pinyin.py`

Reuses `server.contacts.name_to_pinyin`. Validates against `PINYIN_RE_PATTERN`; falls back to `user_<openid 后 8 位>`; appends `_2`/`_3`... on collision.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_auto_pinyin.py`:

```python
import pytest

from server.auth.auto_pinyin import assign_pinyin
from server.db import Database
from server.pivot_users import PivotUserRepo


def _repo(tmp_path) -> PivotUserRepo:
    return PivotUserRepo(Database(tmp_path / "test.db"))


def test_assign_pinyin_from_chinese_name(tmp_path):
    repo = _repo(tmp_path)
    assert assign_pinyin(name="张三", open_id="ou_abc", repo=repo) == "zhangsan"


def test_assign_pinyin_pass_through_english(tmp_path):
    repo = _repo(tmp_path)
    assert assign_pinyin(name="Alice", open_id="ou_abc", repo=repo) == "alice"


def test_assign_pinyin_appends_suffix_on_collision(tmp_path):
    repo = _repo(tmp_path)
    repo.create(
        display_name="Existing", pinyin="alice", email=None,
        avatar_url="", role="member",
    )
    assert assign_pinyin(name="Alice", open_id="ou_xyz", repo=repo) == "alice_2"


def test_assign_pinyin_skips_taken_suffixes(tmp_path):
    repo = _repo(tmp_path)
    for p in ("alice", "alice_2", "alice_3"):
        repo.create(
            display_name=p, pinyin=p, email=None, avatar_url="", role="member",
        )
    assert assign_pinyin(name="Alice", open_id="ou_xyz", repo=repo) == "alice_4"


def test_assign_pinyin_falls_back_for_invalid_name(tmp_path):
    repo = _repo(tmp_path)
    # Empty / whitespace / chars that produce empty pinyin → fallback to user_<openid8>
    assert assign_pinyin(name="", open_id="ou_abc12345", repo=repo) == "user_ou_abc12"


def test_assign_pinyin_falls_back_when_pinyin_starts_with_digit(tmp_path):
    repo = _repo(tmp_path)
    # PINYIN_RE_PATTERN requires first char a-z; "100" → fallback
    result = assign_pinyin(name="100号", open_id="ou_abcdefgh", repo=repo)
    assert result.startswith("user_")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_auto_pinyin.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create `server/auth/auto_pinyin.py`**

```python
"""Pick a unique pinyin slug for a newly-approved Feishu user.

We feed the IM's display name through pypinyin (via server.contacts.
name_to_pinyin) and then disambiguate against existing PivotUser.pinyin
values. Names that produce an unusable slug (empty, leading non-letter,
illegal chars) fall back to user_<openid 后 8 位> — a stable but uglier
default the user can change later via /api/me/profile."""
from __future__ import annotations

import re

from server.contacts import name_to_pinyin
from server.pivot_users import PINYIN_RE_PATTERN, PivotUserRepo

_PINYIN_RE = re.compile(PINYIN_RE_PATTERN)


def assign_pinyin(*, name: str, open_id: str, repo: PivotUserRepo) -> str:
    base = name_to_pinyin(name) if name else ""
    if not _PINYIN_RE.match(base):
        suffix = (open_id or "")[-8:] or "anon"
        base = f"user_{suffix}"
        # The fallback can itself collide if two open_ids share the same 8
        # tail (extremely unlikely). Run it through the same uniquify loop.
    return _next_unused(base, repo)


def _next_unused(base: str, repo: PivotUserRepo) -> str:
    if repo.get_by_pinyin(base) is None:
        return base
    n = 2
    while True:
        candidate = f"{base}_{n}"
        if repo.get_by_pinyin(candidate) is None:
            return candidate
        n += 1
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest server/tests/test_auto_pinyin.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/auth/auto_pinyin.py server/tests/test_auto_pinyin.py
git commit -m "$(cat <<'EOF'
feat(auth): auto-pinyin assignment for IM-bound users

Wraps server.contacts.name_to_pinyin with collision detection and a
user_<openid8> fallback for names pypinyin can't handle (empty,
emoji-only, leading digit). Used by the invite-flow approval path to
fill PivotUser.pinyin without making the user pick one.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `invite` table simplification + repo update

**Files:**
- Modify: `server/db.py` `_migrate()` and SCHEMA constant
- Modify: `server/invites.py` `Invite` dataclass + `InviteRepo.create`
- Test: `server/tests/test_invites.py` (update existing tests to drop email/display_name)

The `invite` table currently has `email NOT NULL` and `display_name`. Per spec, drop both. Migration: drop the table and recreate (existing rows lost — explicitly approved in spec).

- [ ] **Step 1: Update test file**

Open `server/tests/test_invites.py`. Find every call to `invites.create(...)` and remove the `email=...` and `display_name=...` kwargs (the helper now takes only `created_by`, `ttl_sec`). Find any assertions on `invite.email` / `invite.display_name` and delete those lines. Add a new test:

```python
def test_invite_create_returns_minimal_record(tmp_path):
    invites = InviteRepo(Database(tmp_path / "t.db"))
    token, record = invites.create(created_by="admin", ttl_sec=3600)
    assert record.id
    assert record.token_hash
    assert record.created_by == "admin"
    assert not hasattr(record, "email")
    assert not hasattr(record, "display_name")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest server/tests/test_invites.py -v
```

Expected: FAIL — existing test signatures still pass `email=`; the new minimal test fails because `Invite` still has `email`/`display_name`.

- [ ] **Step 3: Update `Invite` dataclass + `InviteRepo` in `server/invites.py`**

Replace `Invite` (lines 14-24) and `_row_to_invite` (lines 31-43) and `InviteRepo.create` signature with:

```python
@dataclass(frozen=True)
class Invite:
    id: str
    token_hash: str
    created_by: str
    created_at: float
    expires_at: float
    used_at: float | None
    used_by_user_id: str | None


def _row_to_invite(row: sqlite3.Row) -> Invite:
    return Invite(
        id=row["id"],
        token_hash=row["token_hash"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        used_at=row["used_at"],
        used_by_user_id=row["used_by_user_id"],
    )
```

And replace the `create` method (lines 49-75) with:

```python
    def create(
        self,
        *,
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
                " (id, token_hash, created_by, created_at, expires_at)"
                " VALUES (?,?,?,?,?)",
                (new_id, token_hash, created_by, now, now + ttl_sec),
            )
            row = conn.execute(
                "SELECT * FROM invite WHERE id=?", (new_id,)
            ).fetchone()
        assert row is not None
        return token, _row_to_invite(row)
```

- [ ] **Step 4: Update DB schema + add migration in `server/db.py`**

Find the `invite` table CREATE TABLE in the SCHEMA constant (search for `CREATE TABLE invite`). Replace it with:

```sql
CREATE TABLE IF NOT EXISTS invite (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    used_by_user_id TEXT
);
```

In `_migrate()` (right before the existing migrations), add invite table rebuild:

```python
    # invite table: dropped email/display_name in IM-binding-required-invite
    # rework. Existing invite rows are abandoned (per spec — internal 10-user
    # deployment had no live unused invites at cutover).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(invite)")}
    if "email" in cols:
        conn.execute("DROP TABLE invite")
        conn.execute("""
            CREATE TABLE invite (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used_at REAL,
                used_by_user_id TEXT
            )
        """)
```

- [ ] **Step 5: Update consumers (admin_invites + auth_invite + their tests)**

Touch points (do not change behavior here — just unblock the type/signature change. Endpoint logic gets reworked in Tasks 6/7):

In `server/api/admin_invites.py`:
- Drop `email: EmailStr` and `display_name` fields from `CreateInviteBody`
- Drop `i.email` / `i.display_name` from list-response dict
- Drop `email=body.email, display_name=body.display_name` from `invites.create(...)` call
- Drop `record.email` / `record.display_name` from create-response dict

In `server/api/auth_invite.py` `GET /api/invite/{token}` response: drop `"email": invite.email, "display_name": invite.display_name`.

In `server/tests/test_admin_invites_api.py` and `server/tests/test_invite_routes.py` and `server/tests/test_e2e_user_management.py`: any reference to `invite.email`/`display_name` or POST-body containing those fields needs to drop them. (Don't change behavior — just unblock.)

- [ ] **Step 6: Run all affected tests**

```bash
python -m pytest server/tests/test_invites.py server/tests/test_admin_invites_api.py server/tests/test_invite_routes.py -v
```

Expected: all green. (Some tests may still fail because the route logic itself hasn't been rewritten — those are addressed in Tasks 5/6/7. For now you should at minimum get test_invites.py and test_admin_invites_api.py-list-related tests to pass.)

- [ ] **Step 7: Commit**

```bash
git add server/db.py server/invites.py server/api/admin_invites.py server/api/auth_invite.py server/tests/test_invites.py server/tests/test_admin_invites_api.py server/tests/test_invite_routes.py server/tests/test_e2e_user_management.py
git commit -m "$(cat <<'EOF'
refactor(invite): drop email/display_name from invite table + repo

Migration drops the invite table (clears prior rows — internal deployment
had no live unused invites at cutover) and recreates it with just the
fields needed for the IM-binding-required flow. Endpoint accept logic
still references the old shape but is rewritten in follow-up commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `via_invite_id` on `join_application`

**Files:**
- Modify: `server/db.py` SCHEMA + `_migrate()`
- Modify: `server/join_applications.py` `JoinApplication` dataclass + `JoinApplicationRepo.create()`
- Test: `server/tests/test_join_applications.py` (or wherever the existing repo tests live — grep)

- [ ] **Step 1: Write failing test**

In the existing repo test file (`server/tests/test_join_applications.py` if it exists, otherwise add to `server/tests/test_admin_applications_api.py`):

```python
def test_create_application_persists_via_invite_id(tmp_path):
    db = Database(tmp_path / "t.db")
    repo = JoinApplicationRepo(db)
    a = repo.create(
        provider="feishu", external_id="ou_abc", external_union_id=None,
        raw_profile={"name": "Alice"}, suggested_match_user_id=None,
        via_invite_id="inv_123",
    )
    got = repo.get(a.id)
    assert got.via_invite_id == "inv_123"


def test_create_application_via_invite_id_optional_default_none(tmp_path):
    db = Database(tmp_path / "t.db")
    repo = JoinApplicationRepo(db)
    a = repo.create(
        provider="feishu", external_id="ou_abc", external_union_id=None,
        raw_profile={"name": "Alice"}, suggested_match_user_id=None,
    )
    got = repo.get(a.id)
    assert got.via_invite_id is None
```

- [ ] **Step 2: Run failing**

```bash
python -m pytest server/tests/test_join_applications.py -k via_invite -v
```

Expected: FAIL — TypeError or AttributeError on `via_invite_id`.

- [ ] **Step 3: Update SCHEMA + `_migrate()`**

In `server/db.py` SCHEMA, find `CREATE TABLE` for `join_application` and add `via_invite_id TEXT` after `suggested_match_user_id`.

In `_migrate()`, add:

```python
    cols = {row[1] for row in conn.execute("PRAGMA table_info(join_application)")}
    if "via_invite_id" not in cols:
        conn.execute(
            "ALTER TABLE join_application ADD COLUMN via_invite_id TEXT"
        )
```

- [ ] **Step 4: Update `JoinApplication` dataclass + `_row_to_app` + `create()` in `server/join_applications.py`**

Add field to dataclass (after `reject_reason`):

```python
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
    via_invite_id: str | None = None
```

In `_row_to_app`, append:

```python
        via_invite_id=row["via_invite_id"] if "via_invite_id" in row.keys() else None,
```

In `create()`, change signature + INSERT:

```python
    def create(
        self,
        *,
        provider: str,
        external_id: str,
        external_union_id: str | None,
        raw_profile: dict[str, Any],
        suggested_match_user_id: str | None,
        via_invite_id: str | None = None,
    ) -> JoinApplication:
        new_id = uuid.uuid4().hex
        with self._db.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO join_application"
                    " (id, provider, external_id, external_union_id, raw_profile,"
                    "  suggested_match_user_id, status, applied_at, via_invite_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id, provider, external_id, external_union_id,
                     json.dumps(raw_profile, ensure_ascii=False),
                     suggested_match_user_id, "pending", time(),
                     via_invite_id),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(f"duplicate pending application: {e}") from e
        got = self.get(new_id)
        assert got is not None
        return got
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest server/tests/ -k join_application -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add server/db.py server/join_applications.py server/tests/test_join_applications.py
git commit -m "$(cat <<'EOF'
feat(applications): add via_invite_id to join_application

Optional FK to invite.id, set when an application was created via the
invite-bearing Feishu OAuth path. Lets the admin review UI distinguish
'invited by X' applications from raw self-applies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Simplify `POST /api/admin/invites` + `GET /api/invite/{token}`

**Files:**
- Modify: `server/api/admin_invites.py`
- Modify: `server/api/auth_invite.py`
- Test: `server/tests/test_admin_invites_api.py`, `server/tests/test_invite_routes.py`

After Task 3 unblocked the type changes, now finalize endpoint shapes per spec.

- [ ] **Step 1: Write the failing tests**

In `server/tests/test_admin_invites_api.py`, add:

```python
def test_create_invite_accepts_only_ttl(tmp_path):
    client, _, _ = _build_app(tmp_path)
    r = client.post("/api/admin/invites", json={"ttl_days": 5})
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert "link_path" in body
    assert body["provider"] == "feishu"
    assert "email" not in body
    assert "display_name" not in body


def test_create_invite_rejects_email_field(tmp_path):
    """Old contract is gone — server should silently ignore extras (pydantic
    default) but not require them."""
    client, _, _ = _build_app(tmp_path)
    r = client.post("/api/admin/invites", json={})
    assert r.status_code == 200  # ttl_days has a default


def test_list_invites_omits_email_field(tmp_path):
    client, invites, admin = _build_app(tmp_path)
    invites.create(created_by=admin.id, ttl_sec=3600)
    r = client.get("/api/admin/invites")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert "email" not in item
    assert "display_name" not in item
    assert item["provider"] == "feishu"
```

In `server/tests/test_invite_routes.py`:

```python
def test_get_invite_returns_provider_no_email(tmp_path):
    client, invites, _, _ = _make_client(tmp_path)
    token, _ = invites.create(created_by="admin", ttl_sec=3600)
    r = client.get(f"/api/invite/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "feishu"
    assert "email" not in body
    assert "display_name" not in body
    assert "expires_at" in body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_admin_invites_api.py server/tests/test_invite_routes.py -k "accepts_only_ttl or rejects_email or omits_email or returns_provider" -v
```

Expected: FAIL — provider field missing.

- [ ] **Step 3: Update `server/api/admin_invites.py`**

Replace the entire file body with:

```python
"""Admin: invite management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.invites import InviteRepo
from server.pivot_users import PivotUser

# Only feishu is supported in this phase. Reserved for future dingtalk / wecom.
DEFAULT_PROVIDER = "feishu"


class CreateInviteBody(BaseModel):
    ttl_days: int = Field(default=7, ge=1, le=90)


def build_router(invites: InviteRepo, admin_user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/admin/invites")

    @router.get("")
    def list_invites(
        include_used: bool = False,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        items = invites.list_for_admin(include_used=include_used)
        return JSONResponse({
            "items": [
                {
                    "id": i.id,
                    "provider": DEFAULT_PROVIDER,
                    "created_by": i.created_by,
                    "created_at": i.created_at,
                    "expires_at": i.expires_at,
                    "used_at": i.used_at,
                }
                for i in items
            ],
        })

    @router.post("")
    def create_invite(
        body: CreateInviteBody,
        admin: PivotUser = Depends(admin_user_dep),
    ) -> JSONResponse:
        token, record = invites.create(
            created_by=admin.id,
            ttl_sec=body.ttl_days * 86400,
        )
        return JSONResponse({
            "id": record.id,
            "provider": DEFAULT_PROVIDER,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "token": token,
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

- [ ] **Step 4: Update `GET /api/invite/{token}` in `server/api/auth_invite.py`**

In `server/api/auth_invite.py`, find the `@router.get("/api/invite/{token}")` handler and replace its body with:

```python
    @router.get("/api/invite/{token}")
    def load(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        return JSONResponse(
            {
                "expires_at": invite.expires_at,
                "provider": "feishu",
            }
        )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest server/tests/test_admin_invites_api.py server/tests/test_invite_routes.py -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add server/api/admin_invites.py server/api/auth_invite.py server/tests/test_admin_invites_api.py server/tests/test_invite_routes.py
git commit -m "$(cat <<'EOF'
feat(invite): drop email/display_name fields, return provider='feishu'

POST /api/admin/invites now only takes ttl_days; GET /api/invite/{token}
returns just expires_at + provider. Provider field is fixed to 'feishu'
this phase — placeholder for future dingtalk/wecom support without
breaking the API.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Delete `POST /api/invite/{token}/accept`

**Files:**
- Modify: `server/api/auth_invite.py`
- Modify: `server/tests/test_invite_routes.py`

The email/password flow is gone. Remove the endpoint and its tests.

- [ ] **Step 1: Write the negative test**

In `server/tests/test_invite_routes.py`:

```python
def test_invite_accept_endpoint_is_gone(tmp_path):
    client, invites, _, _ = _make_client(tmp_path)
    token, _ = invites.create(created_by="admin", ttl_sec=3600)
    r = client.post(
        f"/api/invite/{token}/accept",
        json={"password": "p" * 8, "display_name": "X", "pinyin": "x"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest server/tests/test_invite_routes.py -k accept_endpoint_is_gone -v
```

Expected: the assertion fails because the route still exists and returns 200/4xx for other reasons.

- [ ] **Step 3: Delete the endpoint**

In `server/api/auth_invite.py`, delete the entire `@router.post("/api/invite/{token}/accept")` handler (the `accept` function) and the `InviteAcceptBody` model. Remove the now-unused imports (`hash_password`, `PINYIN_RE_PATTERN`, etc. — check what's left).

- [ ] **Step 4: Delete + update existing accept tests**

In `server/tests/test_invite_routes.py`, delete the existing tests that POST to `/accept` (those that test successful accept, password length validation, etc.). The negative test from Step 1 stays.

- [ ] **Step 5: Run tests**

```bash
python -m pytest server/tests/test_invite_routes.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add server/api/auth_invite.py server/tests/test_invite_routes.py
git commit -m "$(cat <<'EOF'
feat(invite)!: remove POST /api/invite/{token}/accept

Email/password invite flow is replaced by the Feishu OAuth flow added in
the next commit. There is no migration path for new invites — existing
PivotUsers created via this endpoint keep working (their bcrypt binding
in external_binding stays valid).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add `POST /api/invite/{token}/start`

**Files:**
- Modify: `server/api/auth_invite.py`
- Modify: `server/app.py` (wire feishu_oauth into the auth_invite router)
- Test: `server/tests/test_invite_routes.py`

Returns `{redirect_url}` for the frontend to send the user to. State envelope = HMAC-signed invite_token.

- [ ] **Step 1: Write the failing tests**

In `server/tests/test_invite_routes.py`:

```python
def test_invite_start_returns_redirect_url(tmp_path):
    client, invites, _, _ = _make_client(tmp_path)
    token, _ = invites.create(created_by="admin", ttl_sec=3600)
    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 200
    body = r.json()
    assert body["redirect_url"].startswith("https://open.feishu.cn/")
    assert "state=" in body["redirect_url"]


def test_invite_start_rejects_expired(tmp_path):
    """Already-expired invite returns 410, not a redirect."""
    client, invites, _, _ = _make_client(tmp_path)
    token, record = invites.create(created_by="admin", ttl_sec=1)
    invites.revoke(invite_id=record.id)  # revoke sets expires_at to past
    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 410


def test_invite_start_rejects_used(tmp_path):
    client, invites, _, _ = _make_client(tmp_path)
    token, record = invites.create(created_by="admin", ttl_sec=3600)
    invites.mark_used(invite_id=record.id, used_by_user_id="some_user")
    r = client.post(f"/api/invite/{token}/start")
    assert r.status_code == 410


def test_invite_start_rejects_unknown_token(tmp_path):
    client, _, _, _ = _make_client(tmp_path)
    r = client.post("/api/invite/never-existed/start")
    assert r.status_code == 404
```

`_make_client` will need updating — it has to pass a FeishuOAuth instance + state secret. Adapt the helper to construct one with stub credentials (or use a fake that just records calls); see existing patterns in `server/tests/test_routes.py` for how feishu_oauth is stubbed.

- [ ] **Step 2: Run tests**

```bash
python -m pytest server/tests/test_invite_routes.py -k "invite_start" -v
```

Expected: FAIL — endpoint missing.

- [ ] **Step 3: Add `POST /start` handler**

In `server/api/auth_invite.py`, update `build_router`'s signature and add the new handler:

```python
def build_router(
    invites: InviteRepo,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    sessions: SessionStore,
    feishu_oauth: "FeishuOAuth",
    state_secret: str,
    secure_cookie: bool = False,
) -> APIRouter:
    router = APIRouter()
    samesite = "none" if secure_cookie else "lax"

    @router.get("/api/invite/{token}")
    def load(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        if invite is None:
            raise HTTPException(status_code=404, detail="invalid_or_expired")
        return JSONResponse({"expires_at": invite.expires_at, "provider": "feishu"})

    @router.post("/api/invite/{token}/start")
    def start(token: str) -> JSONResponse:
        invite = invites.resolve_token(token)
        # resolve_token returns None for both unknown AND expired/used.
        # Distinguish so we can return 404 vs 410 per spec.
        if invite is None:
            # Drill into the underlying record to tell apart "never existed"
            # from "exists but no longer usable".
            with invites._db.connect() as conn:  # noqa: SLF001
                row = conn.execute(
                    "SELECT used_at, expires_at FROM invite WHERE token_hash=?",
                    (_hash_token_for_lookup(token),),
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="not_found")
            raise HTTPException(status_code=410, detail="invite_unusable")
        state = encode_invite_state(
            invite_token=token, secret=state_secret,
        )
        return JSONResponse({
            "redirect_url": feishu_oauth.authorize_url(state=state),
        })

    return router


def _hash_token_for_lookup(plaintext: str) -> str:
    """Mirror of server.invites._hash_token but kept local to avoid an
    import-cycle if invites grows to depend on this module."""
    import hashlib
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
```

Add the imports at the top of the file:

```python
from typing import TYPE_CHECKING

from server.auth.invite_state import encode_invite_state

if TYPE_CHECKING:
    from server.auth.feishu_oauth import FeishuOAuth
```

- [ ] **Step 4: Wire in `server/app.py`**

In `server/app.py`, find where `auth_invite_router` is constructed (search for `build_router` from `server.api.auth_invite`). Update the call to pass `feishu_oauth=feishu_oauth, state_secret=settings.invite_state_secret`. The `feishu_oauth` instance and `settings` are already in scope.

`settings.invite_state_secret` may need to be added to the Settings dataclass. Find `class Settings` in `server/settings.py` (or similar) and add:

```python
    invite_state_secret: str = field(default_factory=lambda: os.environ.get(
        "PIVOT_INVITE_STATE_SECRET", secrets.token_urlsafe(32),
    ))
```

(If a single-process dev server: ephemeral default is fine. For prod: must be set in env.)

- [ ] **Step 5: Run tests**

```bash
python -m pytest server/tests/test_invite_routes.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add server/api/auth_invite.py server/app.py server/settings.py server/tests/test_invite_routes.py
git commit -m "$(cat <<'EOF'
feat(invite): POST /api/invite/{token}/start returns Feishu OAuth URL

Frontend hits this endpoint when the invitee clicks the 'log in with
Feishu' button on the invite landing page; we validate the token, build
a HMAC-signed state envelope (carrying the invite_token), and hand back
the authorize URL for client-side redirect. 404 for unknown tokens, 410
for expired/used.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Feishu OAuth callback handles invite state

**Files:**
- Modify: `server/auth/routes.py` (the `/auth/feishu/callback` handler around line 200)
- Test: `server/tests/test_routes.py`

When `state` decodes as an invite envelope, mark invite used + write `via_invite_id` on the application.

- [ ] **Step 1: Write failing tests**

In `server/tests/test_routes.py`, add (using existing test fixtures — adapt to whatever stubs Feishu OAuth there):

```python
def test_feishu_callback_with_invite_state_marks_invite_and_application(tmp_path):
    """callback sees state=v1.<token>.<sig>, decodes, links application."""
    # ... uses existing test harness — set up invite, simulate OAuth callback
    # with state from encode_invite_state, assert:
    #   - invite.used_at is not None
    #   - new application.via_invite_id == invite.id
    pass  # implementer fills in per existing test patterns


def test_feishu_callback_with_invalid_invite_state_returns_400():
    """Tampered state → 400, no application created, invite untouched."""
    pass


def test_feishu_callback_without_invite_state_unchanged():
    """Existing self-apply path still works — application.via_invite_id is None."""
    pass


def test_feishu_callback_invite_state_when_user_already_active(tmp_path):
    """open_id matches existing active PivotUser → mark invite used,
    skip application creation, set session cookie, redirect home."""
    pass
```

The `pass` placeholders aren't OK per skill — the implementer should fill them by mirroring existing patterns in `test_routes.py`. Concretely:
- Find the existing `test_feishu_callback_*` test as a template
- For the invite test, additionally insert an invite row + encode the state via `encode_invite_state` + assert the join_application row's `via_invite_id` field after callback

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest server/tests/test_routes.py -k "callback_with_invite or callback_without_invite or already_active" -v
```

Expected: FAIL.

- [ ] **Step 3: Modify the callback in `server/auth/routes.py`**

Find the `/auth/feishu/callback` handler. Right after the existing `state` is read from the request and BEFORE the existing logic that exchanges code → user info, add:

```python
        invite_token: str | None = None
        if state:
            try:
                invite_token = decode_invite_state(state, secret=invite_state_secret)
            except InviteStateError:
                # Could be (a) old-style pre-invite state from a stale
                # browser (returns from auth pre-rework), or (b) a real
                # signature-mismatch attack. We can't tell apart without
                # more context, so let the existing self-apply path
                # handle it — invite_token stays None.
                invite_token = None
```

Then in the application-creation branch (currently around line 247), pass `via_invite_id`:

```python
        invite_record: Invite | None = None
        if invite_token is not None:
            invite_record = invites.resolve_token(invite_token)
            # If the invite went stale between /start and /callback (e.g.
            # admin revoked it mid-OAuth), proceed as a self-apply — the
            # safest fallback is "create an unmarked application", admin
            # can still review.

        # ... existing "Entry 1: already bound" branch unchanged ...

        # In the "already bound" branch, if invite_record is set, also
        # mark the invite used (creator gets credit even if no new
        # application happens):
        if invite_record is not None:
            invites.mark_used(invite_id=invite_record.id, used_by_user_id=user.id)

        # ... existing "Entry 2: blocking application" check, but if
        # invite_record is set AND the blocking application is pending,
        # patch its via_invite_id:
        if invite_record is not None and blocking is not None and blocking.status == "pending":
            applications.set_via_invite(application_id=blocking.id, via_invite_id=invite_record.id)
            invites.mark_used(invite_id=invite_record.id, used_by_user_id="")  # used_by_user_id allowed empty per spec
            return RedirectResponse(...)  # existing return

        # ... existing "create new application" branch:
        applications.create(
            ...
            via_invite_id=invite_record.id if invite_record else None,
        )
        if invite_record is not None:
            invites.mark_used(invite_id=invite_record.id, used_by_user_id="")
```

You'll also need to add `set_via_invite` to `JoinApplicationRepo` (since blocking-pending case needs to patch existing rows):

```python
    def set_via_invite(self, *, application_id: str, via_invite_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE join_application SET via_invite_id=? WHERE id=?",
                (via_invite_id, application_id),
            )
```

Add imports at top of `routes.py`:

```python
from server.auth.invite_state import InviteStateError, decode_invite_state
from server.invites import Invite
```

`build_router` for auth/routes.py needs `invite_state_secret: str` and `invites: InviteRepo` parameters threaded in. Update the wiring in `server/app.py`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest server/tests/test_routes.py -v 2>&1 | tail -15
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add server/auth/routes.py server/join_applications.py server/app.py server/tests/test_routes.py
git commit -m "$(cat <<'EOF'
feat(auth): Feishu OAuth callback handles invite-bearing state

When the OAuth state envelope decodes to a valid invite_token, the
callback links the resulting application to the invite (via_invite_id)
and marks the invite used. Existing pending applications get patched
with via_invite_id; already-active users just get the invite consumed.
Bad signatures fall through to the self-apply path silently.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Application approval uses auto-pinyin + list returns via_invite metadata

**Files:**
- Modify: `server/api/admin_applications.py`
- Test: `server/tests/test_admin_applications_api.py`

- [ ] **Step 1: Write failing tests**

In `server/tests/test_admin_applications_api.py`:

```python
def test_approve_assigns_auto_pinyin_from_feishu_name(tmp_path):
    client, applications, _, _, _ = _build(tmp_path)
    a = applications.create(
        provider="feishu", external_id="ou_x", external_union_id=None,
        raw_profile={"name": "张三"}, suggested_match_user_id=None,
    )
    r = client.post(f"/api/admin/applications/{a.id}/approve", json={})
    assert r.status_code == 200
    user_id = r.json()["user_id"]
    # Look up the user — pinyin should be 'zhangsan'
    # (use whatever helper your test harness provides; e.g. pivot_users.get(user_id))
    # assert created_user.pinyin == "zhangsan"


def test_list_applications_returns_via_invite_when_set(tmp_path):
    client, applications, invites, pivot_users, admin = _build(tmp_path)
    _, invite_record = invites.create(created_by=admin.id, ttl_sec=3600)
    applications.create(
        provider="feishu", external_id="ou_x", external_union_id=None,
        raw_profile={"name": "X"}, suggested_match_user_id=None,
        via_invite_id=invite_record.id,
    )
    r = client.get("/api/admin/applications?status=pending")
    item = r.json()["items"][0]
    assert item["via_invite"] is not None
    assert item["via_invite"]["invite_id"] == invite_record.id
    assert item["via_invite"]["invited_by_pinyin"] == admin.pinyin
    assert item["via_invite"]["invited_by_display_name"] == admin.display_name


def test_list_applications_returns_via_invite_null_for_self_apply(tmp_path):
    client, applications, _, _, _ = _build(tmp_path)
    applications.create(
        provider="feishu", external_id="ou_x", external_union_id=None,
        raw_profile={"name": "X"}, suggested_match_user_id=None,
    )
    r = client.get("/api/admin/applications?status=pending")
    assert r.json()["items"][0]["via_invite"] is None
```

`_build` may need updating to include InviteRepo + admin user. Adapt per existing harness pattern.

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest server/tests/test_admin_applications_api.py -k "auto_pinyin or via_invite" -v
```

Expected: FAIL.

- [ ] **Step 3: Update `server/api/admin_applications.py`**

In the `approve` handler, replace `pinyin=None` in the `pivot_users.create(...)` call:

```python
        if body.target_pivot_user_id is None:
            try:
                pinyin = assign_pinyin(
                    name=a.raw_profile.get("name") or "",
                    open_id=a.external_id,
                    repo=pivot_users,
                )
                user = pivot_users.create(
                    display_name=a.raw_profile.get("name") or "Unknown",
                    pinyin=pinyin,
                    email=a.raw_profile.get("email"),
                    avatar_url=a.raw_profile.get("avatar_url") or "",
                    role="member",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
```

Add import:

```python
from server.auth.auto_pinyin import assign_pinyin
```

In the list/get response builders, append `via_invite` field:

```python
def _via_invite_info(
    via_invite_id: str | None,
    invites: InviteRepo,
    pivot_users: PivotUserRepo,
) -> dict | None:
    if via_invite_id is None:
        return None
    invite = invites.get(via_invite_id) if hasattr(invites, "get") else None
    # NOTE: InviteRepo as written doesn't have .get(invite_id) — add one
    # in invites.py first. See snippet below.
    if invite is None:
        return {"invite_id": via_invite_id, "invited_by_pinyin": None,
                "invited_by_display_name": None}
    inviter = pivot_users.get(invite.created_by)
    return {
        "invite_id": invite.id,
        "invited_by_pinyin": inviter.pinyin if inviter else None,
        "invited_by_display_name": inviter.display_name if inviter else None,
    }
```

Add to `InviteRepo` in `server/invites.py`:

```python
    def get(self, invite_id: str) -> Invite | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM invite WHERE id=?", (invite_id,)
            ).fetchone()
        return _row_to_invite(row) if row else None
```

In the list-applications handler, populate the field:

```python
        items = [
            {
                # ...existing fields...
                "via_invite": _via_invite_info(
                    a.via_invite_id, invites, pivot_users,
                ),
            }
            for a in apps
        ]
```

`build_router` for admin_applications now needs `invites: InviteRepo` injected. Update its signature and the wiring in `server/app.py`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest server/tests/test_admin_applications_api.py -v 2>&1 | tail -10
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add server/api/admin_applications.py server/invites.py server/app.py server/tests/test_admin_applications_api.py
git commit -m "$(cat <<'EOF'
feat(admin): auto-pinyin on approve + via_invite metadata in list

Approve now uses auto_pinyin.assign_pinyin instead of leaving pivot_user.
pinyin null. List returns each application's via_invite info — invite_id
+ inviter's pinyin + display_name — so the admin UI can show 'invited
by alice' badges next to applications that came through invite links.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Frontend — `api.ts` types and helpers

**Files:**
- Modify: `web/src/api.ts`

- [ ] **Step 1: Update types**

Find `AdminInvite`, `CreatedInvite`, `InvitePreview` types. Replace with:

```ts
export type InviteProvider = "feishu";

export type AdminInvite = {
  id: string;
  provider: InviteProvider;
  created_by: string;
  created_at: number;
  expires_at: number;
  used_at: number | null;
};

export type CreatedInvite = {
  id: string;
  provider: InviteProvider;
  created_at: number;
  expires_at: number;
  token: string;
  link_path: string;
};

export type InvitePreview = {
  expires_at: number;
  provider: InviteProvider;
};
```

- [ ] **Step 2: Update `createInvite` helper**

Find the `createInvite` function. Change signature to `(ttlDays?: number)`:

```ts
export async function createInvite(ttlDays = 7): Promise<CreatedInvite> {
  const r = await fetch("/api/admin/invites", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ttl_days: ttlDays }),
  });
  await throwIfSessionExpired(r);
  if (!r.ok) throw new Error(`create invite failed: ${r.status}`);
  return (await r.json()) as CreatedInvite;
}
```

- [ ] **Step 3: Add `startInvite`**

After `getInvite`:

```ts
export async function startInvite(token: string): Promise<{ redirect_url: string }> {
  const r = await fetch(`/api/invite/${encodeURIComponent(token)}/start`, {
    method: "POST",
    credentials: "include",
  });
  if (r.status === 410) throw new Error("invite_unusable");
  if (r.status === 404) throw new Error("invite_not_found");
  if (!r.ok) throw new Error(`start invite failed: ${r.status}`);
  return (await r.json()) as { redirect_url: string };
}
```

- [ ] **Step 4: Remove `postInviteAccept`**

Delete the `postInviteAccept` function entirely (it called the now-removed endpoint).

- [ ] **Step 5: Update `AdminApplication` type to include `via_invite`**

Find `AdminApplication` type. Add field:

```ts
  via_invite: {
    invite_id: string;
    invited_by_pinyin: string | null;
    invited_by_display_name: string | null;
  } | null;
```

- [ ] **Step 6: Type-check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors. (Errors here mean callers of `createInvite` / `postInviteAccept` need updating in Tasks 11/12.)

If tsc complains about callers, leave those errors — they get fixed in the next two tasks. Or tweak the order: do Tasks 11/12 alongside this commit so type-check is clean before committing.

- [ ] **Step 7: Commit**

```bash
git add web/src/api.ts
git commit -m "$(cat <<'EOF'
feat(web/api): drop email/password fields from invite types, add startInvite

Aligns with backend changes (POST /start, removed /accept). Callers
(AdminInvites, InviteAccept, AdminApplications) updated in next commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Frontend — `AdminInvites.tsx` form + list

**Files:**
- Modify: `web/src/pages/admin/AdminInvites.tsx`

- [ ] **Step 1: Strip email and display_name from CreateInviteDialog**

In `CreateInviteDialog`, remove `email`, `displayName` `useState` declarations. Remove the two `<Input>` fields for email and displayName. Update `submit` to:

```ts
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const inv = await createInvite(ttlDays);
      onCreated(inv);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
```

Update the submit button's `disabled`:

```ts
  disabled={busy}
```

(no email check needed). Update DialogDescription text to reflect the new flow:

```tsx
<DialogDescription>
  生成一条飞书邀请链接，链接里的 token 仅会展示一次。受邀人打开链接会被
  引导到飞书登录。
</DialogDescription>
```

- [ ] **Step 2: Strip email/display_name from `InviteRow`**

Replace the row body. The first line previously showed `invite.email` — replace with the provider badge + invite id (or just the date, since each invite is just an "anonymous link"):

```tsx
<div className="flex items-center gap-2">
  <span className="rounded-full px-2 py-0.5 text-[10.5px] font-bold tracking-wider font-meta"
    style={{
      background: "var(--accent-bg)", color: "var(--accent)",
      border: "1px solid var(--accent)",
    }}>
    飞书
  </span>
  <span className="text-[14px]" style={{ color: "var(--text-mute)" }}>
    invite#{invite.id.slice(0, 8)}
  </span>
  {/* tag (待使用 / 已过期 / 已使用) — keep existing markup */}
</div>
```

Drop the `{invite.display_name ? `${invite.display_name} · ` : ""}` from the secondary line.

- [ ] **Step 3: Run dev server, smoke-test**

```bash
cd web && npm run dev
```

Open `/admin/invites`, click 创建邀请 → only TTL field. Submit → see new entry with "飞书" badge, no email.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/admin/AdminInvites.tsx
git commit -m "$(cat <<'EOF'
feat(admin/invites): strip email/display_name fields, add 飞书 badge

Create dialog now only has TTL; list rows show provider badge instead
of an email column. Invite identity is reduced to the provider + invite
id stub (the link itself remains the only sensitive payload).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Frontend — `InviteAccept.tsx` rewrite as Feishu landing

**Files:**
- Modify: `web/src/pages/InviteAccept.tsx`

- [ ] **Step 1: Replace the entire form section**

In `InviteAccept`, the rendered output for `invite !== null` currently has a 5-field form (email/password/display_name/pinyin/submit). Replace with:

```tsx
  const goFeishu = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const { redirect_url } = await startInvite(token);
      window.location.href = redirect_url;
    } catch (err) {
      const code = err instanceof Error ? err.message : String(err);
      setSubmitError(
        code === "invite_unusable" ? "邀请已失效（过期或已使用）" :
        code === "invite_not_found" ? "邀请链接无效" :
        `跳转失败：${code}`
      );
      setSubmitting(false);
    }
  };

  return (
    <Shell>
      <div className="mb-3 text-[10.5px] font-bold uppercase tracking-[0.22em] font-meta"
        style={{ color: "var(--accent)" }}>
        加入 Pivot
      </div>
      <h2 className="m-0 text-[26px]" style={titleStyle}>欢迎加入</h2>
      <p className="mt-3 text-[14px] leading-[1.65]" style={bodyTextStyle}>
        管理员邀请你加入 Pivot。点下面的按钮用飞书账号登录；登录后会进入
        管理员审核队列，审核通过后即可访问。
      </p>

      <Button
        type="button"
        onClick={goFeishu}
        disabled={submitting}
        className="mt-6 h-11 w-full rounded-[var(--r-sm)] text-[14px] font-semibold shadow-none"
        style={{
          background: "var(--accent)",
          color: "var(--accent-ink)",
          border: "1px solid var(--accent)",
        }}
      >
        {submitting ? "正在跳转飞书…" : "用飞书账号登录"}
      </Button>

      {submitError && (
        <p className="mt-3 text-[12px]" style={{ color: "var(--danger-500)" }}>
          {submitError}
        </p>
      )}

      <p className="mt-4 text-[11.5px] font-meta"
        style={{ color: "var(--text-mute)" }}>
        {expiresLabel}
      </p>
    </Shell>
  );
```

Keep `useState` for `submitError` and `submitting`. Drop `password`, `displayName`, `pinyin` state. Drop `submit` form handler. Drop the imported `Input` / `Label` if unused after the change.

Update import at top:

```tsx
import { getInvite, startInvite, type InvitePreview } from "@/api";
```

(Drop `postInviteAccept`.)

Drop the `Field` and `PINYIN_RE` helpers if unused.

- [ ] **Step 2: Smoke test**

```bash
cd web && npm run dev
```

1. Create an invite via /admin/invites
2. Open the invite link in a different browser/private window
3. Click "用飞书账号登录"
4. Confirm the browser navigates to open.feishu.cn
5. Complete Feishu OAuth → land back on the app, see "等待管理员审核" page

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/InviteAccept.tsx
git commit -m "$(cat <<'EOF'
feat(invite): rewrite landing page as Feishu OAuth handoff

Replaces the email/password/pinyin form with a single "用飞书账号登录"
button that calls /api/invite/{token}/start and redirects to the URL
backend returns. Errors (expired / used / unknown) surface inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Frontend — `AdminApplications.tsx` via_invite badge

**Files:**
- Modify: `web/src/pages/admin/AdminApplications.tsx`

- [ ] **Step 1: Render badge in row**

In the row component for an application, find where the applicant's name renders and add (right after it):

```tsx
{app.via_invite && (
  <span
    className="ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-bold tracking-wider font-meta"
    style={{
      background: "var(--accent-bg)",
      color: "var(--accent)",
      border: "1px solid var(--accent)",
    }}
    title={`邀请来源：${app.via_invite.invited_by_display_name ?? app.via_invite.invited_by_pinyin ?? "未知 admin"}`}
  >
    邀请来源：{app.via_invite.invited_by_display_name ?? app.via_invite.invited_by_pinyin ?? "?"}
  </span>
)}
```

- [ ] **Step 2: Smoke test**

Same as Task 12: run dev server, complete the full invite → OAuth → audit flow with a second user. Confirm `/admin/applications` shows the new application with "邀请来源：\<your pinyin\>" badge.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/admin/AdminApplications.tsx
git commit -m "$(cat <<'EOF'
feat(admin/applications): show 邀请来源 badge for invite-bearing applications

When the application's via_invite is non-null, render the inviter's
display_name (or pinyin) inline so admins can spot directed-invite
applications at a glance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- ✅ **Spec coverage**:
  - 流程总览 → Task 1 (state) + Task 7 (/start) + Task 8 (callback) + Task 9 (approve)
  - invite 表精简 → Task 3
  - via_invite_id 列 → Task 4
  - POST /api/admin/invites simplification → Task 5
  - GET /api/invite/{token} simplification → Task 5
  - DELETE accept → Task 6
  - POST /start → Task 7
  - Feishu callback 改造 → Task 8
  - GET /api/admin/applications via_invite → Task 9
  - admin/invites 表单 + 行 → Task 11
  - InviteAccept 重写 → Task 12
  - admin/applications badge → Task 13
  - api.ts 类型 → Task 10
  - 边界处理（过期 410 / 已用 410 / 未知 404 / open_id 已活跃 / state 验签失败）→ Task 7 + Task 8

- ✅ **No placeholders**: all steps have actual code or specific file/line directives.
- ✅ **Type consistency**: `assign_pinyin` signature consistent (Task 2 / Task 9); `via_invite_id` field name consistent (Tasks 4, 8, 9); `encode/decode_invite_state` used in Tasks 1/7/8; `startInvite` consistent in Tasks 10/12.

注意一处可能要二次澄清：**Task 8** 的"already-active user"分支的实现里写了 `mark_used(invite_id=..., used_by_user_id=user.id)`——但 `used_by_user_id` 在表里 NOT NULL 约束如果存在的话会出错。看 invite 表 schema: `used_by_user_id TEXT`（nullable），所以 OK。