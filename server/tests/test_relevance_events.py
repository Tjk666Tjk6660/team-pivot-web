from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from server.relevance_events import (
    KIND_FILE,
    KIND_MENTION,
    REASON_COMMENT_MENTION,
    RelevanceEventsRepo,
)


@pytest.fixture
def repo(db):
    return RelevanceEventsRepo(db)


# ---------- insert_file / insert_mention ----------


def test_insert_file_first_time_returns_true(repo):
    inserted = repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:22:03+08:00",
        actor_pinyin="lingdao",
    )
    assert inserted is True


def test_insert_file_duplicate_returns_false(repo):
    first = repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:22:03+08:00",
        actor_pinyin="lingdao",
    )
    second = repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="reply_to_my_file",   # 即使 reason 不同,PK 撞,IGNORE
        event_at="2026-04-28T10:22:03+08:00",
        actor_pinyin="lingdao",
    )
    assert first is True
    assert second is False


def test_insert_mention_different_comments_both_persist(repo):
    """同一个 (user, matter, filename) 下被多次 @,event_at 不同,各自落表。"""
    a = repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00",
        actor_pinyin="lingdao",
    )
    b = repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:05:00+08:00",
        actor_pinyin="lingdao",
    )
    assert a is True and b is True
    breakdown = repo.unread_breakdown_per_matter("ou_b")
    assert breakdown == {"m-x": (0, 2)}


def test_insert_mention_same_comment_two_at_dedupes(repo):
    """同一 comment 里 @ 同一人两次 → PK 撞 → 第二次 IGNORE。"""
    a = repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00",
        actor_pinyin="lingdao",
    )
    b = repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00",
        actor_pinyin="lingdao",
    )
    assert a is True and b is False


def test_insert_isolates_users(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    assert repo.unread_breakdown_per_matter("ou_a") == {"m-x": (0, 1)}
    assert repo.unread_breakdown_per_matter("ou_b") == {"m-x": (0, 1)}


def test_insert_isolates_matters(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_a", "m-y", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    breakdown = repo.unread_breakdown_per_matter("ou_a")
    assert breakdown == {"m-x": (1, 0), "m-y": (1, 0)}


# ---------- exists ----------


def test_exists_returns_true_after_insert(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    assert repo.exists(
        user_open_id="ou_a", matter_id="m-x", filename="01.md",
        kind=KIND_FILE,
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    ) is True


def test_exists_returns_false_for_missing_pk(repo):
    assert repo.exists(
        user_open_id="ou_a", matter_id="m-x", filename="01.md",
        kind=KIND_FILE,
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    ) is False


def test_exists_distinguishes_kinds(repo):
    """同一 PK 各部分相同但 kind 不同,各自独立。"""
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    # 同一 (user, matter, file, event_at, actor) 但 kind=mention 不存在
    assert repo.exists(
        user_open_id="ou_a", matter_id="m-x", filename="01.md",
        kind=KIND_MENTION,
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    ) is False


# ---------- mark_all_read_for_file ----------


def test_mark_all_read_for_file_clears_unread_on_that_file(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:01:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:02:00+08:00", actor_pinyin="lingdao",
    )

    n = repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert n == 3
    assert repo.unread_breakdown_per_matter("ou_a") == {}


def test_mark_all_read_for_file_does_not_touch_other_files(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "02.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )

    n = repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert n == 1
    # 02.md 还是未读
    assert repo.unread_breakdown_per_matter("ou_a") == {"m-x": (0, 1)}


def test_mark_all_read_for_file_does_not_touch_other_users(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_b", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert repo.unread_breakdown_per_matter("ou_a") == {}
    assert repo.unread_breakdown_per_matter("ou_b") == {"m-x": (0, 1)}


def test_mark_all_read_for_file_idempotent_on_already_read_rows(repo):
    """重复调用不会再次更新 read_at(WHERE read_at IS NULL 过滤)。"""
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="2026-04-28T10:00:00+08:00", actor_pinyin="lingdao",
    )
    n1 = repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    n2 = repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert n1 == 1
    assert n2 == 0


# ---------- unread_breakdown_per_matter ----------


def test_unread_breakdown_counts_file_and_mention_separately(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_a", "m-x", "02.md",
        reason="reply_to_my_file",
        event_at="t2", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c2", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "03.md",
        comment_at="c3", actor_pinyin="lingdao",
    )
    assert repo.unread_breakdown_per_matter("ou_a") == {"m-x": (2, 3)}


def test_unread_breakdown_excludes_already_read_rows(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "02.md",
        comment_at="c2", actor_pinyin="lingdao",
    )
    repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert repo.unread_breakdown_per_matter("ou_a") == {"m-x": (0, 1)}


def test_unread_breakdown_groups_per_matter(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md", comment_at="c1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-y", "01.md", comment_at="c2", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-y", "02.md", comment_at="c3", actor_pinyin="lingdao",
    )
    assert repo.unread_breakdown_per_matter("ou_a") == {
        "m-x": (0, 1),
        "m-y": (0, 2),
    }


def test_unread_breakdown_empty_when_no_unread(repo):
    assert repo.unread_breakdown_per_matter("ou_nobody") == {}


# ---------- unread_mention_keys_for_matter ----------


def test_unread_mention_keys_returns_only_unread_mentions(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-x", "02.md",
        comment_at="c2", actor_pinyin="boss",
    )
    keys = repo.unread_mention_keys_for_matter("ou_a", "m-x")
    # file 行不应出现在 mention key 集合里
    assert keys == {("01.md", "c1", "lingdao"), ("02.md", "c2", "boss")}


def test_unread_mention_keys_excludes_read_rows(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c1", actor_pinyin="lingdao",
    )
    repo.mark_all_read_for_file("ou_a", "m-x", "01.md")
    assert repo.unread_mention_keys_for_matter("ou_a", "m-x") == set()


def test_unread_mention_keys_isolates_matter(repo):
    repo.insert_mention(
        "ou_a", "m-x", "01.md", comment_at="c1", actor_pinyin="lingdao",
    )
    repo.insert_mention(
        "ou_a", "m-y", "01.md", comment_at="c1", actor_pinyin="lingdao",
    )
    assert repo.unread_mention_keys_for_matter("ou_a", "m-x") == {
        ("01.md", "c1", "lingdao"),
    }


# ---------- file_reasons_for_matter ----------


def test_file_reasons_returns_filename_to_reason_mapping(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_a", "m-x", "02.md",
        reason="reply_to_my_file",
        event_at="t2", actor_pinyin="lingdao",
    )
    # mention 行不应出现
    repo.insert_mention(
        "ou_a", "m-x", "01.md",
        comment_at="c1", actor_pinyin="lingdao",
    )
    out = repo.file_reasons_for_matter("ou_a", "m-x")
    assert out == {"01.md": "owner_assigned", "02.md": "reply_to_my_file"}


def test_file_reasons_isolates_user_and_matter(repo):
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_b", "m-x", "01.md",
        reason="reply_to_my_file",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_a", "m-y", "01.md",
        reason="in_my_matter",
        event_at="t1", actor_pinyin="lingdao",
    )
    assert repo.file_reasons_for_matter("ou_a", "m-x") == {"01.md": "owner_assigned"}
    assert repo.file_reasons_for_matter("ou_b", "m-x") == {"01.md": "reply_to_my_file"}
    assert repo.file_reasons_for_matter("ou_a", "m-y") == {"01.md": "in_my_matter"}


# ---------- 验证 reason / read_at 持久化保留首次 ----------


def test_first_reason_is_kept_on_dup_insert(repo):
    """INSERT OR IGNORE 即使后写的 reason 不同也不替换。"""
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="owner_assigned",
        event_at="t1", actor_pinyin="lingdao",
    )
    repo.insert_file(
        "ou_a", "m-x", "01.md",
        reason="reply_to_my_file",
        event_at="t1", actor_pinyin="lingdao",
    )
    assert repo.file_reasons_for_matter("ou_a", "m-x") == {"01.md": "owner_assigned"}


# ---------- concurrency ----------


def test_concurrent_insert_same_pk_yields_one_row(repo):
    """N 个线程并发 insert 同一 PK,最终表中只有一行,
    且不会因为 SQLite 锁竞争抛 OperationalError。"""
    N = 32

    def worker():
        return repo.insert_mention(
            "ou_a", "m-x", "01.md",
            comment_at="c1", actor_pinyin="lingdao",
        )

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker) for _ in range(N)]
        results = [f.result() for f in as_completed(futures)]

    # 恰有一个 worker 拿到 True(实际写入),其他都是 False(IGNORE)
    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == N - 1

    # 表里只有一行
    with repo._db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM relevance_events WHERE user_open_id='ou_a'"
        ).fetchone()[0]
    assert count == 1


def test_concurrent_distinct_pks_all_persist(repo):
    """N 个线程写不同 PK,全部落表。"""
    N = 32

    def worker(i: int):
        return repo.insert_mention(
            f"ou_{i % 4}", f"m-{i % 3}", f"{i:03d}.md",
            comment_at=f"c{i}", actor_pinyin="lingdao",
        )

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker, i) for i in range(N)]
        results = [f.result() for f in as_completed(futures)]

    assert all(results)  # 全部为 True

    with repo._db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM relevance_events").fetchone()[0]
    assert count == N


def test_concurrent_does_not_raise_locked(repo):
    N = 64

    def worker(i: int):
        try:
            repo.insert_mention(
                f"ou_{i % 8}", "m-x", f"{i % 4:02d}.md",
                comment_at=f"c{i}", actor_pinyin="lingdao",
            )
            return None
        except sqlite3.OperationalError as e:  # pragma: no cover
            return str(e)

    with ThreadPoolExecutor(max_workers=N) as pool:
        errors = [r for r in pool.map(worker, range(N)) if r is not None]

    assert errors == [], f"unexpected sqlite errors under contention: {errors}"


# ---------- exported constants are stable ----------


def test_kind_constants_stable():
    """kind 字段是 PK 一部分,常量值不能随便变(否则历史行查不到)。"""
    assert KIND_FILE == "file"
    assert KIND_MENTION == "mention"
    assert REASON_COMMENT_MENTION == "comment_mention"
