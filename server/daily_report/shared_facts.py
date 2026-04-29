"""Shared fact base for v0.2 daily report (dengke #013).

dengke #013 原话:
    程序层统一提供同一份事实数据;公司报告和个人报告各自独立生成;
    每个报告都要求尽量基于事实来源表达。

本模块就是那一份"统一事实数据"。两个 LLM 调用(公司视角 / 个人视角)
都基于同一份 `SharedFacts` 构造各自的输入,但中间结果互不依赖。

派生信息(matters_by_category / matter_status_breakdown)在程序侧一次性
算好,prompt 构造时直接读,避免两个调用各自重新算一遍。"""
from __future__ import annotations

from dataclasses import dataclass

from server.daily_report.types import (
    MatterEvent,
    TeamSummary,
    TimeWindow,
    UserActivity,
)


@dataclass(frozen=True)
class MatterActivityMetrics:
    """单个 matter 在窗口内的活动强度指标。给 company narrate 写"今日最
    活跃事项"用 —— 数据是计数 / 类型分布,**不含 summary 内容**,所以 LLM
    只能写强度话术(讨论激烈 / 执行最快 / 落地效果好等),写不出"做了什么"。"""
    path: str                              # "category/slug",e.g. "Pivot/数据迁移方案"
    current_status: str
    file_count: int                        # 窗口内该 matter 新增文件数
    file_types: dict[str, int]             # think/act/verify/result/insight 各几个
    status_change: dict | None             # {"from","to"} 或 None
    verify_judgements: dict[str, int]      # passed/failed/partial 各几次
    comments_count: int                    # 窗口内该 matter 新评论数
    activity_score: int                    # 综合分,降序排序用


@dataclass(frozen=True)
class SharedFacts:
    """Unified fact base shared by company-view and personal-view narratives.

    All fields are immutable;两个 narrative 模块只读取,不应改写。"""
    window: TimeWindow
    matter_events: tuple[MatterEvent, ...]          # 24h 内窗口事件
    user_activities: tuple[UserActivity, ...]       # 全员(含 0 活动)
    summary: TeamSummary

    # ----- Derived buckets (computed once, both narratives may consume) ----
    matter_status_breakdown: dict[str, int]
    """current_status → 被触动 matter 数量。供公司视角判断"哪些事项还在
    讨论(planning)、哪些卡住(paused)、哪些完成(finished)"。"""

    file_type_breakdown: dict[str, int]
    """窗口内文件按 type 分桶:think / act / verify / result / insight 各几篇。
    比单一总数更能反映团队"在讨论"还是"在闭环"。"""

    verify_judgements: dict[str, int]
    """窗口内 verify 文件的判定汇总:passed / failed / partial 各几次。
    "实质推进"最强信号 —— passed 多 = 落地多;failed 多 = 卡点多。"""

    top_active_matters: tuple[MatterActivityMetrics, ...]
    """按 activity_score 降序排序,默认取前 5。每条只含强度指标,**不含
    matter 内容摘要**,确保 LLM 写不出虚构细节。"""

    @property
    def active_users(self) -> tuple[UserActivity, ...]:
        return tuple(ua for ua in self.user_activities if ua.is_active)

    @property
    def n_active(self) -> int:
        return sum(1 for ua in self.user_activities if ua.is_active)


def build_shared_facts(
    matter_events: list[MatterEvent],
    user_activities: list[UserActivity],
    summary: TeamSummary,
    window: TimeWindow,
    *,
    top_n_matters: int = 5,
) -> SharedFacts:
    """Compose `SharedFacts` from collector / aggregator outputs."""
    return SharedFacts(
        window=window,
        matter_events=tuple(matter_events),
        user_activities=tuple(user_activities),
        summary=summary,
        matter_status_breakdown=_count_matter_status(matter_events),
        file_type_breakdown=_count_file_types(matter_events),
        verify_judgements=_count_verify_judgements(matter_events),
        top_active_matters=_compute_top_active_matters(
            matter_events, top_n=top_n_matters,
        ),
    )


# --------------------------------------------------------------------------- #
# Derivation helpers                                                          #
# --------------------------------------------------------------------------- #


def category_of(file_path: str) -> str:
    """Extract category from `discussions/<category>/<slug>/...md`.

    Pivot 当前 matter 模型不在 index 里存 category;但文件物理路径承载了
    隐式的目录分类(Pivot / enclaws / 外部客户实施 ...)。落空返回"未分类"。"""
    if not file_path:
        return "未分类"
    parts = file_path.split("/")
    if len(parts) >= 3 and parts[0] == "discussions":
        return parts[1]
    return "未分类"


def _count_matter_status(events: list[MatterEvent]) -> dict[str, int]:
    """current_status → 被触动 matter 数量(基于该窗口内出现过事件的 matter)。
    一个 matter 同窗口多次事件只计一次(以最后出现的 status 为准 — 实际中
    matter status 在窗口内最多变一次)。"""
    matter_status: dict[str, str] = {}
    for e in events:
        # 后写覆盖前写;若 matter 在窗口内有 status_change,e.matter_current_status
        # 已经是 collect_matter 读到的最新值,不会因 status_change 再次变化。
        matter_status[e.matter_id] = e.matter_current_status
    counter: dict[str, int] = {}
    for s in matter_status.values():
        if not s:
            continue
        counter[s] = counter.get(s, 0) + 1
    return counter


def _count_file_types(events: list[MatterEvent]) -> dict[str, int]:
    """统计窗口内每种 file_type 的篇数。只统计 file_in_window 的。"""
    counter: dict[str, int] = {}
    for e in events:
        if not e.file_in_window or not e.file_type:
            continue
        counter[e.file_type] = counter.get(e.file_type, 0) + 1
    return counter


def _count_verify_judgements(events: list[MatterEvent]) -> dict[str, int]:
    """统计窗口内 verify 判定:passed / failed / partial / ... 各几次。"""
    counter: dict[str, int] = {}
    for e in events:
        if not e.file_in_window or e.file_type != "verify":
            continue
        for v in e.verifications:
            j = str(v.get("judgement") or "").strip()
            if not j:
                continue
            counter[j] = counter.get(j, 0) + 1
    return counter


def _compute_top_active_matters(
    events: list[MatterEvent], *, top_n: int,
) -> tuple[MatterActivityMetrics, ...]:
    """按 matter 聚合活动强度指标,降序取前 N。

    activity_score 公式(粗略,实测后再调):
      file_count
      + (status_change 出现 ? 5 : 0)
      + (有 result 文件 ? 3 : 0)
      + verify_judgements.passed * 2
      + verify_judgements.failed * 2  # failed 也是强信号
      + comments_count * 0.5(评论数权重低,单纯讨论也是活跃)
    """
    by_matter: dict[str, dict] = {}
    for e in events:
        if not e.file_in_window:
            # 评论事件(file_in_window=False)单独算 comments
            mid = e.matter_id
            slot = by_matter.setdefault(mid, _new_metric_slot(e))
            slot["comments_count"] += len(e.comments_in_window)
            continue
        mid = e.matter_id
        slot = by_matter.setdefault(mid, _new_metric_slot(e))
        # 用最后出现的 current_status 作为 matter 当前状态
        slot["current_status"] = e.matter_current_status or slot["current_status"]
        slot["file_count"] += 1
        if e.file_type:
            slot["file_types"][e.file_type] = (
                slot["file_types"].get(e.file_type, 0) + 1
            )
        if e.status_change and slot["status_change"] is None:
            slot["status_change"] = {
                "from": e.status_change.get("from"),
                "to": e.status_change.get("to"),
            }
        if e.file_type == "verify":
            for v in e.verifications:
                j = str(v.get("judgement") or "").strip()
                if not j:
                    continue
                slot["verify_judgements"][j] = (
                    slot["verify_judgements"].get(j, 0) + 1
                )
        slot["comments_count"] += len(e.comments_in_window)

    metrics: list[MatterActivityMetrics] = []
    for mid, slot in by_matter.items():
        score = (
            slot["file_count"]
            + (5 if slot["status_change"] else 0)
            + (3 if slot["file_types"].get("result", 0) else 0)
            + slot["verify_judgements"].get("passed", 0) * 2
            + slot["verify_judgements"].get("failed", 0) * 2
            + slot["comments_count"] // 2
        )
        if score == 0:
            # 没文件没评论的边缘情况(理论上 collect_matter 不会留下),跳过
            continue
        metrics.append(MatterActivityMetrics(
            path=slot["path"],
            current_status=slot["current_status"],
            file_count=slot["file_count"],
            file_types=dict(slot["file_types"]),
            status_change=slot["status_change"],
            verify_judgements=dict(slot["verify_judgements"]),
            comments_count=slot["comments_count"],
            activity_score=score,
        ))

    metrics.sort(key=lambda m: (-m.activity_score, m.path))
    return tuple(metrics[:top_n])


def _new_metric_slot(e: MatterEvent) -> dict:
    """初始化一个 matter 的活动指标累加 slot。path = category/matter_id。"""
    return {
        "path": f"{category_of(e.file)}/{e.matter_id}",
        "current_status": e.matter_current_status or "",
        "file_count": 0,
        "file_types": {},
        "status_change": None,
        "verify_judgements": {},
        "comments_count": 0,
    }
