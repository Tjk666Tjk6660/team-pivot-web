from __future__ import annotations

VALID_STATES = frozenset({"open", "concluded", "produced", "closed", "pending"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"concluded", "closed", "pending"}),
    "concluded": frozenset({"open"}),
    "closed": frozenset({"open"}),
    "pending": frozenset({"open"}),
    "produced": frozenset(),
}

REOPEN_TRANSITIONS = frozenset({("concluded", "open"), ("closed", "open")})
REASON_MIN_LEN = 3


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return False
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def requires_reason(from_state: str, to_state: str) -> bool:
    return (from_state, to_state) in REOPEN_TRANSITIONS
