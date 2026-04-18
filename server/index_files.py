from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


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
