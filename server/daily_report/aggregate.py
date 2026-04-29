"""Aggregate raw collector outputs into per-user `UserActivity` records and
a top-level `TeamSummary`.

Routing rules:
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
  - commits         = commits where matched_pinyin == user.pinyin

Items with `creator/owner` set to a raw `ou_xxx` open_id (未注册联系人 fallback,
see `publish.py::_resolve_owner_for_index`) still count toward team-level totals
but are NOT routed to any per-user record. The "个人列表" only covers users with
a pinyin in the `users` table."""
from __future__ import annotations

from server.daily_report.types import (
    CommitRecord,
    MatterEvent,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.users import User


def aggregate(
    matter_events: list[MatterEvent],
    matched_commits: list[CommitRecord],
    unattributed_commits: list[CommitRecord],
    all_users: list[User],
    window: TimeWindow,
    *,
    fetch_warning: str | None = None,
) -> tuple[list[UserActivity], TeamSummary]:
    """Produce (UserActivity[] for all users with pinyin, TeamSummary).

    The returned UserActivity list includes EVERY user with a pinyin —
    inactive users land with empty arrays so the renderer can list them
    in the "今日 0 活动" bucket. Sorting is the caller's job (typically by
    AI score, after scoring runs)."""
    activities: list[UserActivity] = []
    inactive_names: list[str] = []

    eligible_users = [u for u in all_users if u.pinyin]
    for user in eligible_users:
        ua = _build_user_activity(user, matter_events, matched_commits)
        activities.append(ua)
        if not ua.is_active:
            inactive_names.append(ua.display_name)

    summary = _build_team_summary(
        matter_events=matter_events,
        all_commits=matched_commits + unattributed_commits,
        unattributed_commits=unattributed_commits,
        inactive_names=inactive_names,
        window=window,
        fetch_warning=fetch_warning,
    )
    return activities, summary


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _build_user_activity(
    user: User,
    events: list[MatterEvent],
    commits: list[CommitRecord],
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

    user_commits = [c for c in commits if c.matched_pinyin == pinyin]

    return UserActivity(
        pinyin=pinyin,
        display_name=user.name or pinyin,
        file_creates=tuple(file_creates),
        file_owns=tuple(file_owns),
        verifications_given=tuple(verifications_given),
        status_changes_triggered=tuple(status_changes_triggered),
        comments_given=tuple(comments_given),
        mentions_received=mentions_received,
        commits=tuple(user_commits),
    )


def _build_team_summary(
    *,
    matter_events: list[MatterEvent],
    all_commits: list[CommitRecord],
    unattributed_commits: list[CommitRecord],
    inactive_names: list[str],
    window: TimeWindow,
    fetch_warning: str | None,
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
        total_commits=len(all_commits),
        total_status_changes=total_status_changes,
        total_comments=total_comments,
        matters_touched=matters_touched,
        unattributed_commits=tuple(unattributed_commits),
        inactive_users=tuple(inactive_names),
        fetch_warning=fetch_warning,
    )
