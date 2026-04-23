from __future__ import annotations

import pytest

from server.events import (
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_CREATED,
    Event,
    clear_subscribers,
    emit,
    subscribe,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_subscribers()
    yield
    clear_subscribers()


def test_emit_returns_event_with_defaults():
    e = emit(TOPIC_MATTER_CREATED, matter_id="m1", actor="dengke",
            payload={"title": "x"})
    assert e.topic == "matter.created"
    assert e.matter_id == "m1"
    assert e.actor == "dengke"
    assert e.payload == {"title": "x"}
    assert e.at  # timestamp present


def test_subscriber_receives_event():
    bucket: list[Event] = []
    subscribe(bucket.append)
    emit(TOPIC_FILE_APPENDED, matter_id="m", actor="u", payload={"type": "think"})
    assert len(bucket) == 1
    assert bucket[0].topic == "matter.file_appended"
    assert bucket[0].payload["type"] == "think"


def test_multiple_subscribers_all_receive():
    a: list[Event] = []
    b: list[Event] = []
    subscribe(a.append)
    subscribe(b.append)
    emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u")
    assert len(a) == 1 and len(b) == 1


def test_unsubscribe_stops_delivery():
    bucket: list[Event] = []
    off = subscribe(bucket.append)
    emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u")
    off()
    emit(TOPIC_MATTER_CREATED, matter_id="m2", actor="u")
    assert len(bucket) == 1
    assert bucket[0].matter_id == "m"


def test_subscriber_exception_does_not_break_others():
    def bad(event):
        raise RuntimeError("boom")
    bucket: list[Event] = []
    subscribe(bad)
    subscribe(bucket.append)
    emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u")
    assert len(bucket) == 1


def test_clear_subscribers_removes_all():
    bucket: list[Event] = []
    subscribe(bucket.append)
    clear_subscribers()
    emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u")
    assert bucket == []


def test_emit_respects_custom_at():
    e = emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u", at="2026-04-23T10:00:00+08:00")
    assert e.at == "2026-04-23T10:00:00+08:00"


def test_emit_default_payload_is_empty_dict():
    e = emit(TOPIC_MATTER_CREATED, matter_id="m", actor="u")
    assert e.payload == {}
