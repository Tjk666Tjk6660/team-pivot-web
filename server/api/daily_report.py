"""Admin API for the daily report (v0.2 / Phase 5).

Endpoints (all behind require_admin + cookie-only auth):
  GET  /api/admin/daily-report/config     读取配置
  PUT  /api/admin/daily-report/config     写配置
  POST /api/admin/daily-report/trigger    手动触发一次(异步,后台 thread)
  GET  /api/admin/daily-report/last-run   读最近一次运行结果

dengke #012 主张:配置驱动 + 行动优先。配置项默认值由 runner / config_keys
内置,这里只暴露 PUT / GET 让 admin UI 调。

手动触发 → 后台 thread,立即返回 202,避免浏览器对 LLM 慢调用超时。
last-run 端点供 UI 轮询查看结果。"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.daily_report.config_keys import (
    KEY_COMPANY_ENABLED,
    KEY_ENABLED,
    KEY_PERSONAL_ENABLED,
    KEY_PUSH_FREQ,
    KEY_PUSH_TIME,
    KEY_TIME_WINDOW_HOURS,
)
from server.daily_report.runner import run_daily_report
from server.notify import Notifier
from server.pivot_users import PivotUser
from server.settings import SettingsRepo
from server.workspace_runtime import WorkspaceRuntime

log = logging.getLogger("server.api.daily_report")


# --------------------------------------------------------------------------- #
# Pydantic models                                                             #
# --------------------------------------------------------------------------- #


class DailyReportConfig(BaseModel):
    enabled: bool = True
    company_enabled: bool = True
    personal_enabled: bool = True
    time_window_hours: int = Field(default=24, ge=1, le=168)
    push_time: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="每日定时推送时刻 HH:MM (Asia/Shanghai)",
    )
    push_freq: Literal["daily", "weekdays"] = "weekdays"


class TriggerRequest(BaseModel):
    """手动触发 body 可选 dry_run / no_ai 用于测试。"""
    dry_run: bool = False
    no_ai: bool = False


class TriggerResponse(BaseModel):
    ok: bool
    run_id: str
    started_at: str


class LastRunResponse(BaseModel):
    run_id: str | None
    started_at: str | None
    finished_at: str | None
    rc: int | None
    debug: dict | None
    error: str | None


# --------------------------------------------------------------------------- #
# Module-level last-run state (singleton)                                     #
# --------------------------------------------------------------------------- #


_last_run_lock = threading.Lock()
_last_run: dict[str, Any] = {
    "run_id": None,
    "started_at": None,
    "finished_at": None,
    "rc": None,
    "debug": None,
    "error": None,
}


def _set_last_run(**kwargs) -> None:
    with _last_run_lock:
        _last_run.update(kwargs)


def _get_last_run() -> dict[str, Any]:
    with _last_run_lock:
        return dict(_last_run)


# --------------------------------------------------------------------------- #
# Router                                                                      #
# --------------------------------------------------------------------------- #


def build_router(
    workspace: WorkspaceRuntime,
    settings: SettingsRepo,
    notifier: Notifier,
    db_path: Path,
    admin_user_cookie_only: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/daily-report")

    # ------------------ config: GET / PUT ------------------ #

    @router.get("/config")
    def get_config(_: PivotUser = Depends(admin_user_cookie_only)) -> DailyReportConfig:
        return DailyReportConfig(
            enabled=_read_bool(settings, KEY_ENABLED, default=True),
            company_enabled=_read_bool(settings, KEY_COMPANY_ENABLED, default=True),
            personal_enabled=_read_bool(settings, KEY_PERSONAL_ENABLED, default=True),
            time_window_hours=_read_int(settings, KEY_TIME_WINDOW_HOURS, default=24),
            push_time=(settings.get(KEY_PUSH_TIME) or "09:30").strip() or "09:30",
            push_freq=_read_push_freq(settings),
        )

    @router.put("/config")
    def put_config(
        body: DailyReportConfig,
        _: PivotUser = Depends(admin_user_cookie_only),
    ):
        settings.set(KEY_ENABLED, "1" if body.enabled else "0")
        settings.set(KEY_COMPANY_ENABLED, "1" if body.company_enabled else "0")
        settings.set(KEY_PERSONAL_ENABLED, "1" if body.personal_enabled else "0")
        settings.set(KEY_TIME_WINDOW_HOURS, str(body.time_window_hours))
        settings.set(KEY_PUSH_TIME, body.push_time)
        settings.set(KEY_PUSH_FREQ, body.push_freq)
        return {"ok": True}

    # ------------------ trigger: POST ---------------------- #

    @router.post("/trigger")
    def trigger(
        body: TriggerRequest,
        _: PivotUser = Depends(admin_user_cookie_only),
    ) -> TriggerResponse:
        if not _read_bool(settings, KEY_ENABLED, default=True):
            raise HTTPException(
                status_code=409,
                detail="daily_report disabled — flip enabled=true to allow trigger",
            )

        run_id = f"run-{int(time.time() * 1000)}"
        started_at = datetime.now().isoformat()
        _set_last_run(
            run_id=run_id,
            started_at=started_at,
            finished_at=None,
            rc=None,
            debug=None,
            error=None,
        )

        index_dir = workspace.path / "index"

        thread = threading.Thread(
            target=_run_in_thread,
            kwargs=dict(
                run_id=run_id,
                db_path=db_path,
                workspace_index_dir=index_dir,
                dry_run=body.dry_run,
                no_ai=body.no_ai,
                notifier=notifier,
            ),
            name=f"daily-report-{run_id}",
            daemon=True,
        )
        thread.start()

        return TriggerResponse(
            ok=True, run_id=run_id, started_at=started_at,
        )

    # ------------------ last-run: GET ---------------------- #

    @router.get("/last-run")
    def last_run(
        _: PivotUser = Depends(admin_user_cookie_only),
    ) -> LastRunResponse:
        return LastRunResponse(**_get_last_run())

    return router


# --------------------------------------------------------------------------- #
# Background runner                                                           #
# --------------------------------------------------------------------------- #


def _run_in_thread(
    *,
    run_id: str,
    db_path: Path,
    workspace_index_dir: Path,
    dry_run: bool,
    no_ai: bool,
    notifier: Notifier,
) -> None:
    """Threaded wrapper — never raises into the caller's thread; updates
    `_last_run` so the GET /last-run endpoint can show the result."""
    try:
        rc, debug = run_daily_report(
            db_path=db_path,
            workspace_index_dir=workspace_index_dir,
            dry_run=dry_run,
            no_ai=no_ai,
            notifier=notifier,
        )
        _set_last_run(
            finished_at=datetime.now().isoformat(),
            rc=rc,
            debug=debug,
            error=None,
        )
        log.info("daily-report manual trigger done run_id=%s rc=%d", run_id, rc)
    except Exception as e:  # noqa: BLE001
        log.exception("daily-report manual trigger crashed run_id=%s", run_id)
        _set_last_run(
            finished_at=datetime.now().isoformat(),
            rc=-1,
            debug=None,
            error=f"{type(e).__name__}: {e}",
        )


# --------------------------------------------------------------------------- #
# Settings helpers                                                            #
# --------------------------------------------------------------------------- #


def _read_bool(settings: SettingsRepo, key: str, *, default: bool) -> bool:
    raw = settings.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def _read_int(settings: SettingsRepo, key: str, *, default: int) -> int:
    raw = settings.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _read_push_freq(settings: SettingsRepo) -> Literal["daily", "weekdays"]:
    """读 push_freq,坏值兜底到默认 weekdays。"""
    raw = (settings.get(KEY_PUSH_FREQ) or "weekdays").strip().lower()
    return "daily" if raw == "daily" else "weekdays"
