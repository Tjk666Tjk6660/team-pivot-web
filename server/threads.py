from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from server.index_files import read_thread_index
from server.posts import Post, read_post

_UNSAFE_CHARS = set('/\\:*?"<>|\t\n\r')
_POST_NUMBER_RE = re.compile(r"^(\d{3})_")
_HASH_SUFFIX_RE = re.compile(r"_([a-f0-9]{6})\.md$")


def sanitize_slug(title: str) -> str:
    out = "".join("_" if ch in _UNSAFE_CHARS else ch for ch in title.strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out or "untitled"


def next_post_number(thread_dir: Path) -> int:
    if not thread_dir.is_dir():
        return 1
    numbers: list[int] = []
    for f in thread_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            m = _POST_NUMBER_RE.match(f.name)
            if m:
                numbers.append(int(m.group(1)))
    return (max(numbers) if numbers else 0) + 1


def generate_unique_hash(thread_dir: Path, max_attempts: int = 20) -> str:
    existing: set[str] = set()
    if thread_dir.is_dir():
        for f in thread_dir.iterdir():
            m = _HASH_SUFFIX_RE.search(f.name)
            if m:
                existing.add(m.group(1))
    for _ in range(max_attempts):
        h = secrets.token_hex(3)
        if h not in existing:
            return h
    raise RuntimeError(f"could not generate unique hash after {max_attempts}")


@dataclass(frozen=True)
class ThreadMeta:
    category: str
    slug: str
    title: str
    author: str | None
    status: str | None
    last_updated: str | None
    post_count: int


@dataclass(frozen=True)
class ThreadDetail:
    meta: ThreadMeta
    posts: list[Post]


def list_threads(
    discussions_root: Path,
    index_dir: Path | None = None,
    category: str | None = None,
) -> list[ThreadMeta]:
    root = Path(discussions_root)
    if not root.is_dir():
        return []
    cat_dirs = (
        [root / category] if category else [p for p in sorted(root.iterdir()) if p.is_dir()]
    )
    results: list[ThreadMeta] = []
    for cat in cat_dirs:
        if not cat.is_dir():
            continue
        for tdir in sorted(cat.iterdir()):
            if not tdir.is_dir():
                continue
            meta = _thread_meta(cat.name, tdir, index_dir)
            if meta is not None:
                results.append(meta)
    results.sort(key=lambda m: m.last_updated or "", reverse=True)
    return results


def get_thread(
    discussions_root: Path,
    index_dir: Path | None,
    category: str,
    slug: str,
) -> ThreadDetail | None:
    tdir = Path(discussions_root) / category / slug
    if not tdir.is_dir():
        return None
    meta = _thread_meta(category, tdir, index_dir)
    if meta is None:
        return None
    return ThreadDetail(meta=meta, posts=_list_posts(tdir))


def _thread_meta(category: str, tdir: Path, index_dir: Path | None) -> ThreadMeta | None:
    posts = _list_posts(tdir)
    if not posts:
        return None
    proposal = next((p for p in posts if p.frontmatter.get("type") == "proposal"), None)
    if proposal is None:
        return None
    title = str(
        proposal.frontmatter.get("title")
        or _extract_h1(proposal.body)
        or _derive_title(proposal.filename)
    )
    author = proposal.frontmatter.get("author")

    status: str | None = None
    last_updated: str | None = None
    if index_dir is not None:
        idx = read_thread_index(index_dir, tdir.name)
        if idx is not None:
            status = idx.status
            last_updated = idx.last_updated

    return ThreadMeta(
        category=category,
        slug=tdir.name,
        title=title,
        author=str(author) if author else None,
        status=status,
        last_updated=last_updated,
        post_count=len(posts),
    )


def _list_posts(tdir: Path) -> list[Post]:
    posts: list[Post] = []
    for f in sorted(tdir.iterdir()):
        if f.suffix != ".md":
            continue
        if f.name.startswith("SUMMARY") or f.name.startswith("RESULT"):
            continue
        try:
            p = read_post(f)
        except Exception:
            continue
        if p.frontmatter.get("index_state") == "un-indexed":
            continue
        posts.append(p)
    return posts


def _extract_h1(body: str) -> str | None:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
        if s:
            return None
    return None


def _derive_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    parts = stem.split("_")
    if len(parts) >= 3:
        return "_".join(parts[1:-1]).replace("-", " ")
    return stem
