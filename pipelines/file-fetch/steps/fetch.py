"""File fetch step: read files and auto-attach related INDEX YAML text.

Per 004 5.3:
  - business file (under discussions/<cat>/<thread>/)  -> attach its INDEX
  - index file                                          -> return as-is
  - other                                                -> return content only
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.config import from_env  # noqa: E402


def _classify(rel_path: str) -> tuple[str, str | None]:
    """Return (kind, thread_slug_or_None) for a data_space-relative path."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 4 and parts[0] == "discussions":
        return "business", parts[2]
    if (
        len(parts) >= 2
        and parts[0] == "index"
        and parts[-1].endswith("-discuss.index.yaml")
    ):
        slug = parts[-1][: -len("-discuss.index.yaml")]
        return "index", slug
    return "other", None


def main():
    payload = json.loads(sys.stdin.read())
    ctx = from_env()
    data_space = Path(ctx.data_space_dir)

    raw_paths = payload["input"].get("paths", "")
    paths = [p.strip() for p in raw_paths.split(",") if p.strip()]

    files_out: list[dict] = []
    attached: dict[str, str] = {}

    for p in paths:
        abs_path = (data_space / p).resolve() if not Path(p).is_absolute() else Path(p)
        try:
            rel = abs_path.relative_to(data_space)
        except ValueError:
            files_out.append({"path": p, "error": "outside data_space", "kind": "other"})
            continue
        if not abs_path.exists():
            files_out.append(
                {"path": str(rel.as_posix()), "error": "not found", "kind": "other"}
            )
            continue

        content = abs_path.read_text(encoding="utf-8")
        kind, thread_slug = _classify(str(rel.as_posix()))
        files_out.append(
            {"path": str(rel.as_posix()), "content": content, "kind": kind}
        )

        if kind == "business" and thread_slug and thread_slug not in attached:
            idx_rel = f"index/{thread_slug}-discuss.index.yaml"
            idx_abs = data_space / idx_rel
            if idx_abs.exists():
                attached[thread_slug] = idx_abs.read_text(encoding="utf-8")

    sys.stdout.write(
        json.dumps(
            {"output": {"files": files_out, "attached_indexes": attached}},
        )
    )


if __name__ == "__main__":
    main()
