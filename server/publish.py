from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from server.contacts import ContactRepo
from server.index_files import (
    append_reply_to_index,
    append_standalone_mention,
    create_thread_index,
)
from server.notify import Notifier
from server.posts import mark_indexed, read_post, write_post_pending
from server.threads import (
    generate_unique_hash,
    get_thread,
    next_post_number,
    sanitize_slug,
)
from server.users import User
from server.workspace import Workspace


class PublishError(Exception):
    pass


def publish_proposal(
    workspace: Workspace,
    user: User,
    *,
    category: str,
    title: str,
    body: str,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
) -> dict:
    if not user.pinyin:
        raise PublishError("profile setup required")
    now = _now_iso()
    cat_dir = workspace.discussions_dir / category
    slug = _make_unique_slug(cat_dir, title)
    thread_dir = cat_dir / slug
    filename = f"001_{user.pinyin}_proposal_{generate_unique_hash(thread_dir)}.md"
    log.info(
        "publish proposal user=%s category=%s slug=%s filename=%s",
        user.pinyin, category, slug, filename,
    )
    fm = {"type": "proposal", "author": user.pinyin, "created": now}
    final_body = _ensure_h1(body, title)
    mention_block = _resolve_mentions(mention_open_ids, mention_comments, contacts)

    with workspace.write_session(
        message=f"feat: new discussion - {title}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        post_path = thread_dir / filename
        write_post_pending(post_path, frontmatter=fm, body=final_body)
        create_thread_index(
            workspace.index_dir,
            category=category,
            slug=slug,
            filename=filename,
            author_id=user.pinyin,
            now_iso=now,
            mention=mention_block,
        )
        mark_indexed(post_path)
    if notifier is not None:
        notifier.notify_new_thread(
            category=category, slug=slug, title=title,
            author_name=user.name, body=body,
            mention_open_ids=mention_open_ids or None,
            mention_comments=mention_comments,
        )
    return {"category": category, "slug": slug, "filename": filename}


def publish_reply(
    workspace: Workspace,
    user: User,
    *,
    category: str,
    slug: str,
    body: str,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
    reply_to: str | None = None,
    references: list[str] | None = None,
) -> dict:
    if not user.pinyin:
        raise PublishError("profile setup required")
    thread_dir = workspace.discussions_dir / category / slug
    if not thread_dir.is_dir():
        raise PublishError("thread not found")

    now = _now_iso()
    seq = next_post_number(thread_dir)
    filename = f"{seq:03d}_{user.pinyin}_reply_{generate_unique_hash(thread_dir)}.md"
    log.info(
        "publish reply user=%s category=%s slug=%s filename=%s",
        user.pinyin, category, slug, filename,
    )
    fm = {"type": "reply", "author": user.pinyin, "created": now}
    mention_block = _resolve_mentions(mention_open_ids, mention_comments, contacts)

    with workspace.write_session(
        message=f"chore: reply to {slug}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        post_path = thread_dir / filename
        write_post_pending(post_path, frontmatter=fm, body=body)
        append_reply_to_index(
            workspace.index_dir,
            category=category,
            slug=slug,
            filename=filename,
            author_id=user.pinyin,
            now_iso=now,
            mention=mention_block,
            reply_to=reply_to,
            references=references,
        )
        mark_indexed(post_path)
    if notifier is not None:
        thread_title = _lookup_thread_title(workspace, category, slug)
        notifier.notify_new_reply(
            category=category, slug=slug, thread_title=thread_title,
            author_name=user.name, body=body,
            mention_open_ids=mention_open_ids or None,
            mention_comments=mention_comments,
        )
    return {"filename": filename}


def add_standalone_mention(
    workspace: Workspace,
    user: User,
    *,
    category: str,
    slug: str,
    target_filename: str,
    mention_open_ids: list[str],
    mention_comments: str,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
) -> dict:
    if not user.pinyin:
        raise PublishError("profile setup required")
    if not mention_open_ids:
        raise PublishError("no users to mention")
    if not (mention_comments or "").strip():
        raise PublishError("comments required")
    thread_dir = workspace.discussions_dir / category / slug
    target_path = thread_dir / target_filename
    if not target_path.is_file():
        raise PublishError("target post not found")

    now = _now_iso()
    mention_block = _resolve_mentions(mention_open_ids, mention_comments, contacts)
    assert mention_block is not None

    with workspace.write_session(
        message=f"chore: mention on {slug}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        append_standalone_mention(
            workspace.index_dir,
            category=category,
            slug=slug,
            target_filename=target_filename,
            author_id=user.pinyin,
            mention=mention_block,
            now_iso=now,
        )
    if notifier is not None:
        thread_title = _lookup_thread_title(workspace, category, slug)
        try:
            excerpt = read_post(target_path).body
        except Exception:
            excerpt = ""
        notifier.notify_standalone_mention(
            category=category, slug=slug, thread_title=thread_title,
            target_filename=target_filename,
            author_name=user.name,
            mention_open_ids=mention_open_ids,
            mention_comments=mention_comments,
            post_excerpt=excerpt,
        )
    return {"ok": True}


def _resolve_mentions(
    open_ids: list[str] | None,
    comments: str | None,
    contacts: ContactRepo | None,
) -> dict | None:
    if not open_ids:
        return None
    users: list[dict] = []
    resolved = contacts.get_many(open_ids) if contacts else {}
    for oid in open_ids:
        c = resolved.get(oid)
        users.append({"user": c.name if c else oid, "open_id": oid})
    block: dict = {"users": users}
    if comments:
        block["comments"] = comments
    return block


def _lookup_thread_title(workspace: Workspace, category: str, slug: str) -> str:
    detail = get_thread(workspace.discussions_dir, workspace.index_dir, category, slug)
    if detail is not None and detail.meta.title:
        return detail.meta.title
    return slug


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _make_unique_slug(category_dir: Path, title: str) -> str:
    base = sanitize_slug(title)
    if not (category_dir / base).exists():
        return base
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}-{suffix}"


def _ensure_h1(body: str, title: str) -> str:
    stripped = body.lstrip()
    if stripped.startswith("# "):
        return body
    return f"# {title}\n\n{body.rstrip()}\n"
