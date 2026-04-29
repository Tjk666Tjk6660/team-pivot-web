"""Time-window computation for the daily report.

Default window: yesterday 09:30 → today 09:30 (Asia/Shanghai),
half-open `[since, until)`. push_hour/minute 和 window_hours 可由 caller
覆盖(runner 从 settings 读 push_time / time_window_hours 后传入)。"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from server.daily_report.types import TimeWindow

CHINA_TZ = ZoneInfo("Asia/Shanghai")
_REPORT_START_TIME = time(9, 30)


def compute_window(
    now: datetime,
    *,
    push_hour: int = 9,
    push_minute: int = 30,
    window_hours: int = 24,
) -> TimeWindow:
    """计算 [since, until) 半开区间。

    - `until` = 距 `now` 最近的、已经过的 push_time 时刻
      · now ≥ 今天的 push_time → until = 今天 push_time
      · now < 今天的 push_time → until = 昨天 push_time(避免窗口包含未来)
    - `since` = `until - window_hours`

    举例:push_time=09:30, window_hours=24
      · now = 今天 14:00 → 窗口 [昨天 09:30, 今天 09:30)
      · now = 今天 08:00 → 窗口 [前天 09:30, 昨天 09:30)

    `now` 期望 tz-aware;naive 视为 Asia/Shanghai。"""
    if now.tzinfo is None:
        now_china = now.replace(tzinfo=CHINA_TZ)
    else:
        now_china = now.astimezone(CHINA_TZ)

    today_target = now_china.replace(
        hour=push_hour, minute=push_minute,
        second=0, microsecond=0,
    )
    until = today_target if now_china >= today_target else today_target - timedelta(days=1)
    since = until - timedelta(hours=window_hours)
    return TimeWindow(since=since, until=until)


def parse_iso_window(since_iso: str, until_iso: str) -> TimeWindow:
    """Parse user-provided --since/--until ISO 8601 strings into a TimeWindow.

    Both must be tz-aware — refusing naive inputs avoids ambiguity in
    cross-timezone replay scenarios. Internally normalized to Asia/Shanghai
    so downstream rendering uses one timezone."""
    since = datetime.fromisoformat(since_iso)
    until = datetime.fromisoformat(until_iso)
    if since.tzinfo is None:
        raise ValueError(
            f"--since must be tz-aware ISO 8601 (e.g. '...+08:00'): {since_iso!r}"
        )
    if until.tzinfo is None:
        raise ValueError(
            f"--until must be tz-aware ISO 8601 (e.g. '...+08:00'): {until_iso!r}"
        )
    if not since < until:
        raise ValueError(
            f"--since must be strictly before --until: {since_iso} >= {until_iso}"
        )
    return TimeWindow(
        since=since.astimezone(CHINA_TZ),
        until=until.astimezone(CHINA_TZ),
    )
