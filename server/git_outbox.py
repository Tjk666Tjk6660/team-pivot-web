"""SQLite-backed outbox for the asynchronous git push pipeline (方案 A).

设计上下文（see act 006_dengke_act / think 007_liuyu_think）：
    write_session 在请求生命周期里只负责"加锁 → pull(lazy) → 写盘 → commit"。
    完成本地 commit 后，往本表 enqueue 一行 pending；后台 GitWorker 单线程串行
    消费，把多条 pending 合并为一次 git push。这样：
      * 用户感受到的写延迟从 "pull RTT + push RTT × 重试" 降到 "本地 commit < 200ms"
      * push 失败不再阻塞用户，由 worker 退避重试 + 阈值告警

幂等模型：
    一个 worker round = 1 次 git push = 把仓库 HEAD 推到远端。所以 N 条 pending
    可以 collapse 成一次 push，全部一起 mark_succeeded。这是为什么 outbox 不存
    "要推哪个 commit"——push 永远以当前 HEAD 为准。

崩溃恢复：
    worker 启动时调 sweep_in_flight()，把所有 status='in_flight' 改回 'pending'。
    上次 worker 没来得及 mark_succeeded 就退出了 → 下次自动重试，幂等且安全
    （远端已有的 commit 再 push 一次是 no-op）。
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from time import time
from typing import Iterable

from server.db import Database

log = logging.getLogger(__name__)


# Single-tenant default. SaaS 接口位 (§9.1 #1)：所有 outbox 行都带 tenant_id，
# 单租户期写死 "default"，未来切多租户时按 tenant 分批 push。
DEFAULT_TENANT = "default"


@dataclass(frozen=True)
class OutboxRow:
    id: int
    tenant_id: str
    enqueued_at: float
    status: str
    attempts: int
    last_attempt_at: float | None
    last_error: str | None
    succeeded_at: float | None
    reason: str | None


class GitPushOutbox:
    """Thread-safe outbox 仓储。所有方法都在单独的 sqlite 连接事务中完成。

    enqueue 由 write_session 在持锁状态下调用（同进程内不会与 worker
    冲突，但仍然需要数据库事务以防 SQLite 自身的 busy timeout）；其他方法
    由 worker (单 asyncio task → asyncio.to_thread) 调用。
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── enqueue (called from write_session) ──────────────────────────────────

    def enqueue(self, *, tenant_id: str = DEFAULT_TENANT, reason: str | None = None) -> int:
        """Queue a "please push" signal. Returns the new row id.

        多次 enqueue 之间无去重——worker 一次会把所有 pending 一起 mark_succeeded
        所以重复入队不会引发重复 push。代价只是 outbox 表会偶尔多几行 succeeded
        历史，由 vacuum_succeeded 周期清理。
        """
        with self._db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO git_push_outbox"
                " (tenant_id, enqueued_at, status, attempts, reason)"
                " VALUES (?,?,?,?,?)",
                (tenant_id, time(), "pending", 0, reason),
            )
            new_id = cur.lastrowid
        log.debug("git_outbox enqueued id=%s reason=%s", new_id, reason)
        return int(new_id)

    # ── claim/release (called from worker) ───────────────────────────────────

    def has_pending(self, tenant_id: str = DEFAULT_TENANT) -> bool:
        """Cheap check used by the worker to decide whether to wake up."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM git_push_outbox"
                " WHERE tenant_id=? AND status='pending'"
                " LIMIT 1",
                (tenant_id,),
            ).fetchone()
        return row is not None

    def claim_batch(
        self, tenant_id: str = DEFAULT_TENANT,
    ) -> list[tuple[int, int]]:
        """Atomically take all pending rows for this tenant → mark in_flight,
        return ``[(id, attempts_after_increment), ...]``.

        Worker is single-task per tenant so there is no cross-claim contention;
        the transaction here protects against an in-flight enqueue committing
        concurrently. Returning attempts alongside id avoids a follow-up SELECT
        when the worker needs to decide pending-retry vs terminal-failure."""
        now = time()
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, attempts FROM git_push_outbox"
                " WHERE tenant_id=? AND status='pending'"
                " ORDER BY enqueued_at",
                (tenant_id,),
            ).fetchall()
            if not rows:
                return []
            ids = [int(r[0]) for r in rows]
            # attempts column reflects the value AFTER this claim.
            new_attempts = [int(r[1]) + 1 for r in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE git_push_outbox"
                f" SET status='in_flight', last_attempt_at=?, attempts=attempts+1"
                f" WHERE id IN ({placeholders})",
                (now, *ids),
            )
        log.debug("git_outbox claimed batch_size=%d", len(ids))
        return list(zip(ids, new_attempts))

    def mark_succeeded(self, ids: Iterable[int]) -> None:
        ids_list = list(ids)
        if not ids_list:
            return
        now = time()
        placeholders = ",".join("?" for _ in ids_list)
        with self._db.connect() as conn:
            conn.execute(
                f"UPDATE git_push_outbox"
                f" SET status='succeeded', succeeded_at=?, last_error=NULL"
                f" WHERE id IN ({placeholders})",
                (now, *ids_list),
            )
        log.debug("git_outbox mark_succeeded n=%d", len(ids_list))

    def mark_failed(self, ids: Iterable[int], error: str) -> None:
        """Roll the batch back to pending so the worker retries. We don't
        flip to 'failed' immediately — only after attempts >= max_attempts
        will the worker call mark_terminal_failed below."""
        ids_list = list(ids)
        if not ids_list:
            return
        truncated = (error or "")[:500]
        placeholders = ",".join("?" for _ in ids_list)
        with self._db.connect() as conn:
            conn.execute(
                f"UPDATE git_push_outbox"
                f" SET status='pending', last_error=?"
                f" WHERE id IN ({placeholders})",
                (truncated, *ids_list),
            )
        log.warning("git_outbox mark_failed n=%d error=%s", len(ids_list), truncated[:120])

    def mark_terminal_failed(self, ids: Iterable[int], error: str) -> None:
        """Give up: bury the batch as 'failed' so the worker stops retrying.
        Admin tooling can re-queue or investigate; user writes keep working
        because new enqueues get fresh ids."""
        ids_list = list(ids)
        if not ids_list:
            return
        truncated = (error or "")[:500]
        placeholders = ",".join("?" for _ in ids_list)
        with self._db.connect() as conn:
            conn.execute(
                f"UPDATE git_push_outbox"
                f" SET status='failed', last_error=?"
                f" WHERE id IN ({placeholders})",
                (truncated, *ids_list),
            )
        log.error(
            "git_outbox mark_terminal_failed n=%d error=%s", len(ids_list), truncated[:120],
        )

    # ── recovery + admin ────────────────────────────────────────────────────

    def sweep_in_flight(self) -> int:
        """Reset any 'in_flight' rows back to 'pending'. Called by GitWorker.start
        on boot — covers the case where the previous run was killed mid-push.
        Returns the number of rows reset (for logging)."""
        with self._db.connect() as conn:
            cur = conn.execute(
                "UPDATE git_push_outbox"
                " SET status='pending'"
                " WHERE status='in_flight'"
            )
            n = cur.rowcount
        if n > 0:
            log.warning("git_outbox swept %d in_flight rows back to pending", n)
        return int(n)

    def pending_count(self, tenant_id: str = DEFAULT_TENANT) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM git_push_outbox"
                " WHERE tenant_id=? AND status IN ('pending','in_flight')",
                (tenant_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_recent_failures(self, *, limit: int = 20) -> list[OutboxRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM git_push_outbox"
                " WHERE status='failed'"
                " ORDER BY last_attempt_at DESC NULLS LAST"
                " LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row(r) for r in rows]

    def vacuum_succeeded(self, *, older_than_seconds: float = 7 * 24 * 3600) -> int:
        """Trim succeeded history older than N seconds. Pure housekeeping;
        outbox correctness does not depend on it."""
        cutoff = time() - older_than_seconds
        with self._db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM git_push_outbox"
                " WHERE status='succeeded' AND succeeded_at < ?",
                (cutoff,),
            )
            n = cur.rowcount
        if n > 0:
            log.info("git_outbox vacuumed %d old succeeded rows", n)
        return int(n)


def _row(r: sqlite3.Row) -> OutboxRow:
    return OutboxRow(
        id=int(r["id"]),
        tenant_id=str(r["tenant_id"]),
        enqueued_at=float(r["enqueued_at"]),
        status=str(r["status"]),
        attempts=int(r["attempts"]),
        last_attempt_at=(
            float(r["last_attempt_at"]) if r["last_attempt_at"] is not None else None
        ),
        last_error=r["last_error"],
        succeeded_at=(
            float(r["succeeded_at"]) if r["succeeded_at"] is not None else None
        ),
        reason=r["reason"],
    )
