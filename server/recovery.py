from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from server.index_files import (
    _atomic_write_yaml,
    append_reply_to_index,
    create_thread_index,
)
from server.posts import mark_indexed, read_post, scan_un_indexed

log = logging.getLogger(__name__)


def repair_partial_writes(discussions_root: Path, index_dir: Path) -> int:
    fixed = 0
    for post_path in scan_un_indexed(discussions_root):
        log.info("recovery repairing path=%s", post_path)
        try:
            _repair_post(post_path, discussions_root, index_dir)
            fixed += 1
        except Exception:
            log.exception("recovery failed for path=%s", post_path)
            continue
    return fixed


def _repair_post(post_path: Path, discussions_root: Path, index_dir: Path) -> None:
    rel = post_path.relative_to(discussions_root)
    if len(rel.parts) < 3:
        return
    category, slug = rel.parts[0], rel.parts[1]
    filename = post_path.name

    post = read_post(post_path)
    fm = post.frontmatter
    ptype = str(fm.get("type", "reply"))
    author_id = str(fm.get("author", "unknown"))
    now = str(fm.get("created_at") or _now_iso())

    index_path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not index_path.is_file():
        create_thread_index(
            index_dir, category=category, slug=slug,
            filename=filename, author_id=author_id, now_iso=now,
        )
    else:
        data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        discussions = data.get("discussions") or []
        files = (discussions[0].get("files") if discussions else None) or []
        if not any(f.get("path") == filename for f in files):
            if ptype == "proposal" and discussions:
                origin = f"discussions/{category}/{slug}/"
                discussions[0].setdefault("files", []).append(
                    {"path": filename, "summary": "", "refs": []}
                )
                data["last_updated"] = now
                data.setdefault("timeline", []).append({
                    "time": now,
                    "event": f"{author_id} created thread (recovered)",
                    "file": f"{origin}{filename}",
                })
                _atomic_write_yaml(index_path, data)
            else:
                append_reply_to_index(
                    index_dir, category=category, slug=slug,
                    filename=filename, author_id=author_id, now_iso=now,
                )
    mark_indexed(post_path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
