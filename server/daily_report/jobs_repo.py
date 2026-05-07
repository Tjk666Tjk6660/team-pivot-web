"""Repository for `daily_report_jobs` table — v2 多任务管理。

管理员配置的每条定时任务都是一行 jobs 记录。scheduler poll 时按
`status='active' AND next_run_at <= now` 拉到期任务,fire 后由 scheduler
更新运行状态字段(last_run_id / last_status / retry_count / next_run_at)。

时间戳列(next_run_at / last_notified_at / created_at / updated_at)在 DB
里用 Unix epoch REAL 存,Python 层接受/返回 tz-aware datetime。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from server.daily_report.window import CHINA_TZ
from server.db import Database

JobView = Literal["company", "personal"]
JobStatus = Literal["active", "paused", "archived"]
PushFreq = Literal[
    "daily", "weekdays",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "month_start", "month_end",
]
ReceiverType = Literal["groups", "users"]


class _Unset:
    """Sentinel 类型,区分"不传参"与"显式 None"。"""
    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    view: JobView
    status: JobStatus
    push_time: str                         # 'HH:MM'
    push_freq: PushFreq
    window_hours: int
    channel: str                           # 'feishu' (v1 仅此)
    receiver_type: ReceiverType
    receiver_ids: tuple[str, ...] | None   # None = 默认全部 bot 群(只对 groups 有效)
    next_run_at: datetime | None
    last_run_id: int | None
    last_status: str | None
    retry_count: int
    last_notified_at: datetime | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class JobsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ----------------------------------------------------------------- #
    # Reads                                                             #
    # ----------------------------------------------------------------- #

    def get(self, job_id: int) -> Job | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_report_jobs WHERE id = ?", (job_id,),
            ).fetchone()
            return _row_to_job(row) if row else None

    def list_all(self, *, include_archived: bool = False) -> list[Job]:
        """所有 jobs,默认过滤掉 archived(给 admin UI 用)。"""
        with self._db.connect() as conn:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM daily_report_jobs ORDER BY id ASC",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM daily_report_jobs"
                    " WHERE status != 'archived' ORDER BY id ASC",
                ).fetchall()
            return [_row_to_job(r) for r in rows]

    def list_due(self, now: datetime) -> list[Job]:
        """status='active' 且 next_run_at <= now 的任务,按 next_run_at 升序。
        给 scheduler poll 用。"""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_report_jobs"
                " WHERE status = 'active' AND next_run_at IS NOT NULL"
                " AND next_run_at <= ?"
                " ORDER BY next_run_at ASC",
                (now.timestamp(),),
            ).fetchall()
            return [_row_to_job(r) for r in rows]

    # ----------------------------------------------------------------- #
    # Writes                                                            #
    # ----------------------------------------------------------------- #

    def create(
        self,
        *,
        name: str,
        view: JobView,
        push_time: str,
        push_freq: PushFreq = "weekdays",
        window_hours: int = 24,
        channel: str = "feishu",
        receiver_type: ReceiverType,
        receiver_ids: list[str] | None = None,
        status: JobStatus = "active",
        next_run_at: datetime | None = None,
        created_by: str | None = None,
    ) -> Job:
        now = time.time()
        ids_json = json.dumps(list(receiver_ids)) if receiver_ids else None
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO daily_report_jobs("
                "  name, view, status, push_time, push_freq, window_hours,"
                "  channel, receiver_type, receiver_ids, next_run_at,"
                "  retry_count, created_by, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
                (
                    name, view, status, push_time, push_freq, window_hours,
                    channel, receiver_type, ids_json,
                    next_run_at.timestamp() if next_run_at else None,
                    created_by, now, now,
                ),
            )
            job_id = cur.lastrowid
        job = self.get(job_id)
        assert job is not None
        return job

    def update_config(
        self,
        job_id: int,
        *,
        name: str | None = None,
        view: JobView | None = None,
        push_time: str | None = None,
        push_freq: PushFreq | None = None,
        window_hours: int | None = None,
        receiver_type: ReceiverType | None = None,
        receiver_ids: list[str] | None | _Unset = _UNSET,
        next_run_at: datetime | None | _Unset = _UNSET,
    ) -> None:
        """部分更新配置字段。`receiver_ids` / `next_run_at` 明确支持设为 None,
        所以用 _UNSET 哨兵区分"不传参"与"显式置 None"。"""
        sets = []
        params: list = []
        if name is not None: sets.append("name=?"); params.append(name)
        if view is not None: sets.append("view=?"); params.append(view)
        if push_time is not None: sets.append("push_time=?"); params.append(push_time)
        if push_freq is not None: sets.append("push_freq=?"); params.append(push_freq)
        if window_hours is not None: sets.append("window_hours=?"); params.append(window_hours)
        if receiver_type is not None: sets.append("receiver_type=?"); params.append(receiver_type)
        if receiver_ids is not _UNSET:
            sets.append("receiver_ids=?")
            params.append(json.dumps(list(receiver_ids)) if receiver_ids else None)
        if next_run_at is not _UNSET:
            sets.append("next_run_at=?")
            params.append(next_run_at.timestamp() if next_run_at else None)
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(job_id)
        with self._db.connect() as conn:
            conn.execute(
                f"UPDATE daily_report_jobs SET {', '.join(sets)} WHERE id=?",
                tuple(params),
            )

    def delete(self, job_id: int) -> bool:
        """硬删:DELETE 该 job 行。

        runs 表里的历史记录通过冗余的 `view` 字段自包含,即使 job 行不在了
        也能完整查历史(见 db.py schema 注释)。所以 hard delete 是安全的:
        不会破坏历史可见性,也不需要 cascade。

        ⚠ 注意:本方法对**已归档**(legacy)的 job 同样有效,UI 重命名为
        "删除任务"后,新流程不再产生 archived 状态,但老数据可能有,通过
        admin 重新打开后再删依然走这条路径。

        Returns True 当且仅当 DELETE 真删除了 1 行(job 之前存在)。
        """
        with self._db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM daily_report_jobs WHERE id=?", (job_id,),
            )
            return cur.rowcount > 0

    def update_status(self, job_id: int, status: JobStatus,
                      *, next_run_at: datetime | None | _Unset = _UNSET) -> None:
        """切换 active / paused / archived。
        - paused / archived 调用方应同时清空 next_run_at(显式传 None)
        - active 调用方应同时算好 next_run_at 传入"""
        with self._db.connect() as conn:
            if next_run_at is _UNSET:
                conn.execute(
                    "UPDATE daily_report_jobs SET status=?, updated_at=? WHERE id=?",
                    (status, time.time(), job_id),
                )
            else:
                conn.execute(
                    "UPDATE daily_report_jobs SET status=?, next_run_at=?,"
                    " updated_at=? WHERE id=?",
                    (
                        status,
                        next_run_at.timestamp() if next_run_at else None,
                        time.time(), job_id,
                    ),
                )

    def update_after_run(
        self,
        job_id: int,
        *,
        last_run_id: int,
        last_status: str,
        next_run_at: datetime | None,
        retry_count: int,
        last_notified_at: datetime | None | _Unset = _UNSET,
    ) -> None:
        """fire 完成后由 scheduler 调,更新运行状态字段。"""
        params: list = [
            last_run_id, last_status,
            next_run_at.timestamp() if next_run_at else None,
            retry_count,
        ]
        sql = (
            "UPDATE daily_report_jobs SET last_run_id=?, last_status=?,"
            " next_run_at=?, retry_count=?"
        )
        if last_notified_at is not _UNSET:
            sql += ", last_notified_at=?"
            params.append(
                last_notified_at.timestamp() if last_notified_at else None,
            )
        sql += ", updated_at=? WHERE id=?"
        params.append(time.time())
        params.append(job_id)
        with self._db.connect() as conn:
            conn.execute(sql, tuple(params))

    def clear_last_run_id_in(self, run_ids: list[int]) -> int:
        """365 天清理 runs 时调用:把 jobs.last_run_id 中引用即将删除的
        runs id 全部置 NULL。返回受影响行数。"""
        if not run_ids:
            return 0
        with self._db.connect() as conn:
            placeholders = ",".join("?" for _ in run_ids)
            cur = conn.execute(
                f"UPDATE daily_report_jobs SET last_run_id=NULL,"
                f" updated_at=? WHERE last_run_id IN ({placeholders})",
                (time.time(), *run_ids),
            )
            return cur.rowcount


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _row_to_job(row) -> Job:
    receiver_ids_raw = row["receiver_ids"]
    receiver_ids: tuple[str, ...] | None
    if receiver_ids_raw is None:
        receiver_ids = None
    else:
        try:
            receiver_ids = tuple(json.loads(receiver_ids_raw))
        except (ValueError, TypeError):
            receiver_ids = None
    return Job(
        id=row["id"],
        name=row["name"],
        view=row["view"],
        status=row["status"],
        push_time=row["push_time"],
        push_freq=row["push_freq"],
        window_hours=row["window_hours"],
        channel=row["channel"],
        receiver_type=row["receiver_type"],
        receiver_ids=receiver_ids,
        next_run_at=_to_dt(row["next_run_at"]),
        last_run_id=row["last_run_id"],
        last_status=row["last_status"],
        retry_count=row["retry_count"],
        last_notified_at=_to_dt(row["last_notified_at"]),
        created_by=row["created_by"],
        created_at=_to_dt(row["created_at"]) or datetime.now(tz=CHINA_TZ),
        updated_at=_to_dt(row["updated_at"]) or datetime.now(tz=CHINA_TZ),
    )


def _to_dt(epoch: float | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=CHINA_TZ)
