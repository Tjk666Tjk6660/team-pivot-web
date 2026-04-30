"""v2 多任务调度器 — 每分钟扫表 + 状态机驱动。

替代 v0.2 的 `DailyReportScheduler`(单 sleep / 单 job 模型)。

核心循环:
  每 60 秒 poll 一次 jobs_repo.list_due(now):
    对每条 due job:
      1. 检查内存中是否还有 thread 在跑(防止上次 LLM 慢调用未完成)
      2. 判断"漏跑容忍":
         - 漏跑 ≤ 30 分钟 → fire(算"刚刚 fire"的正常情况)
         - 漏跑 > 30 分钟 → 不补跑,发漏跑通知,推到下个周期
      3. fire 在新 thread 跑 runner;线程内根据 rc 决定:
         - 成功 → 清 retry_count,next_run_at = 下个周期
         - 失败 → retry_count++;< 3 次 next_run_at = now + 5 min;
                  ≥ 3 次发失败通知 + 重置 + 下个周期

每天首次 poll 跑一次 365 天 runs 清理(同时 jobs.last_run_id 置 NULL)。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from server.daily_report.jobs_repo import Job, JobsRepo
from server.daily_report.runs_repo import RunsRepo
from server.daily_report.window import CHINA_TZ
from server.notify import Notifier
from server.settings import SettingsRepo

log = logging.getLogger("server.daily_report.job_scheduler")


# 调度参数(保持代码内,不暴露 settings,避免被随意调坏)
POLL_INTERVAL_SEC = 60
MISSED_TOLERANCE_MIN = 30
MAX_RETRY = 3
RETRY_DELAY_MIN = 5
RUNS_RETENTION_DAYS = 365


class JobScheduler:
    """asyncio 后台任务,挂在 FastAPI lifespan 上。"""

    def __init__(
        self,
        *,
        db_path: Path,
        workspace_index_dir_provider: Callable[[], Path],
        jobs_repo: JobsRepo,
        runs_repo: RunsRepo,
        settings: SettingsRepo,
        notifier: Notifier,
    ) -> None:
        self._db_path = db_path
        self._workspace_provider = workspace_index_dir_provider
        self._jobs_repo = jobs_repo
        self._runs_repo = runs_repo
        self._settings = settings
        self._notifier = notifier

        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # job_id → 正在跑的 thread(防止 fire 叠加)
        self._running_threads: dict[int, threading.Thread] = {}
        self._last_cleanup_date: date | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._loop(), name="daily-report-job-scheduler",
        )
        log.info("daily-report job scheduler started (poll=%ds)", POLL_INTERVAL_SEC)

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                log.exception("scheduler task raised on shutdown")
        alive = [tid for tid, t in self._running_threads.items() if t.is_alive()]
        if alive:
            log.info(
                "daily-report scheduler stopping; %d fire thread(s) still "
                "running, letting them finish: %s", len(alive), alive,
            )
        log.info("daily-report job scheduler stopped")

    # ----------------------------------------------------------------- #
    # 主循环                                                            #
    # ----------------------------------------------------------------- #

    async def _loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                now = datetime.now(tz=CHINA_TZ)
                self._poll_and_fire(now)
                self._maybe_cleanup_runs(now)
            except Exception:  # noqa: BLE001
                log.exception("scheduler loop iteration failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=POLL_INTERVAL_SEC,
                )
                return
            except asyncio.TimeoutError:
                continue

    # ----------------------------------------------------------------- #
    # poll + fire                                                       #
    # ----------------------------------------------------------------- #

    def _poll_and_fire(self, now: datetime) -> None:
        due_jobs = self._jobs_repo.list_due(now)
        for job in due_jobs:
            # 防止上一轮 fire 还没完成
            prev = self._running_threads.get(job.id)
            if prev and prev.is_alive():
                log.warning(
                    "job %d still running (last fire), skipping this round",
                    job.id,
                )
                continue
            elif prev:
                # thread 已结束,清理引用
                del self._running_threads[job.id]

            # 漏跑判断
            if job.next_run_at is None:
                continue        # 防御:active 但 next_run_at 为空(异常状态)
            delay_min = (now - job.next_run_at).total_seconds() / 60.0
            if delay_min > MISSED_TOLERANCE_MIN:
                self._handle_missed(job, now)
                continue

            # 在容忍范围内 → 立即 fire
            self._spawn_fire(job, now)

    # ----------------------------------------------------------------- #
    # 漏跑处理                                                          #
    # ----------------------------------------------------------------- #

    def _handle_missed(self, job: Job, now: datetime) -> None:
        """漏跑 > 30min:不补跑,记一条 skipped run,发通知,推到下个周期。"""
        log.warning(
            "job %d (%s) missed by %.1f min; sending alert + skip",
            job.id, job.name,
            (now - job.next_run_at).total_seconds() / 60.0 if job.next_run_at else 0,
        )
        run_id = self._runs_repo.start(
            job_id=job.id, trigger_type="scheduled",
            view=job.view, started_at=now,
        )
        self._runs_repo.finish(
            run_id, status="skipped",
            error=f"missed > {MISSED_TOLERANCE_MIN}min, no makeup",
        )
        next_at = compute_next_run_at(
            now=now, push_time=job.push_time, push_freq=job.push_freq,
        )
        self._jobs_repo.update_after_run(
            job.id,
            last_run_id=run_id, last_status="skipped",
            next_run_at=next_at, retry_count=0,
            last_notified_at=now,
        )
        self._send_miss_alert(job, expected_at=job.next_run_at)

    # ----------------------------------------------------------------- #
    # fire 一个 job(在 thread 里跑 runner)                              #
    # ----------------------------------------------------------------- #

    def _spawn_fire(self, job: Job, fired_at: datetime) -> None:
        # scheduler 在 spawn 前 INSERT running run,thread 完成后 update finish
        # 即使 thread crash 也有 run 记录(可观测)
        trigger = "retry" if job.retry_count > 0 else "scheduled"
        run_id = self._runs_repo.start(
            job_id=job.id, trigger_type=trigger,
            view=job.view, started_at=fired_at,
        )
        thread = threading.Thread(
            target=self._run_one_job_safely,
            args=(job, fired_at, run_id),
            name=f"daily-report-job-{job.id}",
            daemon=True,
        )
        self._running_threads[job.id] = thread
        thread.start()

    def _run_one_job_safely(
        self, job: Job, fired_at: datetime, run_id: int,
    ) -> None:
        """在新 thread 跑 runner。完成后更新 runs + jobs 状态机。"""
        from server.daily_report.runner import run_daily_report_for_job

        try:
            rc, debug = run_daily_report_for_job(
                job=job,
                db_path=self._db_path,
                workspace_index_dir=self._workspace_provider(),
                notifier=self._notifier,
                now=fired_at,
            )
            error = None
            if rc == 0:
                run_status = "succeeded"
            elif rc == 1:
                run_status = "partial"
                error = (debug.get("error") or "partial broadcast")[:200]
            else:
                run_status = "failed"
                error = (debug.get("error") or f"rc={rc}")[:200]
        except Exception as e:  # noqa: BLE001
            log.exception("job %d crashed in fire thread", job.id)
            rc = -1
            run_status = "failed"
            error = f"{type(e).__name__}: {e}"
            debug = {"crashed": True}

        # 写 finish
        finished_at = datetime.now(tz=CHINA_TZ)
        import json as _j
        try:
            debug_json = _j.dumps(debug, ensure_ascii=False, default=str)
        except Exception:
            debug_json = None
        self._runs_repo.finish(
            run_id, finished_at=finished_at, status=run_status, rc=rc,
            cards_sent=(debug.get("receivers") or {}).get("sent"),
            cards_total=(debug.get("receivers") or {}).get("total"),
            error=error, debug_json=debug_json,
        )

        # 更新 jobs 状态机
        if run_status == "succeeded":
            next_at = compute_next_run_at(
                now=finished_at, push_time=job.push_time,
                push_freq=job.push_freq,
            )
            self._jobs_repo.update_after_run(
                job.id,
                last_run_id=run_id, last_status="succeeded",
                next_run_at=next_at, retry_count=0,
            )
            log.info("job %d succeeded; next_run_at=%s",
                     job.id, next_at.isoformat())
        else:
            # 失败 → 重试逻辑
            new_retry = job.retry_count + 1
            if new_retry < MAX_RETRY:
                retry_at = finished_at + timedelta(minutes=RETRY_DELAY_MIN)
                self._jobs_repo.update_after_run(
                    job.id,
                    last_run_id=run_id, last_status=run_status,
                    next_run_at=retry_at, retry_count=new_retry,
                )
                log.warning(
                    "job %d %s (retry %d/%d), retry at %s",
                    job.id, run_status, new_retry, MAX_RETRY,
                    retry_at.isoformat(),
                )
            else:
                # MAX_RETRY 次数后:发通知 + 重置 + 跳到下个周期
                next_at = compute_next_run_at(
                    now=finished_at, push_time=job.push_time,
                    push_freq=job.push_freq,
                )
                self._jobs_repo.update_after_run(
                    job.id,
                    last_run_id=run_id, last_status=run_status,
                    next_run_at=next_at, retry_count=0,
                    last_notified_at=finished_at,
                )
                log.error(
                    "job %d %s after %d retries, sending alert + skip to "
                    "next cycle %s",
                    job.id, run_status, MAX_RETRY, next_at.isoformat(),
                )
                failures = (debug.get("receivers") or {}).get("failures") or []
                self._send_failure_alert(
                    job, error=error or "unknown", failures=failures,
                )

        # 释放 thread tracking
        self._running_threads.pop(job.id, None)

    # ----------------------------------------------------------------- #
    # 通知卡(漏跑 / 失败)                                              #
    # ----------------------------------------------------------------- #

    def _send_miss_alert(self, job: Job, *, expected_at: datetime | None) -> None:
        from server.daily_report.render import build_admin_alert_card

        card = build_admin_alert_card(
            alert_type="missed",
            job_name=job.name,
            job_view=job.view,
            expected_at=expected_at,
        )
        admin_chats, admin_users = _read_admin_notify_targets(self._settings)
        self._notifier.send_admin_alert(
            card, event=f"daily-report miss job={job.id}",
            admin_chat_ids=admin_chats,
            admin_open_ids=admin_users,
        )

    def _send_failure_alert(
        self, job: Job, *, error: str, failures: list[dict] | None = None,
    ) -> None:
        from server.daily_report.render import build_admin_alert_card

        # 把 failures 里的 open_id / chat_id 解成可读名,告警卡更有用
        resolved = self._resolve_failure_names(job, failures or [])

        card = build_admin_alert_card(
            alert_type="failed",
            job_name=job.name,
            job_view=job.view,
            error=error,
            retry_count=MAX_RETRY,
            failures=resolved,
        )
        admin_chats, admin_users = _read_admin_notify_targets(self._settings)
        self._notifier.send_admin_alert(
            card, event=f"daily-report failure job={job.id}",
            admin_chat_ids=admin_chats,
            admin_open_ids=admin_users,
        )

    def _resolve_failure_names(
        self, job: Job, failures: list[dict],
    ) -> list[dict]:
        """把 failures 里 open_id 解成 contacts.name(若是 chat_id 则 best-effort
        从 list_bot_chats 找 chat name)。返回每条加 name 字段后的 list。"""
        if not failures:
            return []
        if job.receiver_type == "users":
            try:
                from server.contacts import ContactRepo
                from server.db import Database
                db = Database(self._db_path)
                contacts = ContactRepo(db)
                ids = [f["to"] for f in failures if f.get("to")]
                name_map = contacts.get_many(ids)
            except Exception:
                log.warning("resolve failure names: contacts lookup failed",
                            exc_info=True)
                name_map = {}
            return [
                {
                    **f,
                    "name": (
                        name_map[f["to"]].name
                        if f.get("to") in name_map
                        else None
                    ),
                }
                for f in failures
            ]
        # groups: best-effort 用 list_bot_chats 名称(失败就不带 name)
        try:
            chats = self._notifier.list_bot_chats()
            chat_name = {c["chat_id"]: c.get("name") for c in chats}
        except Exception:
            chat_name = {}
        return [
            {**f, "name": chat_name.get(f.get("to"))}
            for f in failures
        ]

    # ----------------------------------------------------------------- #
    # 365 天清理(每天首次 poll 跑一次)                                  #
    # ----------------------------------------------------------------- #

    def _maybe_cleanup_runs(self, now: datetime) -> None:
        today = now.date()
        if self._last_cleanup_date == today:
            return
        try:
            cutoff = now - timedelta(days=RUNS_RETENTION_DAYS)
            deleted_ids = self._runs_repo.delete_before(cutoff)
            if deleted_ids:
                # 代码层维护 jobs.last_run_id 引用一致性
                affected = self._jobs_repo.clear_last_run_id_in(deleted_ids)
                log.info(
                    "daily-report runs cleanup: deleted %d run(s) older than "
                    "%d days; cleared %d job last_run_id references",
                    len(deleted_ids), RUNS_RETENTION_DAYS, affected,
                )
        except Exception:  # noqa: BLE001
            log.exception("runs cleanup failed; will retry tomorrow")
        # 不论成功失败,标记今天已尝试,避免本日内重复
        self._last_cleanup_date = today


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


_WEEKDAY_FREQ_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def compute_next_run_at(
    *,
    now: datetime,
    push_time: str,
    push_freq: str,
) -> datetime:
    """计算下一次 fire 时刻。

    支持的 push_freq:
      - 'daily'              每天
      - 'weekdays'           仅 Mon–Fri
      - 'mon' .. 'sun'       仅指定单个 weekday
      - 'month_start'        每月 1 日
      - 'month_end'          每月最后一日(28/29/30/31 自动算)

    通用规则:始终从 (今天 push_time) 起步,若 now 已过则推到明天,
    再按 freq 含义往后推到下一个匹配日。

    坏 push_freq 值兜底为 'daily'(等价于不过滤)。
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=CHINA_TZ)

    h, m = _parse_hhmm(push_time)
    today_target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    candidate = today_target if now < today_target else today_target + timedelta(days=1)

    if push_freq == "daily":
        return candidate
    if push_freq == "weekdays":
        # weekday: 0=Mon ... 5=Sat 6=Sun
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if push_freq in _WEEKDAY_FREQ_MAP:
        target = _WEEKDAY_FREQ_MAP[push_freq]
        while candidate.weekday() != target:
            candidate += timedelta(days=1)
        return candidate
    if push_freq == "month_start":
        # 推到 candidate >= 当月或下一个月的 1 号
        if candidate.day != 1:
            year, month = candidate.year, candidate.month + 1
            if month > 12:
                year += 1
                month = 1
            candidate = candidate.replace(year=year, month=month, day=1)
        return candidate
    if push_freq == "month_end":
        import calendar
        last_day = calendar.monthrange(candidate.year, candidate.month)[1]
        if candidate.day < last_day:
            candidate = candidate.replace(day=last_day)
        # candidate.day == last_day 已是当月末 → 直接返回
        return candidate

    log.warning("compute_next_run_at: unknown push_freq=%r, falling back to daily",
                push_freq)
    return candidate


def _parse_hhmm(s: str) -> tuple[int, int]:
    """坏值兜底 09:30。"""
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 9, 30


def _read_admin_notify_targets(
    settings: SettingsRepo,
) -> tuple[list[str], list[str]]:
    """读 daily_report.admin_notify_chat_ids / admin_notify_open_ids,
    JSON 解析失败则视为空。返回 (chat_ids, open_ids)。"""
    import json as _j

    def _parse(raw: str | None) -> list[str]:
        if not raw or not raw.strip():
            return []
        try:
            v = _j.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []

    chats = _parse(settings.get("daily_report.admin_notify_chat_ids"))
    users = _parse(settings.get("daily_report.admin_notify_open_ids"))
    return chats, users
