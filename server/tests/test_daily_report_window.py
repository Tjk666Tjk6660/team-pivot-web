"""Tests for `server.daily_report.window`."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server.daily_report.types import TimeWindow
from server.daily_report.window import (
    CHINA_TZ,
    compute_window,
    parse_iso_window,
)


# --------------------------------------------------------------------------- #
# compute_window                                                              #
# --------------------------------------------------------------------------- #


def test_compute_window_at_trigger_time():
    """触发点正好 09:30:00 → 昨天 09:30 ~ 今天 09:30。"""
    now = datetime(2026, 4, 27, 9, 30, 0, tzinfo=CHINA_TZ)
    w = compute_window(now)
    assert w.since == datetime(2026, 4, 26, 9, 30, 0, tzinfo=CHINA_TZ)
    assert w.until == datetime(2026, 4, 27, 9, 30, 0, tzinfo=CHINA_TZ)


def test_compute_window_slightly_after_trigger():
    """09:31:12 触发(systemd timer accuracy 抖动)→ 仍是昨天 09:30 → 今天 09:30。
    边界对齐到 09:30 整,微秒/秒被清零。"""
    now = datetime(2026, 4, 27, 9, 31, 12, 999, tzinfo=CHINA_TZ)
    w = compute_window(now)
    assert w.since == datetime(2026, 4, 26, 9, 30, 0, tzinfo=CHINA_TZ)
    assert w.until == datetime(2026, 4, 27, 9, 30, 0, tzinfo=CHINA_TZ)


def test_compute_window_naive_datetime_assumed_china():
    """无 tz 输入按 Asia/Shanghai 处理(防御性兜底)。"""
    now = datetime(2026, 4, 27, 9, 30, 0)
    w = compute_window(now)
    assert w.since.tzinfo is not None
    assert w.since.utcoffset().total_seconds() == 8 * 3600


def test_compute_window_cross_month():
    """5-1 09:30 → 4-30 09:30 ~ 5-1 09:30。"""
    now = datetime(2026, 5, 1, 9, 30, 0, tzinfo=CHINA_TZ)
    w = compute_window(now)
    assert w.since.month == 4 and w.since.day == 30
    assert w.until.month == 5 and w.until.day == 1


def test_compute_window_cross_year():
    """元旦 09:30 → 跨年。"""
    now = datetime(2027, 1, 1, 9, 30, 0, tzinfo=CHINA_TZ)
    w = compute_window(now)
    assert w.since == datetime(2026, 12, 31, 9, 30, 0, tzinfo=CHINA_TZ)
    assert w.until == datetime(2027, 1, 1, 9, 30, 0, tzinfo=CHINA_TZ)


def test_compute_window_leap_day():
    """3-1 09:30 in leap year → 2-29 09:30。"""
    now = datetime(2024, 3, 1, 9, 30, 0, tzinfo=CHINA_TZ)
    w = compute_window(now)
    assert w.since == datetime(2024, 2, 29, 9, 30, 0, tzinfo=CHINA_TZ)


def test_compute_window_input_in_other_tz_normalized():
    """输入 UTC 时间会先转 Asia/Shanghai 再推算。
    UTC 01:30 == 北京 09:30。"""
    now_utc = datetime(2026, 4, 27, 1, 30, 0, tzinfo=ZoneInfo("UTC"))
    w = compute_window(now_utc)
    assert w.since == datetime(2026, 4, 26, 9, 30, 0, tzinfo=CHINA_TZ)
    assert w.until == datetime(2026, 4, 27, 9, 30, 0, tzinfo=CHINA_TZ)


# --------------------------------------------------------------------------- #
# TimeWindow properties                                                       #
# --------------------------------------------------------------------------- #


def test_window_label_uses_since_date():
    """卡片 header 用 since(覆盖日期)的 month-day。"""
    w = TimeWindow(
        since=datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ),
    )
    assert w.label == "4-26"


def test_window_date_iso():
    w = TimeWindow(
        since=datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ),
    )
    assert w.date_iso == "2026-04-26"


# --------------------------------------------------------------------------- #
# parse_iso_window                                                            #
# --------------------------------------------------------------------------- #


def test_parse_iso_window_happy():
    w = parse_iso_window(
        "2026-04-26T09:30:00+08:00",
        "2026-04-27T09:30:00+08:00",
    )
    assert w.since == datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ)
    assert w.until == datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ)


def test_parse_iso_window_rejects_naive():
    """无 tz 输入直接报错——避免跨时区误用。"""
    with pytest.raises(ValueError, match="tz-aware"):
        parse_iso_window("2026-04-26T09:30:00", "2026-04-27T09:30:00")


def test_parse_iso_window_rejects_naive_until():
    """until 无 tz 也报错(不仅检查 since)。"""
    with pytest.raises(ValueError, match="tz-aware"):
        parse_iso_window(
            "2026-04-26T09:30:00+08:00",
            "2026-04-27T09:30:00",
        )


def test_parse_iso_window_rejects_inverted_range():
    """since >= until 直接报错。"""
    with pytest.raises(ValueError, match="strictly before"):
        parse_iso_window(
            "2026-04-27T09:30:00+08:00",
            "2026-04-26T09:30:00+08:00",
        )


def test_parse_iso_window_rejects_zero_range():
    """since == until 也属于无效。"""
    with pytest.raises(ValueError, match="strictly before"):
        parse_iso_window(
            "2026-04-27T09:30:00+08:00",
            "2026-04-27T09:30:00+08:00",
        )


def test_parse_iso_window_normalizes_to_china_tz():
    """传 UTC 输入,内部统一转 Asia/Shanghai(同一时刻不同表示)。"""
    w = parse_iso_window(
        "2026-04-26T01:30:00+00:00",
        "2026-04-27T01:30:00+00:00",
    )
    assert w.since.utcoffset().total_seconds() == 8 * 3600
    assert w.since.hour == 9 and w.since.minute == 30
    assert w.until.hour == 9 and w.until.minute == 30
