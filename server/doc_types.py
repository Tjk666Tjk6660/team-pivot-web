from __future__ import annotations

VALID_DOC_TYPES = frozenset({"think", "act", "verify", "result", "insight"})

# Event-type timeline entries (no MD file, no body, no status × type matrix).
# Currently only owner_change; kept as a frozenset so adding future event types
# (e.g., assignment, reminder) doesn't ripple through callers.
VALID_EVENT_TYPES = frozenset({"owner_change"})

# status × type allow matrix.
# Literal port of pivot-interface.md "最小服务端校验建议", with two documented deviations
# from pivot-product.md §五 logged in AI-docs/coding-test-plan/deviations.md:
#   - executing + result is allowed unconditionally (no "准备结束时" gating)
#   - reviewed is a strict deny (the "原则上不再新增" softening is resolved to a hard rule)
ALLOWED_TYPES_BY_STATUS: dict[str, frozenset[str]] = {
    "planning": frozenset({"think", "act", "verify"}),
    "executing": frozenset({"think", "act", "verify", "result"}),
    "paused": frozenset({"think"}),
    "finished": frozenset({"insight"}),
    "cancelled": frozenset({"insight"}),
    "reviewed": frozenset(),
}

VALID_JUDGEMENTS = frozenset({"passed", "failed", "cancelled"})
VALID_OUTCOMES = frozenset({"finished", "cancelled"})


def is_doc_type(value: str) -> bool:
    return value in VALID_DOC_TYPES


def is_type_allowed_in_status(doc_type: str, status: str) -> bool:
    return doc_type in ALLOWED_TYPES_BY_STATUS.get(status, frozenset())
