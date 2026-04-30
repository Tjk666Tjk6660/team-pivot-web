"""Scoring queue + background asyncio worker + per-job orchestrator.

Architecture (design §5.2):
- ScoringQueue 跨线程：trigger 在 sync FastAPI threadpool 入队，worker 在
  asyncio loop 出队。用 `loop.call_soon_threadsafe` 桥接。
- ScoringWorker 单 worker 串行（v1 无并发；OpenRouter rate limit 友好）
- run_scoring_once 是 sync orchestrator，AI 调用通过 oneshot.generate_text
  (httpx 同步 + asyncio.run 内部)，所以 worker 用 asyncio.to_thread 卸载

Failure 路径全部走 store.finish_run('failed', error=...) 把短消息塞进 run.error，
admin UI 详情页能看见。绝不抛异常给上层（worker loop 不能死掉）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from typing import Awaitable, Callable

from server.ai.client import DEFAULT_BASE_URL, DEFAULT_MODEL
from server.ai.oneshot import AIError, generate_text
from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUserRepo
from server.posts import read_post
from server.scoring.ai_runner import AdaptError, build_score_writes, build_weight_map
from server.scoring.prompt import (
    PromptTooLargeError,
    build_scoring_prompt,
)
from server.scoring.resolve import PinyinResolver
from server.scoring.schema import SchemaError, parse_and_validate
from server.scoring.store import ScoringJob, ScoringStore
from server.scoring.trigger import (
    KEY_MODEL,
    KEY_TIMEOUT_SECONDS,
)
from server.settings import SettingsRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)

# AI endpoint settings shared with the chat assistant (server/api/ai.py).
# Scoring overrides only the model; api_key + base_url come from the same
# admin-configured slot.
_AI_KEY_API_KEY = "ai.openrouter_api_key"
_AI_KEY_BASE_URL = "ai.base_url"
_AI_KEY_MODEL = "ai.model"

DEFAULT_TIMEOUT_SECONDS = 120.0


# ---------- queue ----------


class ScoringQueue:
    """Thread-safe enqueue → asyncio await bridge.

    Usage:
      worker = ScoringWorker(queue, ...)
      await worker.start()           # attaches the queue to current loop
      ...
      queue.enqueue(job)             # called from any thread
      ...
      await worker.stop()            # signals via sentinel
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._q: asyncio.Queue | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is not None:
            raise RuntimeError("ScoringQueue already attached to a loop")
        self._loop = loop
        self._q = asyncio.Queue()

    def detach(self) -> None:
        """Release the loop binding. Used by tests + stop()."""
        self._loop = None
        self._q = None

    def enqueue(self, job: ScoringJob) -> None:
        """Thread-safe. No-op + warning if not attached (would only happen
        between server boot and worker start)."""
        loop = self._loop
        q = self._q
        if loop is None or q is None:
            log.warning(
                "scoring queue not attached, dropping job for matter=%s",
                job.matter_id,
            )
            return
        loop.call_soon_threadsafe(q.put_nowait, job)

    def signal_stop(self) -> None:
        """Push a sentinel so the worker exits its receive loop."""
        loop = self._loop
        q = self._q
        if loop is None or q is None:
            return
        loop.call_soon_threadsafe(q.put_nowait, None)

    async def get(self) -> ScoringJob | None:
        """Await next job. None = stop sentinel."""
        if self._q is None:
            raise RuntimeError("queue not attached")
        return await self._q.get()


# ---------- worker ----------


# Hook type for tests to substitute a fake AI call without monkeypatching the
# global generate_text (cleaner stack traces, easier to inspect call args).
AICall = Callable[..., str]


class ScoringWorker:
    """Background asyncio task draining ScoringQueue serially."""

    def __init__(
        self,
        *,
        queue: ScoringQueue,
        store: ScoringStore,
        workspace: Workspace,
        settings: SettingsRepo,
        pivot_users: PivotUserRepo,
        ai_call: AICall = generate_text,
    ) -> None:
        self._queue = queue
        self._store = store
        self._workspace = workspace
        self._settings = settings
        self._pivot_users = pivot_users
        self._ai_call = ai_call
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._queue.attach(loop)
        self._task = asyncio.create_task(self._run(), name="scoring-worker")
        log.info("scoring worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._queue.signal_stop()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("scoring worker raised on shutdown")
        finally:
            self._queue.detach()
            self._task = None
            log.info("scoring worker stopped")

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                return  # stop sentinel
            try:
                await asyncio.to_thread(
                    run_scoring_once, job,
                    store=self._store,
                    workspace=self._workspace,
                    settings=self._settings,
                    pivot_users=self._pivot_users,
                    ai_call=self._ai_call,
                )
            except Exception:
                # Defense: run_scoring_once should already swallow + finish_run,
                # but if it throws unexpectedly we still must not kill the loop.
                log.exception(
                    "scoring worker iteration failed matter=%s",
                    job.matter_id,
                )


# ---------- per-job orchestrator ----------


def run_scoring_once(
    job: ScoringJob,
    *,
    store: ScoringStore,
    workspace: Workspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
    ai_call: AICall = generate_text,
) -> None:
    """Run one scoring job end-to-end. Sync; called from worker thread.

    Any failure path lands as either:
      - mark_skipped: pre-AI conditions not met (matter missing, no owner, dup)
      - finish_run('failed', error=...): we did start a run but it didn't make it
        to a successful score
      - finish_run('success'): score row + evidence written, OR AI explicitly
        skipped (empty scores, subject in skipped_subjects)

    NEVER raises — failures are logged + recorded in run.error.
    """
    try:
        _run_scoring_once_inner(
            job, store=store, workspace=workspace, settings=settings,
            pivot_users=pivot_users, ai_call=ai_call,
        )
    except Exception:
        # Unexpected — try to record the matter even if no run was created
        log.exception(
            "scoring orchestrator unexpected failure matter=%s subject=%s",
            job.matter_id, job.subject_user_id,
        )


def _run_scoring_once_inner(
    job: ScoringJob,
    *,
    store: ScoringStore,
    workspace: Workspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
    ai_call: AICall,
) -> None:
    # 1. Read current matter index (re-read in case index changed since trigger)
    index = read_matter_index(matter_index_path(workspace.index_dir, job.matter_id))
    if index is None:
        log.info("scoring: matter index missing matter=%s", job.matter_id)
        store.mark_skipped(job, timeline_hash="", reason="matter_not_found")
        return

    timeline_hash = compute_timeline_hash(index)

    # 2. Idempotency check (auto only; admin:rerun bypasses)
    if job.triggered_by != "admin:rerun" and store.has_success(
        job.matter_id, timeline_hash,
    ):
        log.info(
            "scoring: duplicate timeline matter=%s hash=%s",
            job.matter_id, timeline_hash[:12],
        )
        store.mark_skipped(job, timeline_hash=timeline_hash, reason="duplicate_timeline")
        return

    # 3. Re-fetch owner (handles rare race: owner changed between trigger
    # and now). Use timeline pinyin as the prompt subject.
    owner_pinyin = (index.get("matter") or {}).get("owner") or ""
    if not owner_pinyin:
        store.mark_skipped(job, timeline_hash=timeline_hash, reason="no_owner")
        return

    # 4. Load AI endpoint
    ai_settings = _load_ai_endpoint(settings)
    model = (settings.get(KEY_MODEL) or "").strip()
    if not model and ai_settings is not None:
        model = ai_settings.model
    if not model:
        model = DEFAULT_MODEL

    if ai_settings is None:
        # No api_key — record a failed run so admin sees why
        run_id = _try_start_run(store, job, timeline_hash=timeline_hash, model=model)
        if run_id is not None:
            store.finish_run(run_id, "failed", error="ai_key_missing")
        return

    # 5. Start the run (atomic with idempotency check via partial unique idx)
    run_id = _try_start_run(store, job, timeline_hash=timeline_hash, model=model)
    if run_id is None:
        # Lost the idempotency race — another run is in flight
        store.mark_skipped(job, timeline_hash=timeline_hash, reason="race_lost")
        return

    store.transition_running(run_id)

    # 6. Build prompt (incl. weight map + file body loader)
    resolver = PinyinResolver(pivot_users._db)
    weights = store.list_weights()
    weight_map = build_weight_map(weights, resolver)

    def file_body_loader(file_rel: str) -> str:
        return _read_file_body(workspace, file_rel)

    try:
        messages = build_scoring_prompt(
            index_data=index,
            weight_map=weight_map,
            subject_pinyin=owner_pinyin,
            file_body_loader=file_body_loader,
        )
    except PromptTooLargeError as e:
        store.finish_run(run_id, "failed", error=f"prompt_too_large: {e}"[:500])
        return

    # 7. Call AI
    timeout = _load_timeout(settings)
    try:
        raw = ai_call(
            messages=messages,
            model=model,
            api_key=ai_settings.api_key,
            base_url=ai_settings.base_url,
            timeout_seconds=timeout,
        )
    except (AIError, TimeoutError, asyncio.TimeoutError) as e:
        store.finish_run(
            run_id, "failed",
            error=f"ai_error: {type(e).__name__}: {str(e)[:200]}",
        )
        return
    except Exception as e:  # noqa: BLE001
        store.finish_run(
            run_id, "failed",
            error=f"ai_unexpected: {type(e).__name__}: {str(e)[:200]}",
        )
        return

    # 8. Parse + validate (anti-fabrication)
    try:
        parsed = parse_and_validate(raw, index, expected_subject=owner_pinyin)
    except SchemaError as e:
        store.finish_run(run_id, "failed", error=f"schema_error: {e}"[:500])
        return

    # 9. Adapt to store types (pinyin → user_id, server-authoritative weight)
    try:
        result = build_score_writes(parsed, resolver=resolver, weight_map=weight_map)
    except AdaptError as e:
        store.finish_run(run_id, "failed", error=f"adapt_error: {e}"[:500])
        return

    if result is None:
        # AI explicitly skipped (empty scores + subject in skipped_subjects)
        log.info(
            "scoring: AI skipped subject (insufficient evidence) matter=%s run=%s",
            job.matter_id, run_id,
        )
        store.finish_run(run_id, "success")
        return

    score_write, evidence_writes = result
    try:
        store.write_results(run_id, score_write, evidence_writes)
    except ValueError as e:
        store.finish_run(run_id, "failed", error=f"store_error: {e}"[:500])
        return

    store.finish_run(run_id, "success")
    log.info(
        "scoring success matter=%s run=%s overall=%.2f confidence=%s",
        job.matter_id, run_id, score_write.overall, score_write.confidence,
    )


# ---------- helpers ----------


class _AIEndpointConfig:
    """Tuple-like with .api_key/.base_url/.model — reuses daily_report's pattern."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model


def _load_ai_endpoint(settings: SettingsRepo) -> _AIEndpointConfig | None:
    """Pull api_key + base_url + default model from main AI settings.

    Returns None if api_key isn't configured (admin must set it via
    /admin/ai/settings before scoring works)."""
    api_key = (settings.get(_AI_KEY_API_KEY) or "").strip()
    if not api_key:
        return None
    base_url = (settings.get(_AI_KEY_BASE_URL) or DEFAULT_BASE_URL).strip()
    model = (settings.get(_AI_KEY_MODEL) or DEFAULT_MODEL).strip()
    return _AIEndpointConfig(api_key=api_key, base_url=base_url, model=model)


def _load_timeout(settings: SettingsRepo) -> float:
    raw = (settings.get(KEY_TIMEOUT_SECONDS) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        v = float(raw)
        if 1.0 <= v <= 600.0:
            return v
    except ValueError:
        pass
    log.warning("scoring invalid timeout_seconds=%r, using %.0f", raw, DEFAULT_TIMEOUT_SECONDS)
    return DEFAULT_TIMEOUT_SECONDS


def _read_file_body(workspace: Workspace, file_rel: str) -> str:
    """Mirror of api/matters._read_item_body — read the .md body via posts.read_post.

    Returns empty string if path doesn't start with discussions/, file is
    missing, or parsing fails. Never raises.
    """
    if not file_rel.startswith("discussions/"):
        return ""
    path = workspace.path / file_rel
    if not path.is_file():
        return ""
    try:
        return read_post(path).body
    except Exception:
        return ""


def _try_start_run(
    store: ScoringStore,
    job: ScoringJob,
    *,
    timeline_hash: str,
    model: str,
) -> str | None:
    """Attempt to start a run; return None on idempotency-index conflict.

    The partial unique index (matter_id, timeline_hash) WHERE status IN
    ('queued','running','success') guarantees only one in-flight run per
    timeline version. A duplicate insert raises sqlite3.IntegrityError —
    we catch and surface as "race_lost" via the caller."""
    try:
        return store.start_run(job, timeline_hash=timeline_hash, model=model)
    except sqlite3.IntegrityError:
        return None


def compute_timeline_hash(index: dict) -> str:
    """Stable canonical hash of the matter+timeline blocks.

    Used as the idempotency key — same content yields same hash, so an
    auto-trigger that arrives twice for the same finished state collapses
    into one run. A subsequent edit (new comment, new file, owner change)
    changes the hash and re-allows running.
    """
    canonical = json.dumps(
        {
            "matter": index.get("matter"),
            "timeline": index.get("timeline"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
