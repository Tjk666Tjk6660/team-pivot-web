"""Aggregate matter timeline events into per-user `UserActivity` records and
a top-level `TeamSummary`.

Routing rules (v0.2):
  - file_creates    = events where event.creator == user.pinyin AND file_in_window
  - file_owns       = events where event.owner   == user.pinyin AND creator != self
                                                  AND file_in_window
                       (派给我的活,我没创建但负责推进)
  - verifications_given = verifications on `verify` files where the verify file's
                          owner == user.pinyin
  - status_changes_triggered = the subset of file_creates that carry a
                                non-null status_change
  - comments_given  = comments_in_window across ALL events whose author == self
                       (covers commenting on own files AND others')
  - mentions_received = sum across ALL events of comments_in_window where
                         user.pinyin ∈ comment.mentions

Items with `creator/owner` set to a raw `ou_xxx` open_id (未注册联系人 fallback,
see `publish.py::_resolve_owner_for_index`) still count toward team-level totals
but are NOT routed to any per-user record. The "个人列表" only covers users with
a pinyin in the `users` table.

v0.2 删除了 commits 路径(dengke #005:工作分布在多个 repo,单仓库统计偏)。"""
from __future__ import annotations

from server.daily_report.types import (
    MatterEvent,
    OwnedMatterDigest,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.users import User


def aggregate(
    matter_events: list[MatterEvent],
    all_users: list[User],
    window: TimeWindow,
) -> tuple[list[UserActivity], TeamSummary]:
    """Produce (UserActivity[] for all users with pinyin, TeamSummary).

    The returned UserActivity list includes EVERY user with a pinyin —
    inactive users land with empty arrays so the renderer can list them
    in the "今日 0 活动" bucket. Sorting is the caller's job."""
    # 一次性把 events 按 matter 分桶,_build_user_activity 用得着 + 后面构造
    # OwnedMatterDigest 也用得着,避免每个 user 都重新分桶一遍。
    events_by_matter = _group_events_by_matter(matter_events)

    activities: list[UserActivity] = []
    inactive_names: list[str] = []

    eligible_users = [u for u in all_users if u.pinyin]
    for user in eligible_users:
        ua = _build_user_activity(user, matter_events, events_by_matter)
        activities.append(ua)
        if not ua.is_active:
            inactive_names.append(ua.display_name)

    summary = _build_team_summary(
        matter_events=matter_events,
        inactive_names=inactive_names,
        window=window,
    )
    return activities, summary


def _group_events_by_matter(
    events: list[MatterEvent],
) -> dict[str, list[MatterEvent]]:
    """Group events by matter_id, preserving original order."""
    out: dict[str, list[MatterEvent]] = {}
    for ev in events:
        out.setdefault(ev.matter_id, []).append(ev)
    return out


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _build_user_activity(
    user: User,
    events: list[MatterEvent],
    events_by_matter: dict[str, list[MatterEvent]],
) -> UserActivity:
    pinyin = user.pinyin
    assert pinyin is not None  # eligible_users filter guarantees

    file_creates: list[MatterEvent] = []
    file_owns: list[MatterEvent] = []
    status_changes_triggered: list[MatterEvent] = []
    verifications_given: list[dict] = []
    comments_given = []
    mentions_received = 0

    for ev in events:
        # File-level routing — only events where the file itself is in window
        # count as the user "doing" something (a comment on someone else's
        # old file is collaboration, handled separately below).
        if ev.file_in_window:
            if ev.creator == pinyin:
                file_creates.append(ev)
                if ev.status_change:
                    status_changes_triggered.append(ev)
                if ev.file_type == "verify":
                    verifications_given.extend(ev.verifications)
            elif ev.owner == pinyin:
                # Owner is someone else's — the user is on the hook to drive
                # this work but didn't author the file. Still relevant.
                file_owns.append(ev)
                if ev.file_type == "verify":
                    # Defensive — verify usually has creator == owner, but
                    # if they diverge (group lead created, member ran the
                    # verify), the verifier is the owner.
                    verifications_given.extend(ev.verifications)

        # Comments routing — by author, regardless of file_in_window. A
        # comment on yesterday's file from today is today's collaboration.
        for c in ev.comments_in_window:
            if c.author == pinyin:
                comments_given.append(c)
            if pinyin in c.mentions:
                mentions_received += 1

    matters_as_owner = _build_matters_as_owner(pinyin, events_by_matter)

    return UserActivity(
        pinyin=pinyin,
        display_name=user.name or pinyin,
        file_creates=tuple(file_creates),
        file_owns=tuple(file_owns),
        verifications_given=tuple(verifications_given),
        status_changes_triggered=tuple(status_changes_triggered),
        comments_given=tuple(comments_given),
        mentions_received=mentions_received,
        matters_as_owner=matters_as_owner,
    )


def _build_matters_as_owner(
    pinyin: str,
    events_by_matter: dict[str, list[MatterEvent]],
) -> tuple[OwnedMatterDigest, ...]:
    """For each matter where the user is owner (explicit or inferred) and
    there's at least one in-window event, build a digest.

    "Owner" judgment, in priority:
      1. Explicit: `matter.owner` == pinyin (post-owner_change matters)
      2. Inferred fallback: `matter.owner` is empty (legacy matter where
         owner_change feature wasn't yet adopted) AND the user authored at
         least one in-window file in that matter. The pragmatic assumption:
         老 matter 缺失 owner 字段时,真实负责人就是当下还在该事项里下场
         写文件的人。比起"丢失整个事项",误归一两条更可接受。

    "In-window" means: the matter has at least one MatterEvent (which by
    construction in collect_matter only emits events where file is in window
    or there's an in-window comment). So presence in events_by_matter ==
    today activity.
    """
    digests: list[OwnedMatterDigest] = []
    for matter_id, evs in events_by_matter.items():
        if not evs:
            continue
        # All events of one matter share the same matter-level metadata,
        # so reading any event's matter_owner / matter_title / etc. works.
        first = evs[0]
        is_owner = False
        if first.matter_owner:
            # Explicit owner — only match if it's me
            if first.matter_owner == pinyin:
                is_owner = True
        else:
            # Legacy matter without owner field — fall back to "did self
            # author any in-window file in this matter"
            is_owner = any(
                ev.file_in_window and ev.creator == pinyin
                for ev in evs
            )
        if not is_owner:
            continue
        digests.append(OwnedMatterDigest(
            matter_id=matter_id,
            title=first.matter_title,
            current_status=first.matter_current_status,
            prev_summary=first.matter_prev_summary,
            today_events=tuple(evs),
        ))
    return tuple(digests)


def _build_team_summary(
    *,
    matter_events: list[MatterEvent],
    inactive_names: list[str],
    window: TimeWindow,
) -> TeamSummary:
    # Count "file events": items whose file is in window. Comments-only
    # events (file_in_window=False) don't bump this — they bump comment count.
    files_in_window = [e for e in matter_events if e.file_in_window]
    total_status_changes = sum(
        1 for e in files_in_window if e.status_change
    )
    total_comments = sum(
        len(e.comments_in_window) for e in matter_events
    )
    matters_touched = len({e.matter_id for e in matter_events})

    return TeamSummary(
        window=window,
        total_files=len(files_in_window),
        total_status_changes=total_status_changes,
        total_comments=total_comments,
        matters_touched=matters_touched,
        inactive_users=tuple(inactive_names),
    )
