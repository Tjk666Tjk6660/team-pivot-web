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
    "outcome",
    "comments",
    "status_change",
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
) -> None:
    """Create a new matter index file with a first timeline item.

    The matter is born in `planning`. The initial item must be a legal first
    file (type allowed in planning; optionally carrying status_change to flip
    the matter into executing).
    """
    p = Path(path)
    if p.exists():
        raise FileExistsError(p)
    index: dict[str, Any] = {
        "version": VERSION,
        "matter": {
            "id": matter_id,
            "title": title,
            "current_status": "planning",
            "created_at": now_iso,
            "updated_at": now_iso,
        },
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
    data.setdefault("matter", {})["updated_at"] = now_iso
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
    """Apply defaults + reorder keys for stable on-disk layout."""
    out = dict(item)
    out.setdefault("created_at", now_iso)
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
