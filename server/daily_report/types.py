"""Dataclasses for the daily-report pipeline (v0.2).

v0.2 主轴(基于 dengke #013):
- 只读 Pivot matter 数据,不接入 git 代码仓库
- 不做评分,生成两份独立 LLM 报告(公司视角 / 个人视角)
- 共享底层事实数据,不共享 LLM 中间结果

本文件只保留事实层 dataclass。SharedFacts(Phase 2)+ 公司/个人 narrative
dataclass(Phase 3/4)在各自模块声明,避免 types.py 又长又重。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
# Raw event records (collected from matter index timeline)                   #
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


# --------------------------------------------------------------------------- #
# Aggregated per-user view                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserActivity:
    """Per-user roll-up of matter timeline activity within the window.

    v0.2 去除 commits / mentions_received 之外的旧字段保留;commits 字段
    整体删除(数据源不再读 git)。"""
    pinyin: str
    display_name: str                              # users.name 优先,fallback pinyin
    file_creates: tuple[MatterEvent, ...]          # creator == self
    file_owns: tuple[MatterEvent, ...]             # owner == self AND creator != self
    verifications_given: tuple[dict, ...]          # 自己作为 verify owner 给的 judgements
    status_changes_triggered: tuple[MatterEvent, ...]  # 自己创建的 + 带 status_change 的
    comments_given: tuple[MatterEventComment, ...]  # 自己写的评论(自己/别人文件)
    mentions_received: int

    @property
    def is_active(self) -> bool:
        """True iff at least one event attributed to this user in window."""
        return bool(
            self.file_creates or self.file_owns or self.verifications_given
            or self.comments_given or self.mentions_received
        )


@dataclass(frozen=True)
class TeamSummary:
    """Window-level aggregate stats. `inactive_users` lists users who
    showed zero activity in the window — surfaced in the personal-view card."""
    window: TimeWindow
    total_files: int
    total_status_changes: int
    total_comments: int
    matters_touched: int
    inactive_users: tuple[str, ...]                # display_names
