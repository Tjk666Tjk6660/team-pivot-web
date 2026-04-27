from __future__ import annotations

import pytest

from server.matter_status import (
    ALLOWED_TRANSITIONS,
    VALID_STATES,
    can_file_type_trigger,
    can_transition,
    trigger_types_for,
)


def test_valid_states_are_six():
    assert VALID_STATES == {
        "planning", "executing", "paused", "finished", "cancelled", "reviewed",
    }


@pytest.mark.parametrize("frm,to", [
    ("planning", "executing"),
    ("planning", "paused"),
    ("executing", "paused"),
    ("executing", "finished"),
    ("executing", "cancelled"),
    ("paused", "planning"),
    ("paused", "executing"),
    ("finished", "reviewed"),
    ("cancelled", "reviewed"),
])
def test_allowed_transitions(frm, to):
    assert can_transition(frm, to)


@pytest.mark.parametrize("frm,to", [
    ("planning", "finished"),
    ("planning", "cancelled"),
    ("planning", "reviewed"),
    ("executing", "planning"),
    ("executing", "reviewed"),
    ("paused", "finished"),
    ("paused", "cancelled"),
    ("paused", "reviewed"),
    ("finished", "cancelled"),
    ("finished", "executing"),
    ("cancelled", "finished"),
    ("cancelled", "executing"),
    ("reviewed", "finished"),
    ("reviewed", "cancelled"),
    ("reviewed", "planning"),
])
def test_disallowed_transitions(frm, to):
    assert not can_transition(frm, to)


def test_reviewed_is_terminal():
    assert ALLOWED_TRANSITIONS["reviewed"] == frozenset()
    for s in VALID_STATES:
        assert not can_transition("reviewed", s)


def test_same_state_not_a_transition():
    for s in VALID_STATES:
        assert not can_transition(s, s)


def test_unknown_from_state():
    assert not can_transition("garbage", "planning")


@pytest.mark.parametrize("frm,to,expected", [
    ("planning", "executing", {"act"}),
    ("planning", "paused", {"think"}),
    ("executing", "paused", {"think"}),
    ("executing", "finished", {"result"}),
    ("executing", "cancelled", {"result"}),
    ("paused", "planning", {"think"}),
    ("paused", "executing", {"think"}),
    ("finished", "reviewed", {"insight"}),
    ("cancelled", "reviewed", {"insight"}),
])
def test_trigger_types_for_each_transition(frm, to, expected):
    assert set(trigger_types_for(frm, to)) == expected


def test_trigger_types_for_invalid_transition_empty():
    assert trigger_types_for("planning", "reviewed") == frozenset()


def test_can_file_type_trigger_positive():
    assert can_file_type_trigger("result", "executing", "finished")
    assert can_file_type_trigger("insight", "finished", "reviewed")
    assert can_file_type_trigger("think", "executing", "paused")


def test_can_file_type_trigger_negative():
    assert not can_file_type_trigger("think", "executing", "finished")
    assert not can_file_type_trigger("result", "planning", "executing")
    assert not can_file_type_trigger("verify", "executing", "finished")
