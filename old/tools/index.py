"""INDEX file management for Pivot.

An INDEX file is a YAML document that lives at `index/<thread>-discuss.index.yaml`
and is the single source of truth for:
  - discussion entries with status
  - file listings and cross-references
  - timeline of events (posts, status changes, mentions)

See: 004 Section 4.
"""
from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


def _to_str(value: Any) -> str:
    """Coerce YAML-parsed datetime/date values back to ISO string.

    PyYAML converts unquoted ISO-8601 timestamps to datetime objects, which
    breaks downstream JSON serialization. We always want strings on our
    dataclass fields.
    """
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return "" if value is None else str(value)


class IndexError(Exception):
    """Base exception for INDEX operations."""


class StateTransitionError(IndexError):
    """Raised when attempting an illegal state transition."""


VALID_STATES = {"open", "concluded", "produced", "closed", "pending"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"concluded", "closed", "pending"},
    "concluded": {"produced", "open"},
    "produced": set(),
    "closed": {"open"},
    "pending": {"open"},
}


def can_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is legal per 004 spec."""
    if from_state == to_state:
        return True
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


@dataclass
class FileRef:
    type: str
    path: str


@dataclass
class FileEntry:
    path: str
    summary: str
    refs: list[FileRef] = field(default_factory=list)


@dataclass
class DiscussionEntry:
    path: str
    status: str
    files: list[FileEntry] = field(default_factory=list)


@dataclass
class TimelineEntry:
    time: str
    event: str
    file: Optional[str] = None
    mentions: list[dict[str, str]] = field(default_factory=list)


@dataclass
class IndexFile:
    """In-memory representation of an INDEX YAML file."""
    index_path: str
    origin_path: str
    created: str
    last_updated: str
    discussions: list[DiscussionEntry] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)


def create(index_path: str, origin_path: str, created: str) -> IndexFile:
    idx = IndexFile(
        index_path=index_path,
        origin_path=origin_path,
        created=created,
        last_updated=created,
    )
    save(idx)
    return idx


def load(index_path: str) -> IndexFile:
    with open(index_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    discussions = [
        DiscussionEntry(
            path=d["path"],
            status=d["status"],
            files=[
                FileEntry(
                    path=f["path"],
                    summary=f.get("summary", ""),
                    refs=[FileRef(r["type"], r["path"]) for r in f.get("refs", [])],
                )
                for f in d.get("files", [])
            ],
        )
        for d in raw.get("discussions", [])
    ]
    timeline = [
        TimelineEntry(
            time=_to_str(t["time"]),
            event=_to_str(t["event"]),
            file=(None if t.get("file") is None else _to_str(t.get("file"))),
            mentions=t.get("mention", []) or [],
        )
        for t in raw.get("timeline", [])
    ]
    return IndexFile(
        index_path=index_path,
        origin_path=_to_str(raw.get("origin_path", "")),
        created=_to_str(raw.get("created", "")),
        last_updated=_to_str(raw.get("last_updated", "")),
        discussions=discussions,
        timeline=timeline,
    )


def save(idx: IndexFile) -> None:
    path = Path(idx.index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "origin_path": idx.origin_path,
        "created": idx.created,
        "last_updated": idx.last_updated,
        "discussions": [
            {
                "path": d.path,
                "status": d.status,
                "files": [
                    {
                        "path": f.path,
                        "summary": f.summary,
                        "refs": [{"type": r.type, "path": r.path} for r in f.refs],
                    }
                    for f in d.files
                ],
            }
            for d in idx.discussions
        ],
        "timeline": [
            {
                "time": t.time,
                "event": t.event,
                **({"file": t.file} if t.file else {}),
                **({"mention": t.mentions} if t.mentions else {}),
            }
            for t in idx.timeline
        ],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            payload,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    os.replace(tmp, path)


def add_discussion_entry(
    idx: IndexFile,
    discussion_path: str,
    status: str,
) -> IndexFile:
    if status not in VALID_STATES:
        raise IndexError(f"Invalid status: {status}")
    if any(d.path == discussion_path for d in idx.discussions):
        raise IndexError(f"Discussion entry already exists: {discussion_path}")
    idx.discussions.append(DiscussionEntry(path=discussion_path, status=status))
    return idx


def add_file_to_discussion(
    idx: IndexFile,
    discussion_path: str,
    file_path: str,
    summary: str,
    refs: list[dict[str, str]],
) -> IndexFile:
    entry = _find_discussion(idx, discussion_path)
    entry.files.append(
        FileEntry(
            path=file_path,
            summary=summary,
            refs=[FileRef(type=r["type"], path=r["path"]) for r in refs],
        )
    )
    return idx


def add_timeline_entry(
    idx: IndexFile,
    *,
    time: str,
    event: str,
    file: Optional[str] = None,
    mentions: Optional[list[dict[str, str]]] = None,
) -> IndexFile:
    idx.timeline.append(
        TimelineEntry(
            time=time,
            event=event,
            file=file,
            mentions=mentions or [],
        )
    )
    idx.last_updated = time
    return idx


def set_status(
    idx: IndexFile,
    discussion_path: str,
    new_status: str,
) -> IndexFile:
    entry = _find_discussion(idx, discussion_path)
    if not can_transition(entry.status, new_status):
        raise StateTransitionError(
            f"Illegal transition {entry.status} -> {new_status} for {discussion_path}"
        )
    entry.status = new_status
    return idx


def _find_discussion(idx: IndexFile, discussion_path: str) -> DiscussionEntry:
    for d in idx.discussions:
        if d.path == discussion_path:
            return d
    raise IndexError(f"Discussion entry not found: {discussion_path}")
