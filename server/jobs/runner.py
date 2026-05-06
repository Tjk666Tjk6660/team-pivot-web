"""Generic background-worker primitives (方案 C 骨架).

Two pre-existing workers in the codebase already share the same shape:
    * server.scoring.worker.ScoringWorker  — drains an asyncio.Queue
    * server.git_worker.GitWorker          — drains a SQLite outbox

They both:
  * own a single asyncio.Task that loops until shutdown
  * swallow per-iteration errors so the loop never dies
  * bridge sync work (subprocess / sqlite) via asyncio.to_thread
  * support threadsafe wake-up so callers from the FastAPI threadpool can
    nudge the worker without crossing into its event loop directly

This module captures that contract in `WorkerTask` so future async tasks
(image processing, batch import, scheduled cron-like jobs) don't reinvent
the lifecycle plumbing every time. `JobRunner` is a thin registry that
starts / stops a group of WorkerTasks together — useful for app.py
lifespan to coordinate them as one bundle.

Scope decision (think 007 §6.1):
    * Migrate GitWorker to WorkerTask now (small surface, fresh code).
    * Leave ScoringWorker as-is; it has a working queue model and its own
      sweep_orphans path. Migrating it is on the table for a follow-up
      when next-touched, not part of the current PR.
"""
from __future__ import annotations

import abc
import asyncio
import logging
from typing import Iterable

log = logging.getLogger(__name__)


class WorkerTask(abc.ABC):
    """Base class for single-asyncio-task background workers.

    Subclasses override `_drain_once` (mandatory) and `_on_start_hook`
    (optional) — the lifecycle plumbing lives entirely here.

    Lifecycle contract:
        await worker.start()    # idempotent; no-op if already running
        worker.notify()         # threadsafe wake-up; safe before start()
        await worker.stop()     # idempotent; waits up to stop_grace_s

    Error model:
        `_drain_once` may raise; the loop logs + sleeps `error_backoff_s`
        before the next iteration. A bug in user code MUST NOT kill the
        worker (this is the property the existing ScoringWorker /
        GitWorker depend on for resilience).

    Wake-up model:
        - `notify()` sets an asyncio.Event via `loop.call_soon_threadsafe`
          (so it's safe to call from any thread, including the FastAPI
          sync threadpool that handles publish requests).
        - The loop also wakes every `poll_interval_s` as a backstop, so a
          missed notify just delays processing by at most one interval —
          never strands work indefinitely.
    """

    # Subclasses set name in __init__ so logs identify which worker is talking.
    name: str = "worker"
    # Interval (seconds) between unconditional polls. Tune by subclass:
    # quick local outboxes can use 1s; slow remote-poll workers use 60s.
    poll_interval_s: float = 30.0
    # Max time to wait for the loop to exit cleanly on stop(). After this we
    # cancel hard; cancelled iterations should be safe to drop.
    stop_grace_s: float = 10.0
    # If `_drain_once` raises, sleep this long before next attempt to avoid
    # a hot crash-loop on a systemic bug.
    error_backoff_s: float = 5.0

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ── public lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        try:
            await self._on_start_hook()
        except Exception:
            log.exception("%s on_start_hook failed; continuing", self.name)
        # Kick once on boot so any pre-existing work gets picked up
        # immediately rather than waiting a poll interval.
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name=self.name)
        log.info("%s started (poll=%.1fs)", self.name, self.poll_interval_s)

    async def stop(self) -> None:
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=self.stop_grace_s)
            except asyncio.TimeoutError:
                log.warning(
                    "%s did not stop within %.1fs; cancelling",
                    self.name, self.stop_grace_s,
                )
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("%s raised during stop", self.name)
            finally:
                self._task = None
                self._wake = None
                self._loop = None
        log.info("%s stopped", self.name)

    def notify(self) -> None:
        """Threadsafe wake-up. No-op before start() / after stop()."""
        loop = self._loop
        wake = self._wake
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            # Loop is closing; harmless.
            pass

    # ── overridable hooks ──────────────────────────────────────────────────

    async def _on_start_hook(self) -> None:
        """Optional. Called once after the loop is wired but before the first
        `_drain_once`. Use for crash recovery (sweep stale rows, reset
        in-flight markers, etc). Exceptions are logged and swallowed."""

    @abc.abstractmethod
    async def _drain_once(self) -> None:
        """One iteration of work. Implementation responsibilities:
          * MUST eventually return (no infinite loops here — the parent loop
            handles scheduling).
          * MAY raise; parent will log + back off + retry.
          * SHOULD use asyncio.to_thread for blocking work.
        """

    # ── main loop (final) ──────────────────────────────────────────────────

    async def _run(self) -> None:
        assert self._wake is not None
        while not self._stopping:
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.poll_interval_s,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._stopping:
                return
            try:
                await self._drain_once()
            except Exception:
                log.exception("%s drain iteration crashed", self.name)
                await asyncio.sleep(self.error_backoff_s)


class JobRunner:
    """Owns a group of WorkerTasks and starts/stops them as a bundle.

    Usage in app.py lifespan:
        runner = JobRunner()
        runner.register(git_worker)
        runner.register(image_worker)        # future
        ...
        await runner.start_all()
        try:
            yield
        finally:
            await runner.stop_all()

    Workers are independent — start_all starts them concurrently, stop_all
    stops them concurrently; one worker's failure never affects others.
    """

    def __init__(self) -> None:
        self._workers: list[WorkerTask] = []
        self._by_name: dict[str, WorkerTask] = {}

    def register(self, worker: WorkerTask) -> None:
        if worker.name in self._by_name:
            raise ValueError(f"worker name already registered: {worker.name}")
        self._workers.append(worker)
        self._by_name[worker.name] = worker
        log.debug("job_runner registered worker=%s", worker.name)

    def get(self, name: str) -> WorkerTask | None:
        return self._by_name.get(name)

    def workers(self) -> Iterable[WorkerTask]:
        return tuple(self._workers)

    async def start_all(self) -> None:
        # Start sequentially — each start() is fast (just creates a task);
        # gather adds non-trivial complexity for negligible benefit.
        for w in self._workers:
            try:
                await w.start()
            except Exception:
                log.exception(
                    "job_runner failed to start worker=%s; continuing", w.name,
                )

    async def stop_all(self) -> None:
        # Stop concurrently so a single hung worker doesn't block shutdown
        # of others. Each worker has its own stop_grace_s timeout.
        if not self._workers:
            return
        results = await asyncio.gather(
            *(w.stop() for w in self._workers), return_exceptions=True,
        )
        for w, r in zip(self._workers, results):
            if isinstance(r, BaseException):
                log.warning("worker=%s stop raised: %r", w.name, r)
