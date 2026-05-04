from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


# Topic names (string constants rather than an Enum so subscribers can match by str)
TOPIC_MATTER_CREATED = "matter.created"
TOPIC_FILE_APPENDED = "matter.file_appended"
TOPIC_COMMENT_APPENDED = "matter.comment_appended"
TOPIC_STATUS_CHANGED = "matter.status_changed"
TOPIC_RESULT_CREATED = "matter.result_created"
TOPIC_MATTER_OWNER_CHANGED = "matter.owner_changed"
# Invalidation/restoration events on a matter's timeline. Emitted by
# publish_matter_event when an author withdraws or restores their own file.
# SSE layer maps this to "matter.updated" with reason="event_appended" (thin SSE).
TOPIC_MATTER_EVENT_APPENDED = "matter.event_appended"


@dataclass(frozen=True)
class Event:
    topic: str
    matter_id: str
    actor: str
    at: str
    payload: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[Event], None]

_subscribers: list[Subscriber] = []


def subscribe(subscriber: Subscriber) -> Callable[[], None]:
    """Register a subscriber. Returns an unsubscribe function."""
    _subscribers.append(subscriber)

    def unsubscribe() -> None:
        try:
            _subscribers.remove(subscriber)
        except ValueError:
            pass

    return unsubscribe


def emit(
    topic: str,
    *,
    matter_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    at: str | None = None,
) -> Event:
    event = Event(
        topic=topic,
        matter_id=matter_id,
        actor=actor,
        at=at or _now_iso(),
        payload=payload or {},
    )
    log.info(
        "event topic=%s matter=%s actor=%s", event.topic, event.matter_id, event.actor,
        extra={"event": _event_to_dict(event)},
    )
    for sub in list(_subscribers):
        try:
            sub(event)
        except Exception:
            log.exception("event subscriber failed topic=%s", topic)
    return event


def clear_subscribers() -> None:
    """Intended for tests only."""
    _subscribers.clear()


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "topic": event.topic,
        "matter_id": event.matter_id,
        "actor": event.actor,
        "at": event.at,
        "payload": event.payload,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
