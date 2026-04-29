"""Dataclasses for the daily-report pipeline. All structures are frozen
(immutable) so they pass safely between collector / aggregator / scorer /
renderer without surprise mutation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


# --------------------------------------------------------------------------- #
# Time window                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TimeWindow:
    """Half-open interval [since, until). Both tz-aware (Asia/Shanghai
    after `compute_window` / `parse_iso_window` normalize)."""
    since: datetime
    until: datetime

    @property
    def label(self) -> str:
        """`{month}-{day}` of the day this report covers (= since.date()),
        used in the card header (e.g. '4-26')."""
        return f"{self.since.month}-{self.since.day}"

    @property
    def date_iso(self) -> str:
        """ISO date of the day this report covers."""
        return self.since.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Raw event records                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MatterEventComment:
    """A comment on a matter timeline item that fell inside the window —
    even when its parent file was created earlier."""
    created_at: datetime
    author: str          # pinyin or open_id (whatever the index has)
    body: str
    mentions: tuple[str, ...]   # pinyin / open_id list


@dataclass(frozen=True)
class MatterEvent:
    """A timeline file item (or its in-window comments) we care about."""
    matter_id: str
    matter_title: str
    matter_current_status: str
    file: str                          # discussions/<cat>/<slug>/NNN_<author>_<type>_<hash>.md
    file_type: str                     # think / act / verify / result / insight
    created_at: datetime               # tz-aware (Asia/Shanghai)
    file_in_window: bool               # True 当 file 自身的 created_at 在窗口内
    creator: str                       # pinyin or open_id
    owner: str
    summary: str
    status_change: dict | None         # {"from": "...", "to": "..."} or None
    verifications: tuple[dict, ...]    # verify file's [{target, judgement, comment}, ...]
    comments_in_window: tuple[MatterEventComment, ...]


@dataclass(frozen=True)
class CommitRecord:
    """A git commit from the team-pivot-web code mirror, in window."""
    sha: str
    author_name: str
    author_email: str
    committed_at: datetime
    subject: str
    files_changed: int
    insertions: int
    deletions: int
    matched_pinyin: str | None = None  # filled by attribution.py


# --------------------------------------------------------------------------- #
# Aggregated per-user view                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserActivity:
    pinyin: str
    display_name: str                              # users.name 优先,fallback pinyin
    file_creates: tuple[MatterEvent, ...]          # creator == self
    file_owns: tuple[MatterEvent, ...]             # owner == self AND creator != self
    verifications_given: tuple[dict, ...]          # 自己作为 verify owner 给的 judgements
    status_changes_triggered: tuple[MatterEvent, ...]  # 自己创建的 + 带 status_change 的
    comments_given: tuple[MatterEventComment, ...]  # 自己写的评论(自己/别人文件)
    mentions_received: int
    commits: tuple[CommitRecord, ...]

    @property
    def is_active(self) -> bool:
        """True iff at least one event/commit attributed to this user."""
        return bool(
            self.file_creates or self.file_owns or self.verifications_given
            or self.comments_given or self.commits or self.mentions_received
        )


@dataclass(frozen=True)
class TeamSummary:
    """Window-level aggregate stats. `inactive_users` and `unattributed_commits`
    surface in the card so the manager sees gaps."""
    window: TimeWindow
    total_files: int
    total_commits: int
    total_status_changes: int
    total_comments: int
    matters_touched: int
    unattributed_commits: tuple[CommitRecord, ...]
    inactive_users: tuple[str, ...]                # display_names
    fetch_warning: str | None = None               # 代码仓库未刷新时的提示文本


# --------------------------------------------------------------------------- #
# AI scoring                                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserScore:
    pinyin: str
    score: float
    sub_scores: dict[str, float | None]            # {output, progress, blocker, collab}
    summary: str                                   # <= ~60 字
    highlights: tuple[str, ...]                    # 1-3 突出条目


@dataclass(frozen=True)
class ScoringResult:
    status: Literal["ai", "fallback"]
    team_score: float
    team_sub_scores: dict[str, float | None]
    team_summary: str
    per_user: tuple[UserScore, ...]
    raw_response: str = ""                         # AI 原文 for debug
    fallback_reason: str | None = None             # 降级时填


# --------------------------------------------------------------------------- #
# Final report                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TeamReport:
    """Top-level structure passed to the renderer."""
    summary: TeamSummary
    user_activities: tuple[UserActivity, ...]      # 已按总分降序排序
    scoring: ScoringResult
