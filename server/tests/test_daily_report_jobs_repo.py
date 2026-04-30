"""Tests for `server.daily_report.jobs_repo.JobsRepo`.

Covers CRUD + due query + status transitions + receiver_ids JSON serialization
+ partial update + clear_last_run_id_in (365 天清理用)。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from server.daily_report.jobs_repo import JobsRepo
from server.daily_report.window import CHINA_TZ
from server.db import Database


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    return JobsRepo(db)


# --------------------------------------------------------------------------- #
# create + get                                                                #
# --------------------------------------------------------------------------- #


def test_create_with_minimal_fields(repo):
    job = repo.create(
        name="公司视角 · 早报",
        view="company",
        push_time="09:30",
        receiver_type="groups",
    )
    assert job.id > 0
    assert job.name == "公司视角 · 早报"
    assert job.view == "company"
    assert job.status == "active"           # 默认
    assert job.push_freq == "weekdays"      # 默认
    assert job.window_hours == 24           # 默认
    assert job.channel == "feishu"          # 默认
    assert job.receiver_type == "groups"
    assert job.receiver_ids is None         # 默认 None = 全部 bot 群
    assert job.retry_count == 0
    assert job.last_run_id is None
    assert job.next_run_at is None
    assert job.created_by is None


def test_create_with_full_fields(repo):
    next_at = datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ)
    job = repo.create(
        name="dengke 早报",
        view="personal",
        push_time="08:00",
        push_freq="daily",
        window_hours=48,
        receiver_type="users",
        receiver_ids=["ou_user_a", "ou_user_b"],
        status="paused",
        next_run_at=next_at,
        created_by="ou_admin",
    )
    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.push_time == "08:00"
    assert fetched.push_freq == "daily"
    assert fetched.window_hours == 48
    assert fetched.receiver_type == "users"
    assert fetched.receiver_ids == ("ou_user_a", "ou_user_b")
    assert fetched.status == "paused"
    assert fetched.created_by == "ou_admin"
    # 时间往返不丢精度
    assert abs((fetched.next_run_at - next_at).total_seconds()) < 1


def test_get_missing_returns_none(repo):
    assert repo.get(99999) is None


def test_create_accepts_new_freq_values(repo):
    """v2 push_freq 扩展:7 weekday + month_start/end 都能写入(无 CHECK 约束阻挡)"""
    for freq in ["mon", "tue", "wed", "thu", "fri", "sat", "sun",
                 "month_start", "month_end"]:
        job = repo.create(
            name=f"x-{freq}", view="company", push_time="09:00",
            push_freq=freq,  # type: ignore[arg-type]
            receiver_type="groups",
        )
        fetched = repo.get(job.id)
        assert fetched is not None
        assert fetched.push_freq == freq


# --------------------------------------------------------------------------- #
# list_all + list_due                                                         #
# --------------------------------------------------------------------------- #


def test_list_all_excludes_archived_by_default(repo):
    j1 = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    j2 = repo.create(name="b", view="personal", push_time="09:00", receiver_type="groups")
    repo.update_status(j2.id, "archived")

    items = repo.list_all()
    ids = [j.id for j in items]
    assert j1.id in ids
    assert j2.id not in ids


def test_list_all_with_archived_includes_all(repo):
    j1 = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    j2 = repo.create(name="b", view="personal", push_time="09:00", receiver_type="groups")
    repo.update_status(j2.id, "archived")
    items = repo.list_all(include_archived=True)
    assert len(items) == 2


def test_list_due_returns_only_active_and_due(repo):
    now = datetime.now(tz=CHINA_TZ)
    past = now - timedelta(minutes=5)
    future = now + timedelta(hours=1)

    # 过期 active —— 应该返回
    j_due = repo.create(
        name="due", view="company", push_time="09:00", receiver_type="groups",
        next_run_at=past,
    )
    # 过期但 paused —— 不应返回
    j_paused = repo.create(
        name="paused", view="company", push_time="09:00", receiver_type="groups",
        next_run_at=past, status="paused",
    )
    # 未来 active —— 不应返回
    j_future = repo.create(
        name="future", view="company", push_time="09:00", receiver_type="groups",
        next_run_at=future,
    )
    # next_run_at IS NULL —— 不应返回(刚创建尚未排期 / archived 后清空)
    j_null = repo.create(
        name="null", view="company", push_time="09:00", receiver_type="groups",
    )

    due = repo.list_due(now)
    ids = [j.id for j in due]
    assert ids == [j_due.id]


def test_list_due_orders_by_next_run_at_ascending(repo):
    now = datetime.now(tz=CHINA_TZ)
    j1 = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups",
                     next_run_at=now - timedelta(minutes=5))
    j2 = repo.create(name="b", view="company", push_time="09:00", receiver_type="groups",
                     next_run_at=now - timedelta(minutes=10))
    j3 = repo.create(name="c", view="company", push_time="09:00", receiver_type="groups",
                     next_run_at=now - timedelta(minutes=2))
    due = repo.list_due(now)
    assert [j.id for j in due] == [j2.id, j1.id, j3.id]


# --------------------------------------------------------------------------- #
# update_config                                                               #
# --------------------------------------------------------------------------- #


def test_update_config_partial(repo):
    job = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    repo.update_config(job.id, name="renamed", push_time="10:30")
    fetched = repo.get(job.id)
    assert fetched.name == "renamed"
    assert fetched.push_time == "10:30"
    assert fetched.view == "company"          # 未传不动


def test_update_config_receiver_ids_can_be_set_to_list(repo):
    job = repo.create(name="a", view="company", push_time="09:00",
                      receiver_type="groups", receiver_ids=["oc_a"])
    repo.update_config(job.id, receiver_ids=["oc_x", "oc_y"])
    assert repo.get(job.id).receiver_ids == ("oc_x", "oc_y")


def test_update_config_receiver_ids_explicit_none_clears(repo):
    """显式传 None 应该清空(对应"恢复默认 bot 群")。"""
    job = repo.create(name="a", view="company", push_time="09:00",
                      receiver_type="groups", receiver_ids=["oc_a"])
    repo.update_config(job.id, receiver_ids=None)
    assert repo.get(job.id).receiver_ids is None


def test_update_config_no_args_is_noop(repo):
    job = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    before = repo.get(job.id).updated_at
    repo.update_config(job.id)
    after = repo.get(job.id).updated_at
    assert before == after                   # 不传任何字段应该完全 no-op


# --------------------------------------------------------------------------- #
# update_status                                                               #
# --------------------------------------------------------------------------- #


def test_update_status_active_to_paused_clears_next_run_at(repo):
    job = repo.create(
        name="a", view="company", push_time="09:00", receiver_type="groups",
        next_run_at=datetime.now(tz=CHINA_TZ) + timedelta(hours=1),
    )
    assert repo.get(job.id).next_run_at is not None
    repo.update_status(job.id, "paused", next_run_at=None)
    assert repo.get(job.id).status == "paused"
    assert repo.get(job.id).next_run_at is None


def test_update_status_archived_clears_next_run_at(repo):
    job = repo.create(
        name="a", view="company", push_time="09:00", receiver_type="groups",
        next_run_at=datetime.now(tz=CHINA_TZ) + timedelta(hours=1),
    )
    repo.update_status(job.id, "archived", next_run_at=None)
    assert repo.get(job.id).status == "archived"
    assert repo.get(job.id).next_run_at is None


# --------------------------------------------------------------------------- #
# update_after_run                                                            #
# --------------------------------------------------------------------------- #


def test_update_after_run_writes_all_fields(repo):
    job = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    next_at = datetime.now(tz=CHINA_TZ) + timedelta(days=1)
    repo.update_after_run(
        job.id,
        last_run_id=42,
        last_status="succeeded",
        next_run_at=next_at,
        retry_count=0,
    )
    fetched = repo.get(job.id)
    assert fetched.last_run_id == 42
    assert fetched.last_status == "succeeded"
    assert fetched.retry_count == 0
    assert abs((fetched.next_run_at - next_at).total_seconds()) < 1


def test_update_after_run_can_set_last_notified_at(repo):
    job = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    notify_at = datetime.now(tz=CHINA_TZ)
    repo.update_after_run(
        job.id,
        last_run_id=1,
        last_status="missed",
        next_run_at=None,
        retry_count=0,
        last_notified_at=notify_at,
    )
    assert repo.get(job.id).last_notified_at is not None


# --------------------------------------------------------------------------- #
# clear_last_run_id_in                                                        #
# --------------------------------------------------------------------------- #


def test_clear_last_run_id_in_nullifies_matching(repo):
    j1 = repo.create(name="a", view="company", push_time="09:00", receiver_type="groups")
    j2 = repo.create(name="b", view="company", push_time="09:00", receiver_type="groups")
    repo.update_after_run(j1.id, last_run_id=100, last_status="succeeded",
                          next_run_at=None, retry_count=0)
    repo.update_after_run(j2.id, last_run_id=101, last_status="succeeded",
                          next_run_at=None, retry_count=0)

    rows_affected = repo.clear_last_run_id_in([100])
    assert rows_affected == 1
    assert repo.get(j1.id).last_run_id is None
    assert repo.get(j2.id).last_run_id == 101    # 未受影响


def test_clear_last_run_id_in_empty_list_is_noop(repo):
    assert repo.clear_last_run_id_in([]) == 0


# 表层不再做枚举值校验 — view / status / push_freq / channel / receiver_type
# 都已在 Pydantic 层(server.api.daily_report_v2)拦截。jobs_repo 信任入参。
# window_hours 范围(1-168)同样由 Pydantic 在 API 边界守住。
