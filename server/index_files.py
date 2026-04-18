from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


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
            {
                "time": now_iso,
                "event": f"{author_id} created thread",
                "file": f"{origin}{filename}",
            }
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
) -> Path:
    path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    origin = f"discussions/{category}/{slug}/"
    discussions = data.setdefault("discussions", [])
    if discussions and isinstance(discussions[0], dict):
        discussions[0].setdefault("files", []).append(
            {"path": filename, "summary": "", "refs": []}
        )
    else:
        discussions.append(
            {
                "path": origin,
                "status": "open",
                "files": [{"path": filename, "summary": "", "refs": []}],
            }
        )
    data["last_updated"] = now_iso
    data.setdefault("timeline", []).append(
        {
            "time": now_iso,
            "event": f"{author_id} replied",
            "file": f"{origin}{filename}",
        }
    )
    _atomic_write_yaml(path, data)
    return path
