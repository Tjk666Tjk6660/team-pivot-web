"""v2 多任务管理 admin API。

端点(全部前缀 /api/admin/daily-report,需 admin + cookie 鉴权):

  GET    /jobs                     列出 jobs(默认过滤 archived)
  POST   /jobs                     创建 job
  GET    /jobs/{id}                单条详情
  PUT    /jobs/{id}                部分更新配置
  PUT    /jobs/{id}/status         切换 active / paused / archived
  DELETE /jobs/{id}                软删(等同于 status=archived)
  POST   /jobs/{id}/run-now        立即跑该 job 一次(后台 thread)
  GET    /jobs/{id}/runs           分页历史(time desc)
  GET    /runs/{run_id}            单条 run 详情(含 debug_json)
  POST   /manual-trigger           不绑 job 的一次性触发
  GET    /admin-notify             读 admin 通知接收人配置
  PUT    /admin-notify             写 admin 通知接收人配置
  GET    /feishu-chats             列出 bot 所在的飞书群(给 UI 选群用)

约定:
- 所有时间戳 ISO 8601 字符串(Asia/Shanghai)
- run-now / manual-trigger 走后台 thread,立即返回 run_id;前端通过
  GET /runs/{id} 轮询状态
- 配置改了(push_time/push_freq)同时重算 next_run_at(如 status=active)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server.auth.admin import require_admin
from server.daily_report.job_scheduler import compute_next_run_at
from server.daily_report.jobs_repo import Job, JobsRepo, _UNSET
from server.daily_report.runs_repo import Run, RunsRepo
from server.daily_report.types import TimeWindow
from server.daily_report.window import CHINA_TZ
from server.notify import Notifier
from server.settings import SettingsRepo
from server.users import User
from server.workspace_runtime import WorkspaceRuntime

log = logging.getLogger("server.api.daily_report_v2")

KEY_ADMIN_NOTIFY_CHAT_IDS = "daily_report.admin_notify_chat_ids"
KEY_ADMIN_NOTIFY_OPEN_IDS = "daily_report.admin_notify_open_ids"


# --------------------------------------------------------------------------- #
# Pydantic models                                                             #
# --------------------------------------------------------------------------- #


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


_PushFreqLiteral = Literal[
    "daily", "weekdays",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "month_start", "month_end",
]


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    view: Literal["company", "personal"]
    push_time: str = Field(pattern=_HHMM)
    push_freq: _PushFreqLiteral = "weekdays"
    window_hours: int = Field(default=24, ge=1, le=168)
    receiver_type: Literal["groups", "users"]
    receiver_ids: list[str] | None = None
    status: Literal["active", "paused"] = "active"


class JobUpdateIn(BaseModel):
    """部分更新。Pydantic v2 用 model_fields_set 区分'未传'与'显式 None/空'。
    receiver_ids 显式传 [] 或 null = 清空(回到默认 bot 群)。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    view: Literal["company", "personal"] | None = None
    push_time: str | None = Field(default=None, pattern=_HHMM)
    push_freq: _PushFreqLiteral | None = None
    window_hours: int | None = Field(default=None, ge=1, le=168)
    receiver_type: Literal["groups", "users"] | None = None
    receiver_ids: list[str] | None = None


class StatusUpdateIn(BaseModel):
    status: Literal["active", "paused", "archived"]


class RunNowIn(BaseModel):
    dry_run: bool = False
    no_ai: bool = False


class ManualTriggerIn(BaseModel):
    """不绑 job 的一次性触发。窗口 = [now - window_hours, now)。"""
    view: Literal["company", "personal"]
    window_hours: int = Field(default=24, ge=1, le=168)
    receiver_type: Literal["groups", "users"]
    receiver_ids: list[str] | None = None
    dry_run: bool = False
    no_ai: bool = False


class AdminNotifyIn(BaseModel):
    chat_ids: list[str] = Field(default_factory=list)
    open_ids: list[str] = Field(default_factory=list)


class JobOut(BaseModel):
    id: int
    name: str
    view: str
    status: str
    push_time: str
    push_freq: str
    window_hours: int
    channel: str
    receiver_type: str
    receiver_ids: list[str] | None
    next_run_at: str | None
    last_run_id: int | None
    last_status: str | None
    retry_count: int
    last_notified_at: str | None
    created_by: str | None
    created_at: str
    updated_at: str


class RunOut(BaseModel):
    id: int
    job_id: int | None
    trigger_type: str
    view: str
    started_at: str
    finished_at: str | None
    status: str
    rc: int | None
    cards_sent: int | None
    cards_total: int | None
    ai_tokens_in: int | None
    ai_tokens_out: int | None
    error: str | None


class RunDetailOut(RunOut):
    debug_json: str | None


class RunsPageOut(BaseModel):
    items: list[RunOut]
    page: int
    size: int
    total: int


class FeishuChatOut(BaseModel):
    chat_id: str
    name: str
    avatar: str | None


class TriggerResponse(BaseModel):
    ok: bool
    run_id: int
    started_at: str


# --------------------------------------------------------------------------- #
# Router                                                                      #
# --------------------------------------------------------------------------- #


def build_router(
    *,
    workspace: WorkspaceRuntime,
    settings: SettingsRepo,
    notifier: Notifier,
    db_path: Path,
    jobs_repo: JobsRepo,
    runs_repo: RunsRepo,
    current_user_cookie_only: Callable,
    index_dir_provider: Callable[[], Path] | None = None,
    users_db_path: Path | None = None,
) -> APIRouter:
    """v2 daily report admin router.

    `index_dir_provider`(dev override):返回 matter index 目录路径的 callable。
        默认 None → 用 `workspace.path / "index"`(正常路径)。
        Dev 时由 app.py 注入 lambda,优先返回 cfg.daily_report_index_dir_override。
    `users_db_path`(dev override):personal 视角的全员列表来源(只读)。
        默认 None → 用 `db_path`(正常路径)。
    """
    router = APIRouter(
        prefix="/api/admin/daily-report",
        dependencies=[Depends(require_admin)],
    )

    def _index_dir() -> Path:
        if index_dir_provider is not None:
            return index_dir_provider()
        return workspace.path / "index"

    # ------------------ jobs CRUD --------------------------- #

    @router.get("/jobs")
    def list_jobs(
        include_archived: bool = Query(False),
        _: User = Depends(current_user_cookie_only),
    ) -> list[JobOut]:
        items = jobs_repo.list_all(include_archived=include_archived)
        return [_job_to_out(j) for j in items]

    @router.post("/jobs", status_code=201)
    def create_job(
        body: JobIn,
        user: User = Depends(current_user_cookie_only),
    ) -> JobOut:
        # 创建时算首个 next_run_at(只对 status=active)
        now = datetime.now(tz=CHINA_TZ)
        next_at = (
            compute_next_run_at(now=now, push_time=body.push_time,
                                push_freq=body.push_freq)
            if body.status == "active" else None
        )
        try:
            job = jobs_repo.create(
                name=body.name,
                view=body.view,
                push_time=body.push_time,
                push_freq=body.push_freq,
                window_hours=body.window_hours,
                receiver_type=body.receiver_type,
                receiver_ids=body.receiver_ids,
                status=body.status,
                next_run_at=next_at,
                created_by=user.open_id,
            )
        except Exception as e:
            log.exception("create job failed")
            raise HTTPException(400, f"create failed: {e}")
        return _job_to_out(job)

    @router.get("/jobs/{job_id}")
    def get_job(
        job_id: int,
        _: User = Depends(current_user_cookie_only),
    ) -> JobOut:
        job = jobs_repo.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return _job_to_out(job)

    @router.put("/jobs/{job_id}")
    def update_job(
        job_id: int,
        body: JobUpdateIn,
        _: User = Depends(current_user_cookie_only),
    ) -> JobOut:
        job = jobs_repo.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.status == "archived":
            raise HTTPException(409, "cannot update archived job")

        # 用 model_fields_set 区分"未传"与"显式 None"
        sent = body.model_fields_set
        kwargs: dict[str, Any] = {}
        for f in ("name", "view", "push_time", "push_freq", "window_hours",
                  "receiver_type"):
            if f in sent:
                kwargs[f] = getattr(body, f)
        if "receiver_ids" in sent:
            # 显式传 [] / None 都视为"清空回默认 bot 群"
            kwargs["receiver_ids"] = body.receiver_ids or None
        if not kwargs:
            return _job_to_out(job)

        jobs_repo.update_config(job_id, **kwargs)

        # 如果改了 push_time / push_freq 且 status=active,重算 next_run_at
        time_changed = "push_time" in sent or "push_freq" in sent
        if time_changed and job.status == "active":
            updated = jobs_repo.get(job_id)
            assert updated is not None
            new_next = compute_next_run_at(
                now=datetime.now(tz=CHINA_TZ),
                push_time=updated.push_time,
                push_freq=updated.push_freq,
            )
            jobs_repo.update_config(job_id, next_run_at=new_next)

        result = jobs_repo.get(job_id)
        assert result is not None
        return _job_to_out(result)

    @router.put("/jobs/{job_id}/status")
    def update_status(
        job_id: int,
        body: StatusUpdateIn,
        _: User = Depends(current_user_cookie_only),
    ) -> JobOut:
        job = jobs_repo.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")

        if body.status == "active":
            # 恢复运行 → 算 next_run_at
            next_at = compute_next_run_at(
                now=datetime.now(tz=CHINA_TZ),
                push_time=job.push_time,
                push_freq=job.push_freq,
            )
            jobs_repo.update_status(job_id, "active", next_run_at=next_at)
        else:
            # paused / archived → 清 next_run_at
            jobs_repo.update_status(job_id, body.status, next_run_at=None)

        result = jobs_repo.get(job_id)
        assert result is not None
        return _job_to_out(result)

    @router.delete("/jobs/{job_id}", status_code=200)
    def delete_job(
        job_id: int,
        _: User = Depends(current_user_cookie_only),
    ) -> dict:
        """软删:status=archived,清 next_run_at。"""
        job = jobs_repo.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        jobs_repo.update_status(job_id, "archived", next_run_at=None)
        return {"ok": True}

    # ------------------ run-now / manual-trigger ------------ #

    @router.post("/jobs/{job_id}/run-now")
    def run_now(
        job_id: int,
        body: RunNowIn,
        _: User = Depends(current_user_cookie_only),
    ) -> TriggerResponse:
        """立即用该 job 配置跑一次,不影响 next_run_at / retry_count / last_status。"""
        job = jobs_repo.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.status == "archived":
            raise HTTPException(409, "cannot run-now archived job")

        now = datetime.now(tz=CHINA_TZ)
        run_id = runs_repo.start(
            job_id=job.id, trigger_type="retry",
            view=job.view, started_at=now,
        )
        thread = threading.Thread(
            target=_run_job_in_thread,
            kwargs=dict(
                job=job, run_id=run_id,
                runs_repo=runs_repo,
                db_path=db_path,
                workspace_index_dir=_index_dir(),
                notifier=notifier,
                dry_run=body.dry_run,
                no_ai=body.no_ai,
                users_db_path=users_db_path,
            ),
            name=f"daily-report-run-now-{job_id}",
            daemon=True,
        )
        thread.start()

        return TriggerResponse(
            ok=True, run_id=run_id, started_at=now.isoformat(),
        )

    @router.post("/manual-trigger")
    def manual_trigger(
        body: ManualTriggerIn,
        _: User = Depends(current_user_cookie_only),
    ) -> TriggerResponse:
        """不绑 job 的一次性触发。窗口 = [now - window_hours, now)。"""
        if body.receiver_type == "users" and not body.receiver_ids:
            raise HTTPException(400, "receiver_ids required when receiver_type=users")

        now = datetime.now(tz=CHINA_TZ)
        # 构造 dummy Job(不入库,只供 runner 用)
        dummy = Job(
            id=0, name="manual-trigger", view=body.view,
            status="active",
            push_time="09:30", push_freq="daily",
            window_hours=body.window_hours,
            channel="feishu",
            receiver_type=body.receiver_type,
            receiver_ids=tuple(body.receiver_ids) if body.receiver_ids else None,
            next_run_at=None, last_run_id=None, last_status=None,
            retry_count=0, last_notified_at=None,
            created_by=None, created_at=now, updated_at=now,
        )
        # 显式时间窗口 = 过去 N 小时
        explicit_window = TimeWindow(
            since=now - timedelta(hours=body.window_hours),
            until=now,
        )

        run_id = runs_repo.start(
            job_id=None, trigger_type="manual",
            view=body.view, started_at=now,
        )
        thread = threading.Thread(
            target=_run_job_in_thread,
            kwargs=dict(
                job=dummy, run_id=run_id,
                runs_repo=runs_repo,
                db_path=db_path,
                workspace_index_dir=_index_dir(),
                notifier=notifier,
                dry_run=body.dry_run,
                no_ai=body.no_ai,
                explicit_window=explicit_window,
                users_db_path=users_db_path,
            ),
            name=f"daily-report-manual-{run_id}",
            daemon=True,
        )
        thread.start()

        return TriggerResponse(
            ok=True, run_id=run_id, started_at=now.isoformat(),
        )

    # ------------------ runs ------------------------------- #

    @router.get("/jobs/{job_id}/runs")
    def list_runs_for_job(
        job_id: int,
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=200),
        _: User = Depends(current_user_cookie_only),
    ) -> RunsPageOut:
        if jobs_repo.get(job_id) is None:
            raise HTTPException(404, "job not found")
        items, total = runs_repo.list_for_job(job_id, page=page, size=size)
        return RunsPageOut(
            items=[_run_to_out(r) for r in items],
            page=page, size=size, total=total,
        )

    @router.get("/runs/{run_id}")
    def get_run(
        run_id: int,
        _: User = Depends(current_user_cookie_only),
    ) -> RunDetailOut:
        run = runs_repo.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return _run_to_detail_out(run)

    # ------------------ admin notify config ---------------- #

    @router.get("/admin-notify")
    def get_admin_notify(
        _: User = Depends(current_user_cookie_only),
    ) -> AdminNotifyIn:
        return AdminNotifyIn(
            chat_ids=_load_json_list(settings, KEY_ADMIN_NOTIFY_CHAT_IDS),
            open_ids=_load_json_list(settings, KEY_ADMIN_NOTIFY_OPEN_IDS),
        )

    @router.put("/admin-notify")
    def put_admin_notify(
        body: AdminNotifyIn,
        _: User = Depends(current_user_cookie_only),
    ) -> dict:
        settings.set(KEY_ADMIN_NOTIFY_CHAT_IDS,
                     json.dumps(body.chat_ids, ensure_ascii=False))
        settings.set(KEY_ADMIN_NOTIFY_OPEN_IDS,
                     json.dumps(body.open_ids, ensure_ascii=False))
        return {"ok": True}

    # ------------------ feishu chats ----------------------- #

    @router.get("/feishu-chats")
    def list_feishu_chats(
        _: User = Depends(current_user_cookie_only),
    ) -> list[FeishuChatOut]:
        chats = notifier.list_bot_chats()
        return [
            FeishuChatOut(
                chat_id=c["chat_id"],
                name=c.get("name") or "",
                avatar=c.get("avatar") or None,
            )
            for c in chats
        ]

    return router


# --------------------------------------------------------------------------- #
# Background thread: run a (real or dummy) job                                #
# --------------------------------------------------------------------------- #


def _run_job_in_thread(
    *,
    job: Job,
    run_id: int,
    runs_repo: RunsRepo,
    db_path: Path,
    workspace_index_dir: Path,
    notifier: Notifier,
    dry_run: bool,
    no_ai: bool,
    explicit_window: TimeWindow | None = None,
    users_db_path: Path | None = None,
) -> None:
    """跑 runner.run_daily_report_for_job + UPDATE runs.finish。
    与 JobScheduler 的 _run_one_job_safely 类似但不更新 jobs 表(因为是 ad-hoc)。"""
    from server.daily_report.runner import run_daily_report_for_job

    try:
        rc, debug = run_daily_report_for_job(
            job=job, db_path=db_path,
            workspace_index_dir=workspace_index_dir,
            notifier=notifier,
            dry_run=dry_run, no_ai=no_ai,
            explicit_window=explicit_window,
            users_db_path=users_db_path,
        )
        if rc == 0:
            status = "succeeded"
            error = None
        elif rc == 1:
            status = "partial"
            error = (debug.get("error") or "partial broadcast")[:200]
        else:
            status = "failed"
            error = (debug.get("error") or f"rc={rc}")[:200]
    except Exception as e:  # noqa: BLE001
        log.exception("ad-hoc run crashed run_id=%d", run_id)
        rc = -1
        status = "failed"
        error = f"{type(e).__name__}: {e}"
        debug = {"crashed": True}

    try:
        debug_json = json.dumps(debug, ensure_ascii=False, default=str)
    except Exception:
        debug_json = None

    runs_repo.finish(
        run_id, status=status, rc=rc,
        cards_sent=(debug.get("receivers") or {}).get("sent"),
        cards_total=(debug.get("receivers") or {}).get("total"),
        error=error, debug_json=debug_json,
    )


# --------------------------------------------------------------------------- #
# Pydantic ↔ dataclass converters                                             #
# --------------------------------------------------------------------------- #


def _job_to_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        name=job.name,
        view=job.view,
        status=job.status,
        push_time=job.push_time,
        push_freq=job.push_freq,
        window_hours=job.window_hours,
        channel=job.channel,
        receiver_type=job.receiver_type,
        receiver_ids=list(job.receiver_ids) if job.receiver_ids else None,
        next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
        last_run_id=job.last_run_id,
        last_status=job.last_status,
        retry_count=job.retry_count,
        last_notified_at=(
            job.last_notified_at.isoformat() if job.last_notified_at else None
        ),
        created_by=job.created_by,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def _run_to_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        job_id=run.job_id,
        trigger_type=run.trigger_type,
        view=run.view,
        started_at=run.started_at.isoformat(),
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        status=run.status,
        rc=run.rc,
        cards_sent=run.cards_sent,
        cards_total=run.cards_total,
        ai_tokens_in=run.ai_tokens_in,
        ai_tokens_out=run.ai_tokens_out,
        error=run.error,
    )


def _run_to_detail_out(run: Run) -> RunDetailOut:
    base = _run_to_out(run)
    return RunDetailOut(**base.model_dump(), debug_json=run.debug_json)


def _load_json_list(settings: SettingsRepo, key: str) -> list[str]:
    raw = settings.get(key)
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []
