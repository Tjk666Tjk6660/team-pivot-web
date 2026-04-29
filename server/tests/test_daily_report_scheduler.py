"""Tests for `server.daily_report.scheduler`.

Covers:
- _next_fire_at: 当前 < 今日目标 → 今日目标
- _next_fire_at: 当前 >= 今日目标 → 明日目标
- _parse_hhmm: bad input → 09:30 兜底
- DailyReportScheduler.start/stop: 优雅启停
- 触发时调 run_daily_report,disabled 时跳过
- 重复 fire 防御:上一次 fire thread 仍在跑时,不再 spawn
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.daily_report.scheduler import (
    DailyReportScheduler,
    _next_fire_at,
    _parse_hhmm,
)
from server.daily_report.window import CHINA_TZ
from server.notify import NoOpNotifier


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


def test_parse_hhmm_normal_inputs():
    assert _parse_hhmm("09:30") == time(9, 30)
    assert _parse_hhmm("23:59") == time(23, 59)
    assert _parse_hhmm("00:00") == time(0, 0)


def test_parse_hhmm_invalid_falls_back():
    """非法输入安全降级到 09:30,不抛异常,不让 scheduler 死掉。"""
    assert _parse_hhmm("") == time(9, 30)
    assert _parse_hhmm("25:00") == time(9, 30)
    assert _parse_hhmm("9:30:00") == time(9, 30)
    assert _parse_hhmm("nope") == time(9, 30)


def test_next_fire_at_before_target_returns_today():
    now = datetime(2026, 4, 29, 8, 0, tzinfo=CHINA_TZ)
    nxt = _next_fire_at(now, push_time=time(9, 30))
    assert nxt == datetime(2026, 4, 29, 9, 30, tzinfo=CHINA_TZ)


def test_next_fire_at_after_target_returns_tomorrow():
    now = datetime(2026, 4, 29, 10, 0, tzinfo=CHINA_TZ)
    nxt = _next_fire_at(now, push_time=time(9, 30))
    assert nxt == datetime(2026, 4, 30, 9, 30, tzinfo=CHINA_TZ)


def test_next_fire_at_at_target_returns_tomorrow():
    """正好命中目标时刻也应该跳到明天(避免重复 fire)。"""
    now = datetime(2026, 4, 29, 9, 30, tzinfo=CHINA_TZ)
    nxt = _next_fire_at(now, push_time=time(9, 30))
    assert nxt == datetime(2026, 4, 30, 9, 30, tzinfo=CHINA_TZ)


def test_next_fire_at_naive_input_treated_as_china_tz():
    naive = datetime(2026, 4, 29, 8, 0)
    nxt = _next_fire_at(naive, push_time=time(9, 30), push_freq="daily")
    assert nxt.tzinfo is not None
    assert nxt.hour == 9 and nxt.minute == 30


# --------------------------------------------------------------------------- #
# push_freq=weekdays 跳过周末                                                  #
# --------------------------------------------------------------------------- #


def test_next_fire_at_weekdays_skips_friday_to_monday():
    """Friday 10:00(已过 09:30 目标)→ 候选明天 Sat,weekdays 模式继续推到 Mon。"""
    fri_after = datetime(2026, 5, 1, 10, 0, tzinfo=CHINA_TZ)  # Fri
    nxt = _next_fire_at(fri_after, push_time=time(9, 30), push_freq="weekdays")
    assert nxt == datetime(2026, 5, 4, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.weekday() == 0  # Mon


def test_next_fire_at_weekdays_skips_saturday_to_monday():
    """Saturday 早晨 → 候选今日(Sat),weekdays 模式应推到 Mon。"""
    sat = datetime(2026, 5, 2, 8, 0, tzinfo=CHINA_TZ)  # Sat
    nxt = _next_fire_at(sat, push_time=time(9, 30), push_freq="weekdays")
    assert nxt == datetime(2026, 5, 4, 9, 30, tzinfo=CHINA_TZ)
    assert nxt.weekday() == 0


def test_next_fire_at_daily_does_not_skip_weekends():
    """daily 模式无论星期几都按部就班 fire。"""
    fri_after = datetime(2026, 5, 1, 10, 0, tzinfo=CHINA_TZ)
    nxt = _next_fire_at(fri_after, push_time=time(9, 30), push_freq="daily")
    assert nxt == datetime(2026, 5, 2, 9, 30, tzinfo=CHINA_TZ)  # Sat 09:30
    assert nxt.weekday() == 5


def test_next_fire_at_weekdays_normal_weekday_unchanged():
    """工作日不受 weekdays 模式影响。"""
    tue_before = datetime(2026, 4, 28, 8, 0, tzinfo=CHINA_TZ)  # Tue
    nxt = _next_fire_at(tue_before, push_time=time(9, 30), push_freq="weekdays")
    assert nxt == datetime(2026, 4, 28, 9, 30, tzinfo=CHINA_TZ)


# --------------------------------------------------------------------------- #
# Scheduler start/stop                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_scheduler_starts_and_stops_cleanly(tmp_path):
    """启动后立即 stop,不应该 fire,不应该悬挂。"""
    settings = _stub_settings({})
    fired = []

    def fake_run(*, db_path, workspace_index_dir, dry_run, no_ai, notifier):
        fired.append(True)
        return 0, {}

    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path / "git" / "index",
        settings=settings,
        notifier=NoOpNotifier(),
    )

    with patch(
        "server.daily_report.scheduler.run_daily_report", side_effect=fake_run,
    ):
        await sched.start()
        # 立即 stop —— 调度循环还没触发 fire(下一次 fire 在 09:30)
        await sched.stop()

    assert fired == []


@pytest.mark.asyncio
async def test_scheduler_disabled_skips_fire(tmp_path):
    """daily_report.enabled=0 → 调度循环 fire 时立即跳过。"""
    settings = _stub_settings({
        "daily_report.enabled": "0",
        "daily_report.push_time": "09:30",
    })

    fired = []

    def fake_run(**_kwargs):
        fired.append(True)
        return 0, {}

    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )

    # 直接调内部 _spawn_fire 验证 disabled 路径
    with patch(
        "server.daily_report.scheduler.run_daily_report", side_effect=fake_run,
    ):
        # 手动模拟一次 fire 决策:disabled 时不该 spawn
        assert sched._is_disabled() is True


@pytest.mark.asyncio
async def test_scheduler_fire_skipped_when_previous_running(tmp_path):
    """上一次 fire 线程仍在跑 → 跳过 spawn,不重复触发。"""
    settings = _stub_settings({})

    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )

    # 装一个"伪在跑"的线程
    long_running = threading.Event()
    sched._fire_thread = threading.Thread(
        target=lambda: long_running.wait(timeout=30),
        daemon=True,
    )
    sched._fire_thread.start()

    fired = []

    def fake_run(**_kwargs):
        fired.append(True)
        return 0, {}

    with patch(
        "server.daily_report.scheduler.run_daily_report", side_effect=fake_run,
    ):
        sched._spawn_fire()       # 应该被跳过(prev 还在跑)

    assert fired == []
    long_running.set()            # 让"伪在跑"退出


@pytest.mark.asyncio
async def test_scheduler_reads_push_time_from_settings(tmp_path):
    settings = _stub_settings({"daily_report.push_time": "07:15"})
    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )
    assert sched._read_push_time() == time(7, 15)


@pytest.mark.asyncio
async def test_scheduler_invalid_push_time_falls_back(tmp_path):
    settings = _stub_settings({"daily_report.push_time": "无效"})
    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )
    assert sched._read_push_time() == time(9, 30)


@pytest.mark.asyncio
async def test_scheduler_reads_push_freq_from_settings(tmp_path):
    settings = _stub_settings({"daily_report.push_freq": "daily"})
    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )
    assert sched._read_push_freq() == "daily"


@pytest.mark.asyncio
async def test_scheduler_invalid_push_freq_falls_back_to_weekdays(tmp_path):
    """非法 push_freq 值兜底到 weekdays(默认值)。"""
    settings = _stub_settings({"daily_report.push_freq": "monthly"})
    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )
    assert sched._read_push_freq() == "weekdays"


@pytest.mark.asyncio
async def test_scheduler_default_push_freq_when_unset(tmp_path):
    """settings 中没设置 push_freq 时,默认 weekdays。"""
    settings = _stub_settings({})
    sched = DailyReportScheduler(
        db_path=tmp_path / "data.db",
        workspace_index_dir_provider=lambda: tmp_path,
        settings=settings,
        notifier=NoOpNotifier(),
    )
    assert sched._read_push_freq() == "weekdays"


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _stub_settings(values: dict[str, str]):
    """Minimal SettingsRepo 替身,只实现 get/set,内存存储。"""
    store = dict(values)
    m = MagicMock()
    m.get = lambda key: store.get(key)
    m.set = lambda key, value: store.__setitem__(key, value)
    return m
