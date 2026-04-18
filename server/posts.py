from __future__ import annotations

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
