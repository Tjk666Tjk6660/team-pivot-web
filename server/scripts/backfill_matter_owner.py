from __future__ import annotations

import argparse
from pathlib import Path

from server.matter_index import _atomic_write_yaml, _reorder, read_matter_index

_MATTER_KEY_ORDER = (
    "id",
    "title",
    "current_status",
    "owner",
    "created_at",
    "updated_at",
)


def backfill_matter_owner(index_dir: Path, *, dry_run: bool = False) -> list[Path]:
    """Fill missing matter.owner from the first file timeline entry's creator.

    The script is intentionally conservative: malformed indexes, legacy thread
    indexes, empty timelines, and indexes whose first entry is not a file entry
    are skipped.
    """
    changed: list[Path] = []
    for path in sorted(Path(index_dir).glob("*.index.yaml")):
        data = read_matter_index(path)
        if not data:
            continue
        matter = data.get("matter")
        timeline = data.get("timeline")
        if not isinstance(matter, dict) or not isinstance(timeline, list) or not timeline:
            continue
        if matter.get("owner"):
            continue
        first = timeline[0]
        if not isinstance(first, dict):
            continue
        if not first.get("file"):
            continue
        creator = first.get("creator")
        if not creator:
            continue
        matter["owner"] = creator
        data["matter"] = _reorder(matter, _MATTER_KEY_ORDER)
        changed.append(path)
        if not dry_run:
            _atomic_write_yaml(path, data)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill missing matter.owner fields in *.index.yaml files.",
    )
    parser.add_argument("index_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    changed = backfill_matter_owner(args.index_dir, dry_run=args.dry_run)
    action = "would update" if args.dry_run else "updated"
    print(f"{action} {len(changed)} matter index file(s)")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
