#!/usr/bin/env python
"""Audit: post-migration content writes pivot_user.id (ULID), not legacy
open_id / pinyin.

Per design §7.1.1, every matter index file written after the
user-management migration ships should store ``creator`` / ``owner`` /
``mentions[]`` / ``readers[]`` as ``pivot_user.id``. Old files keep
their original (pre-migration) values; the read-side resolver is
backward-compatible. This script flags any *new* matter index whose
values still look like Feishu open_ids — a sign that ``publish.py``
hasn't been updated to thread ULIDs through to disk.

Heuristic:
  - ``ou_…`` / ``on_…`` prefix → feishu open_id (red flag)
  - hex-only 32-char string → likely a uuid.uuid4().hex ULID (ok)
  - anything else → pinyin or contact name (ok-ish; warn but not red)

Filtering by ``--since-mtime`` lets you scope to files written after
migration go-live; default is "everything".

Usage:
    uv run python scripts/audit_new_content_uses_ulid.py \\
        --index-dir var/git/main/index [--since-mtime 1714521600]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

_OPEN_ID_RE = re.compile(r"^(ou|on)_[A-Za-z0-9]{16,}$")
_HEX32_RE = re.compile(r"^[a-f0-9]{32}$")

USER_REF_FIELDS = ("creator", "owner", "actor", "from_owner", "to_owner")


def _classify(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "empty"
    if _OPEN_ID_RE.match(value):
        return "open_id"
    if _HEX32_RE.match(value):
        return "ulid"
    return "other"


def _scan_value(label: str, value: object, findings: list[dict]) -> None:
    cls = _classify(value)
    if cls == "open_id":
        findings.append({"field": label, "value": value, "kind": "open_id"})


def _scan_index(path: Path, findings: list[dict]) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        findings.append({"field": "<parse>", "value": str(e), "kind": "error"})
        return
    if not isinstance(data, dict):
        return
    matter = data.get("matter") or {}
    for key in ("creator", "owner"):
        _scan_value(f"matter.{key}", matter.get(key), findings)
    for i, item in enumerate(data.get("timeline") or []):
        if not isinstance(item, dict):
            continue
        for key in USER_REF_FIELDS:
            if key in item:
                _scan_value(f"timeline[{i}].{key}", item.get(key), findings)
        for j, m in enumerate(item.get("mentions") or []):
            _scan_value(f"timeline[{i}].mentions[{j}]", m, findings)
        for j, c in enumerate(item.get("comments") or []):
            if not isinstance(c, dict):
                continue
            _scan_value(f"timeline[{i}].comments[{j}].author", c.get("author"), findings)
            for k, m in enumerate(c.get("mentions") or []):
                _scan_value(
                    f"timeline[{i}].comments[{j}].mentions[{k}]", m, findings,
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--index-dir", type=Path, required=True,
        help="matter index dir (typically var/git/<repo>/index)",
    )
    parser.add_argument(
        "--since-mtime", type=float, default=None,
        help="only scan files modified after this unix timestamp",
    )
    args = parser.parse_args()

    if not args.index_dir.is_dir():
        sys.exit(f"index dir not found: {args.index_dir}")

    paths = sorted(args.index_dir.glob("*.index.yaml"))
    paths = [p for p in paths if not p.name.endswith("-discuss.index.yaml")]
    if args.since_mtime is not None:
        paths = [p for p in paths if p.stat().st_mtime >= args.since_mtime]

    print(f"scanning {len(paths)} matter index file(s) under {args.index_dir}")
    if args.since_mtime:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(args.since_mtime))
        print(f"  (only files modified after {ts})")

    total_open_id = 0
    bad_files = 0
    for p in paths:
        findings: list[dict] = []
        _scan_index(p, findings)
        open_id_hits = [f for f in findings if f["kind"] == "open_id"]
        errors = [f for f in findings if f["kind"] == "error"]
        if open_id_hits or errors:
            bad_files += 1
            print()
            print(f"[!] {p.name}")
            for hit in open_id_hits:
                print(f"     open_id leak  {hit['field']:<48}  {hit['value']}")
                total_open_id += 1
            for err in errors:
                print(f"     parse error    {err['value']}")

    print()
    print("=" * 64)
    if total_open_id == 0 and bad_files == 0:
        print(f"  [ok] all {len(paths)} files use ULID for user references")
        return 0
    print(
        f"  [!] {bad_files} file(s) carry {total_open_id} open_id leak(s) — "
        "publish.py write paths still emit legacy open_ids"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
