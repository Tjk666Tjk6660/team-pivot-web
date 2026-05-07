"""Tests for `server.daily_report.job_scheduler.JobScheduler` 状态机。

覆盖:
- compute_next_run_at:weekdays 跳周末 / daily 不跳
- _poll_and_fire:成功 / 失败重试 / 失败到上限发通知 / 漏跑 ≤30min 立即补 / 漏跑 >30min 通知
- 365 天清理 + 同步 jobs.last_run_id 置 NULL
- 启停优雅
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.daily_report.job_scheduler import (
    JobScheduler,
    MAX_RETRY,
    MISSED_TOLERANCE_MIN,
    RETRY_DELAY_MIN,
    RUNS_RETENTION_DAYS,
    compute_next_run_at,
)
from server.daily_report.jobs_repo import JobsRepo
from server.daily_report.runs_repo import RunsRepo
from server.daily_report.window import CHINA_TZ
from server.db import Database
from server.notify import NoOpNotifier
from server.settings import SettingsRepo


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / "test.db")
    return {
        "db": db,
        "jobs": JobsRepo(db),
        "runs": RunsRepo(db),
        "settings": SettingsRepo(db),
        "tmp_path": tmp_path,
    }


def _make_scheduler(setup, **overrides):
    return JobScheduler(
        db_path=setup["tmp_path"] / "test.db",
        workspace_index_dir_provider=lambda: setup["tmp_path"] / "ws",
        jobs_repo=setup["jobs"],
        runs_repo=setup["runs"],
        settings=setup["settings"],
        notifier=overrides.get("notifier", NoOpNotifier()),
    )


# --------------------------------------------------------------------------- #
# compute_next_run_at                                                         #
# --------------------------------------------------------------------------- #


def test_compute_next_run_at_weekdays_normal():
    # Tuesday 08:00 → today 09:30
    now = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=now, push_time="09:30", push_freq="weekdays")
    assert nxt == datetime(2026, 4, 28, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_weekdays_friday_after():
    # Friday 10:00 → 候选 Sat 09:30 → 跳到 Mon 09:30
    fri_after = datetime(2026, 5, 1, 10, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=fri_after, push_time="09:30", push_freq="weekdays")
    assert nxt == datetime(2026, 5, 4, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.weekday() == 0


def test_compute_next_run_at_daily_does_not_skip():
    fri_after = datetime(2026, 5, 1, 10, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=fri_after, push_time="09:30", push_freq="daily")
    assert nxt == datetime(2026, 5, 2, 9, 30, tzinfo=CHINA_TZ)  # Sat


def test_compute_next_run_at_invalid_push_time_falls_back():
    now = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=now, push_time="bad", push_freq="weekdays")
    assert nxt == datetime(2026, 4, 28, 9, 30, tzinfo=CHINA_TZ)  # 兜底 09:30


# 2026-04-28 = Tuesday, 04-29 = Wed, ..., 05-01 = Fri, 05-02 = Sat, 05-03 = Sun, 05-04 = Mon


def test_compute_next_run_at_specific_weekday_today():
    """周二 08:00 + freq=tue → 当天 09:30"""
    tue = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=tue, push_time="09:30", push_freq="tue")
    assert nxt == datetime(2026, 4, 28, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_specific_weekday_after_today():
    """周二 10:00 + freq=tue → 下周二 09:30"""
    tue_after = datetime(2026, 4, 28, 10, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=tue_after, push_time="09:30", push_freq="tue")
    assert nxt == datetime(2026, 5, 5, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_specific_weekday_friday_jumps_to_next_friday():
    """周一 → freq=fri 应该跳到本周五"""
    mon = datetime(2026, 4, 27, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=mon, push_time="09:30", push_freq="fri")
    assert nxt == datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.weekday() == 4


def test_compute_next_run_at_sunday_freq_sun():
    """已是周日 08:00 + freq=sun → 当天 09:30"""
    sun = datetime(2026, 5, 3, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=sun, push_time="09:30", push_freq="sun")
    assert nxt == datetime(2026, 5, 3, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.weekday() == 6


def test_compute_next_run_at_month_start_before_first():
    """4 月 28 日 → 下一次 month_start = 5 月 1 日"""
    apr28 = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=apr28, push_time="09:30", push_freq="month_start")
    assert nxt == datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.day == 1


def test_compute_next_run_at_month_start_on_first_before_time():
    """5 月 1 日 08:00 → 5 月 1 日 09:30(同一天还没到点)"""
    may1 = datetime(2026, 5, 1, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=may1, push_time="09:30", push_freq="month_start")
    assert nxt == datetime(2026, 5, 1, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_start_on_first_after_time():
    """5 月 1 日 10:00 → 6 月 1 日 09:30"""
    may1_after = datetime(2026, 5, 1, 10, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=may1_after, push_time="09:30", push_freq="month_start")
    assert nxt == datetime(2026, 6, 1, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_start_year_rollover():
    """12 月 15 日 → 1 月 1 日(年度跨越)"""
    dec15 = datetime(2026, 12, 15, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=dec15, push_time="09:30", push_freq="month_start")
    assert nxt == datetime(2027, 1, 1, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_end_april():
    """4 月 28 → 4 月 30(4 月 30 天)"""
    apr28 = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=apr28, push_time="09:30", push_freq="month_end")
    assert nxt == datetime(2026, 4, 30, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_end_jan_31():
    """1 月 5 → 1 月 31 日(31 天大月)"""
    jan5 = datetime(2026, 1, 5, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=jan5, push_time="09:30", push_freq="month_end")
    assert nxt == datetime(2026, 1, 31, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_end_feb_leap():
    """闰年 2024 年 2 月 → 2/29"""
    feb5 = datetime(2024, 2, 5, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=feb5, push_time="09:30", push_freq="month_end")
    assert nxt == datetime(2024, 2, 29, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_end_feb_non_leap():
    """非闰年 2026 年 2 月 → 2/28"""
    feb5 = datetime(2026, 2, 5, 8, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=feb5, push_time="09:30", push_freq="month_end")
    assert nxt == datetime(2026, 2, 28, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_month_end_already_last_day_after_time():
    """4 月 30 11:00(已过 09:30)→ 5 月 31"""
    apr30_after = datetime(2026, 4, 30, 11, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=apr30_after, push_time="09:30", push_freq="month_end")
    assert nxt == datetime(2026, 5, 31, 9, 30, tzinfo=CHINA_TZ)


def test_compute_next_run_at_unknown_freq_falls_back_to_daily():
    """未知 freq → 当 daily 处理"""
    now = datetime(2026, 4, 28, 10, 0, tzinfo=CHINA_TZ)
    nxt = compute_next_run_at(now=now, push_time="09:30", push_freq="bogus")
    assert nxt == datetime(2026, 4, 29, 9, 30, tzinfo=CHINA_TZ)


# --------------------------------------------------------------------------- #
# _poll_and_fire 状态机                                                       #
# --------------------------------------------------------------------------- #


def _create_due_job(setup, *, view="company", retry_count=0,
                    next_run_at_offset_min=-5):
    """创建一条 next_run_at 在 now 前 N 分钟的 active job(默认刚 due 5 分钟)。"""
    now = datetime.now(tz=CHINA_TZ)
    job = setup["jobs"].create(
        name=f"test-{view}",
        view=view,
        push_time="09:30",
        receiver_type="groups",
        next_run_at=now + timedelta(minutes=next_run_at_offset_min),
    )
    if retry_count:
        setup["jobs"].update_after_run(
            job.id, last_run_id=0, last_status="failed",
            next_run_at=job.next_run_at, retry_count=retry_count,
        )
    return job


def test_poll_and_fire_success_clears_retry_and_sets_next_cycle(setup):
    """成功 fire → retry_count=0,next_run_at 推到下个周期。"""
    sched = _make_scheduler(setup)
    job = _create_due_job(setup)

    # mock runner 返回 success
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, {"receivers": {"sent": 2, "total": 2}}),
    ):
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))
        # 等 thread 完成
        thread = sched._running_threads.get(job.id)
        if thread:
            thread.join(timeout=5)

    # 验证 jobs 状态
    fetched = setup["jobs"].get(job.id)
    assert fetched.last_status == "succeeded"
    assert fetched.retry_count == 0
    assert fetched.next_run_at > datetime.now(tz=CHINA_TZ)  # 推到未来

    # 验证 runs 表
    runs, total = setup["runs"].list_for_job(job.id)
    assert total == 1
    assert runs[0].status == "succeeded"
    assert runs[0].rc == 0


def test_poll_and_fire_failure_first_two_times_retries_in_5min(setup):
    """失败 → retry_count++,next_run_at = now+5min(重试)。"""
    sched = _make_scheduler(setup)
    job = _create_due_job(setup)

    # mock runner 返回 fail
    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(2, {"error": "ai timeout"}),
    ):
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))
        thread = sched._running_threads.get(job.id)
        if thread:
            thread.join(timeout=5)

    fetched = setup["jobs"].get(job.id)
    assert fetched.last_status == "failed"
    assert fetched.retry_count == 1
    # next_run_at ≈ now + 5min(允许 30 秒误差)
    expected = datetime.now(tz=CHINA_TZ) + timedelta(minutes=RETRY_DELAY_MIN)
    diff = abs((fetched.next_run_at - expected).total_seconds())
    assert diff < 30


def test_poll_and_fire_failure_third_time_sends_alert_and_skips(setup):
    """已 retry_count=2 时再 fail → 触发通知 + 重置 + 跳到下个周期。"""
    notifier = MagicMock()
    sched = _make_scheduler(setup, notifier=notifier)
    job = _create_due_job(setup, retry_count=MAX_RETRY - 1)  # 已经重试 2 次

    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(2, {"error": "still failing"}),
    ):
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))
        thread = sched._running_threads.get(job.id)
        if thread:
            thread.join(timeout=5)

    fetched = setup["jobs"].get(job.id)
    # retry_count 已重置
    assert fetched.retry_count == 0
    # next_run_at 推到下个周期(明天 09:30)
    expected_next = compute_next_run_at(
        now=datetime.now(tz=CHINA_TZ),
        push_time=job.push_time, push_freq=job.push_freq,
    )
    diff = abs((fetched.next_run_at - expected_next).total_seconds())
    assert diff < 60
    # last_notified_at 已设
    assert fetched.last_notified_at is not None
    # 失败通知被发送(send_admin_alert 调用过)
    notifier.send_admin_alert.assert_called_once()


def test_poll_and_fire_missed_within_tolerance_fires_normally(setup):
    """漏跑 < 30 min:作为正常 fire 处理(不发漏跑通知)。"""
    notifier = MagicMock()
    sched = _make_scheduler(setup, notifier=notifier)
    # next_run_at 在 20 分钟前(< 30 min 容忍)
    job = _create_due_job(setup, next_run_at_offset_min=-20)

    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, {"receivers": {"sent": 2, "total": 2}}),
    ):
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))
        thread = sched._running_threads.get(job.id)
        if thread:
            thread.join(timeout=5)

    # 没有发漏跑通知
    notifier.send_admin_alert.assert_not_called()
    # 正常 succeeded
    runs, _ = setup["runs"].list_for_job(job.id)
    assert runs[0].status == "succeeded"


def test_poll_and_fire_missed_beyond_tolerance_alerts_and_skips(setup):
    """漏跑 > 30 min:不补跑,发漏跑通知,推下个周期,记 skipped run。"""
    notifier = MagicMock()
    sched = _make_scheduler(setup, notifier=notifier)
    # next_run_at 在 60 分钟前(> 30 min 容忍)
    job = _create_due_job(setup, next_run_at_offset_min=-60)

    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
        return_value=(0, {}),  # 不应被调用
    ) as mock_runner:
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))

    # runner 没被调
    mock_runner.assert_not_called()
    # 发了漏跑通知
    notifier.send_admin_alert.assert_called_once()

    # 一条 skipped run
    runs, total = setup["runs"].list_for_job(job.id)
    assert total == 1
    assert runs[0].status == "skipped"

    # next_run_at 推到下个周期
    fetched = setup["jobs"].get(job.id)
    assert fetched.last_status == "skipped"
    assert fetched.retry_count == 0
    assert fetched.last_notified_at is not None


def test_poll_and_fire_skips_job_with_thread_still_running(setup):
    """上轮 fire 还在跑时,本轮不重复 fire(防止 LLM 调用叠加)。"""
    sched = _make_scheduler(setup)
    job = _create_due_job(setup)

    # 模拟"上次 fire 仍在跑"
    import threading
    blocker = threading.Event()
    fake_thread = threading.Thread(target=blocker.wait, daemon=True)
    fake_thread.start()
    sched._running_threads[job.id] = fake_thread

    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
    ) as mock_runner:
        sched._poll_and_fire(datetime.now(tz=CHINA_TZ))

    # 跳过,runner 没被调
    mock_runner.assert_not_called()
    blocker.set()  # 让 fake thread 退出
    fake_thread.join(timeout=2)


def test_poll_and_fire_paused_job_not_picked(setup):
    """status='paused' 的 job 即使 next_run_at 过期也不被 fire。"""
    sched = _make_scheduler(setup)
    now = datetime.now(tz=CHINA_TZ)
    job = setup["jobs"].create(
        name="paused", view="company", push_time="09:30", receiver_type="groups",
        next_run_at=now - timedelta(hours=1),
        status="paused",
    )

    with patch(
        "server.daily_report.runner.run_daily_report_for_job",
    ) as mock_runner:
        sched._poll_and_fire(now)

    mock_runner.assert_not_called()
    runs, total = setup["runs"].list_for_job(job.id)
    assert total == 0


# --------------------------------------------------------------------------- #
# 365 天清理                                                                  #
# --------------------------------------------------------------------------- #


def test_cleanup_runs_deletes_old_and_clears_jobs_last_run_id(setup):
    sched = _make_scheduler(setup)
    job = setup["jobs"].create(
        name="x", view="company", push_time="09:30", receiver_type="groups",
    )
    # 一条老 run(超 365 天)+ 一条新 run
    base = datetime.now(tz=CHINA_TZ)
    old_run_id = setup["runs"].start(
        job_id=job.id, trigger_type="scheduled",
        view="company", started_at=base - timedelta(days=400),
    )
    new_run_id = setup["runs"].start(
        job_id=job.id, trigger_type="scheduled",
        view="company", started_at=base - timedelta(days=10),
    )
    # 把 jobs.last_run_id 设成 old_run_id(模拟该 job 上次 run 是已过期的)
    setup["jobs"].update_after_run(
        job.id, last_run_id=old_run_id, last_status="succeeded",
        next_run_at=base + timedelta(days=1), retry_count=0,
    )
    assert setup["jobs"].get(job.id).last_run_id == old_run_id

    # 跑清理
    sched._maybe_cleanup_runs(base)

    # 老 run 被删
    assert setup["runs"].get(old_run_id) is None
    # 新 run 还在
    assert setup["runs"].get(new_run_id) is not None
    # jobs.last_run_id 被置 NULL
    assert setup["jobs"].get(job.id).last_run_id is None


def test_cleanup_runs_only_runs_once_per_day(setup):
    sched = _make_scheduler(setup)
    base = datetime.now(tz=CHINA_TZ)
    setup["runs"].start(
        job_id=1, trigger_type="scheduled", view="company",
        started_at=base - timedelta(days=400),
    )
    sched._maybe_cleanup_runs(base)
    # 标记为今日已清,第二次调用不再清(但即使再清也无害,这里只验证幂等)
    assert sched._last_cleanup_date == base.date()
    # 二次 poll 同一天不重复清(可通过 mock 验证 delete_before 调用次数)
    with patch.object(setup["runs"], "delete_before", return_value=[]) as mock:
        sched._maybe_cleanup_runs(base)
        mock.assert_not_called()


# --------------------------------------------------------------------------- #
# 启停                                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_scheduler_start_stop_cleanly(setup):
    sched = _make_scheduler(setup)
    await sched.start()
    await sched.stop()
    # 没有异常即可,任务无 due 不会真 fire
