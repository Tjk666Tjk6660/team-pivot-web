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
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.pivot_users import PivotUser


def aggregate(
    matter_events: list[MatterEvent],
    all_users: list[PivotUser],
    window: TimeWindow,
) -> tuple[list[UserActivity], TeamSummary]:
    """Produce (UserActivity[] for all users with pinyin, TeamSummary).

    The returned UserActivity list includes EVERY user with a pinyin —
    inactive users land with empty arrays so the renderer can list them
    in the "今日 0 活动" bucket. Sorting is the caller's job."""
    activities: list[UserActivity] = []
    inactive_names: list[str] = []

    eligible_users = [u for u in all_users if u.pinyin]
    for user in eligible_users:
        ua = _build_user_activity(user, matter_events)
        activities.append(ua)
        if not ua.is_active:
            inactive_names.append(ua.display_name)

    summary = _build_team_summary(
        matter_events=matter_events,
        inactive_names=inactive_names,
        window=window,
    )
    return activities, summary


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _build_user_activity(
    user: PivotUser,
    events: list[MatterEvent],
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

    return UserActivity(
        pinyin=pinyin,
        display_name=user.name or pinyin,
        file_creates=tuple(file_creates),
        file_owns=tuple(file_owns),
        verifications_given=tuple(verifications_given),
        status_changes_triggered=tuple(status_changes_triggered),
        comments_given=tuple(comments_given),
        mentions_received=mentions_received,
    )


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
