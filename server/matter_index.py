from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from server.matter_validator import ValidationResult, validate_append

VERSION = 1

# Canonical key order for timeline items, matching pivot-product.md §八 example.
# Keys not in this list are appended in their original insertion order.
#
# `invalidated_*` reverse-write fields slot between verifications_received and
# outcome — they describe the file's current state but are written by the
# invalidation event handler, not authored by the file's creator.
# See AI-docs/invalidate-self/product-design.md §2.1.
_ITEM_KEY_ORDER = (
    "file",
    "created_at",
    "creator",
    "owner",
    "type",
    "summary",
    "quote",
    "refer",
    "verifications",
    "verifications_received",
    "invalidated",
    "invalidated_at",
    "invalidated_reason",
    "invalidated_by",
    "outcome",
    "comments",
    "status_change",
)

# Event-type entries (owner_change) have a different shape — no file / body /
# creator. Use a dedicated key order so on-disk layout stays stable and doesn't
# get polluted by file-type fields.
_OWNER_CHANGE_KEY_ORDER = (
    "type",
    "created_at",
    "actor",
    "from_owner",
    "to_owner",
    "reason",
    "status_change",
)

# Invalidation/restoration event entries: no `type` field (distinguished from
# file items by absence of `type`, and from owner_change by absence of `type`
# as well — owner_change has type=owner_change). Carries `reason` to encode
# event subtype (misposted / inaccurate / restored) per design §2.2.
_INVALIDATION_EVENT_KEY_ORDER = (
    "creator",
    "created_at",
    "quote",
    "reason",
    "summary",
)

# Canonical matter block key order: keep new optional fields (owner) slotted
# in the same place across writes.
_MATTER_KEY_ORDER = (
    "id",
    "title",
    "current_status",
    "owner",
    "created_at",
    "updated_at",
)


# ---------- dataclasses (read-only views for callers that want structure) ----------


@dataclass(frozen=True)
class Matter:
    id: str
    title: str
    current_status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MatterIndex:
    matter: Matter
    timeline: list[dict]


# ---------- errors ----------


class ValidationError(Exception):
    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__(result.message or result.code or "validation failed")


# ---------- path helper ----------


def matter_index_path(index_dir: Path, matter_id: str) -> Path:
    # matter_id = slug (flat), per AI-docs/designs/2026-04-23-index-refactor-design.md §2.1.
    # Filename {matter_id}.index.yaml replaces the old {slug}-discuss.index.yaml.
    return Path(index_dir) / f"{matter_id}.index.yaml"


# ---------- read ----------


def read_matter_index(path: Path) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def snapshot(path: Path) -> dict | None:
    """Deep copy of the current matter index, safe for AI-monitor consumers."""
    data = read_matter_index(path)
    if data is None:
        return None
    return copy.deepcopy(data)


def view(path: Path) -> MatterIndex | None:
    """Structured read-only view. Returns None if the index is missing or malformed."""
    data = read_matter_index(path)
    if not data:
        return None
    m = data.get("matter") or {}
    try:
        matter = Matter(
            id=str(m["id"]),
            title=str(m["title"]),
            current_status=str(m["current_status"]),
            created_at=str(m["created_at"]),
            updated_at=str(m["updated_at"]),
        )
    except (KeyError, TypeError):
        return None
    timeline = data.get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    return MatterIndex(matter=matter, timeline=list(timeline))


# ---------- write ----------


def create_matter_index(
    path: Path,
    *,
    matter_id: str,
    title: str,
    initial_item: dict[str, Any],
    now_iso: str,
    matter_owner: str | None = None,
) -> None:
    """Create a new matter index file with a first timeline item.

    The matter is born in `planning`. The initial item must be a legal first
    file (type allowed in planning; optionally carrying status_change to flip
    the matter into executing).

    `matter_owner` (matter-level owner, distinct from item-level owner) is
    written into the matter block when provided. None means "unassigned" and
    is intentionally absent from the yaml — UI shows "未分配".
    """
    p = Path(path)
    if p.exists():
        raise FileExistsError(p)
    matter_block: dict[str, Any] = {
        "id": matter_id,
        "title": title,
        "current_status": "planning",
    }
    if matter_owner:
        matter_block["owner"] = matter_owner
    matter_block["created_at"] = now_iso
    matter_block["updated_at"] = now_iso
    index: dict[str, Any] = {
        "version": VERSION,
        "matter": _reorder(matter_block, _MATTER_KEY_ORDER),
        "timeline": [],
    }
    item = _normalize_item(initial_item, now_iso=now_iso)
    result = validate_append(index, item)
    if not result.ok:
        raise ValidationError(result)
    index["timeline"].append(item)
    _apply_status_change(index, item)
    index["matter"]["updated_at"] = now_iso
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(p, index)


def append_file_item(
    path: Path,
    *,
    item: dict[str, Any],
    now_iso: str,
) -> None:
    """Append a new file item to an existing matter's timeline.

    Calls `validate_append` as a second gate (API layer is expected to have
    already called it to produce 422 errors with precise field codes).

    For verify items, also reverse-writes each verifications[i] back onto the
    target act's `verifications_received[]` (P4.7). Both writes happen inside
    the same atomic tmp+rename below, so the reverse-write is all-or-nothing.
    """
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    normalized = _normalize_item(item, now_iso=now_iso)
    result = validate_append(data, normalized)
    if not result.ok:
        raise ValidationError(result)
    data.setdefault("timeline", []).append(normalized)
    _apply_status_change(data, normalized)
    _reverse_write_verifications(data, normalized)
    data.setdefault("matter", {})["updated_at"] = now_iso
    _atomic_write_yaml(p, data)


def apply_owner_change(
    path: Path,
    *,
    item: dict[str, Any],
    now_iso: str,
) -> None:
    """Append an owner_change timeline event and atomically update the matter
    block (owner + optional current_status) in a single yaml write.

    The validator rejects shape errors (reason / from_owner stale / etc.)
    before any disk write happens, so a successful return means index +
    matter.owner are both consistent on disk.
    """
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    normalized = _normalize_item(item, now_iso=now_iso)
    result = validate_append(data, normalized)
    if not result.ok:
        raise ValidationError(result)
    data.setdefault("timeline", []).append(normalized)
    matter = data.setdefault("matter", {})
    # Sync matter.owner to the new owner. None to_owner shouldn't happen
    # (validator catches it), but be defensive.
    new_owner = normalized.get("to_owner")
    if new_owner:
        matter["owner"] = new_owner
    # Apply optional combined status_change (e.g., planning → executing).
    _apply_status_change(data, normalized)
    matter["updated_at"] = now_iso
    # Re-order matter block so owner/updated_at stay in their canonical slots
    # after the in-place mutation above.
    data["matter"] = _reorder(matter, _MATTER_KEY_ORDER)
    _atomic_write_yaml(p, data)


def append_comment(
    path: Path,
    *,
    target_file: str,
    comment: dict[str, Any],
    now_iso: str,
) -> None:
    """Append a comment to the comments[] of a specific timeline item.

    Mentions and standalone-mention-as-comment semantics are handled here.
    Does NOT bump matter.updated_at — comments are discussion material,
    not matter progress.
    """
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    for entry in data.get("timeline") or []:
        if entry.get("file") == target_file:
            c = dict(comment)
            c.setdefault("created_at", now_iso)
            entry.setdefault("comments", []).append(_canonical_comment(c))
            _atomic_write_yaml(p, data)
            return
    raise ValueError(f"target_file not found in timeline: {target_file!r}")


# ---------- internals ----------


def _normalize_item(item: dict[str, Any], *, now_iso: str) -> dict[str, Any]:
    """Apply defaults + reorder keys for stable on-disk layout.

    Three timeline entry shapes are dispatched here:
      1. File items (think/act/verify/result/insight): have `type` ∈ VALID_DOC_TYPES,
         get _ITEM_KEY_ORDER + creator→owner fallback + comment normalization.
      2. Owner change events: have `type=owner_change`, get _OWNER_CHANGE_KEY_ORDER,
         skip file-only fallbacks (no creator concept).
      3. Invalidation/restoration events: **no `type` field**, identified by
         presence of `reason`, get _INVALIDATION_EVENT_KEY_ORDER. See
         AI-docs/invalidate-self/product-design.md §2.2.
    """
    out = dict(item)
    out.setdefault("created_at", now_iso)
    if out.get("type") == "owner_change":
        return _reorder(out, _OWNER_CHANGE_KEY_ORDER)
    if "type" not in out and "reason" in out:
        return _reorder(out, _INVALIDATION_EVENT_KEY_ORDER)
    creator = out.get("creator")
    if creator and not out.get("owner"):
        out["owner"] = creator
    # Normalize nested comments
    if out.get("comments"):
        out["comments"] = [_canonical_comment(c) for c in out["comments"]]
    return _reorder(out, _ITEM_KEY_ORDER)


def _canonical_comment(c: dict[str, Any]) -> dict[str, Any]:
    return _reorder(dict(c), ("created_at", "body", "mentions"))


def _reorder(d: dict[str, Any], key_order: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in key_order:
        if k in d:
            out[k] = d[k]
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def _apply_status_change(index: dict[str, Any], item: dict[str, Any]) -> None:
    sc = item.get("status_change")
    if not sc:
        return
    to = sc.get("to")
    if to:
        index.setdefault("matter", {})["current_status"] = to


def _reverse_write_verifications(
    index: dict[str, Any], verify_item: dict[str, Any]
) -> None:
    """For a freshly-appended verify item, mirror each verifications[i] onto
    the target act's `verifications_received[]` (P4.7).

    Cross-matter targets (target sits in another matter, only listed in the
    verify's `refer[]` whitelist) are silently skipped — there is no act
    timeline item in the current index to attach to. Targets of unexpected
    type are also skipped; the validator already enforces target.type == act,
    so this is a defensive belt.
    """
    if verify_item.get("type") != "verify":
        return
    by_file: dict[str, dict[str, Any]] = {}
    for it in index.get("timeline") or []:
        f = it.get("file")
        if f:
            by_file[f] = it
    verify_file = verify_item.get("file")
    verified_at = verify_item.get("created_at")
    verified_by = verify_item.get("owner") or verify_item.get("creator")
    for v in verify_item.get("verifications") or []:
        target_item = by_file.get(v.get("target"))
        if target_item is None or target_item.get("type") != "act":
            continue
        target_item.setdefault("verifications_received", []).append({
            "verify_file": verify_file,
            "verified_at": verified_at,
            "verified_by": verified_by,
            "judgement": v.get("judgement"),
            "comment": v.get("comment"),
        })


def _reverse_write_invalidation(
    index: dict[str, Any], event_item: dict[str, Any]
) -> None:
    """For a freshly-appended invalidation/restoration event, mirror the effect
    onto the target file's `invalidated_*` reverse-write fields.

    Behavior per AI-docs/invalidate-self/product-design.md §2.2:
      - reason ∈ {misposted, inaccurate} → set invalidated=True + 3 metadata fields
      - reason == restored → set invalidated=False; keep the other 3 fields as
        audit trail (so the timeline tells the full story when paired with the
        new event entry)

    Cross-matter / missing targets are silently skipped — the validator already
    ensures the target exists in this matter timeline before write.
    """
    # Identify invalidation events: no `type` field, has `reason`. owner_change
    # has type=owner_change so it's filtered out by the first guard.
    if "type" in event_item or "reason" not in event_item:
        return
    reason = event_item.get("reason")
    if reason not in ("misposted", "inaccurate", "restored"):
        return
    target_path = event_item.get("quote")
    if not target_path:
        return
    timeline = index.get("timeline") or []
    target_item = None
    for it in timeline:
        if it.get("file") == target_path:
            target_item = it
            break
    if target_item is None:
        return
    if reason == "restored":
        target_item["invalidated"] = False
        # Keep invalidated_at / invalidated_reason / invalidated_by as audit trail.
    else:
        target_item["invalidated"] = True
        target_item["invalidated_at"] = event_item.get("created_at")
        target_item["invalidated_reason"] = reason
        target_item["invalidated_by"] = event_item.get("creator")
    # Re-canonicalize key order so the 4 reverse-write fields settle into their
    # canonical slots (verifications_received → invalidated_* → outcome).
    reordered = _reorder(target_item, _ITEM_KEY_ORDER)
    target_item.clear()
    target_item.update(reordered)


def append_event(
    path: Path,
    *,
    event: dict[str, Any],
    now_iso: str,
) -> None:
    """Append an invalidation/restoration event entry to a matter's timeline,
    and reverse-write its effect onto the target file's invalidated_* fields.

    Atomic: validate → append entry → reverse-write → atomic yaml write. If
    validation fails, no partial state hits disk.

    Does NOT bump matter.updated_at — invalidation is a "declarative withdrawal",
    not matter progress (per design §5.5: keep timeline and status machine as
    independent fact streams). The frontend gets notified via SSE
    `matter.updated` (reason=event_appended) and refetches.
    """
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    normalized = _normalize_item(event, now_iso=now_iso)
    result = validate_append(data, normalized)
    if not result.ok:
        raise ValidationError(result)
    data.setdefault("timeline", []).append(normalized)
    _reverse_write_invalidation(data, normalized)
    _atomic_write_yaml(p, data)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)
