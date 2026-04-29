"""Time-window computation for the daily report.

Default window: yesterday 09:30 → today 09:30 (Asia/Shanghai),
half-open `[since, until)`. Operators can override via CLI for replay."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from server.daily_report.types import TimeWindow

CHINA_TZ = ZoneInfo("Asia/Shanghai")
_REPORT_START_TIME = time(9, 30)


def compute_window(now: datetime) -> TimeWindow:
    """Default window: from yesterday 09:30 (Asia/Shanghai) to today 09:30.

    `now` should be tz-aware. A naive datetime is assumed to be Asia/Shanghai
    local time (defensive — callers really should pass tz-aware though).
    """
    if now.tzinfo is None:
        now_china = now.replace(tzinfo=CHINA_TZ)
    else:
        now_china = now.astimezone(CHINA_TZ)

    today_930 = now_china.replace(
        hour=_REPORT_START_TIME.hour,
        minute=_REPORT_START_TIME.minute,
        second=0,
        microsecond=0,
    )
    yesterday_930 = today_930 - timedelta(days=1)
    return TimeWindow(since=yesterday_930, until=today_930)


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
