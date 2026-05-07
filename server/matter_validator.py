from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.doc_types import (
    ALLOWED_TYPES_BY_STATUS,
    VALID_DOC_TYPES,
    VALID_EVENT_REASONS,
    VALID_EVENT_TYPES,
    VALID_JUDGEMENTS,
    VALID_OUTCOMES,
)
from server.matter_status import (
    VALID_STATES,
    can_event_type_trigger,
    can_file_type_trigger,
    can_transition,
)

OWNER_CHANGE_REASON_MAX = 200

# Annotation v1 only supports the "evaluation" type — a structured subjective
# judgement of a file. Future flavors (e.g. follow-up question) will land as
# new whitelist entries; never accept unknown types silently to avoid
# schema drift in the on-disk YAML.
VALID_ANNOTATION_TYPES = frozenset({"evaluation"})

ANNOTATION_BODY_MIN = 1
ANNOTATION_BODY_MAX = 300

# Derived fields that v1 explicitly refuses on the writer side. These are
# either AI-computed (weight / score_delta) or upstream-only labels
# (sentiment / dimension / rating). Letting them through would (a) anchor
# the annotation YAML schema before the AI layer is designed, and (b) let
# clients smuggle scoring inputs around the AI pipeline. Both Pydantic and
# the writer schema reject them so a malicious dict that bypasses the API
# layer still can't land.
ANNOTATION_FORBIDDEN_DERIVED_FIELDS = frozenset({
    "weight", "rating", "dimension", "sentiment", "score_delta",
})


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
    # P4.7 I3: `verifications_received` is server-derived (mirrored from verify
    # items into the target act). Clients must never author it directly.
    if "verifications_received" in item:
        return _fail(
            "field_not_writable",
            "verifications_received",
            "verifications_received is server-derived; clients cannot set it",
        )

    matter = index_data.get("matter") or {}
    current_status = matter.get("current_status")
    if current_status not in VALID_STATES:
        return _fail(
            "unknown_matter_status",
            "matter.current_status",
            f"unknown status: {current_status!r}",
        )

    doc_type = item.get("type")

    # Invalidation/restoration events: no `type` field, identified by `reason`.
    # Bypasses the file-type × status matrix entirely (events fire in any state).
    # See AI-docs/invalidate-self/product-design.md §三.
    if doc_type is None and "reason" in item:
        return _validate_invalidation_event_shape(item, index_data)

    if not doc_type:
        return _fail("type_missing", "type", "file type is required")

    # Event-type entries (owner_change etc.) bypass the file-type × status
    # matrix entirely — they're not files, can fire in any state, and have
    # their own shape rules. Branch here before the file-type validators.
    if doc_type in VALID_EVENT_TYPES:
        return _validate_event_shape(item, index_data)

    if doc_type not in VALID_DOC_TYPES:
        return _fail("unknown_type", "type", f"unknown type: {doc_type!r}")

    if doc_type not in ALLOWED_TYPES_BY_STATUS.get(current_status, frozenset()):
        return _fail(
            "type_not_allowed",
            "type",
            f"type {doc_type!r} not allowed when matter is {current_status!r}",
        )

    # §5.3 invalidation reference block: a new file item's quote / refer
    # cannot point to an already-invalidated file in this matter. Enforced at
    # file creation path, not at event creation path.
    invalid_ref = _validate_no_quote_to_invalidated(item, index_data)
    if invalid_ref is not None:
        return invalid_ref

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
        err = _validate_verify_shape(item, index_data)
        if err:
            return err

    if doc_type == "result":
        err = _validate_result_shape(item, sc)
        if err:
            return err

    return OK


def validate_annotation(annotation: dict[str, Any]) -> ValidationResult:
    """Writer-side schema gate for an annotation entry.

    Pure function. Run by ``publish.publish_matter_annotation`` (and
    indirectly by the API layer's Pydantic guard) so a derived-field-laden
    dict can't land on disk regardless of which entry path it took.
    Mirrors ``validate_append``'s shape for consistency: returns OK or a
    ``ValidationResult`` with code/field/message that the API layer turns
    into a 422.

    v1 enforces three rules: (1) ``type`` is in the whitelist, (2) ``body``
    is a non-empty string within length cap, (3) no derived fields
    (weight / rating / dimension / sentiment / score_delta) — those are
    AI-computed labels that don't belong in the user-supplied entry.
    """
    if not isinstance(annotation, dict):
        return _fail("annotation_not_object", None, "annotation must be a dict")

    a_type = annotation.get("type")
    if a_type is None:
        return _fail("type_missing", "type", "annotation type is required")
    if a_type not in VALID_ANNOTATION_TYPES:
        return _fail(
            "unknown_annotation_type", "type",
            f"unknown annotation type: {a_type!r};"
            f" expected one of {sorted(VALID_ANNOTATION_TYPES)}",
        )

    body = annotation.get("body")
    if not isinstance(body, str):
        return _fail("body_required", "body", "annotation body is required")
    if len(body) < ANNOTATION_BODY_MIN:
        return _fail("body_too_short", "body", "annotation body must not be empty")
    if len(body) > ANNOTATION_BODY_MAX:
        return _fail(
            "body_too_long", "body",
            f"annotation body exceeds {ANNOTATION_BODY_MAX} chars",
        )

    forbidden = ANNOTATION_FORBIDDEN_DERIVED_FIELDS & annotation.keys()
    if forbidden:
        bad = sorted(forbidden)
        return _fail(
            "derived_field_not_allowed", bad[0],
            f"annotation rejects derived field(s): {bad};"
            " these are AI-computed and not client-writable in v1",
        )

    return OK


def _validate_event_shape(
    item: dict[str, Any], index_data: dict[str, Any]
) -> ValidationResult:
    """Validate an event-type timeline entry. v1 dispatches by type.

    Owner_change shape: actor / from_owner / to_owner / reason; optional
    status_change limited to (planning → executing) per §2.5 of the design.
    """
    doc_type = item.get("type")
    if doc_type == "owner_change":
        return _validate_owner_change_shape(item, index_data)
    return _fail("unknown_event_type", "type", f"unknown event type: {doc_type!r}")


def _validate_owner_change_shape(
    item: dict[str, Any], index_data: dict[str, Any]
) -> ValidationResult:
    matter = index_data.get("matter") or {}

    # actor required (operator who performs the transfer; same format as creator).
    actor = item.get("actor")
    if not actor:
        return _fail("actor_required", "actor", "actor is required")

    # reason required + length cap (design §4.1: 200 char limit).
    reason = item.get("reason")
    if reason is None or not str(reason).strip():
        return _fail("reason_required", "reason", "reason is required")
    if len(str(reason)) > OWNER_CHANGE_REASON_MAX:
        return _fail(
            "reason_too_long",
            "reason",
            f"reason exceeds {OWNER_CHANGE_REASON_MAX} chars",
        )

    # from_owner must equal the effective current owner. Legacy indexes may
    # lack matter.owner entirely; in that case the UI falls back to the first
    # timeline file's owner/creator, so validation uses the same rule. An
    # explicit owner: null still means truly unassigned.
    current_owner = _effective_matter_owner(index_data)
    from_owner = item.get("from_owner")
    if from_owner != current_owner:
        return _fail(
            "owner_stale",
            "from_owner",
            f"from_owner {from_owner!r} does not match current matter.owner {current_owner!r}",
        )

    # to_owner required + must differ from from_owner (avoid no-op transfers).
    to_owner = item.get("to_owner")
    if not to_owner:
        return _fail("to_owner_required", "to_owner", "to_owner is required")
    if to_owner == from_owner:
        return _fail(
            "owner_unchanged",
            "to_owner",
            "to_owner equals from_owner — nothing to do",
        )

    # Optional status_change: must be a legal transition AND owner_change must
    # be a legal trigger for it (v1: only planning → executing).
    sc = item.get("status_change")
    if sc:
        frm = sc.get("from")
        to = sc.get("to")
        current_status = matter.get("current_status")
        if frm != current_status:
            return _fail(
                "status_stale",
                "status_change.from",
                f"status_change.from {frm!r} does not match current {current_status!r}",
            )
        if not can_transition(frm, to):
            return _fail(
                "status_change_not_allowed",
                "status_change",
                f"transition {frm!r} -> {to!r} is not allowed",
            )
        if not can_event_type_trigger("owner_change", frm, to):
            return _fail(
                "status_change_not_allowed_by_event",
                "status_change",
                f"owner_change cannot trigger {frm!r} -> {to!r}",
            )

    return OK


def _effective_matter_owner(index_data: dict[str, Any]) -> str | None:
    matter = index_data.get("matter") or {}
    if "owner" in matter:
        return matter.get("owner")
    for item in index_data.get("timeline") or []:
        if item.get("type") == "owner_change":
            continue
        return item.get("owner") or item.get("creator")
    return None


def _validate_verify_shape(
    item: dict[str, Any], index_data: dict[str, Any]
) -> ValidationResult | None:
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
    # Build local (same-matter) file → type map from timeline.
    # A target is valid when:
    #   (a) it exists in the current matter timeline and its type == "act", OR
    #   (b) it appears in the item's refer[] (treated as cross-matter whitelist;
    #       the pure validator trusts the client on cross-matter type per
    #       AI-docs/designs/2026-04-23-index-refactor-design.md §2.4).
    local_types: dict[str, str] = {}
    for entry in index_data.get("timeline") or []:
        path = entry.get("file")
        if path:
            local_types[path] = entry.get("type") or ""
    refer_set = set(item.get("refer") or [])

    for i, v in enumerate(verifications):
        if not isinstance(v, dict):
            return _fail(
                "invalid_verification",
                f"verifications[{i}]",
                "each verification must be an object",
            )
        target = v.get("target")
        if not target:
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
        local_type = local_types.get(target)
        if local_type is not None:
            if local_type != "act":
                return _fail(
                    "verification_target_not_act",
                    f"verifications[{i}].target",
                    f"target exists in timeline with type {local_type!r}; must be 'act'",
                )
            continue
        if target in refer_set:
            continue
        return _fail(
            "verification_target_not_found",
            f"verifications[{i}].target",
            f"target {target!r} is not in matter timeline and not listed in refer[]",
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


def _validate_invalidation_event_shape(
    item: dict[str, Any], index_data: dict[str, Any]
) -> ValidationResult:
    """Validate an invalidation/restoration event entry (no `type`, has `reason`).

    Encodes the 6 rules from AI-docs/invalidate-self/product-design.md §三:
      1. event creator must equal target file's creator (author-only)
      2. already-invalidated file cannot be invalidated again (must restore first)
      3. not-invalidated file cannot be restored
      4. quote cannot point to another event item (no chained invalidation) —
         enforced implicitly: event items have no `file` field, so the by-file
         lookup naturally cannot resolve to one
      5. quote must point to a file in the SAME matter — enforced implicitly by
         the by-file lookup (cross-matter targets are simply not found)
      6. comment cannot be invalidated — enforced implicitly: comments live
         nested in `timeline[i].comments[]`, never as top-level timeline entries
    """
    creator = item.get("creator")
    if not creator:
        return _fail(
            "creator_required", "creator", "creator is required for event entry",
        )

    quote = item.get("quote")
    if not quote:
        return _fail(
            "quote_required",
            "quote",
            "quote is required (target file path)",
        )

    reason = item.get("reason")
    if reason not in VALID_EVENT_REASONS:
        return _fail(
            "invalid_reason",
            "reason",
            f"reason must be one of {sorted(VALID_EVENT_REASONS)}",
        )

    # Find target file item in this matter's timeline. This single lookup
    # implicitly enforces rules 4, 5, 6: event items / comments / cross-matter
    # paths all fail to resolve to a top-level file entry.
    target_item = None
    for entry in index_data.get("timeline") or []:
        if entry.get("file") == quote:
            target_item = entry
            break
    if target_item is None:
        return _fail(
            "target_not_found",
            "quote",
            f"target {quote!r} is not a file in this matter timeline "
            "(cross-matter / comment / event paths not allowed)",
        )

    # Defensive: target's `type` must be in the file-type whitelist. Owner_change
    # events accidentally given a `file` field would otherwise slip through.
    target_type = target_item.get("type")
    if target_type not in VALID_DOC_TYPES:
        return _fail(
            "target_not_file_item",
            "quote",
            f"target must be a file item (think/act/verify/result/insight); "
            f"got type={target_type!r}",
        )

    # Rule 1: creator must equal target file's creator.
    target_creator = target_item.get("creator")
    if creator != target_creator:
        return _fail(
            "event_creator_mismatch",
            "creator",
            f"creator {creator!r} is not the author of target {quote!r} "
            f"(author={target_creator!r})",
        )

    # Rules 2 & 3: invalidate vs restore must match current state.
    is_invalidated = bool(target_item.get("invalidated"))
    if reason == "restored":
        if not is_invalidated:
            return _fail(
                "target_not_invalidated",
                "reason",
                f"target {quote!r} is not invalidated; cannot restore",
            )
    else:  # misposted / inaccurate
        if is_invalidated:
            return _fail(
                "target_already_invalidated",
                "reason",
                f"target {quote!r} is already invalidated; "
                "restore first before re-invalidating",
            )

    return OK


def _validate_no_quote_to_invalidated(
    item: dict[str, Any], index_data: dict[str, Any]
) -> ValidationResult | None:
    """§5.3 reference block: a new file item's quote / refer cannot target
    an already-invalidated file in the same matter.

    Enforced at file-creation path (not at event-creation path) because the
    constraint is "you cannot build new content on a withdrawn statement",
    not "you cannot withdraw something". Cross-matter refer paths are not
    checked here — they live in another matter, and resolving cross-matter
    invalidation state is out of v1 scope.
    """
    by_file: dict[str, dict[str, Any]] = {}
    for entry in index_data.get("timeline") or []:
        f = entry.get("file")
        if f:
            by_file[f] = entry

    quote = item.get("quote")
    if quote and by_file.get(quote, {}).get("invalidated"):
        return _fail(
            "quote_target_invalidated",
            "quote",
            f"cannot quote already-invalidated file {quote!r}",
        )
    for ref in item.get("refer") or []:
        if by_file.get(ref, {}).get("invalidated"):
            return _fail(
                "refer_target_invalidated",
                "refer",
                f"cannot refer already-invalidated file {ref!r}",
            )
    return None
