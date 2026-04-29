from __future__ import annotations

from server.matter_status import (
    EVENT_TRIGGERS_BY_TRANSITION,
    can_event_type_trigger,
)


def test_owner_change_triggers_planning_to_executing():
    assert can_event_type_trigger("owner_change", "planning", "executing")


def test_owner_change_does_not_trigger_other_transitions():
    other_transitions = [
        ("planning", "paused"),
        ("executing", "paused"),
        ("executing", "finished"),
        ("executing", "cancelled"),
        ("paused", "planning"),
        ("paused", "executing"),
        ("finished", "reviewed"),
        ("cancelled", "reviewed"),
    ]
    for from_, to in other_transitions:
        assert not can_event_type_trigger("owner_change", from_, to), (from_, to)


def test_unknown_event_type_does_not_trigger():
    assert not can_event_type_trigger("status_change", "planning", "executing")
    assert not can_event_type_trigger("", "planning", "executing")
    assert not can_event_type_trigger("comment", "planning", "executing")


def test_event_triggers_table_contains_only_legal_transitions():
    # Sanity: every (from, to) listed must be in ALLOWED_TRANSITIONS.
    from server.matter_status import ALLOWED_TRANSITIONS
    for (from_, to), _events in EVENT_TRIGGERS_BY_TRANSITION.items():
        assert to in ALLOWED_TRANSITIONS.get(from_, frozenset()), (from_, to)


def test_v1_event_triggers_table_only_planning_to_executing():
    # Lock down v1 scope: extending later requires explicit decision.
    assert set(EVENT_TRIGGERS_BY_TRANSITION.keys()) == {("planning", "executing")}
