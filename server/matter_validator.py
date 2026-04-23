from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.doc_types import (
    ALLOWED_TYPES_BY_STATUS,
    VALID_DOC_TYPES,
    VALID_JUDGEMENTS,
    VALID_OUTCOMES,
)
from server.matter_status import (
    VALID_STATES,
    can_file_type_trigger,
    can_transition,
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    code: str | None = None
    field: str | None = None
    message: str | None = None


OK = ValidationResult(ok=True)


def _fail(code: str, field: str | None, message: str) -> ValidationResult:
    return ValidationResult(ok=False, code=code, field=field, message=message)


def validate_append(
    index_data: dict[str, Any], item: dict[str, Any]
) -> ValidationResult:
    """Validate a proposed timeline item against a loaded matter index.

    Pure function: no IO. The matter_index writer is expected to call this
    function internally as a second gate (the API layer calls it first to
    produce precise 422 responses).

    index_data is the YAML-loaded shape: {"matter": {...}, "timeline": [...]}.
    item is the proposed new timeline entry in the same shape.
    """
    matter = index_data.get("matter") or {}
    current_status = matter.get("current_status")
    if current_status not in VALID_STATES:
        return _fail(
            "unknown_matter_status",
            "matter.current_status",
            f"unknown status: {current_status!r}",
        )

    doc_type = item.get("type")
    if not doc_type:
        return _fail("type_missing", "type", "file type is required")
    if doc_type not in VALID_DOC_TYPES:
        return _fail("unknown_type", "type", f"unknown type: {doc_type!r}")

    if doc_type not in ALLOWED_TYPES_BY_STATUS.get(current_status, frozenset()):
        return _fail(
            "type_not_allowed",
            "type",
            f"type {doc_type!r} not allowed when matter is {current_status!r}",
        )

    sc = item.get("status_change")
    if sc:
        frm = sc.get("from")
        to = sc.get("to")
        if frm != current_status:
            return _fail(
                "status_change_from_mismatch",
                "status_change.from",
                f"status_change.from {frm!r} does not match current {current_status!r}",
            )
        if not can_transition(frm, to):
            return _fail(
                "status_change_not_allowed",
                "status_change",
                f"transition {frm!r} -> {to!r} is not allowed",
            )
        if not can_file_type_trigger(doc_type, frm, to):
            return _fail(
                "status_change_trigger_mismatch",
                "type",
                f"type {doc_type!r} cannot trigger {frm!r} -> {to!r}",
            )

    if doc_type == "verify":
        err = _validate_verify_shape(item)
        if err:
            return err

    if doc_type == "result":
        err = _validate_result_shape(item, sc)
        if err:
            return err

    return OK


def _validate_verify_shape(item: dict[str, Any]) -> ValidationResult | None:
    verifications = item.get("verifications")
    if verifications is None:
        return _fail(
            "verifications_required",
            "verifications",
            "verify requires verifications[]",
        )
    if not isinstance(verifications, list) or len(verifications) == 0:
        return _fail(
            "verifications_empty",
            "verifications",
            "verifications must be a non-empty list",
        )
    for i, v in enumerate(verifications):
        if not isinstance(v, dict):
            return _fail(
                "invalid_verification",
                f"verifications[{i}]",
                "each verification must be an object",
            )
        if not v.get("target"):
            return _fail(
                "verification_target_required",
                f"verifications[{i}].target",
                "verification target is required",
            )
        judgement = v.get("judgement")
        if judgement not in VALID_JUDGEMENTS:
            return _fail(
                "invalid_judgement",
                f"verifications[{i}].judgement",
                f"judgement must be one of {sorted(VALID_JUDGEMENTS)}",
            )
    return None


def _validate_result_shape(
    item: dict[str, Any], sc: dict[str, Any] | None
) -> ValidationResult | None:
    outcome = item.get("outcome")
    if not outcome:
        return _fail("outcome_required", "outcome", "result requires outcome")
    if outcome not in VALID_OUTCOMES:
        return _fail(
            "invalid_outcome",
            "outcome",
            f"outcome must be one of {sorted(VALID_OUTCOMES)}",
        )
    if not sc:
        return _fail(
            "result_without_status_change",
            "status_change",
            "result must carry status_change to finished or cancelled",
        )
    return None
