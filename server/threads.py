from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from server.posts import Post, read_post


@dataclass(frozen=True)
class ThreadMeta:
    category: str
    slug: str
    title: str
    author: str | None
    status: str | None
    post_count: int


@dataclass(frozen=True)
class ThreadDetail:
    meta: ThreadMeta
    posts: list[Post]


def list_threads(discussions_root: Path, category: str | None = None) -> list[ThreadMeta]:
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
            meta = _thread_meta(cat.name, tdir)
            if meta is not None:
                results.append(meta)
    return results


def get_thread(discussions_root: Path, category: str, slug: str) -> ThreadDetail | None:
    tdir = Path(discussions_root) / category / slug
    if not tdir.is_dir():
        return None
    meta = _thread_meta(category, tdir)
    if meta is None:
        return None
    return ThreadDetail(meta=meta, posts=_list_posts(tdir))


def _thread_meta(category: str, tdir: Path) -> ThreadMeta | None:
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
    return ThreadMeta(
        category=category,
        slug=tdir.name,
        title=title,
        author=str(author) if author else None,
        status=None,
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
            posts.append(read_post(f))
        except Exception:
            continue
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
