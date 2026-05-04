"""Unit tests for the SSE adapter at server/api/matters_events.py.

We focus on the pure mapping function `_make_sse_event` rather than spinning
up a real EventSource — the I/O wrapping is thin and stable, but the topic
filter is where regressions land.
"""

from __future__ import annotations

from server.api.matters_events import _make_sse_event
from server.events import (
    Event,
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_CREATED,
    TOPIC_MATTER_EVENT_APPENDED,
    TOPIC_RESULT_CREATED,
    TOPIC_STATUS_CHANGED,
)


def _evt(topic) -> Event:
    return Event(
        topic=topic,
        matter_id="m1",
        actor="alice",
        at="2026-04-27T20:00:00+08:00",
        payload={},
    )


def test_make_sse_event_maps_created_topic():
    sse = _make_sse_event(_evt(TOPIC_MATTER_CREATED))
    assert sse is not None
    assert sse["event"] == "matter.created"
    assert sse["data"]["reason"] == "created"


def test_make_sse_event_maps_file_appended_to_updated():
    sse = _make_sse_event(_evt(TOPIC_FILE_APPENDED))
    assert sse is not None
    assert sse["event"] == "matter.updated"
    assert sse["data"]["reason"] == "file_appended"


def test_make_sse_event_maps_comment_appended_to_updated():
    """Comment events take the same wire shape as file events — frontend
    handler treats them identically (both trigger matters-list refetch),
    so unread_count differences must come from the inbox computation, not
    from a divergent SSE payload."""
    sse = _make_sse_event(_evt(TOPIC_COMMENT_APPENDED))
    assert sse is not None
    assert sse["event"] == "matter.updated"
    assert sse["data"]["reason"] == "comment_appended"


def test_make_sse_event_drops_status_changed_and_result():
    """status_changed / result_created always travel with a file_appended,
    so the SSE adapter intentionally drops them to avoid double refreshes."""
    assert _make_sse_event(_evt(TOPIC_STATUS_CHANGED)) is None
    assert _make_sse_event(_evt(TOPIC_RESULT_CREATED)) is None


def test_make_sse_event_envelope_has_required_keys():
    sse = _make_sse_event(_evt(TOPIC_MATTER_CREATED))
    assert sse is not None
    assert set(sse.keys()) == {"id", "event", "data"}
    assert "-" in sse["id"]  # <ms-ts>-<seq>
    assert {"matter_id", "reason", "actor", "at"} == set(sse["data"].keys())


def test_make_sse_event_maps_event_appended_thin():
    """Invalidation/restoration events (P1–P3) are thin: they ride the same
    `matter.updated` SSE event name with reason='event_appended', so the
    front-end treats them identically to file/comment updates and refetches
    the full matter detail. Per AI-docs/invalidate-self/product-design.md §5.1.

    Critically, the SSE data payload must NOT carry business fields (target_file,
    summary, etc.) — those live in the events.py bus payload for the notifier
    but are stripped at the SSE boundary.
    """
    bus_event = Event(
        topic=TOPIC_MATTER_EVENT_APPENDED,
        matter_id="m1",
        actor="dengke",
        at="2026-04-27T20:00:00+08:00",
        payload={
            "target_file": "discussions/Pivot/m1/002_dengke_act_x.md",
            "reason": "misposted",
            "summary": "误发,撤回",
        },
    )
    sse = _make_sse_event(bus_event)
    assert sse is not None
    assert sse["event"] == "matter.updated"
    assert sse["data"]["reason"] == "event_appended"
    assert sse["data"]["matter_id"] == "m1"
    assert sse["data"]["actor"] == "dengke"
    # Thin SSE: business fields must NOT leak into the SSE data payload
    assert "target_file" not in sse["data"]
    assert "summary" not in sse["data"]
