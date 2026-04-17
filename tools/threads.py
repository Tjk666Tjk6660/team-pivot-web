"""Thread discovery, enumeration, and short-hash filename generation.

Simplified port of appv2/tools/threads.py + new short-hash utilities per 004 8.2.
"""
from __future__ import annotations

import os
import re
import secrets
from glob import glob
from pathlib import Path
from typing import Any, Optional

from tools.atomicity import read_business_file


def generate_short_hash() -> str:
    """Return a random 6-char lowercase hex string."""
    return secrets.token_hex(3)


def ensure_unique_filename_hash(repo_path: str, max_attempts: int = 10) -> str:
    """Generate a 6-hex hash that does not collide with any existing `*_<hash>.*` file
    under repo_path. Raises RuntimeError if max_attempts are exhausted.
    """
    for _ in range(max_attempts):
        h = generate_short_hash()
        pattern = os.path.join(repo_path, "**", f"*_{h}.*")
        if not glob(pattern, recursive=True):
            return h
    raise RuntimeError(
        f"Could not generate a unique hash after {max_attempts} attempts"
    )


_POST_NUMBER_RE = re.compile(r"^(\d{3})_")


def next_post_number(thread_dir: str) -> int:
    """Scan a thread directory for files named `NNN_...` and return max(NNN)+1.
    RESULT_*.md and any file not matching `NNN_` are ignored. Empty dir returns 1.
    """
    path = Path(thread_dir)
    if not path.is_dir():
        return 1
    numbers: list[int] = []
    for f in path.iterdir():
        if not f.is_file() or f.suffix != ".md":
            continue
        match = _POST_NUMBER_RE.match(f.name)
        if match:
            numbers.append(int(match.group(1)))
    return (max(numbers) if numbers else 0) + 1


def find_thread_category(discussions_root: str, thread_slug: str) -> Optional[str]:
    """Scan discussions/ to find which category a given thread belongs to.

    Returns the category name if found, None otherwise. If the same thread
    slug exists under multiple categories (shouldn't happen), returns the
    first one found.
    """
    root = Path(discussions_root)
    if not root.is_dir() or not thread_slug:
        return None
    for cat_dir in root.iterdir():
        if not cat_dir.is_dir():
            continue
        thread_dir = cat_dir / thread_slug
        if thread_dir.is_dir():
            return cat_dir.name
    return None


def list_threads(
    discussions_root: str,
    category: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List all threads under discussions/ (optionally filtered by category)."""
    root = Path(discussions_root)
    if not root.is_dir():
        return []
    results: list[dict[str, Any]] = []
    categories = [root / category] if category else [p for p in root.iterdir() if p.is_dir()]
    for cat_dir in categories:
        if not cat_dir.is_dir():
            continue
        for thread_dir in cat_dir.iterdir():
            if not thread_dir.is_dir():
                continue
            if _has_proposal(thread_dir):
                results.append(
                    {
                        "category": cat_dir.name,
                        "slug": thread_dir.name,
                        "path": str(thread_dir.relative_to(discussions_root).as_posix()),
                    }
                )
    return results


def list_posts(thread_dir: str) -> list[dict[str, Any]]:
    """List all posts in a thread directory, sorted by filename."""
    path = Path(thread_dir)
    if not path.is_dir():
        return []
    posts = []
    for f in sorted(path.iterdir()):
        if f.suffix != ".md":
            continue
        if f.name.startswith("SUMMARY"):
            continue
        parsed = read_business_file(str(f))
        posts.append(
            {
                "filename": f.name,
                "frontmatter": parsed.frontmatter,
                "body": parsed.body,
            }
        )
    return posts


def get_thread_author(thread_dir: str) -> Optional[str]:
    """Return the author of the first proposal file in a thread, or None if not found.

    The thread author is the person who created the proposal (typically file 001). This
    is used by permission checks in discuss-summarize/result/status pipelines.
    """
    posts = list_posts(thread_dir)
    for p in posts:
        if p["frontmatter"].get("type") == "proposal":
            author = p["frontmatter"].get("author")
            if author:
                return str(author)
    return None


def _has_proposal(thread_dir: Path) -> bool:
    for f in thread_dir.iterdir():
        if f.suffix != ".md":
            continue
        try:
            parsed = read_business_file(str(f))
            if parsed.frontmatter.get("type") == "proposal":
                return True
        except Exception:
            continue
    return False
