from __future__ import annotations

VALID_STATES = frozenset({
    "planning",
    "executing",
    "paused",
    "finished",
    "cancelled",
    "reviewed",
})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "planning": frozenset({"executing", "paused"}),
    "executing": frozenset({"paused", "finished", "cancelled"}),
    "paused": frozenset({"planning", "executing"}),
    "finished": frozenset({"reviewed"}),
    "cancelled": frozenset({"reviewed"}),
    "reviewed": frozenset(),
}

# Which file type is allowed to carry each status_change.
# A file not listed for a given (from, to) cannot trigger that transition.
TRIGGER_TYPES_BY_TRANSITION: dict[tuple[str, str], frozenset[str]] = {
    ("planning", "executing"): frozenset({"act"}),
    ("planning", "paused"): frozenset({"think"}),
    ("executing", "paused"): frozenset({"think"}),
    ("executing", "finished"): frozenset({"result"}),
    ("executing", "cancelled"): frozenset({"result"}),
    ("paused", "planning"): frozenset({"think"}),
    ("paused", "executing"): frozenset({"think"}),
    ("finished", "reviewed"): frozenset({"insight"}),
    ("cancelled", "reviewed"): frozenset({"insight"}),
}


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return False
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def trigger_types_for(from_state: str, to_state: str) -> frozenset[str]:
    return TRIGGER_TYPES_BY_TRANSITION.get((from_state, to_state), frozenset())


def can_file_type_trigger(file_type: str, from_state: str, to_state: str) -> bool:
    return file_type in trigger_types_for(from_state, to_state)
