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

from server.db import Database
from server.events import (
    Event,
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_CREATED,
    TOPIC_MATTER_OWNER_CHANGED,
    TOPIC_MATTER_VISIBILITY_CHANGED,
    subscribe,
)
from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUser
from server.visibility_scopes import VisibilityScope
from server.visibility_store import read_category_visibility
from server.workspace import Workspace


log = logging.getLogger("server.api.matters_events")


# Map internal topics to SSE event names + reason strings. Topics outside this
# map are ignored (e.g. STATUS_CHANGED / RESULT_CREATED are out of scope for v1).
_TOPIC_MAP: dict[str, tuple[str, str]] = {
    TOPIC_MATTER_CREATED: ("matter.created", "created"),
    TOPIC_FILE_APPENDED: ("matter.updated", "file_appended"),
    TOPIC_COMMENT_APPENDED: ("matter.updated", "comment_appended"),
    TOPIC_MATTER_OWNER_CHANGED: ("matter.updated", "owner_changed"),
    TOPIC_MATTER_VISIBILITY_CHANGED: ("matter.updated", "visibility_changed"),
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


def build_router(
    current_user: Callable,
    workspace: Workspace | None = None,
    db: Database | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/matters/events")
    async def stream_matter_events(
        request: Request,
        user: PivotUser = Depends(current_user),
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
            if not _can_read_event(sse, user, workspace, db):
                return
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
                    if not _can_read_event(item, user, workspace, db):
                        continue
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


def _can_read_event(
    item: dict[str, Any],
    user: PivotUser,
    workspace: Workspace | None,
    db: Database | None,
) -> bool:
    if workspace is None:
        return True
    matter_id = str((item.get("data") or {}).get("matter_id") or "")
    if not matter_id:
        return True
    data = read_matter_index(matter_index_path(workspace.index_dir, matter_id))
    if data is None:
        return False
    return _can_read_matter(data, user, workspace, db)


def _can_read_matter(
    data: dict,
    user: PivotUser,
    workspace: Workspace,
    db: Database | None,
) -> bool:
    roles = _roles_for_user(user, db)
    category = _matter_category(data)
    if category:
        category_visibility = read_category_visibility(
            workspace.path / "categories",
            category,
        )
        if category_visibility.mode == "restricted" and not (
            set(roles) & set(category_visibility.authorized_roles)
        ):
            return False
    visibility = VisibilityScope.from_dict((data.get("matter") or {}).get("visibility"))
    if visibility.mode == "public":
        return True
    if set(roles) & set(visibility.roles):
        return True
    return bool(set(_identifiers_for_user(user)) & set(visibility.user_ids))


def _matter_category(data: dict) -> str | None:
    timeline = data.get("timeline") or []
    if not timeline:
        return None
    parts = str(timeline[0].get("file") or "").split("/")
    if len(parts) >= 4 and parts[0] == "discussions":
        return parts[1]
    return None


def _identifiers_for_user(user: PivotUser) -> list[str]:
    values = [
        getattr(user, "id", None),
        getattr(user, "open_id", None),
        getattr(user, "pinyin", None),
        getattr(user, "email", None),
    ]
    return [str(v) for v in values if v]


def _roles_for_user(user: PivotUser, db: Database | None) -> list[str]:
    roles = getattr(user, "roles", None)
    if isinstance(roles, list):
        return [str(role) for role in roles]
    if db is None:
        return []
    identifiers = _identifiers_for_user(user)
    if not identifiers:
        return []
    placeholders = ",".join("?" for _ in identifiers)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT role FROM pivot_user"
            f" WHERE status='active' AND (id IN ({placeholders})"
            f" OR pinyin IN ({placeholders}) OR email IN ({placeholders}))"
            " LIMIT 1",
            (*identifiers, *identifiers, *identifiers),
        ).fetchone()
    if row is None:
        return []
    return _decode_role_list(row["role"])


def _decode_role_list(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    return [value]
