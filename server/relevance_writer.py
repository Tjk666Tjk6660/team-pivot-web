"""Real-time writer for relevance_events.

Subscribes to the in-process event bus (`server/events.py`) and writes
relevance rows on each matter mutation. Failures are swallowed + logged;
the hourly scanner (`server/relevance_scanner.py`) is the safety net.

Three paths:

  - file-level (kind='file'): on TOPIC_FILE_APPENDED, read the matter index,
    locate the just-appended item, and run compute_relevance against every
    registered user. INSERT OR IGNORE rows for hits.
  - mention-level (kind='mention'): on TOPIC_COMMENT_APPENDED, walk
    `payload.mentions` (raw open_ids), resolve each to a registered user,
    skip self-mentions and unregistered contacts, INSERT OR IGNORE rows.
  - matter-event (kind='mention', filename=''): on
    TOPIC_MATTER_OWNER_CHANGED, write a row for {matter_creator,
    from_owner, to_owner} so each sees a "与我相关" red dot on the matter.
    Actor self-excluded.

TOPIC_MATTER_CREATED is intentionally ignored: publish_matter_create also
emits TOPIC_FILE_APPENDED for the same first file, so handling both would
double-write (INSERT OR IGNORE makes it safe but wastes work).
"""

from __future__ import annotations

import logging
from typing import Callable

from server.events import (
    Event,
    TOPIC_COMMENT_APPENDED,
    TOPIC_FILE_APPENDED,
    TOPIC_MATTER_OWNER_CHANGED,
    subscribe,
)
from server.external_bindings import ExternalBindingRepo
from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUser, PivotUserRepo
from server.relevance import compute_relevance
from server.relevance_events import (
    REASON_MATTER_OWNER_CHANGED,
    RelevanceEventsRepo,
)
from server.workspace import Workspace

log = logging.getLogger(__name__)


def install(
    *,
    workspace: Workspace,
    users_repo: PivotUserRepo,
    bindings: ExternalBindingRepo | None = None,
    repo: RelevanceEventsRepo,
) -> Callable[[], None]:
    """Subscribe to the event bus. Returns an unsubscribe callable."""

    def on_event(event: Event) -> None:
        try:
            if event.topic == TOPIC_FILE_APPENDED:
                _handle_file_appended(workspace, users_repo, repo, event)
            elif event.topic == TOPIC_COMMENT_APPENDED:
                _handle_comment_appended(users_repo, bindings, repo, event)
            elif event.topic == TOPIC_MATTER_OWNER_CHANGED:
                _handle_matter_owner_changed(users_repo, bindings, repo, event)
        except Exception:
            log.exception(
                "relevance_writer failed topic=%s matter=%s",
                event.topic, event.matter_id,
            )

    return subscribe(on_event)


# ---------- handlers ----------


def _handle_file_appended(
    workspace: Workspace,
    users_repo: PivotUserRepo,
    repo: RelevanceEventsRepo,
    event: Event,
) -> None:
    file_rel = (event.payload or {}).get("file") or ""
    if not file_rel:
        log.warning(
            "file_appended event without file payload matter=%s", event.matter_id,
        )
        return

    data = read_matter_index(matter_index_path(workspace.index_dir, event.matter_id))
    if data is None:
        log.warning(
            "file_appended event for missing matter index matter=%s", event.matter_id,
        )
        return

    item = _find_item_by_file(data, file_rel)
    if item is None:
        log.warning(
            "file_appended event item not found in index matter=%s file=%s",
            event.matter_id, file_rel,
        )
        return

    filename = file_rel.rsplit("/", 1)[-1]
    item_created_at = str(item.get("created_at") or event.at)
    item_creator = str(item.get("creator") or event.actor)

    inserted = 0
    for user in users_repo.all():
        ok, reason = compute_relevance(item, data, user)
        if not ok or reason is None:
            continue
        if repo.insert_file(
            user.open_id,
            event.matter_id,
            filename,
            reason=reason,
            event_at=item_created_at,
            actor_pinyin=item_creator,
        ):
            inserted += 1

    log.info(
        "relevance file rows written matter=%s file=%s inserted=%d",
        event.matter_id, filename, inserted,
    )


def _handle_comment_appended(
    users_repo: PivotUserRepo,
    bindings: ExternalBindingRepo | None,
    repo: RelevanceEventsRepo,
    event: Event,
) -> None:
    payload = event.payload or {}
    target_file = payload.get("target_file") or ""
    mentions = list(payload.get("mentions") or [])
    # File author/owner are added by publish_matter_comment so the file's
    # creator gets a red dot for activity on their own work even when not
    # explicitly @-ed. Pre-resolved to open_ids upstream — no contacts
    # lookup needed here.
    file_author_open_ids = list(payload.get("file_author_open_ids") or [])
    recipients = mentions + file_author_open_ids
    if not target_file or not recipients:
        return

    filename = target_file.rsplit("/", 1)[-1]
    actor_pinyin = str(event.actor or "")

    inserted = 0
    for recipient_id in recipients:
        target = _resolve_user_ref(str(recipient_id), users_repo, bindings)
        if target is None:
            # unregistered contact — skip (they can't log in to see the red
            # dot anyway; DM still goes out via notify.py)
            continue
        if target.pinyin and target.pinyin == actor_pinyin:
            # self-exclusion
            continue
        if repo.insert_mention(
            target.open_id,
            event.matter_id,
            filename,
            comment_at=event.at,
            actor_pinyin=actor_pinyin,
        ):
            inserted += 1

    log.info(
        "relevance mention rows written matter=%s file=%s inserted=%d/%d",
        event.matter_id, filename, inserted, len(recipients),
    )


def _handle_matter_owner_changed(
    users_repo: PivotUserRepo,
    bindings: ExternalBindingRepo | None,
    repo: RelevanceEventsRepo,
    event: Event,
) -> None:
    payload = event.payload or {}
    candidates: list[str] = []
    for key in ("matter_creator", "from_owner", "to_owner"):
        v = payload.get(key)
        if v:
            candidates.append(str(v))
    if not candidates:
        return

    actor_pinyin = str(event.actor or "")
    seen_open_ids: set[str] = set()
    inserted = 0
    for pinyin in candidates:
        target = _resolve_user_ref(pinyin, users_repo, bindings)
        if target is None or not target.open_id:
            # Unregistered (legacy index, raw open_id, or contact-only owner).
            # No open_id to receive a red dot anyway.
            continue
        if target.pinyin and target.pinyin == actor_pinyin:
            continue
        if target.open_id in seen_open_ids:
            continue
        seen_open_ids.add(target.open_id)
        if repo.insert_matter_event(
            target.open_id,
            event.matter_id,
            reason=REASON_MATTER_OWNER_CHANGED,
            event_at=event.at,
            actor_pinyin=actor_pinyin,
        ):
            inserted += 1

    log.info(
        "relevance matter_owner_changed rows written matter=%s inserted=%d/%d",
        event.matter_id, inserted, len(seen_open_ids),
    )


def _find_item_by_file(matter_data: dict, file_rel: str) -> dict | None:
    for it in matter_data.get("timeline") or []:
        if it.get("file") == file_rel:
            return it
    return None


def _resolve_user_ref(
    ref: str,
    users_repo: PivotUserRepo,
    bindings: ExternalBindingRepo | None,
) -> PivotUser | None:
    target = users_repo.get_by_any_id(ref)
    if target is not None:
        return target
    if bindings is None:
        return None
    binding = bindings.lookup_any_provider(ref)
    return users_repo.get(binding.pivot_user_id) if binding is not None else None
