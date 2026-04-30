from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from server.doc_types import VALID_DOC_TYPES
from server.matter_index import read_matter_index
from server.posts import read_post
from server.read_state import ReadStateRepo
from server.threads import ThreadMeta, list_threads

_CONTENT_TYPES = {"proposal", "reply"}
# Per P4.5 decision: every timeline item counts as unread (no type filter).
_MATTER_CONTENT_TYPES = frozenset(VALID_DOC_TYPES)


@dataclass(frozen=True)
class InboxItem:
    meta: ThreadMeta
    unread_count: int
    last_post_filename: str | None
    last_post_author: str | None


def compute_inbox(
    discussions_root: Path,
    index_dir: Path,
    pivot_user_id: str,
    read_states: ReadStateRepo,
) -> list[InboxItem]:
    state = read_states.all_for_user(pivot_user_id)
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


def compute_unread_counts(
    discussions_root: Path,
    index_dir: Path,
    pivot_user_id: str,
    read_states: ReadStateRepo,
) -> dict[str, int]:
    """Returns {category/slug: unread_count} for threads with unread proposal/reply posts."""
    state = read_states.all_for_user(pivot_user_id)
    result: dict[str, int] = {}
    for meta in list_threads(discussions_root, index_dir):
        tdir = discussions_root / meta.category / meta.slug
        filenames = _post_filenames(tdir)
        key = f"{meta.category}/{meta.slug}"
        last_read = state.get(key)
        if last_read is None:
            count = len(filenames)
        else:
            count = sum(1 for f in filenames if f > last_read)
        if count > 0:
            result[key] = count
    return result


def latest_post_filename(thread_dir: Path) -> str | None:
    fs = _post_filenames(thread_dir)
    return fs[-1] if fs else None


def latest_matter_post_filename(matter_dir: Path) -> str | None:
    fs = _post_filenames(matter_dir, types=_MATTER_CONTENT_TYPES)
    return fs[-1] if fs else None


def _post_filenames(tdir: Path, types: frozenset[str] = None) -> list[str]:
    """Returns sorted filenames of indexed posts matching ``types`` (default proposal/reply)."""
    if types is None:
        types = frozenset(_CONTENT_TYPES)
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
        if p.frontmatter.get("type") not in types:
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


# ---------- matter ----------


@dataclass(frozen=True)
class MatterInboxItem:
    matter_id: str
    category: str
    title: str
    current_status: str
    updated_at: str | None
    file_count: int
    unread_count: int
    last_file_type: str | None
    last_summary: str | None
    last_file_author: str | None


def _list_matter_index_paths(index_dir: Path) -> list[Path]:
    p = Path(index_dir)
    if not p.is_dir():
        return []
    out: list[Path] = []
    for f in p.glob("*.index.yaml"):
        if f.name.endswith("-discuss.index.yaml"):
            continue
        out.append(f)
    return out


def _derive_matter_category(data: dict) -> str | None:
    timeline = data.get("timeline") or []
    if not timeline:
        return None
    first = timeline[0].get("file") or ""
    parts = first.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]


def compute_matter_inbox(
    discussions_root: Path,
    index_dir: Path,
    pivot_user_id: str,
    read_states: ReadStateRepo,
) -> list[MatterInboxItem]:
    """Return matters with unread timeline items for the given user."""
    state = read_states.all_for_user(pivot_user_id)
    out: list[MatterInboxItem] = []
    for index_path in _list_matter_index_paths(index_dir):
        data = read_matter_index(index_path)
        if data is None:
            continue
        matter = data.get("matter") or {}
        matter_id = str(matter.get("id") or index_path.stem.replace(".index", ""))
        category = _derive_matter_category(data)
        if category is None:
            continue
        tdir = discussions_root / category / matter_id
        filenames = _post_filenames(tdir, types=_MATTER_CONTENT_TYPES)
        if not filenames:
            continue
        key = f"{category}/{matter_id}"
        last_read = state.get(key)
        unread = (
            filenames
            if last_read is None
            else [f for f in filenames if f > last_read]
        )
        if not unread:
            continue
        timeline = data.get("timeline") or []
        last_item = timeline[-1] if timeline else {}
        last_filename = filenames[-1]
        last_author = _post_author(tdir / last_filename)
        out.append(
            MatterInboxItem(
                matter_id=matter_id,
                category=category,
                title=str(matter.get("title") or matter_id),
                current_status=str(matter.get("current_status") or "planning"),
                updated_at=(str(matter.get("updated_at")) if matter.get("updated_at") else None),
                file_count=len(timeline),
                unread_count=len(unread),
                last_file_type=last_item.get("type"),
                last_summary=last_item.get("summary"),
                last_file_author=last_author,
            )
        )
    return out


def compute_matter_unread_counts(
    discussions_root: Path,
    index_dir: Path,
    pivot_user_id: str,
    read_states: ReadStateRepo,
) -> dict[str, int]:
    """Returns {category/matter_id: unread_count}."""
    state = read_states.all_for_user(pivot_user_id)
    result: dict[str, int] = {}
    for index_path in _list_matter_index_paths(index_dir):
        data = read_matter_index(index_path)
        if data is None:
            continue
        matter_id = str((data.get("matter") or {}).get("id") or "")
        category = _derive_matter_category(data)
        if not matter_id or not category:
            continue
        tdir = discussions_root / category / matter_id
        filenames = _post_filenames(tdir, types=_MATTER_CONTENT_TYPES)
        key = f"{category}/{matter_id}"
        last_read = state.get(key)
        count = (
            len(filenames)
            if last_read is None
            else sum(1 for f in filenames if f > last_read)
        )
        if count > 0:
            result[key] = count
    return result


def compute_matter_unread_breakdown(
    discussions_root: Path,
    index_dir: Path,
    pivot_user_id: str,
    read_states: ReadStateRepo,
    relevance_repo,
) -> dict[str, tuple[int, int]]:
    """Returns ``{category/matter_id: (red, gray)}``.

    Red = unread file-level relevance + unread mentions for the user.
    Gray = the rest of the matter's normal file-level unread (filename >
    last_read_post_filename, minus the file-level relevance hits already
    counted in red). Mention rows do not factor into gray — by definition
    a mention is relevant.

    The two sources are independent SQL/file-system reads:
      * ``relevance_repo.unread_breakdown_per_matter`` returns
        {matter_id: (red_files, red_mentions)} (one GROUP BY)
      * file-system listing + read_state high-water mark gives the
        traditional "unread file count"

    Composing them:
        red  = red_files + red_mentions
        gray = max(total_unread - red_files, 0)
    """
    state = read_states.all_for_user(pivot_user_id)
    breakdown = relevance_repo.unread_breakdown_per_matter(pivot_user_id)

    result: dict[str, tuple[int, int]] = {}
    for index_path in _list_matter_index_paths(index_dir):
        data = read_matter_index(index_path)
        if data is None:
            continue
        matter_id = str((data.get("matter") or {}).get("id") or "")
        category = _derive_matter_category(data)
        if not matter_id or not category:
            continue
        tdir = discussions_root / category / matter_id
        filenames = _post_filenames(tdir, types=_MATTER_CONTENT_TYPES)
        key = f"{category}/{matter_id}"
        last_read = state.get(key)
        unread_count = (
            len(filenames)
            if last_read is None
            else sum(1 for f in filenames if f > last_read)
        )

        red_files, red_mentions = breakdown.get(matter_id, (0, 0))
        red = red_files + red_mentions
        gray = max(unread_count - red_files, 0)

        if red == 0 and gray == 0:
            continue
        result[key] = (red, gray)

    return result
