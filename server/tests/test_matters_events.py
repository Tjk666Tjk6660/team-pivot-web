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
    TOPIC_RESULT_CREATED,
    TOPIC_STATUS_CHANGED,
    TOPIC_MATTER_VISIBILITY_CHANGED,
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


def test_make_sse_event_maps_visibility_changed_to_updated():
    sse = _make_sse_event(_evt(TOPIC_MATTER_VISIBILITY_CHANGED))
    assert sse is not None
    assert sse["event"] == "matter.updated"
    assert sse["data"]["reason"] == "visibility_changed"


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
