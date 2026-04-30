from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from server.contacts import ContactRepo
from server.file_reads import FileReadRepo
from server.events import (
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_CREATED,
    TOPIC_MATTER_OWNER_CHANGED,
    TOPIC_RESULT_CREATED,
    TOPIC_STATUS_CHANGED,
    emit,
)
from server.index_files import (
    append_reply_to_index,
    append_standalone_mention,
    create_thread_index,
)
from server.matter_index import (
    ValidationError as MatterIndexValidationError,
    append_comment as matter_append_comment,
    append_file_item as matter_append_file_item,
    apply_owner_change as matter_apply_owner_change,
    create_matter_index,
    matter_index_path,
    read_matter_index,
)
from server.notify import Notifier
from server.posts import mark_indexed, write_post_pending
from server.threads import (
    generate_unique_hash,
    get_thread,
    next_post_number,
    sanitize_slug,
)
from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo
from server.users import User, UserRepo
from server.workspace import Workspace


class PublishError(Exception):
    pass


class MatterNotFoundError(PublishError):
    pass


class MatterAlreadyExistsError(PublishError):
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
            author_name=user.name,
            filename=filename,
            body=body,
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
            author_name=user.name,
            filename=filename,
            body=body,
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
        notifier.notify_standalone_mention(
            category=category, slug=slug, thread_title=thread_title,
            target_filename=target_filename,
            author_name=user.name,
            mention_open_ids=mention_open_ids,
            mention_comments=mention_comments,
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


def _resolve_mentions_for_index(
    open_ids: list[str] | None,
    users: UserRepo | None,
) -> list[str] | None:
    """Convert frontend-supplied open_ids into the form the matter index stores.

    Registered Pivot users (have pinyin) → pinyin, matching creator/owner.
    Un-registered contacts (only known via Feishu open_id) → keep open_id.
    Returns None if input is None/empty so callers can drop the field cleanly.

    Note: Per design §7.1.1 the storage contract for new content is
    pivot_user.id (ULID), and ``_normalize_mentions_to_pivot_user_ids``
    below is the forward-looking equivalent. This pinyin-keyed helper is
    kept while publish.py is still threaded through the legacy
    ``UserRepo``; once auth + publish.py settle on PivotUser, the
    pinyin-conversion branch is deleted.
    """
    if not open_ids:
        return None
    out: list[str] = []
    for oid in open_ids:
        u = users.get_by_any_id(oid) if users else None
        if u and u.pinyin:
            out.append(u.pinyin)
        else:
            out.append(oid)
    return out


def _normalize_mentions_to_pivot_user_ids(
    refs: list[str] | None,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
    contacts: ContactRepo | None = None,
) -> list[str] | None:
    """Per design §7.1.1: resolve any inbound mention reference (ULID,
    feishu open_id, or contact name/pinyin) to ``pivot_user.id`` for
    persistence in matter index / frontmatter.

    Resolution order matches the read-side ``DisplayResolver``:
      1. direct ULID hit on ``pivot_user`` — frontend new-version controls
         already submit ULIDs
      2. feishu open_id → external_binding → pivot_user.id
      3. contact name/pinyin → ContactRepo lookup → open_id → binding
      4. unresolved (external feishu user with no binding yet) → preserve
         the original open_id string; the read-side resolver will fall
         back to ``contacts`` and render a name + status='unknown'

    Returns ``None`` for empty input so callers can drop the field cleanly.
    """
    if not refs:
        return None
    out: list[str] = []
    for ref in refs:
        if not ref:
            continue
        u = pivot_users.get(ref)
        if u is not None:
            out.append(u.id)
            continue
        b = bindings.lookup_any_provider(ref)
        if b is not None:
            out.append(b.pivot_user_id)
            continue
        if contacts is not None and not ref.startswith(("ou_", "on_")):
            cands = contacts.lookup_candidates(ref)
            if len(cands) == 1:
                resolved = bindings.lookup_any_provider(cands[0].open_id)
                if resolved is not None:
                    out.append(resolved.pivot_user_id)
                    continue
                out.append(cands[0].open_id)
                continue
        out.append(ref)
    return out


def _ulids_to_feishu_open_ids(
    refs: list[str] | None,
    pivot_users: PivotUserRepo,
    bindings: ExternalBindingRepo,
) -> list[str]:
    """Reverse of ``_normalize_mentions_to_pivot_user_ids`` for the notify
    side: a Feishu DM card needs concrete open_ids to fill ``<at id="…">``
    tags. Refs that are already open_ids pass through; ULIDs are looked up
    via the user's feishu binding (if any). Refs without a feishu binding
    are dropped from the notify list — they correspond to invite-only
    users who simply don't have a Feishu account to DM.
    """
    if not refs:
        return []
    out: list[str] = []
    for ref in refs:
        if not ref:
            continue
        if ref.startswith(("ou_", "on_")):
            out.append(ref)
            continue
        u = pivot_users.get(ref)
        if u is None:
            continue
        feishu_binding = next(
            (b for b in bindings.list_for_user(u.id) if b.provider == "feishu"),
            None,
        )
        if feishu_binding is not None:
            out.append(feishu_binding.external_id)
    return out


def _resolve_comments_mentions(
    comments: list[dict] | None,
    users: UserRepo | None,
    contacts: ContactRepo | None,
    *,
    author: str,
) -> list[dict] | None:
    """Normalize a comments[] payload for index storage:
    - inject `author` (the file's creator — embedded comments are always
      authored by the same user posting the file; CommentIn schema does not
      accept author from clients);
    - resolve each comment's mentions[] via _resolve_mentions_for_index.
    Returns a new list; does not mutate input.

    Note: Web 前端 MentionField 总是发真 open_id；MCP 客户端可能直接发 name/
    pinyin。先经 contacts 转成 open_id，再走"已注册→pinyin / 未注册→保留
    open_id"的分流，否则未注册联系人的拼音会被原样落盘、渲染兜底成拼音。
    与 publish_matter_comment 的做法一致。"""
    if not comments:
        return comments
    out: list[dict] = []
    for c in comments:
        cc = dict(c)
        cc["author"] = author
        if cc.get("mentions"):
            open_ids = _resolve_mention_strings_to_open_ids(cc["mentions"], contacts)
            cc["mentions"] = _resolve_mentions_for_index(open_ids, users)
        out.append(cc)
    return out


class AmbiguousMentionError(PublishError):
    """One or more @-mention inputs matched multiple contacts.

    Carries the structured candidate list so the API layer can return a 422
    that the AI can show the user for disambiguation, e.g. "你想 @ 哪个刘宇？".
    Each entry is `{"input": str, "candidates": [{"open_id": str, "name": str}]}`.
    """

    def __init__(self, ambiguities: list[dict]) -> None:
        self.ambiguities = ambiguities
        super().__init__(f"ambiguous_mention: {len(ambiguities)} input(s) matched multiple contacts")


def _resolve_mention_strings_to_open_ids(
    values: list[str] | None,
    contacts: ContactRepo | None,
) -> list[str]:
    """Convert any user-supplied mention strings (open_id / union_id / name /
    en_name) to actual Feishu open_ids for the notifier.

    Web's MentionField always emits real open_ids, so this used to be a no-op
    pass-through — but MCP tools accept name/en_name from AI, and the Feishu
    notifier silently dropped every DM whose `<at id="…">` payload wasn't a
    real open_id. We resolve via ContactRepo (the table also covers users
    who only exist as Feishu contacts and never logged into Pivot).

    Resolution policy:
      - Unique match → use that contact's open_id.
      - Multiple matches (e.g. 两个"刘宇") → raise AmbiguousMentionError so
        the caller can ask the user to pick. We never silently pick one,
        because @-pinging the wrong person is worse than no DM at all.
      - No match but value looks like a Feishu ID (`ou_…` / `on_…`) → pass
        through, guards against stale contact sync.
      - No match and not an ID → drop with a warning. Lenient like
        _resolve_mentions_for_index — one bad name shouldn't fail the
        whole publish call.

    Multiple ambiguous inputs are collected first, then raised together so
    the user can resolve them all in one round-trip.
    """
    if not values:
        return []
    if contacts is None:
        return [v for v in values if v]
    out: list[str] = []
    ambiguous: list[dict] = []
    for v in values:
        if not v:
            continue
        candidates = contacts.lookup_candidates(v)
        if len(candidates) == 1:
            out.append(candidates[0].open_id)
        elif len(candidates) > 1:
            ambiguous.append({
                "input": v,
                "candidates": [
                    {"open_id": c.open_id, "name": c.name}
                    for c in candidates
                ],
            })
        elif v.startswith(("ou_", "on_")):
            out.append(v)
        else:
            log.warning("mention_unresolvable input=%r (skipped)", v)
    if ambiguous:
        raise AmbiguousMentionError(ambiguous)
    return out


def _extract_notify_mentions(
    comments: list[dict] | None,
) -> tuple[list[str] | None, str | None]:
    """Pull raw 圈人 open_ids + 留言 out of the bundled comments[0] payload.

    Frontend (CreateFileDialog) folds @-mentions into the file's first comment
    because the matter file API does not have dedicated top-level mention
    fields (see CreateFileDialog.tsx 圈人 + 留言 hack). The Feishu notifier,
    however, needs the *raw* open_ids to fill `<at id="…">` markdown tags
    (schema 2.0) and to deliver per-recipient DMs.

    This helper teases that data back out before _resolve_comments_mentions
    rewrites open_ids to pinyin for index storage. Safe to call with None / [].
    """
    if not comments:
        return None, None
    first = comments[0] or {}
    raw = first.get("mentions")
    if not isinstance(raw, list) or not raw:
        return None, None
    open_ids = [str(x) for x in raw if x]
    if not open_ids:
        return None, None
    body = first.get("body")
    text = str(body).strip() if isinstance(body, str) else None
    return open_ids, (text or None)


def _resolve_file_author_recipients(
    matter_data: dict,
    target_file: str,
    *,
    actor: User,
    users: UserRepo | None,
    already_notified: list[str],
) -> list[str]:
    """Find the open_ids that should be DMed/relevance-rowed because the
    comment is on *their* file — i.e. the targeted timeline item's creator
    and owner. Skips: the actor (self), unregistered identifiers (no User
    row to map to an open_id), and anyone already in ``already_notified``
    (the explicit @-mention list — they're handled separately).
    Result is order-stable + deduped."""
    if users is None or not target_file:
        return []
    item = _find_timeline_item(matter_data, target_file)
    if item is None:
        return []
    candidates: list[str] = []
    seen: set[str] = set(already_notified or [])
    for pinyin in (item.get("creator"), item.get("owner")):
        if not pinyin:
            continue
        u = users.get_by_any_id(str(pinyin))
        if u is None or not u.open_id:
            continue
        if u.open_id == actor.open_id or u.open_id in seen:
            continue
        candidates.append(u.open_id)
        seen.add(u.open_id)
    return candidates


def _find_timeline_item(matter_data: dict, target_file: str) -> dict | None:
    """Match by full path or basename — the comments API accepts either, and
    the matter index stores the full ``discussions/<cat>/<slug>/<file>`` form."""
    if not target_file:
        return None
    for it in matter_data.get("timeline") or []:
        rel = it.get("file") or ""
        if rel == target_file or rel.endswith("/" + target_file):
            return it
    return None


def _resolve_owner_name(owner: str | None, users: UserRepo | None) -> str | None:
    if not owner:
        return None
    u = users.get_by_any_id(owner) if users else None
    if u:
        return u.name
    return owner


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


# =============================================================================
# Matter model publish path (P2)
#
# Disk layout stays the same: discussions/<category>/<slug>/NNN_<pinyin>_<type>_<hash>.md
# matter_id = slug (flat, per AI-docs/designs/2026-04-23-index-refactor-design.md §2.1).
# INDEX file: index/<matter_id>.index.yaml.
# =============================================================================


def publish_matter_create(
    workspace: Workspace,
    user: User,
    *,
    category: str,
    title: str,
    initial_item: dict,
    matter_owner_open_id: str | None = None,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
    users: UserRepo | None = None,
    file_reads: FileReadRepo | None = None,
) -> dict:
    """Create a new matter and write its first timeline item.

    initial_item keys (per pivot-interface.md POST /api/matters):
        type: think | act  (validator also rejects anything else in planning)
        summary: str  (required)
        body: str  (Markdown body of the MD file)
        owner: str  (optional; defaults to creator)
        comments: list[dict]  (optional)

    `matter_owner_open_id` (matter-level owner, distinct from item-level
    initial_item.owner) is resolved through the same _resolve_owner_for_index
    chain as creator/owner. None means "default to creator". Reaching here with
    an unknown id raises PublishError so the API layer can return 422.
    """
    if not user.pinyin:
        raise PublishError("profile setup required")
    if not title.strip():
        raise PublishError("title required")

    # Resolve matter-level owner. None / empty / equals creator's open_id
    # all collapse to "owner = creator" so the on-disk owner field is
    # always a valid pinyin/open_id, never the literal `me.open_id`.
    # When pointing to someone else, require them to be a registered Pivot
    # user (has a pinyin). Stricter than file-level owner — matter-level owner
    # drives "我负责的 Matter" filters and scheduler views, so keeping the
    # identifier space tight to known users avoids dangling references.
    matter_owner_pinyin = user.pinyin
    if matter_owner_open_id and matter_owner_open_id != user.open_id:
        target_user = users.get_by_any_id(matter_owner_open_id) if users else None
        if target_user is None or not target_user.pinyin:
            raise PublishError(f"matter owner not found: {matter_owner_open_id}")
        matter_owner_pinyin = target_user.pinyin

    slug = _make_unique_matter_slug(workspace, title)
    matter_id = slug
    index_path = matter_index_path(workspace.index_dir, matter_id)
    thread_dir = workspace.discussions_dir / category / slug

    doc_type = initial_item.get("type") or "think"
    now = _now_iso()
    filename = f"001_{user.pinyin}_{doc_type}_{generate_unique_hash(thread_dir)}.md"
    file_rel = f"discussions/{category}/{slug}/{filename}"

    md_body = initial_item.get("body") or ""
    md_body = _ensure_h1(md_body, title)
    md_fm = {"type": doc_type, "author": user.pinyin, "created": now}
    if initial_item.get("body_source") in ("ai", "manual"):
        md_fm["body_source"] = initial_item["body_source"]
    md_path = thread_dir / filename

    # Resolve comments[].mentions from open_id → pinyin (or keep open_id when
    # the mentioned person isn't a registered Pivot user). The notifier still
    # receives raw open_ids elsewhere; only the on-disk matter index stores the
    # resolved form.
    item_input = dict(initial_item)
    if item_input.get("comments"):
        item_input["comments"] = _resolve_comments_mentions(
            item_input["comments"], users, contacts, author=user.pinyin,
        )

    # Frontend (CreateFileDialog) bundles 圈人 + 留言 into comments[0] because
    # matter has no top-level mention field. Extract raw open_ids + 留言 from
    # the original (un-resolved) initial_item so the Feishu notifier can fire
    # both the group card's <at> tags and the per-recipient DM. Without this,
    # mentions silently fail to notify.
    notify_mention_open_ids, notify_mention_comments = _extract_notify_mentions(
        initial_item.get("comments")
    )
    owner_notify_open_id = matter_owner_open_id or user.open_id
    # Resolve before write (see publish_matter_comment for rationale): an
    # ambiguous @ aborts the create with a 422 + candidate list rather than
    # leaving a half-written matter on disk.
    notify_mention_resolved = _resolve_mention_strings_to_open_ids(
        notify_mention_open_ids, contacts,
    )

    item = _build_timeline_item(
        item_input,
        file_rel=file_rel,
        creator=user.pinyin,
        now_iso=now,
        users=users,
    )

    log.info(
        "publish matter create user=%s category=%s slug=%s filename=%s",
        user.pinyin, category, slug, filename,
    )

    with workspace.write_session(
        message=f"feat: new matter - {title}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        # Two-phase write: MD gets index_state=un-indexed first, then after the
        # matter index is updated we flip it to indexed. Crash between the two
        # writes leaves the MD as un-indexed so recovery/operators can see it.
        write_post_pending(md_path, frontmatter=md_fm, body=md_body)
        create_matter_index(
            index_path,
            matter_id=matter_id,
            title=title,
            initial_item=item,
            now_iso=now,
            matter_owner=matter_owner_pinyin,
        )
        mark_indexed(md_path)

    matter_snapshot = read_matter_index(index_path) or {}
    # Author has obviously already "read" their own freshly-published file —
    # mark it so the read indicator on their own card isn't stuck at zero
    # readers, and so the relevance/reader UIs treat it as already-seen.
    if file_reads is not None:
        file_reads.mark(user.open_id, matter_id, filename)
    emit(
        TOPIC_MATTER_CREATED,
        matter_id=matter_id,
        actor=user.pinyin,
        at=now,
        payload={"title": title, "category": category, "first_file": file_rel},
    )
    _emit_file_appended(matter_snapshot, item, actor=user.pinyin, now=now)

    if notifier is not None:
        notifier.notify_new_thread(
            category=category, slug=slug, title=title,
            author_name=user.name,
            filename=filename,
            body=md_body,
            owner_open_id=owner_notify_open_id,
            mention_open_ids=notify_mention_resolved or None,
            mention_comments=notify_mention_comments,
        )
    return {
        "matter_id": matter_id,
        "category": category,
        "slug": slug,
        "filename": filename,
        "file": file_rel,
        "matter": matter_snapshot.get("matter", {}),
        "item": item,
    }


def publish_matter_append(
    workspace: Workspace,
    user: User,
    *,
    matter_id: str,
    item_body: dict,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
    users: UserRepo | None = None,
    file_reads: FileReadRepo | None = None,
) -> dict:
    """Append a new timeline item (think/act/verify/result/insight) to a matter.

    item_body keys (per pivot-interface.md POST /api/matters/{id}/files):
        type: think | act | verify | result | insight  (required)
        summary: str  (required)
        body: str  (optional MD body)
        owner: str  (optional; defaults to creator)
        quote: str  (optional)
        refer: list[str]  (optional)
        comments: list[dict]  (optional)
        verifications: list[dict]  (verify only)
        outcome: str  (result only)
        status_change: {from, to}  (optional; validator enforces trigger rules)
    """
    if not user.pinyin:
        raise PublishError("profile setup required")

    index_path = matter_index_path(workspace.index_dir, matter_id)
    data = read_matter_index(index_path)
    if data is None:
        raise MatterNotFoundError(matter_id)

    category = _derive_category_from_timeline(data)
    if category is None:
        raise PublishError(f"cannot derive category for matter {matter_id!r}")

    thread_dir = workspace.discussions_dir / category / matter_id
    now = _now_iso()
    doc_type = item_body.get("type") or ""
    seq = next_post_number(thread_dir)
    filename = f"{seq:03d}_{user.pinyin}_{doc_type}_{generate_unique_hash(thread_dir)}.md"
    file_rel = f"discussions/{category}/{matter_id}/{filename}"

    item_input = dict(item_body)
    if item_input.get("comments"):
        item_input["comments"] = _resolve_comments_mentions(
            item_input["comments"], users, contacts, author=user.pinyin,
        )

    # Same mention bundling extraction as publish_matter_create — frontend
    # ships 圈人留言 in comments[0] and we need raw open_ids for the notifier.
    notify_mention_open_ids, notify_mention_comments = _extract_notify_mentions(
        item_body.get("comments")
    )
    # Resolve before write — see publish_matter_comment for rationale.
    notify_mention_resolved = _resolve_mention_strings_to_open_ids(
        notify_mention_open_ids, contacts,
    )

    item = _build_timeline_item(
        item_input,
        file_rel=file_rel,
        creator=user.pinyin,
        now_iso=now,
        users=users,
    )

    md_body = item_body.get("body") or ""
    md_fm = {"type": doc_type, "author": user.pinyin, "created": now}
    if item_body.get("body_source") in ("ai", "manual"):
        md_fm["body_source"] = item_body["body_source"]
    md_path = thread_dir / filename

    log.info(
        "publish matter append user=%s matter=%s type=%s filename=%s",
        user.pinyin, matter_id, doc_type, filename,
    )

    with workspace.write_session(
        message=f"chore: append {doc_type} to {matter_id}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        # Two-phase write (see publish_matter_create for rationale).
        write_post_pending(md_path, frontmatter=md_fm, body=md_body)
        matter_append_file_item(index_path, item=item, now_iso=now)
        mark_indexed(md_path)

    matter_snapshot = read_matter_index(index_path) or {}
    # Mark author as having read their own newly-appended file (see
    # publish_matter_create for rationale).
    if file_reads is not None:
        file_reads.mark(user.open_id, matter_id, filename)
    _emit_file_appended(matter_snapshot, item, actor=user.pinyin, now=now)

    # Notifier: reuse the existing thread-era methods so Feishu keeps pushing
    # card updates. Semantically a matter file append is "reply to the matter".
    if notifier is not None:
        matter_meta = matter_snapshot.get("matter") or {}
        matter_title = matter_meta.get("title") or matter_id
        notifier.notify_new_reply(
            category=category, slug=matter_id, thread_title=matter_title,
            author_name=user.name,
            filename=filename,
            body=md_body,
            mention_open_ids=notify_mention_resolved or None,
            mention_comments=notify_mention_comments,
        )
        sc = item.get("status_change")
        if sc:
            # P4.5 G 补遗：matter 的 status_change 天然由一篇具体文件触发
            # （act / result / insight / think），把这篇文件的 type + summary
            # + filename 带进卡片，让通知有"为什么变的"信息。
            item_filename = (item.get("file") or "").rsplit("/", 1)[-1] or None
            notifier.notify_status_change(
                category=category, slug=matter_id, thread_title=matter_title,
                from_state=sc.get("from") or "",
                to_state=sc.get("to") or "",
                author_name=user.name,
                reason=None,
                trigger_type=item.get("type"),
                trigger_summary=item.get("summary"),
                trigger_filename=item_filename,
            )

    return {
        "matter_id": matter_id,
        "filename": filename,
        "file": file_rel,
        "matter": matter_snapshot.get("matter", {}),
        "item": item,
    }


def publish_matter_comment(
    workspace: Workspace,
    user: User,
    *,
    matter_id: str,
    target_file: str,
    body: str,
    mentions: list[str] | None = None,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
    users: UserRepo | None = None,
) -> dict:
    """Append a comment to a specific timeline item in a matter."""
    if not user.pinyin:
        raise PublishError("profile setup required")
    if not (body or "").strip():
        raise PublishError("comment body required")

    index_path = matter_index_path(workspace.index_dir, matter_id)
    data = read_matter_index(index_path)
    if data is None:
        raise MatterNotFoundError(matter_id)

    # Resolve @-mentions BEFORE any disk write — if a name/pinyin matches
    # multiple contacts (e.g. 张博 / 张菠 both → "zhangbo"), we raise
    # AmbiguousMentionError here so the route returns 422 with the candidate
    # list and no half-written comment lingers in the matter index.
    notify_open_ids = _resolve_mention_strings_to_open_ids(
        list(mentions) if mentions else None, contacts,
    )

    # File author / owner deserve a notification when someone comments on
    # their file, even if they weren't explicitly @-ed: the relevance system
    # only fires on explicit mentions (see relevance_writer), and the
    # standalone-mention card only highlights @-ed users. Without this, the
    # file's author is completely silent about activity on their own work.
    file_author_open_ids = _resolve_file_author_recipients(
        data, target_file, actor=user, users=users,
        already_notified=notify_open_ids,
    )

    now = _now_iso()
    comment = {
        "body": body,
        "author": user.pinyin,
    }
    # mentions 入 index 时把已注册用户的 open_id 转成 pinyin，与 creator/owner
    # 同格式；未注册联系人保留 open_id（无 pinyin 可用）。通知发送一侧仍用原始
    # open_ids（见下方 notifier 调用），不受影响。
    # 注意喂的是 notify_open_ids 而不是 mentions：MCP 客户端可以传 name/pinyin，
    # _resolve_mentions_for_index 内部 users.get_by_any_id 仅命中 pinyin 而不会
    # 查 contacts，导致未注册联系人的拼音被原样落盘 → 渲染兜底成拼音。先解析
    # 为真 open_id 后再分流，保证 index 形态恒为 pinyin / open_id。
    resolved_mentions = _resolve_mentions_for_index(notify_open_ids, users)
    if resolved_mentions:
        comment["mentions"] = resolved_mentions

    with workspace.write_session(
        message=f"chore: comment on {matter_id}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        matter_append_comment(
            index_path,
            target_file=target_file,
            comment=comment,
            now_iso=now,
        )

    emit(
        TOPIC_COMMENT_APPENDED,
        matter_id=matter_id,
        actor=user.pinyin,
        at=now,
        payload={
            "target_file": target_file,
            "body": body,
            "mentions": mentions or [],
            "file_author_open_ids": file_author_open_ids,
        },
    )

    # Notifier: reuse the standalone-mention path so @-recipients get a DM.
    if notifier is not None and (notify_open_ids or file_author_open_ids):
        matter_meta = data.get("matter") or {}
        matter_title = matter_meta.get("title") or matter_id
        category = _derive_category_from_timeline(data) or "matters"
        target_basename = (target_file or "").rsplit("/", 1)[-1] or target_file
        notifier.notify_standalone_mention(
            category=category, slug=matter_id, thread_title=matter_title,
            target_filename=target_basename,
            author_name=user.name,
            mention_open_ids=notify_open_ids,
            mention_comments=body,
            dm_extra_open_ids=file_author_open_ids or None,
        )

    return {"matter_id": matter_id, "target_file": target_file, "at": now}


def publish_matter_owner_change(
    workspace: Workspace,
    user: User,
    *,
    matter_id: str,
    to_owner_open_id: str,
    reason: str,
    status_change: dict | None = None,
    contacts: ContactRepo | None = None,
    notifier: Notifier | None = None,
    users: UserRepo | None = None,
) -> dict:
    """Transfer matter-level ownership.

    Writes a single owner_change timeline entry plus updates matter.owner +
    optional matter.current_status atomically through `apply_owner_change`.
    The validator inside the writer surfaces all shape errors (reason / stale
    / etc.) as MatterIndexValidationError; the API layer maps those to 422.

    Emits TOPIC_MATTER_OWNER_CHANGED on success so the SSE channel can refresh
    affected clients (matter list + open detail page).
    """
    if not user.pinyin:
        raise PublishError("profile setup required")

    index_path = matter_index_path(workspace.index_dir, matter_id)
    data = read_matter_index(index_path)
    if data is None:
        raise MatterNotFoundError(matter_id)
    from_owner = _effective_matter_owner(data)

    # Same strictness as create-time matter owner: require a registered user
    # (with pinyin), otherwise reject. Permissive contact fallback isn't
    # appropriate for matter-level owner — see publish_matter_create for why.
    target_user = users.get_by_any_id(to_owner_open_id) if users else None
    if target_user is None or not target_user.pinyin:
        raise PublishError(f"owner_unknown:{to_owner_open_id}")
    to_owner = target_user.pinyin

    now = _now_iso()
    item: dict = {
        "type": "owner_change",
        "actor": user.pinyin,
        "from_owner": from_owner,
        "to_owner": to_owner,
        "reason": reason,
    }
    if status_change is not None:
        item["status_change"] = dict(status_change)

    with workspace.write_session(
        message=f"chore: owner change on {matter_id}",
        author_name=user.name,
        author_email=f"{user.pinyin}@pivot.local",
    ):
        matter_apply_owner_change(index_path, item=item, now_iso=now)

    matter_snapshot = read_matter_index(index_path) or {}
    matter_meta = matter_snapshot.get("matter") or {}
    category = _derive_category_from_timeline(matter_snapshot) or "matters"
    matter_creator = _matter_creator_pinyin(matter_snapshot)
    emit(
        TOPIC_MATTER_OWNER_CHANGED,
        matter_id=matter_id,
        actor=user.pinyin,
        at=now,
        payload={
            "from_owner": from_owner,
            "to_owner": to_owner,
            "reason": reason,
            "status_change": dict(status_change) if status_change else None,
            # matter_creator: pinyin of the first non-event timeline item's
            # creator. Pre-resolved here so relevance_writer doesn't re-read
            # the index. Used to mark the matter creator as "与我相关" on
            # ownership transfers.
            "matter_creator": matter_creator,
        },
    )
    if notifier is not None:
        from_owner_name = _resolve_owner_name(from_owner, users)
        notifier.notify_owner_change(
            category=category,
            slug=matter_id,
            thread_title=matter_meta.get("title") or matter_id,
            actor_name=user.name,
            from_owner_name=from_owner_name,
            to_owner_name=target_user.name,
            to_owner_open_id=target_user.open_id,
            reason=reason,
            status_change=dict(status_change) if status_change else None,
        )
    return {
        "matter_id": matter_id,
        "matter": matter_snapshot.get("matter", {}),
        "item": item,
        "at": now,
    }


# --- matter helpers -----------------------------------------------------------


def _resolve_owner_for_index(
    value: str | None, users: UserRepo | None
) -> str | None:
    """Resolve a frontend-submitted owner identifier into the on-disk index
    form. Frontend (`OwnerPicker`) submits the chosen contact's `open_id`
    because that's the canonical key in the contacts table, but on-disk we
    want the same shape as `creator` — pinyin for registered users; raw
    value (open_id, when the chosen contact hasn't logged in yet) as the
    fallback. Mirrors `_resolve_mentions_for_index` and the
    `creator/owner` same-format invariant.

    Without this resolution, picking another person as owner used to land
    the bare `ou_xxxxxxxxxxxxxxxx` open_id into the matter index, which
    propagates further into `verifications_received.verified_by` (derived
    from the verify file's owner in `matter_index._reverse_write_verifications`)."""
    if not value:
        return None
    if users:
        u = users.get_by_any_id(value)
        if u and u.pinyin:
            return u.pinyin
    return value


def _effective_matter_owner(matter_data: dict) -> str | None:
    matter = matter_data.get("matter") or {}
    if "owner" in matter:
        return matter.get("owner")
    for item in matter_data.get("timeline") or []:
        if item.get("type") == "owner_change":
            continue
        return item.get("owner") or item.get("creator")
    return None


def _matter_creator_pinyin(matter_data: dict) -> str | None:
    """First non-event timeline item's creator (pinyin). Mirrors how
    api/matters._summarize_matter derives the matter-level creator field —
    keep the two in lock-step."""
    for item in matter_data.get("timeline") or []:
        if item.get("type") == "owner_change":
            continue
        creator = item.get("creator")
        return str(creator) if creator else None
    return None


def _build_timeline_item(
    body: dict,
    *,
    file_rel: str,
    creator: str,
    now_iso: str,
    users: UserRepo | None = None,
) -> dict:
    raw_owner = body.get("owner")
    resolved_owner = _resolve_owner_for_index(raw_owner, users) if raw_owner else None
    item: dict = {
        "file": file_rel,
        "created_at": now_iso,
        "creator": creator,
        "owner": resolved_owner or creator,
        "type": body.get("type"),
        "summary": body.get("summary") or "",
    }
    for key in ("quote", "refer", "verifications", "outcome", "comments", "status_change"):
        if body.get(key) is not None:
            item[key] = body[key]
    return item


def _emit_file_appended(matter_snapshot: dict, item: dict, *, actor: str, now: str) -> None:
    matter = matter_snapshot.get("matter") or {}
    matter_id = matter.get("id", "")
    payload_base = {
        "file": item.get("file"),
        "type": item.get("type"),
        "creator": item.get("creator"),
        "owner": item.get("owner"),
    }
    emit(
        TOPIC_FILE_APPENDED,
        matter_id=matter_id,
        actor=actor,
        at=now,
        payload=payload_base,
    )
    sc = item.get("status_change")
    if sc:
        emit(
            TOPIC_STATUS_CHANGED,
            matter_id=matter_id,
            actor=actor,
            at=now,
            payload={
                "from": sc.get("from"),
                "to": sc.get("to"),
                "trigger_file": item.get("file"),
                "trigger_type": item.get("type"),
            },
        )
    if item.get("type") == "result":
        emit(
            TOPIC_RESULT_CREATED,
            matter_id=matter_id,
            actor=actor,
            at=now,
            payload={
                "file": item.get("file"),
                "outcome": item.get("outcome"),
            },
        )


def _derive_category_from_timeline(matter_data: dict) -> str | None:
    """Pull category out of the first timeline item's path.

    file: "discussions/<category>/<slug>/<NNN>_..."
    """
    timeline = matter_data.get("timeline") or []
    if not timeline:
        return None
    first = timeline[0]
    path = first.get("file") or ""
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]


def _make_unique_matter_slug(workspace: Workspace, title: str) -> str:
    base = sanitize_slug(title)
    index_dir = workspace.index_dir
    if not matter_index_path(index_dir, base).exists():
        return base
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}-{suffix}"
