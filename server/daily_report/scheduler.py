"""In-process scheduler for the daily report (v0.2).

替代之前的 systemd timer + 一次性脚本方案。优点:
- 部署只动一份 systemd unit(主服务),admin UI / 端点 / 定时跑 一份代码栈
- 状态不用跨进程通信,/api/admin/daily-report/last-run 既看手动跑也看定时跑
- 配置改完即时生效(reload 配置 → next-fire 时计算用新值),无需重装 timer

设计要点:
- 启动:asyncio 后台任务,睡到下一个目标时刻 → fire → 再睡到下一天
- fire:**offload 到 thread**(`run_daily_report` 同步 + LLM 慢调用,1-2 分钟,
  不能阻塞 asyncio loop)
- 停服:`stop()` 唤醒 sleep,scheduler 协程退出;正在跑的 fire 线程让它跑完
  (LLM 调用不能安全 abort)
- 总开关:每次 fire 前检查 `daily_report.enabled`,关闭即跳过(但调度循环不停)

单 worker 假设:Pivot prod 当前是单 uvicorn 进程。多 worker 部署需要 SQLite 时间
戳锁(future work)。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable

from server.daily_report.config_keys import KEY_ENABLED, KEY_PUSH_TIME
from server.daily_report.runner import run_daily_report
from server.daily_report.window import CHINA_TZ
from server.notify import Notifier
from server.settings import SettingsRepo

log = logging.getLogger("server.daily_report.scheduler")

DEFAULT_PUSH_TIME = "09:30"


class DailyReportScheduler:
    """asyncio 后台任务包装。挂在 FastAPI lifespan 上即可。"""

    def __init__(
        self,
        *,
        db_path: Path,
        workspace_index_dir_provider: Callable[[], Path],
        settings: SettingsRepo,
        notifier: Notifier,
    ) -> None:
        self._db_path = db_path
        self._workspace_index_dir_provider = workspace_index_dir_provider
        self._settings = settings
        self._notifier = notifier
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._fire_thread: threading.Thread | None = None

    async def start(self) -> None:
        """开 asyncio 后台调度循环。重复 start 是 no-op。"""
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._loop(), name="daily-report-scheduler",
        )
        log.info("daily-report scheduler started")

    async def stop(self) -> None:
        """优雅停止调度循环。正在跑的 fire 线程不打断。"""
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                log.exception("scheduler task raised on shutdown")
        if self._fire_thread and self._fire_thread.is_alive():
            log.info(
                "daily-report fire thread still running on shutdown — "
                "letting it finish (won't abort LLM call mid-flight)",
            )
        log.info("daily-report scheduler stopped")

    # ------------------------------------------------------------------ #
    # internals                                                          #
    # ------------------------------------------------------------------ #

    async def _loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                next_fire = _next_fire_at(
                    datetime.now(tz=CHINA_TZ),
                    push_time=self._read_push_time(),
                )
                sleep_secs = max(
                    1.0, (next_fire - datetime.now(tz=CHINA_TZ)).total_seconds(),
                )
                log.info(
                    "daily-report scheduler sleeping %.0fs until %s",
                    sleep_secs, next_fire.isoformat(),
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=sleep_secs,
                    )
                    return   # 收到 stop 信号
                except asyncio.TimeoutError:
                    pass     # 时间到,fire

                if self._is_disabled():
                    log.info(
                        "daily-report scheduler fire skipped: %s=0",
                        KEY_ENABLED,
                    )
                    continue

                self._spawn_fire()
            except Exception:  # noqa: BLE001
                # 调度循环本身不能死掉 —— 失败也要进入下一轮 sleep。
                # 极端情况(配置坏、时区 lib 异常)避免日志噪音同时还能恢复。
                log.exception(
                    "daily-report scheduler loop iteration failed; "
                    "sleeping 60s before retry",
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=60.0)
                    return
                except asyncio.TimeoutError:
                    continue

    def _spawn_fire(self) -> None:
        """fire 一次报告。在新 thread 里跑,避免阻塞 asyncio loop。"""
        if self._fire_thread and self._fire_thread.is_alive():
            log.warning(
                "daily-report fire skipped: previous run still in progress",
            )
            return
        self._fire_thread = threading.Thread(
            target=self._run_safely,
            name="daily-report-fire",
            daemon=True,
        )
        self._fire_thread.start()

    def _run_safely(self) -> None:
        try:
            workspace_index_dir = self._workspace_index_dir_provider()
            rc, _debug = run_daily_report(
                db_path=self._db_path,
                workspace_index_dir=workspace_index_dir,
                dry_run=False,
                no_ai=False,
                notifier=self._notifier,
            )
            log.info("daily-report scheduled fire done rc=%d", rc)
        except Exception:  # noqa: BLE001
            log.exception("daily-report scheduled fire crashed")

    def _read_push_time(self) -> time:
        raw = (self._settings.get(KEY_PUSH_TIME) or DEFAULT_PUSH_TIME).strip()
        return _parse_hhmm(raw)

    def _is_disabled(self) -> bool:
        raw = (self._settings.get(KEY_ENABLED) or "1").strip().lower()
        return raw in ("0", "false", "off", "no")


# --------------------------------------------------------------------------- #
# Time math                                                                   #
# --------------------------------------------------------------------------- #


def _parse_hhmm(s: str) -> time:
    """Parse 'HH:MM' (24h, Asia/Shanghai). Bad input → 09:30 默认。"""
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return time(h, m)
    except (ValueError, AttributeError):
        pass
    log.warning("daily-report invalid push_time %r, using 09:30", s)
    return time(9, 30)


def _next_fire_at(now_china: datetime, *, push_time: time) -> datetime:
    """计算下一次 fire 时刻。

    - 若 now < 今天 push_time → 今天 push_time
    - 若 now >= 今天 push_time → 明天 push_time
    - 不补跑(主服务挂了过夜恢复后,直到下一个 push_time 才跑;管理员可在
      /admin 手动触发补一次)
    """
    if now_china.tzinfo is None:
        now_china = now_china.replace(tzinfo=CHINA_TZ)
    today_target = now_china.replace(
        hour=push_time.hour, minute=push_time.minute,
        second=0, microsecond=0,
    )
    if now_china < today_target:
        return today_target
    return today_target + timedelta(days=1)
