"""Tests for `server.daily_report.runs_repo.RunsRepo`.

Covers start/finish lifecycle + pagination + delete_before(365 天清理)
+ error truncation。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from server.daily_report.runs_repo import RunsRepo
from server.daily_report.window import CHINA_TZ
from server.db import Database


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    return RunsRepo(db)


# --------------------------------------------------------------------------- #
# start + finish                                                              #
# --------------------------------------------------------------------------- #


def test_start_returns_id_and_marks_running(repo):
    rid = repo.start(job_id=1, trigger_type="scheduled", view="company")
    assert rid > 0
    run = repo.get(rid)
    assert run is not None
    assert run.status == "running"
    assert run.finished_at is None
    assert run.job_id == 1
    assert run.trigger_type == "scheduled"
    assert run.view == "company"


def test_start_with_null_job_id_for_manual(repo):
    """手动一次性触发 job_id=NULL。"""
    rid = repo.start(job_id=None, trigger_type="manual", view="company")
    run = repo.get(rid)
    assert run.job_id is None
    assert run.trigger_type == "manual"


def test_finish_marks_succeeded(repo):
    rid = repo.start(job_id=1, trigger_type="scheduled", view="company")
    repo.finish(
        rid, status="succeeded", rc=0,
        cards_sent=2, cards_total=2,
        ai_tokens_in=1500, ai_tokens_out=320,
    )
    run = repo.get(rid)
    assert run.status == "succeeded"
    assert run.rc == 0
    assert run.finished_at is not None
    assert run.cards_sent == 2
    assert run.cards_total == 2
    assert run.ai_tokens_in == 1500
    assert run.ai_tokens_out == 320


def test_finish_marks_failed_with_error(repo):
    rid = repo.start(job_id=1, trigger_type="scheduled", view="company")
    repo.finish(rid, status="failed", rc=-1, error="ai_error: TimeoutError")
    run = repo.get(rid)
    assert run.status == "failed"
    assert run.rc == -1
    assert "TimeoutError" in run.error


def test_finish_truncates_long_error(repo):
    """error 字段超过 200 字应被截断。"""
    rid = repo.start(job_id=1, trigger_type="scheduled", view="company")
    long = "x" * 500
    repo.finish(rid, status="failed", error=long)
    run = repo.get(rid)
    assert len(run.error) <= 201            # 200 + ellipsis
    assert run.error.endswith("…")


def test_finish_stores_debug_json(repo):
    rid = repo.start(job_id=1, trigger_type="scheduled", view="company")
    repo.finish(rid, status="succeeded", debug_json='{"n_active": 11}')
    assert repo.get(rid).debug_json == '{"n_active": 11}'


# --------------------------------------------------------------------------- #
# list_for_job (pagination)                                                   #
# --------------------------------------------------------------------------- #


def test_list_for_job_pagination_descending_by_started_at(repo):
    base = datetime(2026, 4, 1, 9, 30, tzinfo=CHINA_TZ)
    ids = []
    for i in range(25):
        # 每条 started_at 间隔 1 天,模拟 25 天的运行历史
        rid = repo.start(
            job_id=1, trigger_type="scheduled", view="company",
            started_at=base + timedelta(days=i),
        )
        ids.append(rid)

    # 第 1 页:应该是最新的 20 条(第 25 天的在最前)
    page1, total = repo.list_for_job(1, page=1, size=20)
    assert total == 25
    assert len(page1) == 20
    # 第 1 条应该是最新的 = ids[24]
    assert page1[0].id == ids[24]
    assert page1[-1].id == ids[5]            # 第 20 条 = ids[5]

    # 第 2 页:剩下 5 条(第 1-5 天)
    page2, total2 = repo.list_for_job(1, page=2, size=20)
    assert total2 == 25
    assert len(page2) == 5
    assert page2[0].id == ids[4]
    assert page2[-1].id == ids[0]


def test_list_for_job_filters_by_job_id(repo):
    """只返回该 job 的记录。"""
    repo.start(job_id=1, trigger_type="scheduled", view="company")
    repo.start(job_id=2, trigger_type="scheduled", view="personal")
    repo.start(job_id=2, trigger_type="scheduled", view="personal")
    items, total = repo.list_for_job(2)
    assert total == 2
    assert all(r.job_id == 2 for r in items)


def test_list_for_job_empty_returns_empty(repo):
    items, total = repo.list_for_job(99999)
    assert items == []
    assert total == 0


# --------------------------------------------------------------------------- #
# latest_for_job                                                              #
# --------------------------------------------------------------------------- #


def test_latest_for_job_returns_most_recent(repo):
    base = datetime(2026, 4, 1, 9, 30, tzinfo=CHINA_TZ)
    repo.start(job_id=1, trigger_type="scheduled", view="company",
               started_at=base)
    rid_latest = repo.start(job_id=1, trigger_type="scheduled", view="company",
                            started_at=base + timedelta(hours=2))
    repo.start(job_id=1, trigger_type="scheduled", view="company",
               started_at=base + timedelta(hours=1))
    latest = repo.latest_for_job(1)
    assert latest is not None
    assert latest.id == rid_latest


def test_latest_for_job_none_when_no_runs(repo):
    assert repo.latest_for_job(1) is None


# --------------------------------------------------------------------------- #
# delete_before (365 天清理)                                                  #
# --------------------------------------------------------------------------- #


def test_delete_before_returns_deleted_ids(repo):
    base = datetime(2026, 4, 1, tzinfo=CHINA_TZ)
    old_ids = []
    for i in range(3):
        rid = repo.start(job_id=1, trigger_type="scheduled", view="company",
                         started_at=base + timedelta(days=i))
        old_ids.append(rid)
    new_ids = []
    for i in range(2):
        rid = repo.start(job_id=1, trigger_type="scheduled", view="company",
                         started_at=base + timedelta(days=400 + i))
        new_ids.append(rid)

    cutoff = base + timedelta(days=10)
    deleted = repo.delete_before(cutoff)
    assert sorted(deleted) == sorted(old_ids)

    # old 全部不在了
    for rid in old_ids:
        assert repo.get(rid) is None
    # new 都在
    for rid in new_ids:
        assert repo.get(rid) is not None


def test_delete_before_empty_returns_empty(repo):
    """没有可删的记录时返回空列表,不报错。"""
    deleted = repo.delete_before(datetime(2020, 1, 1, tzinfo=CHINA_TZ))
    assert deleted == []


def test_delete_before_handles_large_batches(repo):
    """超过 SQLite 999 参数上限时仍能正常删除(分批逻辑)。"""
    base = datetime(2026, 4, 1, tzinfo=CHINA_TZ)
    for i in range(1100):
        repo.start(job_id=1, trigger_type="scheduled", view="company",
                   started_at=base + timedelta(seconds=i))

    cutoff = base + timedelta(days=1)
    deleted = repo.delete_before(cutoff)
    assert len(deleted) == 1100
    items, total = repo.list_for_job(1)
    assert total == 0


# --------------------------------------------------------------------------- #
# cancel + finish guard                                                       #
# --------------------------------------------------------------------------- #


def test_cancel_marks_running_run_as_failed(repo):
    """cancel a running run → status=failed, error stamped."""
    rid = repo.start(job_id=1, trigger_type="manual", view="personal")
    ok = repo.cancel(rid, reason="manually cancelled by admin")
    assert ok is True
    run = repo.get(rid)
    assert run.status == "failed"
    assert run.error == "manually cancelled by admin"
    assert run.finished_at is not None


def test_cancel_returns_false_when_already_finished(repo):
    """cancel a finished run → returns False, original status untouched."""
    rid = repo.start(job_id=1, trigger_type="manual", view="company")
    repo.finish(rid, status="succeeded", rc=0)
    ok = repo.cancel(rid, reason="late cancel attempt")
    assert ok is False
    run = repo.get(rid)
    assert run.status == "succeeded"   # untouched
    # Sanity: cancel reason should NOT have stomped the original error
    assert run.error is None


def test_cancel_returns_false_when_run_does_not_exist(repo):
    """cancel non-existent run id → False (caller distinguishes via get)."""
    assert repo.cancel(99999) is False


def test_cancel_truncates_long_reason(repo):
    rid = repo.start(job_id=1, trigger_type="manual", view="company")
    long_reason = "x" * 300
    repo.cancel(rid, reason=long_reason)
    run = repo.get(rid)
    assert run.error.endswith("…")
    assert len(run.error) <= 201    # 200 + ellipsis


def test_finish_does_not_overwrite_cancelled_state(repo):
    """守卫验证: 如果 run 已被 cancel 标为 failed,迟到的 thread finish()
    不会把它改回 succeeded。"""
    rid = repo.start(job_id=1, trigger_type="manual", view="personal")
    repo.cancel(rid, reason="user cancelled")
    # Simulate the runaway thread eventually completing & calling finish
    repo.finish(rid, status="succeeded", rc=0,
                cards_sent=2, cards_total=2)
    run = repo.get(rid)
    # Cancelled state held — finish was a no-op
    assert run.status == "failed"
    assert run.error == "user cancelled"
    # And the late finish did NOT stamp success metrics either
    assert run.cards_sent is None
    assert run.rc is None
