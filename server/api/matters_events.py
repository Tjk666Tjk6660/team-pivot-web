"""SSE notification stream for matter changes.

Subscribes to the existing in-process event bus (server/events.py) and fans
each matter-related event out to connected clients as a thin SSE frame:

    event: matter.created | matter.updated
    id:    <ms-timestamp>-<seq>
    data:  {"matter_id": "...", "reason": "...", "actor": "...", "at": "..."}

The frame intentionally carries only the matter id + reason. Clients fetch
real data via existing REST endpoints (/api/matters, /api/matters/{id}).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from collections import deque
from typing import Any, Callable, Deque

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from server.events import (
    Event,
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_CREATED,
    TOPIC_MATTER_OWNER_CHANGED,
    subscribe,
)
from server.users import User


log = logging.getLogger("server.api.matters_events")


# Map internal topics to SSE event names + reason strings. Topics outside this
# map are ignored (e.g. STATUS_CHANGED / RESULT_CREATED are out of scope for v1).
_TOPIC_MAP: dict[str, tuple[str, str]] = {
    TOPIC_MATTER_CREATED: ("matter.created", "created"),
    TOPIC_FILE_APPENDED: ("matter.updated", "file_appended"),
    TOPIC_COMMENT_APPENDED: ("matter.updated", "comment_appended"),
    TOPIC_MATTER_OWNER_CHANGED: ("matter.updated", "owner_changed"),
}

# Process-level ring buffer for Last-Event-ID replay. New connections that
# present a Last-Event-ID header receive any later events still in the ring
# before live tailing begins. The buffer is best-effort: clients also do a
# resume-refetch on reconnect, so missing replay entries are recoverable.
_RING_MAXLEN = 512
_ring: Deque[dict[str, Any]] = deque(maxlen=_RING_MAXLEN)
_seq = itertools.count(1)

# Per-connection queue size. If a client cannot drain fast enough we drop the
# event silently; the front-end's reconnect/visibility resume path will cover
# the gap with a full refetch.
_QUEUE_MAXLEN = 256

# Idle ping interval (seconds). Keeps long-lived connections alive across
# proxies and verifies liveness without a real event.
_PING_INTERVAL_SEC = 25.0


def _make_sse_event(event: Event) -> dict[str, Any] | None:
    """Translate a bus Event to an SSE-shaped dict, or None if not relevant."""
    mapped = _TOPIC_MAP.get(event.topic)
    if mapped is None:
        return None
    sse_name, reason = mapped
    return {
        "id": f"{int(time.time() * 1000)}-{next(_seq)}",
        "event": sse_name,
        "data": {
            "matter_id": event.matter_id,
            "reason": reason,
            "actor": event.actor,
            "at": event.at,
        },
    }


def _format_frame(item: dict[str, Any]) -> str:
    return (
        f"id: {item['id']}\n"
        f"event: {item['event']}\n"
        f"data: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
    )


def _replay_after(last_id: str | None) -> list[dict[str, Any]]:
    """Return events from the ring strictly newer than last_id."""
    if not last_id:
        return []
    out: list[dict[str, Any]] = []
    seen = False
    # Linear scan; ring is small (<= 512). Order is preserved by deque.
    for item in list(_ring):
        if seen:
            out.append(item)
            continue
        if item["id"] == last_id:
            seen = True
    return out


def build_router(current_user: Callable) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/matters/events")
    async def stream_matter_events(
        request: Request,
        user: User = Depends(current_user),
    ) -> StreamingResponse:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXLEN)

        def on_event(event: Event) -> None:
            sse = _make_sse_event(event)
            if sse is None:
                return
            # Append to the global ring (single-writer per emit, deque is
            # thread-safe for append). Subsequent connections can replay it.
            _ring.append(sse)
            # Hand off to the connection's own queue. put_nowait is safe to
            # call from any thread because Queue uses an internal lock; but to
            # play well with the asyncio loop we route through call_soon_threadsafe.
            try:
                loop.call_soon_threadsafe(_offer_nowait, queue, sse)
            except RuntimeError:
                # Loop already closed / connection torn down.
                pass

        unsubscribe = subscribe(on_event)
        last_id = request.headers.get("last-event-id")

        async def generator() -> Any:
            try:
                yield ":connected\n\n"
                # Replay any events newer than the resume id, before live tail.
                for item in _replay_after(last_id):
                    yield _format_frame(item)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(
                            queue.get(), timeout=_PING_INTERVAL_SEC
                        )
                        yield _format_frame(item)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                unsubscribe()
                log.debug("matter events stream closed user=%s", user.open_id)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # nginx: do not buffer SSE; flush every chunk to the client.
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _offer_nowait(queue: asyncio.Queue[dict[str, Any]], item: dict[str, Any]) -> None:
    """Best-effort enqueue. On overflow we drop the event; the client's resume
    path (visibility / reconnect) will recover via full refetch."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        log.warning("matter events queue full, dropping event id=%s", item.get("id"))
