from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Post:
    filename: str
    frontmatter: dict[str, Any]
    body: str


def write_post(path: Path, *, frontmatter: dict[str, Any], body: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(
        frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip("\n")
    content = f"---\n{fm_yaml}\n---\n{body if body.endswith(chr(10)) else body + chr(10)}"
    content = content.encode("utf-8", errors="replace").decode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_post_pending(
    path: Path, *, frontmatter: dict[str, Any], body: str
) -> None:
    fm = dict(frontmatter)
    fm["index_state"] = "un-indexed"
    write_post(path, frontmatter=fm, body=body)


def mark_indexed(path: Path) -> None:
    post = read_post(path)
    fm = dict(post.frontmatter)
    fm["index_state"] = "indexed"
    write_post(path, frontmatter=fm, body=post.body)


def scan_un_indexed(discussions_root: Path):
    root = Path(discussions_root)
    if not root.is_dir():
        return
    for p in root.rglob("*.md"):
        if p.name.startswith("SUMMARY") or p.name.startswith("RESULT"):
            continue
        try:
            post = read_post(p)
        except Exception:
            continue
        if post.frontmatter.get("index_state") == "un-indexed":
            yield p


def read_post(path: Path) -> Post:
    content = Path(path).read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return Post(filename=Path(path).name, frontmatter={}, body=content)
    fm_text, body = m.groups()
    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    return Post(filename=Path(path).name, frontmatter=fm, body=body)
