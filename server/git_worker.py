"""Background asyncio task that drains GitPushOutbox by running git push.

设计上下文：方案 A · Write Pipeline 的"远端推送"那半边。
  - write_session 持锁期间只做本地 commit + outbox.enqueue → ms 级返回
  - 本 worker 单 task 串行消费 outbox：claim → git push → mark_succeeded
  - N 条 pending 折叠成一次 git push（push 状态本身就是聚合的）
  - 失败时按 attempts 阶梯退避；超过 max_attempts 进 'failed' 终态、不再阻塞用户

唤醒模型：
  混合 push/poll —— enqueue 端通过 GitWorker.notify() 触发 asyncio.Event.set
  立即唤醒；同时 _run() 每 poll_interval_s 兜底醒一次（应对漏通知 / 启动后
  的崩溃恢复 / 远端被人推过新提交后我们也想顺带 sync 等场景）。

线程模型：
  outbox / 实际的 git push 都是 sync 调用（subprocess.run 阻塞），全部走
  asyncio.to_thread 卸载到 threadpool，不会卡 event loop。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from server.git_outbox import GitPushOutbox

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


class GitWorker:
    """Single background task that pushes whenever the outbox has pending rows.

    Lifecycle:
        worker = GitWorker(outbox=..., push_fn=..., repo_dir=...)
        await worker.start()                # in lifespan startup
        ...
        outbox.enqueue(...); worker.notify()  # called by write_session
        ...
        await worker.stop()                 # in lifespan shutdown

    Reentrancy: start() / stop() are safe to call multiple times.
    """

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
        self._outbox = outbox
        self._push_fn = push_fn
        self._repo_dir = str(repo_dir)
        self._max_attempts = max_attempts
        self._poll_interval_s = poll_interval_s
        self._tenant_id = tenant_id

        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        # Crash recovery: any rows the previous run claimed but didn't ack
        # are reset to pending so this run picks them up on the first tick.
        try:
            n = await asyncio.to_thread(self._outbox.sweep_in_flight)
        except Exception:
            log.exception("git_worker sweep_in_flight failed; continuing")
            n = 0
        # Kick the worker once on boot so any pre-existing pending rows
        # (server restarted between enqueue and push) get drained immediately.
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="git-worker")
        log.info(
            "git_worker started repo=%s swept_in_flight=%d poll=%.1fs",
            self._repo_dir, n, self._poll_interval_s,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                log.warning("git_worker did not stop within 10s; cancelling")
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("git_worker raised during stop")
            finally:
                self._task = None
                self._wake = None
                self._loop = None
        log.info("git_worker stopped")

    # ── notification (called from any thread) ──────────────────────────────

    def notify(self) -> None:
        """Threadsafe wakeup. write_session calls this right after enqueue.

        No-op if the worker hasn't started yet (early boot) or has stopped —
        the next poll-interval tick will pick the row up regardless."""
        loop = self._loop
        wake = self._wake
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            # Loop may be closing; harmless to skip.
            pass

    # ── main loop ──────────────────────────────────────────────────────────

    async def _run(self) -> None:
        assert self._wake is not None
        while not self._stopping:
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._poll_interval_s,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._stopping:
                return
            try:
                await self._drain_once()
            except Exception:
                # Defensive: _drain_once should already swallow + record errors,
                # but a bug here MUST NOT kill the worker loop.
                log.exception("git_worker drain iteration crashed")
                # Backoff before next attempt to avoid hot-loop on systemic bugs.
                await asyncio.sleep(5.0)

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
        # rather than waiting another full poll interval.
        if self._wake is not None:
            self._wake.set()
