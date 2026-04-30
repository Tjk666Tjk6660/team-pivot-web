"""Repository for `daily_report_runs` table — v2 多任务运行历史。

每次 fire(scheduled / manual / retry / makeup)都 INSERT 一行,fire 完成后
UPDATE 对应行的 finished_at / status / 等字段。

365 天清理:scheduler 每天扫一次,删 365 天前的 runs 记录,同时
回写 `jobs.last_run_id = NULL`(代码层处理,不依赖外键级联)。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from server.daily_report.window import CHINA_TZ
from server.db import Database

TriggerType = Literal["scheduled", "manual", "retry", "makeup"]
RunStatus = Literal["running", "succeeded", "failed", "partial", "skipped"]


@dataclass(frozen=True)
class Run:
    id: int
    job_id: int | None        # NULL = 手动一次性触发
    trigger_type: TriggerType
    view: str
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    rc: int | None
    cards_sent: int | None
    cards_total: int | None
    ai_tokens_in: int | None
    ai_tokens_out: int | None
    error: str | None
    debug_json: str | None    # 完整 debug payload(JSON 字符串)


class RunsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ----------------------------------------------------------------- #
    # Writes                                                            #
    # ----------------------------------------------------------------- #

    def start(
        self,
        *,
        job_id: int | None,
        trigger_type: TriggerType,
        view: str,
        started_at: datetime | None = None,
    ) -> int:
        """fire 开始时 INSERT 一行,返回 run_id。"""
        ts = (started_at or datetime.now(tz=CHINA_TZ)).timestamp()
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO daily_report_runs("
                "  job_id, trigger_type, view, started_at, status"
                ") VALUES(?,?,?,?, 'running')",
                (job_id, trigger_type, view, ts),
            )
            return cur.lastrowid

    def finish(
        self,
        run_id: int,
        *,
        finished_at: datetime | None = None,
        status: RunStatus,
        rc: int | None = None,
        cards_sent: int | None = None,
        cards_total: int | None = None,
        ai_tokens_in: int | None = None,
        ai_tokens_out: int | None = None,
        error: str | None = None,
        debug_json: str | None = None,
    ) -> None:
        """fire 完成时 UPDATE。error 自动截断到 200 字。"""
        ts = (finished_at or datetime.now(tz=CHINA_TZ)).timestamp()
        if error and len(error) > 200:
            error = error[:200].rstrip() + "…"
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE daily_report_runs SET"
                "  finished_at=?, status=?, rc=?, cards_sent=?, cards_total=?,"
                "  ai_tokens_in=?, ai_tokens_out=?, error=?, debug_json=?"
                " WHERE id=?",
                (
                    ts, status, rc, cards_sent, cards_total,
                    ai_tokens_in, ai_tokens_out, error, debug_json, run_id,
                ),
            )

    def delete_before(self, cutoff: datetime) -> list[int]:
        """删除 cutoff 之前的所有 runs,返回被删除的 id 列表(供 jobs_repo
        调用 clear_last_run_id_in 回收 last_run_id 引用)。

        365 天清理逻辑:
            1. SELECT id FROM runs WHERE started_at < cutoff
            2. UPDATE jobs SET last_run_id=NULL WHERE last_run_id IN (...)
            3. DELETE FROM runs WHERE id IN (...)
        本方法只负责 1+3,2 由 caller 串起来。"""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM daily_report_runs WHERE started_at < ?",
                (cutoff.timestamp(),),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                # 分批删,避免单条 SQL 参数过多(SQLite 默认 999)
                for i in range(0, len(ids), 500):
                    batch = ids[i:i + 500]
                    placeholders = ",".join("?" for _ in batch)
                    conn.execute(
                        f"DELETE FROM daily_report_runs WHERE id IN ({placeholders})",
                        tuple(batch),
                    )
            return ids

    # ----------------------------------------------------------------- #
    # Reads                                                             #
    # ----------------------------------------------------------------- #

    def get(self, run_id: int) -> Run | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_report_runs WHERE id=?", (run_id,),
            ).fetchone()
            return _row_to_run(row) if row else None

    def list_for_job(
        self,
        job_id: int,
        *,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Run], int]:
        """指定 job 的运行历史,按 started_at DESC 分页。
        返回 (items, total_count)。"""
        if page < 1:
            page = 1
        if size < 1:
            size = 20
        offset = (page - 1) * size
        with self._db.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM daily_report_runs WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM daily_report_runs WHERE job_id=?"
                " ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (job_id, size, offset),
            ).fetchall()
            return [_row_to_run(r) for r in rows], total

    def latest_for_job(self, job_id: int) -> Run | None:
        """该 job 最近一次 run。给 jobs 列表卡片展示用(避免每个 job
        各自查一次)。"""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_report_runs WHERE job_id=?"
                " ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            return _row_to_run(row) if row else None


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _row_to_run(row) -> Run:
    return Run(
        id=row["id"],
        job_id=row["job_id"],
        trigger_type=row["trigger_type"],
        view=row["view"],
        started_at=_to_dt(row["started_at"]) or datetime.now(tz=CHINA_TZ),
        finished_at=_to_dt(row["finished_at"]),
        status=row["status"],
        rc=row["rc"],
        cards_sent=row["cards_sent"],
        cards_total=row["cards_total"],
        ai_tokens_in=row["ai_tokens_in"],
        ai_tokens_out=row["ai_tokens_out"],
        error=row["error"],
        debug_json=row["debug_json"],
    )


def _to_dt(epoch: float | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=CHINA_TZ)
