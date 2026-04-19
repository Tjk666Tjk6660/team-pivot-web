from __future__ import annotations

from server.status_machine import can_transition, requires_reason


def test_open_transitions():
    assert can_transition("open", "concluded")
    assert can_transition("open", "closed")
    assert can_transition("open", "pending")


def test_reopen_transitions():
    assert can_transition("concluded", "open")
    assert can_transition("closed", "open")
    assert can_transition("pending", "open")


def test_disallowed_transitions():
    assert not can_transition("concluded", "closed")
    assert not can_transition("closed", "pending")
    assert not can_transition("pending", "closed")


def test_produced_is_terminal():
    assert not can_transition("produced", "open")
    assert not can_transition("produced", "closed")


def test_same_state_not_a_transition():
    assert not can_transition("open", "open")


def test_unknown_from_state():
    assert not can_transition("garbage", "open")


def test_requires_reason_only_on_reopen_from_concluded_or_closed():
    assert requires_reason("concluded", "open")
    assert requires_reason("closed", "open")
    assert not requires_reason("pending", "open")
    assert not requires_reason("open", "concluded")
    assert not requires_reason("open", "closed")
