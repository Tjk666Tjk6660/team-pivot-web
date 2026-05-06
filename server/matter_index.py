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
    "outcome",
    "mentions",
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

# Canonical matter block key order: keep new optional fields (owner) slotted
# in the same place across writes.
_MATTER_KEY_ORDER = (
    "id",
    "title",
    "current_status",
    "owner",
    "visibility",
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
    _normalize_legacy_comment_keys(data)
    return data


def _normalize_legacy_comment_keys(data: dict) -> None:
    """Rewrite legacy `comments` / inner `mentions` keys into the new
    `mentions` / `targets` shape, in place.

    Old YAML written before the comments → mentions rename has:
        timeline[i].comments[j].body
        timeline[i].comments[j].mentions  # who was @-ed

    New YAML uses:
        timeline[i].mentions[j].body
        timeline[i].mentions[j].targets

    This is the single compatibility point for the rename — all downstream
    code (renderers, scanners, validators, AI prompt) sees only the new
    shape, regardless of which generation wrote the file. Future writebacks
    naturally upgrade the file because the writer always emits the new
    keys; once historical YAML has all been touched once we can drop this
    normalizer entirely.
    """
    timeline = data.get("timeline")
    if not isinstance(timeline, list):
        return
    for item in timeline:
        if not isinstance(item, dict):
            continue
        if "mentions" not in item and "comments" in item:
            item["mentions"] = item.pop("comments")
        inner = item.get("mentions")
        if not isinstance(inner, list):
            continue
        for entry in inner:
            if isinstance(entry, dict) and "targets" not in entry and "mentions" in entry:
                entry["targets"] = entry.pop("mentions")


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
    visibility: dict[str, Any] | None = None,
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
    if visibility is not None:
        matter_block["visibility"] = visibility
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
    """Append a mention to the mentions[] of a specific timeline item.

    The function name is preserved for compatibility with Phase-2 callers
    that haven't been renamed yet; on disk the field is `mentions[]` with
    inner `targets`. Does NOT bump matter.updated_at — mentions are
    discussion material, not matter progress.

    Accepts ``comment`` dicts written in either the legacy shape
    (``{body, mentions: [...]}``) or the new shape (``{body, targets: [...]}``);
    both are normalised to the new shape before append.
    """
    p = Path(path)
    data = read_matter_index(p)
    if data is None:
        raise FileNotFoundError(p)
    for entry in data.get("timeline") or []:
        if entry.get("file") == target_file:
            c = dict(comment)
            c.setdefault("created_at", now_iso)
            entry.setdefault("mentions", []).append(_canonical_mention(c))
            _atomic_write_yaml(p, data)
            return
    raise ValueError(f"target_file not found in timeline: {target_file!r}")


# ---------- internals ----------


def _normalize_item(item: dict[str, Any], *, now_iso: str) -> dict[str, Any]:
    """Apply defaults + reorder keys for stable on-disk layout.

    Branches at type level: file-type entries get the file-type key order
    + creator→owner fallback; event-type entries (owner_change) get their
    own key order and skip the file-only fallbacks (they have no creator).

    Callers may submit items with the legacy ``comments`` field name;
    they are coerced to the new ``mentions`` field (and inner
    ``mentions`` → ``targets``) here so the on-disk shape is always the
    new one regardless of how the caller named its fields.
    """
    out = dict(item)
    out.setdefault("created_at", now_iso)
    if out.get("type") == "owner_change":
        return _reorder(out, _OWNER_CHANGE_KEY_ORDER)
    creator = out.get("creator")
    if creator and not out.get("owner"):
        out["owner"] = creator
    if "mentions" not in out and "comments" in out:
        out["mentions"] = out.pop("comments")
    if out.get("mentions"):
        out["mentions"] = [_canonical_mention(c) for c in out["mentions"]]
    return _reorder(out, _ITEM_KEY_ORDER)


def _canonical_mention(c: dict[str, Any]) -> dict[str, Any]:
    """Order keys + rename legacy inner ``mentions`` → ``targets`` so mentions
    persisted to disk are always in the new shape."""
    out = dict(c)
    if "targets" not in out and "mentions" in out:
        out["targets"] = out.pop("mentions")
    return _reorder(out, ("created_at", "body", "targets"))


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
