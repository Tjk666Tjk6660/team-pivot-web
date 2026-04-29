"""Tests for the full-history relevance scanner."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.relevance_events import RelevanceEventsRepo
from server.relevance_scanner import (
    ScanReport,
    is_backfill_on_startup_enabled,
    scan_all,
)
from server.users import UserRepo


# ---------- fixtures ----------


class _StubWorkspace:
    def __init__(self, root: Path) -> None:
        self.path = root
        (root / "index").mkdir(parents=True, exist_ok=True)

    @property
    def index_dir(self) -> Path:
        return self.path / "index"


@pytest.fixture
def workspace(tmp_path):
    return _StubWorkspace(tmp_path)


@pytest.fixture
def relevance_repo(db):
    return RelevanceEventsRepo(db)


def _register_user(users: UserRepo, *, pinyin: str) -> str:
    open_id = f"ou_{pinyin}"
    users.upsert_from_feishu(
        open_id=open_id, union_id=None, name=pinyin, avatar_url="",
    )
    users.update_profile(open_id, pinyin=pinyin)
    return open_id


def _write_matter(workspace: _StubWorkspace, matter_id: str, data: dict) -> None:
    p = workspace.index_dir / f"{matter_id}.index.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _proposal(creator: str, file_rel: str, owner: str | None = None) -> dict:
    return {
        "file": file_rel,
        "type": "think",
        "creator": creator,
        "owner": owner or creator,
        "summary": "",
        "created_at": "2026-04-28T10:00:00+08:00",
    }


def _act_with_comments(
    creator: str,
    file_rel: str,
    *,
    owner: str | None = None,
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


# ---------- empty / edge ----------


def test_scan_all_no_users_returns_zero(workspace, users, relevance_repo):
    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report == ScanReport(inserted=0, skipped=0, matters=0)


def test_scan_all_no_matters_returns_zero(workspace, users, relevance_repo):
    _register_user(users, pinyin="alice")
    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report.inserted == 0
    assert report.skipped == 0
    assert report.matters == 0


# ---------- file-level rows ----------


def test_scan_writes_owner_assigned_rows(workspace, users, relevance_repo):
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md", owner="alice",
            ),
        ],
    })

    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report.inserted >= 1
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (1, 0)}


def test_scan_writes_in_my_matter_for_others_actions(
    workspace, users, relevance_repo,
):
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("alice", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments("bob", "discussions/cat/m-x/02.md"),
        ],
    })

    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)
    # alice 创建 matter,bob 在里面发 act → in_my_matter
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (1, 0)}


# ---------- mention-level rows ----------


def test_scan_writes_mention_rows_for_each_comment(
    workspace, users, relevance_repo,
):
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md",
                comments=[
                    {
                        "created_at": "2026-04-28T11:01:00+08:00",
                        "body": "看下 @alice",
                        "author": "bob",
                        "mentions": ["alice"],
                    },
                    {
                        "created_at": "2026-04-28T11:02:00+08:00",
                        "body": "再看 @alice",
                        "author": "bob",
                        "mentions": ["alice"],
                    },
                ],
            ),
        ],
    })

    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)
    # alice 不是 file owner / quote target,所以没 file 行;但 2 条 mention
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 2)}


def test_scan_skips_self_mention_in_comments(workspace, users, relevance_repo):
    bob_id = _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md",
                comments=[
                    {
                        "created_at": "2026-04-28T11:01:00+08:00",
                        "body": "@bob 自己 @ 自己",
                        "author": "bob",
                        "mentions": ["bob"],
                    },
                ],
            ),
        ],
    })

    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)
    assert relevance_repo.unread_breakdown_per_matter(bob_id) == {}


def test_scan_skips_unregistered_contact(workspace, users, relevance_repo):
    _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md",
                comments=[
                    {
                        "created_at": "2026-04-28T11:01:00+08:00",
                        "body": "@外部",
                        "author": "bob",
                        "mentions": ["ou_external_unregistered"],
                    },
                ],
            ),
        ],
    })

    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)
    with relevance_repo._db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM relevance_events").fetchone()[0]
    assert n == 0


# ---------- idempotency ----------


def test_scan_twice_inserts_zero_second_time(workspace, users, relevance_repo):
    """第二次扫描所有行已存在,inserted=0 全是 skipped。"""
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    _write_matter(workspace, "m-x", {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md", owner="alice",
                comments=[
                    {
                        "created_at": "2026-04-28T11:01:00+08:00",
                        "body": "@alice",
                        "author": "bob",
                        "mentions": ["alice"],
                    },
                ],
            ),
        ],
    })

    first = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    second = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )

    assert first.inserted >= 2  # at minimum: 1 file row + 1 mention row
    assert second.inserted == 0
    assert second.skipped >= first.inserted

    # 行内容不变
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (1, 1)}


def test_scan_picks_up_new_mention_added_after_first_run(
    workspace, users, relevance_repo,
):
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    base_data = {
        "matter": {"id": "m-x"},
        "timeline": [
            _proposal("bob", file_rel="discussions/cat/m-x/01.md"),
            _act_with_comments(
                "bob", "discussions/cat/m-x/02.md",
                comments=[
                    {
                        "created_at": "2026-04-28T11:01:00+08:00",
                        "body": "@alice", "author": "bob",
                        "mentions": ["alice"],
                    },
                ],
            ),
        ],
    }
    _write_matter(workspace, "m-x", base_data)
    scan_all(workspace=workspace, users_repo=users, repo=relevance_repo)

    # 模拟实时写入漏掉了一条新评论(只追加 yaml,没 emit)
    base_data["timeline"][1]["comments"].append({
        "created_at": "2026-04-28T11:05:00+08:00",
        "body": "@alice 又一条", "author": "bob",
        "mentions": ["alice"],
    })
    _write_matter(workspace, "m-x", base_data)

    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report.inserted == 1  # 只补了缺失的那条
    assert relevance_repo.unread_breakdown_per_matter(alice_id) == {"m-x": (0, 2)}


# ---------- multi-matter ----------


def test_scan_walks_multiple_matters(workspace, users, relevance_repo):
    alice_id = _register_user(users, pinyin="alice")
    _register_user(users, pinyin="bob")

    for matter_id in ("m-x", "m-y"):
        _write_matter(workspace, matter_id, {
            "matter": {"id": matter_id},
            "timeline": [
                _proposal("bob", file_rel=f"discussions/cat/{matter_id}/01.md"),
                _act_with_comments(
                    "bob", f"discussions/cat/{matter_id}/02.md", owner="alice",
                ),
            ],
        })

    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report.matters == 2
    breakdown = relevance_repo.unread_breakdown_per_matter(alice_id)
    assert breakdown == {"m-x": (1, 0), "m-y": (1, 0)}


def test_scan_skips_legacy_discuss_index_files(workspace, users, relevance_repo):
    """老 thread 模型的 *-discuss.index.yaml 不应被扫描器认为是 matter。"""
    _register_user(users, pinyin="alice")

    legacy = workspace.index_dir / "thread-discuss.index.yaml"
    legacy.write_text(
        yaml.safe_dump({"matter": {"id": "thread"}, "timeline": []}),
        encoding="utf-8",
    )

    report = scan_all(
        workspace=workspace, users_repo=users, repo=relevance_repo,
    )
    assert report.matters == 0


# ---------- env switch ----------


def test_is_backfill_on_startup_enabled_default_true(monkeypatch):
    monkeypatch.delenv("RELEVANCE_BACKFILL_ON_STARTUP", raising=False)
    assert is_backfill_on_startup_enabled() is True


@pytest.mark.parametrize(
    "value", ["false", "FALSE", "0", "no", "off"],
)
def test_is_backfill_on_startup_enabled_disable_values(monkeypatch, value):
    monkeypatch.setenv("RELEVANCE_BACKFILL_ON_STARTUP", value)
    assert is_backfill_on_startup_enabled() is False


@pytest.mark.parametrize(
    "value", ["true", "TRUE", "1", "yes", "on", ""],
)
def test_is_backfill_on_startup_enabled_truthy_values(monkeypatch, value):
    monkeypatch.setenv("RELEVANCE_BACKFILL_ON_STARTUP", value)
    assert is_backfill_on_startup_enabled() is True
