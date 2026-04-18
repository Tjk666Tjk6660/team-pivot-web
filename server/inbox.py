from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from server.posts import read_post
from server.read_state import ReadStateRepo
from server.threads import ThreadMeta, list_threads


@dataclass(frozen=True)
class InboxItem:
    meta: ThreadMeta
    unread_count: int
    last_post_filename: str | None
    last_post_author: str | None


def compute_inbox(
    discussions_root: Path,
    index_dir: Path,
    user_open_id: str,
    read_states: ReadStateRepo,
) -> list[InboxItem]:
    state = read_states.all_for_user(user_open_id)
    items: list[InboxItem] = []
    for meta in list_threads(discussions_root, index_dir):
        tdir = discussions_root / meta.category / meta.slug
        filenames = _post_filenames(tdir)
        if not filenames:
            continue
        key = f"{meta.category}/{meta.slug}"
        last_read = state.get(key)
        if last_read is None:
            unread = filenames
        else:
            unread = [f for f in filenames if f > last_read]
        if not unread:
            continue
        last_filename = filenames[-1]
        last_author = _post_author(tdir / last_filename)
        items.append(
            InboxItem(
                meta=meta,
                unread_count=len(unread),
                last_post_filename=last_filename,
                last_post_author=last_author,
            )
        )
    return items


def latest_post_filename(thread_dir: Path) -> str | None:
    fs = _post_filenames(thread_dir)
    return fs[-1] if fs else None


def _post_filenames(tdir: Path) -> list[str]:
    if not tdir.is_dir():
        return []
    out: list[str] = []
    for f in sorted(tdir.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        if f.name.startswith("SUMMARY") or f.name.startswith("RESULT"):
            continue
        try:
            p = read_post(f)
        except Exception:
            continue
        if p.frontmatter.get("index_state") == "un-indexed":
            continue
        out.append(f.name)
    return out


def _post_author(path: Path) -> str | None:
    try:
        p = read_post(path)
    except Exception:
        return None
    author = p.frontmatter.get("author")
    return str(author) if author else None
