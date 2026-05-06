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
    """A timeline file item (or its in-window comments) we care about.

    `matter_intent` 与 `matter_prev_summary` 是 matter 级语境(同一 matter 的
    所有 event 携带相同值,collect_matter 一次性计算 + 广播):
    - matter_intent:第一条 think 的 summary —— 这件事是干啥的、解决什么问题
    - matter_prev_summary:窗口之前最后一条 timeline 的 summary —— 上一步推到哪了
    供日报 LLM 写出"X 是 Y、之前 Z、今天 W"的因果叙事;空字符串表示该信号
    不存在(matter 是新开的 / 没 think / 等)。"""
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
    # matter 级语境(同一 matter 各 event 携带相同值;空串 = 信号不存在)
    matter_intent: str = ""            # 第一条 think.summary —— 这件事是干啥的、解决什么问题
    matter_prev_summary: str = ""      # 窗口之前最后一条 timeline.summary —— 上一步推到哪了
    matter_timeline_yaml: str = ""     # 完整 timeline 的精简 yaml(v0.4) —— 给 LLM 看 quote 链/状态推进/协作触发的原始 yaml 结构
    # matter 顶层 owner(`matter.owner` from index) —— 个人日报"作为负责人"
    # 角色化叙事用。空串 = matter 没有顶层 owner(老 matter / owner_change 之前)。
    # 公司日报不读这个字段(它从 timeline_yaml 内部直接看 matter.owner),
    # 所以新增此字段对公司日报数据流零影响。
    matter_owner: str = ""


# --------------------------------------------------------------------------- #
# Aggregated per-user view                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OwnedMatterDigest:
    """A matter where I am the matter-level owner (matter.owner == self),
    with today's activity digest. Used by personal-view narrative for
    "作为 X 事项的负责人,今天推到 Y" sentences.

    Only matters with at least one in-window event are included
    (passive-idle owners aren't surfaced here — those are covered by
    the company-view report).
    """
    matter_id: str
    title: str
    current_status: str             # planning/executing/paused/finished/cancelled/reviewed
    prev_summary: str               # 窗口前最后一条 summary,空串 = matter 是新开的
    today_events: tuple[MatterEvent, ...]   # 今天发生在该 matter 的事件(in-window only)


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
    # NEW: matter.owner == self 的事项,今天有活动的清单。供个人日报 prompt
    # 按事项分组叙事("作为 X 负责人推到 Y"),解决"按动作类型分桶"的局限。
    # 默认空 tuple 保证向后兼容(测试里旧用例不传也不会爆)。
    matters_as_owner: tuple[OwnedMatterDigest, ...] = ()

    @property
    def is_active(self) -> bool:
        """True iff at least one event attributed to this user in window."""
        return bool(
            self.file_creates or self.file_owns or self.verifications_given
            or self.comments_given or self.mentions_received
            or self.matters_as_owner
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
