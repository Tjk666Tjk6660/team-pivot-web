"""Render `TeamReport` to a Feishu interactive card dict (schema 2.0).
Composition reuses `notify._card_shell` so we share header / template
machinery with the existing card builders.

The daily report card has **no CTA button** — the report is self-contained
in the markdown, and the Pivot product has no admin page that supports
this task, so a "进入 Pivot" button would just dump readers on the home
page. If a deep-link makes sense later (e.g. per-user dashboard), add
`button_text=...` + `thread_url=...` to the `_card_shell` call below."""
from __future__ import annotations

from datetime import datetime

from server.daily_report.types import TeamReport
from server.notify import _card_shell


def build_daily_report_card(report: TeamReport) -> dict:
    """Build the daily report card dict ready for `FeishuNotifier.broadcast_card`.

    Layout:
      - header: 📊 团队日报 · M-D
      - 覆盖窗口
      - (?) 代码仓库 fetch warning
      - 📈 团队总览 (4 stat numbers + matter / 人 数)
      - (zero-activity branch ends here)
      - ⭐ 团队评分 + 4 维度 + AI 一句话总结  /  fallback 警告
      - 👥 个人评分(降序,由 caller 排好)
      - 😴 今日 0 活动列表
      - ❓ 未识别 commits 总数
    """
    s = report.summary
    sc = report.scoring
    template = "blue" if sc.status == "ai" else "wathet"
    header = f"📊 团队日报 · {s.window.label}"

    parts: list[str] = []

    # Covered window
    parts.append(
        f"📅 覆盖窗口:{_fmt_dt(s.window.since)} → {_fmt_dt(s.window.until)}"
    )
    if s.fetch_warning:
        parts.append(f"⚠️ 代码仓库未刷新({s.fetch_warning})")
    parts.append("")

    # Team stats — matter 主线在前,代码辅助参考在后
    parts.append("**📈 团队总览**")
    parts.append(
        f"- matter 事件 **{s.total_files}** 篇 · "
        f"状态推进 **{s.total_status_changes}** 次 · "
        f"评论 **{s.total_comments}** 条"
    )
    n_active = sum(1 for ua in report.user_activities if ua.is_active)
    parts.append(
        f"- 涉及 matter **{s.matters_touched}** 个 · "
        f"活跃成员 **{n_active}** 人"
    )
    if s.total_commits:
        parts.append(
            f"- _配套代码提交 {s.total_commits} 个(辅助参考)_"
        )
    parts.append("")

    # Zero-activity short-circuit
    if (
        s.total_files == 0
        and s.total_commits == 0
        and s.total_comments == 0
    ):
        parts.append("😴 今日团队无活动(节假日 / 集中放空)")
        return _card_shell(
            header=header,
            template=template,
            markdown="\n".join(parts).rstrip(),
        )

    # Team score block
    if sc.status == "ai":
        parts.append(
            f"**⭐ 团队评分:{_stars(sc.team_score)} ({sc.team_score})**"
        )
        sub = sc.team_sub_scores
        parts.append(
            f"产出 {_fmt_sub(sub.get('output'))} · "
            f"推进 {_fmt_sub(sub.get('progress'))} · "
            f"阻塞 {_fmt_sub(sub.get('blocker'))} · "
            f"协作 {_fmt_sub(sub.get('collab'))}"
        )
        if sc.team_summary:
            parts.append(f"_{sc.team_summary}_")
    else:
        parts.append("**⚠️ AI 评分缺失,以下仅展示统计**")
        if sc.fallback_reason:
            parts.append(f"_(原因:{sc.fallback_reason})_")
    parts.append("")

    # Per-user scores
    if sc.per_user:
        parts.append("**👥 个人评分**")
        ua_by_pinyin = {ua.pinyin: ua for ua in report.user_activities}
        for u in sc.per_user:
            ua = ua_by_pinyin.get(u.pinyin)
            display = ua.display_name if ua else u.pinyin
            parts.append(
                f"**{display}** · {_stars(u.score)} ({u.score})"
            )
            if u.summary:
                parts.append(f"  · {u.summary}")
            if u.highlights:
                parts.append(f"  · {' / '.join(u.highlights)}")
        parts.append("")

    # Inactive list
    if s.inactive_users:
        parts.append(f"😴 今日 0 活动:{', '.join(s.inactive_users)}")
    # Unattributed commits 是 author 映射运维提示,不是事项异常 —— 用淡化样式
    # 提醒管理员去补 daily_report.commit_author_overrides,而不是放在主区让人误以为
    # "团队有 N 个未识别贡献是个大问题"
    if s.unattributed_commits:
        parts.append(
            f"_运维提示:{len(s.unattributed_commits)} 个 commit 暂未关联到用户,"
            f"可在 settings 的 `daily_report.commit_author_overrides` 补充映射_"
        )

    return _card_shell(
        header=header,
        template=template,
        markdown="\n".join(parts).rstrip(),
    )


# --------------------------------------------------------------------------- #
# format helpers                                                              #
# --------------------------------------------------------------------------- #


def _stars(score: float) -> str:
    """Render a 1.0~5.0 score as a 5-char ★/☆ string.

    Uses floor() so 4.5 reads as ★★★★☆ and 4.0 also ★★★★☆ — the half-step
    is conveyed by the numeric `(4.5)` shown next to it. Avoiding the
    half-star unicode (⯪/½) sidesteps font-fallback issues in Feishu cards."""
    if score is None:
        return "─────"
    full = max(0, min(5, int(score)))
    return "★" * full + "☆" * (5 - full)


def _fmt_sub(v: float | None) -> str:
    """Sub-score may be None in fallback mode."""
    if v is None:
        return "—"
    return f"{v:.1f}"


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
