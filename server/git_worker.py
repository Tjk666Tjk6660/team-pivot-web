"""Background asyncio task that drains GitPushOutbox by running git push.

设计上下文：方案 A · Write Pipeline 的"远端推送"那半边。
  - write_session 持锁期间只做本地 commit + outbox.enqueue → ms 级返回
  - 本 worker 单 task 串行消费 outbox：claim → git push → mark_succeeded
  - N 条 pending 折叠成一次 git push（push 状态本身就是聚合的）
  - 失败时按 attempts 阶梯退避；超过 max_attempts 进 'failed' 终态、不再阻塞用户

实现：方案 C 骨架的 WorkerTask 子类。父类负责 start/stop/notify 生命周期 +
错误吞咽 + poll 兜底；本类只关心 git 特定逻辑（claim → push → mark + backoff）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from server.git_outbox import GitPushOutbox
from server.jobs.runner import WorkerTask

log = logging.getLogger(__name__)


# Push function signature: takes the absolute repo dir, raises on failure.
# Default impl is server.git_ops.push; injecting it as a parameter keeps
# this module test-friendly (fakes can simulate failure / latency).
PushFn = Callable[[str], None]


# Backoff schedule (seconds) for retries. Index = attempts done so far.
# attempts=1 → wait 2s before next try, attempts=2 → 5s, ...
# Tuned for "transient network blip" recovery (sub-minute) without melting
# the upstream when something is genuinely broken.
_BACKOFF_SCHEDULE = (2.0, 5.0, 15.0, 30.0, 60.0)


class GitWorker(WorkerTask):
    """Pushes whenever the outbox has pending rows.

    One round = `claim_batch` → `git push` → `mark_succeeded`. Multiple
    pending rows fold into a single push because git push is a state-
    aggregating operation; we treat the whole batch atomically.
    """

    name = "git-worker"

    def __init__(
        self,
        *,
        outbox: GitPushOutbox,
        push_fn: PushFn,
        repo_dir: Path | str,
        max_attempts: int = 5,
        poll_interval_s: float = 30.0,
        tenant_id: str = "default",
    ) -> None:
        super().__init__()
        self._outbox = outbox
        self._push_fn = push_fn
        self._repo_dir = str(repo_dir)
        self._max_attempts = max_attempts
        # Override class-level default with the constructor param so
        # different repos can have different cadences.
        self.poll_interval_s = poll_interval_s
        self._tenant_id = tenant_id

    # ── WorkerTask hooks ────────────────────────────────────────────────────

    async def _on_start_hook(self) -> None:
        """Crash recovery: any rows the previous run claimed but didn't ack
        are reset to pending so this run picks them up on the first tick.
        Re-pushing an already-uploaded commit is a no-op on the remote, so
        the retry is idempotent."""
        try:
            n = await asyncio.to_thread(self._outbox.sweep_in_flight)
            log.info("git_worker swept %d in_flight rows on boot", n)
        except Exception:
            log.exception("git_worker sweep_in_flight failed; continuing")

    async def _drain_once(self) -> None:
        batch = await asyncio.to_thread(
            self._outbox.claim_batch, self._tenant_id,
        )
        if not batch:
            return
        ids = [bid for bid, _ in batch]
        max_attempt_count = max(att for _, att in batch)
        log.debug(
            "git_worker draining batch_size=%d max_attempts=%d",
            len(ids), max_attempt_count,
        )
        try:
            await asyncio.to_thread(self._push_fn, self._repo_dir)
        except Exception as e:
            await self._handle_push_failure(ids, max_attempt_count, e)
            return
        await asyncio.to_thread(self._outbox.mark_succeeded, ids)
        log.info("git_worker pushed batch_size=%d", len(ids))

    # ── failure handling ────────────────────────────────────────────────────

    async def _handle_push_failure(
        self,
        ids: list[int],
        attempts_so_far: int,
        exc: BaseException,
    ) -> None:
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        log.warning(
            "git_worker push failed batch_size=%d attempts=%d error=%s",
            len(ids), attempts_so_far, error,
        )
        if attempts_so_far >= self._max_attempts:
            await asyncio.to_thread(
                self._outbox.mark_terminal_failed, ids, error,
            )
            return
        await asyncio.to_thread(self._outbox.mark_failed, ids, error)
        # Sleep before the next retry; clamp index to schedule length.
        idx = min(attempts_so_far - 1, len(_BACKOFF_SCHEDULE) - 1)
        idx = max(idx, 0)
        await asyncio.sleep(_BACKOFF_SCHEDULE[idx])
        # Wake the loop so the next tick happens immediately after backoff
        # rather than waiting another full poll interval. notify() is a
        # no-op safe to call from any context.
        self.notify()
