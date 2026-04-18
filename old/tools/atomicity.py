"""Two-phase write protocol for business files + INDEX files.

Per 004 spec section 8.1:
  1. Write business file with index_state=un-indexed
  2. Update INDEX file
  3. Rewrite business file with index_state=indexed

On crash, monitor-scan discovers un-indexed files and retries step 2-3 idempotently.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class ParsedBusinessFile:
    frontmatter: dict[str, Any]
    body: str


def write_business_file_pending(
    file_path: str,
    *,
    frontmatter: dict[str, Any],
    body: str,
) -> None:
    """Write a business file with index_state=un-indexed."""
    fm = dict(frontmatter)
    fm["index_state"] = "un-indexed"
    _write(file_path, fm, body)


def mark_indexed(file_path: str) -> None:
    """Rewrite an existing business file flipping index_state to indexed."""
    parsed = read_business_file(file_path)
    parsed.frontmatter["index_state"] = "indexed"
    _write(file_path, parsed.frontmatter, parsed.body)


def read_business_file(file_path: str) -> ParsedBusinessFile:
    content = Path(file_path).read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(content)
    if not match:
        return ParsedBusinessFile(frontmatter={}, body=content)
    fm_text, body = match.groups()
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        # Malformed frontmatter (e.g. unquoted colons) — treat as plain text
        fm = {}
    return ParsedBusinessFile(frontmatter=fm, body=body)


def find_un_indexed_files(root_dir: str) -> Iterator[str]:
    """Walk root_dir recursively, yield paths to business files with index_state=un-indexed."""
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            try:
                parsed = read_business_file(path)
            except Exception:
                continue
            if parsed.frontmatter.get("index_state") == "un-indexed":
                yield path


def _write(file_path: str, frontmatter: dict[str, Any], body: str) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    fm_yaml = fm_yaml.rstrip("\n")
    content = f"---\n{fm_yaml}\n---\n{body}"
    # Replace surrogate chars that some LLMs produce (e.g. \udcae) — they
    # are invalid in UTF-8 and would crash write_text.
    content = content.encode("utf-8", errors="replace").decode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
