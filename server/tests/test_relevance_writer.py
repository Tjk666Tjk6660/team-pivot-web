"""Tests for the real-time relevance event writer.

We don't go through the full publish.py path here; we wire the writer to
the event bus, then directly emit events with the same payloads publish.py
emits, and verify the right rows land in relevance_events.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.events import (
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_OWNER_CHANGED,
    clear_subscribers,
    emit,
)
from server.relevance_events import RelevanceEventsRepo
from server.relevance_writer import install
from server.users import UserRepo


# ---------- fixtures ----------


class _StubWorkspace:
    """Minimal workspace stand-in: only `index_dir` is touched by the writer."""

    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


@pytest.fixture(autouse=True)
def _isolate_event_bus():
    """Each test starts with a clean subscribers list and clears on teardown."""
    clear_subscribers()
    yield
    clear_subscribers()


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def relevance_repo(db):
    return RelevanceEventsRepo(db)


@pytest.fixture
def writer_installed(workspace, users, relevance_repo):
    unsub = install(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    yield
    unsub()


def _register_user(users: UserRepo, *, pinyin: str) -> str:
    """Helper: insert a Feishu-shape user with the given pinyin, return open_id."""
    open_id = f"ou_{pinyin}"
    users.upsert_from_feishu(
        open_id=open_id, union_id=None, name=pinyin, avatar_url="",
    )
    users.update_profile(open_id, pinyin=pinyin)
    return open_id


def _write_matter(workspace: _StubWorkspace, matter_id: str, data: dict) -> None:
    p = workspace.index_dir / f"{matter_id}.index.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _proposal(creator: str, owner: str | None = None, file_rel: str = "") -> dict:
    return {
        "file": file_rel,
        "type": "think",
        "creator": creator,
        "owner": owner or creator,
        "summary": "",
        "created_at": "2026-04-28T10:00:00+08:00",
    }


def _act(
    creator: str,
    owner: str | None = None,
    file_rel: str = "",
    quote: str | None = None,
    comments: list | None = None,
    created_at: str = "2026-04-28T11:00:00+08:00",
) -> dict:
    item: dict = {
        "file": file_rel,
        "type": "act",
        "creator": creator,
        "owner": owner or creator,
        "summary": "",
        "created_at": created_at,
    }
    if quote is not None:
        item["quote"] = quote
    if comments is not None:
        item["comments"] = comments
    return item


# ---------- file-level writes ----------


def test_file_appended_writes_owner_assigned_for_target_user(
    workspace, users, relevance_repo, writer_installed,
):
    _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    file_rel = "discussions/cat/m-x/02-act.md"
    proposal = _proposal("bob", file_rel="discussions/cat/m-x/01-think.md")
    item = _act(
        "bob", owner="alice", file_rel=file_rel,
        created_at="2026-04-28T11:00:00+08:00",
    )
    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [proposal, item],
    })

    emit(
        TOPIC_FILE_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T11:00:00+08:00",
        payload={"file": file_rel, "type": "act", "creator": "bob", "owner": "alice"},
    )

    breakdown = relevance_repo.unread_breakdown_per_matter("ou_alice")
    assert breakdown == {"m-x": (1, 0)}
    # bob 是 actor,self-exclusion 跳过
    assert relevance_repo.unread_breakdown_per_matter("ou_bob") == {}


def test_file_appended_self_creator_no_row_for_actor(
    workspace, users, relevance_repo, writer_installed,
):
    _register_user(users, pinyin="alice")

    file_rel = "discussions/cat/m-x/01-think.md"
    item = _proposal("alice", file_rel=file_rel)
    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [item],
    })

    emit(
        TOPIC_FILE_APPENDED,
        matter_id="m-x", actor="alice", at="2026-04-28T10:00:00+08:00",
        payload={
            "file": file_rel, "type": "think",
            "creator": "alice", "owner": "alice",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter("ou_alice") == {}


def test_file_appended_in_my_matter_for_proposal_creator(
    workspace, users, relevance_repo, writer_installed,
):
    _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    proposal = _proposal("alice", file_rel="discussions/cat/m-x/01.md")
    file_rel = "discussions/cat/m-x/02.md"
    item = _act("bob", file_rel=file_rel)
    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [proposal, item],
    })

    emit(
        TOPIC_FILE_APPENDED,
        matter_id="m-x", actor="bob", at="2026-04-28T11:00:00+08:00",
        payload={"file": file_rel, "type": "act",
                 "creator": "bob", "owner": "bob"},
    )

    breakdown = relevance_repo.unread_breakdown_per_matter("ou_alice")
    # alice 创建 matter,bob 在里面发 act → in_my_matter
    assert breakdown == {"m-x": (1, 0)}


def test_file_appended_idempotent(
    workspace, users, relevance_repo, writer_installed,
):
    """重复 emit 同一个事件,INSERT OR IGNORE 保证只一行。"""
    _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    file_rel = "discussions/cat/m-x/02.md"
    proposal = _proposal("bob", file_rel="discussions/cat/m-x/01.md")
    item = _act("bob", owner="alice", file_rel=file_rel)
    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"}, "timeline": [proposal, item],
    })

    payload = {"file": file_rel, "type": "act",
               "creator": "bob", "owner": "alice"}
    emit(TOPIC_FILE_APPENDED, matter_id="m-x", actor="bob",
         at="2026-04-28T11:00:00+08:00", payload=payload)
    emit(TOPIC_FILE_APPENDED, matter_id="m-x", actor="bob",
         at="2026-04-28T11:00:00+08:00", payload=payload)

    assert relevance_repo.unread_breakdown_per_matter("ou_alice") == {"m-x": (1, 0)}


def test_file_appended_missing_index_logs_and_returns(
    workspace, users, relevance_repo, writer_installed,
):
    """事件指向不存在的 matter index → swallow,不抛。"""
    _register_user(users, pinyin="alice")
    emit(
        TOPIC_FILE_APPENDED,
        matter_id="ghost", actor="bob", at="2026-04-28T11:00:00+08:00",
        payload={"file": "discussions/cat/ghost/01.md"},
    )
    # 没崩,也没行
    assert relevance_repo.unread_breakdown_per_matter("ou_alice") == {}


def test_file_appended_payload_without_file_is_ignored(
    workspace, users, relevance_repo, writer_installed,
):
    _register_user(users, pinyin="alice")
    emit(
        TOPIC_FILE_APPENDED,
        matter_id="m-x", actor="bob", at="2026-04-28T11:00:00+08:00",
        payload={},
    )
    assert relevance_repo.unread_breakdown_per_matter("ou_alice") == {}


# ---------- mention-level writes ----------


def test_comment_appended_writes_mention_for_each_target(
    workspace, users, relevance_repo, writer_installed,
):
    alice_id = _register_user(users, pinyin="alice")
    charlie_id = _register_user(users, pinyin="charlie")
    _register_user(users, pinyin="bob")  # actor

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "看下这条 @alice @charlie",
            "mentions": [alice_id, charlie_id],
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}


def test_comment_appended_self_mention_skipped(
    workspace, users, relevance_repo, writer_installed,
):
    bob_id = _register_user(users, pinyin="bob")

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "@bob 自己 @ 自己",
            "mentions": [bob_id],
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(bob_id) == {}


def test_comment_appended_unregistered_contact_skipped(
    workspace, users, relevance_repo, writer_installed,
):
    """mention 是个未注册的 open_id,users.get_by_any_id 返回 None,跳过。"""
    _register_user(users, pinyin="bob")  # actor

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "@外部联系人",
            "mentions": ["ou_external_unregistered"],
        },
    )

    # 没人收到 mention 行
    with relevance_repo._db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM relevance_events").fetchone()[0]
    assert n == 0


def test_comment_appended_multiple_comments_accumulate(
    workspace, users, relevance_repo, writer_installed,
):
    """同一文件多次 @ 同一人,每条 comment_at 不同 → 各自落表,red 累加。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    base = {
        "target_file": "discussions/cat/m-x/01.md",
        "body": "@alice", "mentions": [alice_id],
    }
    for i in range(5):
        emit(
            TOPIC_COMMENT_APPENDED,
            matter_id="m-x", actor="bob",
            at=f"2026-04-28T12:0{i}:00+08:00",
            payload=base,
        )

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 5)}


def test_comment_appended_no_mentions_writes_nothing(
    workspace, users, relevance_repo, writer_installed,
):
    _register_user(users, pinyin="alice")

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "纯讨论,没 @ 任何人",
            "mentions": [],
        },
    )

    with relevance_repo._db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM relevance_events").fetchone()[0]
    assert n == 0


# ---------- error swallowing ----------


def test_writer_does_not_propagate_exceptions_to_emit(
    workspace, users, relevance_repo, writer_installed,
):
    """即使 writer 内部抛错,emit() 也不应该抛——publish 主路径不能因为
    relevance 衍生数据写入挂掉而整体失败。"""
    # Construct an event whose payload would cause an attribute access
    # crash if we didn't guard. emit() should swallow.
    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={"target_file": "x", "mentions": [None]},  # type: ignore[list-item]
    )
    # No assertion needed — the test passes if emit() didn't throw.


# ---------- unsubscribe ----------


def test_unsubscribe_stops_writes(
    workspace, users, relevance_repo,
):
    """install 返回的 unsubscribe 调用后,后续事件不再写。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    unsub = install(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:00:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "@alice", "mentions": [alice_id],
        },
    )
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}

    unsub()

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id="m-x", actor="bob",
        at="2026-04-28T12:01:00+08:00",
        payload={
            "target_file": "discussions/cat/m-x/01.md",
            "body": "@alice 第二次", "mentions": [alice_id],
        },
    )
    # 仍然只有第一条,unsubscribe 之后没有新行
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}


# ---------- matter owner change ----------


def test_owner_changed_writes_rows_for_creator_old_and_new_owner(
    workspace, users, relevance_repo, writer_installed,
):
    """A 创建 matter 指定 owner=B,B 自己把 owner 转给 C:
    A(创建者)和 C(新 owner)各拿一行;B 是 actor → 自排除。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")  # actor + from_owner
    charlie_id = _register_user(users, pinyin="charlie")

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="bob",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "bob",
            "to_owner": "charlie",
            "reason": "由 charlie 接手后续推进",
            "status_change": None,
            "matter_creator": "alice",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}
    # bob 是 actor,自排除
    assert relevance_repo.unread_breakdown_per_matter("ou_bob") == {}


def test_owner_changed_admin_actor_notifies_old_owner(
    workspace, users, relevance_repo, writer_installed,
):
    """admin(非 from/to/creator)主导转交时,B(旧 owner)也应拿到红点 ——
    告诉他"你已不再是 owner"。"""
    alice_id = _register_user(users, pinyin="alice")
    bob_id = _register_user(users, pinyin="bob")
    charlie_id = _register_user(users, pinyin="charlie")
    _register_user(users, pinyin="admin")  # actor

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="admin",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "bob",
            "to_owner": "charlie",
            "reason": "管理员强制转交",
            "status_change": None,
            "matter_creator": "alice",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(bob_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter("ou_admin") == {}


def test_owner_changed_creator_equals_actor_skips_creator(
    workspace, users, relevance_repo, writer_installed,
):
    """A 自己创建并转交 owner B→C:A 是 actor 兼 creator,A 自排除,
    只有 C 拿到行。"""
    _register_user(users, pinyin="alice")  # actor + creator
    bob_id = _register_user(users, pinyin="bob")
    charlie_id = _register_user(users, pinyin="charlie")

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="alice",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "bob",
            "to_owner": "charlie",
            "reason": "回收后再分配",
            "status_change": None,
            "matter_creator": "alice",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter("ou_alice") == {}
    assert relevance_repo.unread_breakdown_per_matter(bob_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}


def test_owner_changed_creator_equals_to_owner_no_duplicate(
    workspace, users, relevance_repo, writer_installed,
):
    """matter_creator 与 to_owner 同一人(C 创建并自接 owner)时只插一行,
    不应该因为命中两个分类而双倍计数。"""
    _register_user(users, pinyin="bob")  # actor
    charlie_id = _register_user(users, pinyin="charlie")  # creator + to_owner

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="bob",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "bob",
            "to_owner": "charlie",
            "reason": "把这单还给原作者",
            "status_change": None,
            "matter_creator": "charlie",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}


def test_owner_changed_unregistered_owner_skipped(
    workspace, users, relevance_repo, writer_installed,
):
    """from_owner 是未注册联系人(get_by_any_id 返回 None)→ 跳过。
    其他注册用户照常落行。"""
    alice_id = _register_user(users, pinyin="alice")
    charlie_id = _register_user(users, pinyin="charlie")
    _register_user(users, pinyin="actor_admin")

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="actor_admin",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "ghost_pinyin_no_user",
            "to_owner": "charlie",
            "reason": "替换掉离职的旧负责人",
            "status_change": None,
            "matter_creator": "alice",
        },
    )

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}


def test_owner_changed_idempotent(
    workspace, users, relevance_repo, writer_installed,
):
    """同一个 owner_change 事件重复 emit(同 event_at + actor),
    INSERT OR IGNORE 保证不重复。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")
    charlie_id = _register_user(users, pinyin="charlie")

    payload = {
        "from_owner": "bob", "to_owner": "charlie",
        "reason": "r", "status_change": None,
        "matter_creator": "alice",
    }
    emit(TOPIC_MATTER_OWNER_CHANGED, matter_id="m-x", actor="bob",
         at="2026-04-29T10:00:00+08:00", payload=payload)
    emit(TOPIC_MATTER_OWNER_CHANGED, matter_id="m-x", actor="bob",
         at="2026-04-29T10:00:00+08:00", payload=payload)

    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}
    assert relevance_repo.unread_breakdown_per_matter(charlie_id) == {"m-x": (0, 1)}


def test_owner_changed_cleared_when_user_reads_a_file(
    workspace, users, relevance_repo, writer_installed,
):
    """A 读了 matter 里任意一个文件后,owner_change 行也应一起标记为已读 ——
    matter 级事件没有专属文件,挂在文件级 mark_all_read_for_file 上。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id="m-x", actor="bob",
        at="2026-04-29T10:00:00+08:00",
        payload={
            "from_owner": "bob", "to_owner": "alice",
            "reason": "r", "status_change": None,
            "matter_creator": "alice",
        },
    )
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 1)}

    # alice 打开任意一个文件
    relevance_repo.mark_all_read_for_file(alice_id, "m-x", "01-think.md")
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {}
