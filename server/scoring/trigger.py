"""Subscribe to TOPIC_RESULT_CREATED and enqueue scoring jobs.

This module runs in whatever thread emit() is called from (typically a
FastAPI sync route in the threadpool). It does ONLY:
  1. Filter event (topic, scoring.enabled, outcome=='finished')
  2. Read matter index → get matter.owner pinyin
  3. Resolve owner pinyin → pivot_user.id
  4. Enqueue ScoringJob (thread-safe via ScoringQueue)

Per design §1.1 决策 A 枝节边界, an unresolvable owner does NOT create a run
row — only logged + dropped. Run rows track only what we actually attempt.

Per design §1.3 决策 C, only outcome='finished' triggers; 'cancelled' is
ignored (semantically "决定不做了" — not the owner's fault).
"""
from __future__ import annotations

import logging
from typing import Callable

from server.events import TOPIC_RESULT_CREATED, Event, subscribe
from server.matter_index import matter_index_path, read_matter_index
from server.pivot_users import PivotUserRepo
from server.scoring.resolve import PinyinResolver
from server.scoring.store import ScoringJob
from server.settings import SettingsRepo
from server.workspace import Workspace

log = logging.getLogger(__name__)

# Settings keys (single source of truth — referenced from worker + admin API too)
KEY_ENABLED = "scoring.enabled"
KEY_VISIBILITY = "scoring.visibility"
KEY_MODEL = "scoring.model"
KEY_TIMEOUT_SECONDS = "scoring.timeout_seconds"


def install(
    *,
    workspace: Workspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
    queue,                # ScoringQueue (avoid circular import; duck-typed .enqueue())
) -> Callable[[], None]:
    """Subscribe to the event bus. Returns an unsubscribe callable."""

    def on_event(event: Event) -> None:
        try:
            _handle(event, workspace, settings, pivot_users, queue)
        except Exception:
            # Swallow + log: trigger errors must never break publish flow.
            log.exception(
                "scoring trigger failed topic=%s matter=%s",
                event.topic, event.matter_id,
            )

    return subscribe(on_event)


def is_enabled(settings: SettingsRepo) -> bool:
    """Single source of truth for the on/off check (also used by admin API)."""
    raw = (settings.get(KEY_ENABLED) or "0").strip().lower()
    return raw not in ("", "0", "false", "off", "no")


# ---------- internals ----------


def _handle(
    event: Event,
    workspace: Workspace,
    settings: SettingsRepo,
    pivot_users: PivotUserRepo,
    queue,
) -> None:
    if event.topic != TOPIC_RESULT_CREATED:
        return
    if not is_enabled(settings):
        return

    payload = event.payload or {}
    if payload.get("outcome") != "finished":
        # Decision C: cancelled doesn't trigger
        return

    index = read_matter_index(matter_index_path(workspace.index_dir, event.matter_id))
    if index is None:
        log.warning(
            "scoring trigger: matter index missing matter=%s", event.matter_id,
        )
        return

    matter = index.get("matter") or {}
    owner_pinyin = matter.get("owner") or ""
    if not owner_pinyin:
        log.info(
            "scoring trigger skipped: matter.owner empty matter=%s",
            event.matter_id,
        )
        return

    # Fresh resolver per event — cache lifetime tied to this single lookup,
    # avoids stale-cache risk if a user's pinyin changed since last event.
    resolver = PinyinResolver(pivot_users._db)
    owner = resolver.resolve(owner_pinyin)
    if owner is None:
        log.info(
            "scoring trigger skipped: owner pinyin not resolved matter=%s pinyin=%s",
            event.matter_id, owner_pinyin,
        )
        return

    matter_category = _derive_category(index)
    if not matter_category:
        log.warning(
            "scoring trigger: cannot derive category from timeline matter=%s",
            event.matter_id,
        )
        return

    # Best-effort actor resolution — actor pinyin comes from event.actor
    # (publish.py sets it to the user.pinyin who created the result file).
    actor_id: str | None = None
    if event.actor:
        actor = resolver.resolve(event.actor)
        actor_id = actor.id if actor else None

    job = ScoringJob(
        matter_id=event.matter_id,
        matter_category=matter_category,
        subject_user_id=owner.id,
        triggered_by="auto",
        triggered_actor_id=actor_id,
    )
    queue.enqueue(job)
    log.info(
        "scoring trigger enqueued matter=%s subject_user_id=%s actor=%s",
        event.matter_id, owner.id, event.actor,
    )


def _derive_category(index: dict) -> str | None:
    """Pull category from the first timeline file path.

    file: "discussions/<category>/<slug>/<NNN>_..."
    """
    timeline = index.get("timeline") or []
    if not timeline:
        return None
    file_rel = timeline[0].get("file") or ""
    parts = file_rel.split("/")
    if len(parts) < 4 or parts[0] != "discussions":
        return None
    return parts[1]
