"""Real-time writer for relevance_events.

Subscribes to the in-process event bus (`server/events.py`) and writes
relevance rows on each matter mutation. Failures are swallowed + logged;
the hourly scanner (`server/relevance_scanner.py`) is the safety net.

Two paths:

  - file-level (kind='file'): on TOPIC_FILE_APPENDED, read the matter index,
    locate the just-appended item, and run compute_relevance against every
    registered user. INSERT OR IGNORE rows for hits.
  - mention-level (kind='mention'): on TOPIC_COMMENT_APPENDED, walk
    `payload.mentions` (raw open_ids), resolve each to a registered user,
    skip self-mentions and unregistered contacts, INSERT OR IGNORE rows.

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
    subscribe,
)
from server.matter_index import matter_index_path, read_matter_index
from server.relevance import compute_relevance
from server.relevance_events import RelevanceEventsRepo
from server.users import UserRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)


def install(
    *,
    workspace: Workspace,
    users_repo: UserRepo,
    repo: RelevanceEventsRepo,
) -> Callable[[], None]:
    """Subscribe to the event bus. Returns an unsubscribe callable."""

    def on_event(event: Event) -> None:
        try:
            if event.topic == TOPIC_FILE_APPENDED:
                _handle_file_appended(workspace, users_repo, repo, event)
            elif event.topic == TOPIC_COMMENT_APPENDED:
                _handle_comment_appended(users_repo, repo, event)
        except Exception:
            log.exception(
                "relevance_writer failed topic=%s matter=%s",
                event.topic, event.matter_id,
            )

    return subscribe(on_event)


# ---------- handlers ----------


def _handle_file_appended(
    workspace: Workspace,
    users_repo: UserRepo,
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
    users_repo: UserRepo,
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
        target = users_repo.get_by_any_id(str(recipient_id))
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


def _find_item_by_file(matter_data: dict, file_rel: str) -> dict | None:
    for it in matter_data.get("timeline") or []:
        if it.get("file") == file_rel:
            return it
    return None
