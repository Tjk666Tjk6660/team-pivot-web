from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


def change_thread_status(
    index_dir: Path,
    *,
    category: str,
    slug: str,
    from_state: str,
    to_state: str,
    author_id: str,
    reason: str | None,
    now_iso: str,
) -> None:
    path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    discussions = data.get("discussions") or []
    if not (discussions and isinstance(discussions[0], dict)):
        raise ValueError("index has no discussion entry")
    current = discussions[0].get("status")
    if current != from_state:
        raise ValueError(f"status mismatch: expected {from_state}, found {current}")
    discussions[0]["status"] = to_state
    data["last_updated"] = now_iso
    event = _status_event(author_id, from_state, to_state, reason)
    data.setdefault("timeline", []).append({"time": now_iso, "event": event})
    _atomic_write_yaml(path, data)


def _status_event(author_id: str, from_state: str, to_state: str, reason: str | None) -> str:
    if to_state == "open" and from_state in ("concluded", "closed"):
        return f"{author_id} 从 {from_state} 状态重新打开，原因：{reason}"
    return f"{author_id} 状态变更 {from_state} -> {to_state}"


def _build_reply_refs(index_data: dict, origin: str) -> list[dict]:
    discussions = index_data.get("discussions") or []
    if not (discussions and isinstance(discussions[0], dict)):
        return []
    files = discussions[0].get("files") or []
    if not files:
        return []
    proposal_filename = files[0].get("path")
    if not proposal_filename:
        return []
    return [{"type": "from", "path": f"{origin}{proposal_filename}"}]


def _atomic_write_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


@dataclass(frozen=True)
class ThreadIndex:
    status: str | None
    last_updated: str | None


def read_thread_index(index_dir: Path, slug: str) -> ThreadIndex | None:
    path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    status = None
    discussions = data.get("discussions") or []
    if discussions and isinstance(discussions[0], dict):
        s = discussions[0].get("status")
        if s:
            status = str(s)
    last_updated = data.get("last_updated")
    return ThreadIndex(
        status=status,
        last_updated=str(last_updated) if last_updated else None,
    )


def create_thread_index(
    index_dir: Path,
    *,
    category: str,
    slug: str,
    filename: str,
    author_id: str,
    now_iso: str,
    mention: dict | None = None,
) -> Path:
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / f"{slug}-discuss.index.yaml"
    origin = f"discussions/{category}/{slug}/"
    data: dict = {
        "origin_path": origin,
        "created": now_iso,
        "last_updated": now_iso,
        "discussions": [
            {
                "path": origin,
                "status": "open",
                "files": [{"path": filename, "summary": "", "refs": []}],
            }
        ],
        "timeline": [
            _timeline_entry(
                now_iso, f"{author_id} created thread",
                f"{origin}{filename}", mention,
            )
        ],
    }
    _atomic_write_yaml(path, data)
    return path


def append_reply_to_index(
    index_dir: Path,
    *,
    category: str,
    slug: str,
    filename: str,
    author_id: str,
    now_iso: str,
    mention: dict | None = None,
) -> Path:
    path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    origin = f"discussions/{category}/{slug}/"
    refs = _build_reply_refs(data, origin)
    discussions = data.setdefault("discussions", [])
    if discussions and isinstance(discussions[0], dict):
        discussions[0].setdefault("files", []).append(
            {"path": filename, "summary": "", "refs": refs}
        )
    else:
        discussions.append(
            {
                "path": origin,
                "status": "open",
                "files": [{"path": filename, "summary": "", "refs": refs}],
            }
        )
    data["last_updated"] = now_iso
    data.setdefault("timeline", []).append(
        _timeline_entry(now_iso, f"{author_id} replied", f"{origin}{filename}", mention)
    )
    _atomic_write_yaml(path, data)
    return path


def _timeline_entry(time_iso: str, event: str, file: str, mention: dict | None) -> dict:
    entry: dict = {"time": time_iso, "event": event, "file": file}
    if mention and (mention.get("users") or mention.get("comments")):
        entry["mention"] = mention
    return entry
