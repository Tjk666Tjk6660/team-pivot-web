"""Tests for `server.daily_report.aggregate.aggregate`."""
from __future__ import annotations

from datetime import datetime, timezone

from server.daily_report.aggregate import aggregate
from server.daily_report.types import (
    CommitRecord,
    MatterEvent,
    MatterEventComment,
    TimeWindow,
)
from server.daily_report.window import CHINA_TZ
from server.users import User


# --------------------------------------------------------------------------- #
# fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #


def _user(pinyin: str | None, name: str = "") -> User:
    return User(
        open_id=f"ou_{pinyin or 'none'}",
        union_id=None,
        name=name or pinyin or "?",
        avatar_url="",
        pinyin=pinyin,
        github_username=None,
        markdown_style=None,
        created_at=0.0,
    )


def _window() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 26, 9, 30, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 27, 9, 30, tzinfo=CHINA_TZ),
    )


def _event(
    *, matter_id: str = "demo", file: str, file_type: str,
    creator: str, owner: str | None = None,
    file_in_window: bool = True,
    status_change: dict | None = None,
    verifications: tuple[dict, ...] = (),
    comments_in_window: tuple[MatterEventComment, ...] = (),
) -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id,
        matter_title=matter_id,
        matter_current_status="executing",
        file=file,
        file_type=file_type,
        created_at=datetime(2026, 4, 26, 15, 0, tzinfo=CHINA_TZ),
        file_in_window=file_in_window,
        creator=creator,
        owner=owner or creator,
        summary="",
        status_change=status_change,
        verifications=verifications,
        comments_in_window=comments_in_window,
    )


def _comment(*, author: str, body: str = "", mentions: tuple[str, ...] = ()) -> MatterEventComment:
    return MatterEventComment(
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=CHINA_TZ),
        author=author, body=body, mentions=mentions,
    )


def _commit(*, sha: str, pinyin: str | None, subject: str = "x") -> CommitRecord:
    return CommitRecord(
        sha=sha, author_name=pinyin or "ext", author_email=f"{pinyin or 'ext'}@x",
        committed_at=datetime(2026, 4, 26, 14, tzinfo=timezone.utc),
        subject=subject, files_changed=1, insertions=10, deletions=0,
        matched_pinyin=pinyin,
    )


# --------------------------------------------------------------------------- #
# basic routing                                                               #
# --------------------------------------------------------------------------- #


def test_file_creates_routed_to_creator():
    """creator==alice → enters alice.file_creates, not bob's."""
    alice = _user("alice")
    bob = _user("bob")
    ev = _event(file="f1", file_type="think", creator="alice", owner="alice")
    activities, _ = aggregate([ev], [], [], [alice, bob], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["alice"].file_creates) == 1
    assert len(by_pinyin["bob"].file_creates) == 0


def test_file_owns_routed_to_owner_when_creator_differs():
    """alice 创建的 act 派给 bob → bob.file_owns 而不是 file_creates。"""
    alice = _user("alice")
    bob = _user("bob")
    ev = _event(file="f1", file_type="act", creator="alice", owner="bob")
    activities, _ = aggregate([ev], [], [], [alice, bob], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["alice"].file_creates) == 1
    assert len(by_pinyin["bob"].file_owns) == 1
    assert len(by_pinyin["bob"].file_creates) == 0


def test_self_owns_only_in_creates_not_owns():
    """creator == owner → 只进 file_creates,不重复进 file_owns。"""
    alice = _user("alice")
    ev = _event(file="f1", file_type="think", creator="alice", owner="alice")
    activities, _ = aggregate([ev], [], [], [alice], _window())
    a = activities[0]
    assert len(a.file_creates) == 1
    assert len(a.file_owns) == 0


def test_status_change_triggered_subset_of_creates():
    """status_change 必然出现在 creator 的 file_creates 中 + 在 status_changes_triggered。"""
    alice = _user("alice")
    ev = _event(
        file="f1", file_type="result", creator="alice",
        status_change={"from": "executing", "to": "finished"},
    )
    activities, _ = aggregate([ev], [], [], [alice], _window())
    a = activities[0]
    assert len(a.file_creates) == 1
    assert len(a.status_changes_triggered) == 1


def test_verify_verifications_attached_to_creator():
    """verify file 的 verifications[] 进 creator 的 verifications_given。"""
    dengke = _user("dengke")
    ev = _event(
        file="v1", file_type="verify", creator="dengke",
        verifications=({"target": "act1", "judgement": "passed"},),
    )
    activities, _ = aggregate([ev], [], [], [dengke], _window())
    assert len(activities[0].verifications_given) == 1
    assert activities[0].verifications_given[0]["judgement"] == "passed"


# --------------------------------------------------------------------------- #
# comments / mentions                                                         #
# --------------------------------------------------------------------------- #


def test_comments_routed_to_author_across_files():
    """Bob 在 alice 的文件上留言 + 在 carol 的文件上留言 → 都进 bob.comments_given。"""
    alice = _user("alice"); bob = _user("bob"); carol = _user("carol")
    ev1 = _event(
        file="f-alice", file_type="think", creator="alice",
        comments_in_window=(_comment(author="bob"), _comment(author="carol")),
    )
    ev2 = _event(
        file="f-carol", file_type="think", creator="carol",
        comments_in_window=(_comment(author="bob"),),
    )
    activities, _ = aggregate([ev1, ev2], [], [], [alice, bob, carol], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["bob"].comments_given) == 2
    assert len(by_pinyin["carol"].comments_given) == 1
    assert len(by_pinyin["alice"].comments_given) == 0


def test_mentions_received_counted_for_each_target():
    """两条评论各 @ alice 一次 → alice.mentions_received == 2。"""
    alice = _user("alice"); bob = _user("bob")
    ev = _event(
        file="f1", file_type="think", creator="bob",
        comments_in_window=(
            _comment(author="bob", mentions=("alice",)),
            _comment(author="bob", mentions=("alice", "someone")),
        ),
    )
    activities, _ = aggregate([ev], [], [], [alice, bob], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert by_pinyin["alice"].mentions_received == 2


def test_comment_only_event_does_not_count_as_file_create():
    """File 在窗口外但有窗口内评论 → file_in_window=False。
    评论作者拿到 comment_given,但没人拿到 file_creates。"""
    alice = _user("alice"); bob = _user("bob")
    ev = _event(
        file="f-old", file_type="think", creator="alice",
        file_in_window=False,    # 文件本身在窗口外
        comments_in_window=(_comment(author="bob"),),
    )
    activities, _ = aggregate([ev], [], [], [alice, bob], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["alice"].file_creates) == 0   # 文件不在窗口
    assert len(by_pinyin["bob"].comments_given) == 1   # 评论是窗口内


# --------------------------------------------------------------------------- #
# commits                                                                     #
# --------------------------------------------------------------------------- #


def test_commits_routed_by_matched_pinyin():
    alice = _user("alice"); bob = _user("bob")
    cs = [
        _commit(sha="a1", pinyin="alice", subject="alice 1"),
        _commit(sha="a2", pinyin="alice", subject="alice 2"),
        _commit(sha="b1", pinyin="bob", subject="bob 1"),
    ]
    activities, _ = aggregate([], cs, [], [alice, bob], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["alice"].commits) == 2
    assert len(by_pinyin["bob"].commits) == 1


# --------------------------------------------------------------------------- #
# inactive users                                                              #
# --------------------------------------------------------------------------- #


def test_inactive_users_in_summary():
    """用户存在但 0 活动 → 出现在 summary.inactive_users。"""
    alice = _user("alice", name="Alice")
    bob = _user("bob", name="Bob")
    carol = _user("carol", name="Carol")
    # 只有 alice 有活动
    ev = _event(file="f1", file_type="think", creator="alice")
    _, summary = aggregate([ev], [], [], [alice, bob, carol], _window())
    assert "Bob" in summary.inactive_users
    assert "Carol" in summary.inactive_users
    assert "Alice" not in summary.inactive_users


def test_user_without_pinyin_excluded_from_activities():
    """User.pinyin=None(未完成 setup)不进 activities,也不算 inactive。"""
    alice = _user("alice")
    newbie = _user(None, name="新人")
    activities, summary = aggregate([], [], [], [alice, newbie], _window())
    pinyins = [a.pinyin for a in activities]
    assert "alice" in pinyins
    # 新人 pinyin=None 直接跳过,不在 activities 不在 inactive_users
    assert None not in pinyins
    assert "新人" not in summary.inactive_users


# --------------------------------------------------------------------------- #
# team summary numerics                                                       #
# --------------------------------------------------------------------------- #


def test_team_summary_counts():
    alice = _user("alice"); bob = _user("bob")
    ev1 = _event(file="f1", file_type="think", creator="alice")
    ev2 = _event(
        file="f2", file_type="result", creator="bob",
        status_change={"from": "executing", "to": "finished"},
        comments_in_window=(_comment(author="alice"), _comment(author="bob")),
    )
    ev3 = _event(
        matter_id="other", file="f3", file_type="think", creator="alice",
    )
    cs_matched = [_commit(sha="a", pinyin="alice")]
    cs_unmatched = [_commit(sha="b", pinyin=None)]

    _, summary = aggregate(
        [ev1, ev2, ev3], cs_matched, cs_unmatched,
        [alice, bob], _window(),
    )
    assert summary.total_files == 3              # 3 events all file_in_window
    assert summary.total_commits == 2            # matched + unmatched
    assert summary.total_status_changes == 1
    assert summary.total_comments == 2
    assert summary.matters_touched == 2          # demo + other
    assert len(summary.unattributed_commits) == 1


def test_team_summary_open_id_creator_counts_in_team_but_not_per_user():
    """creator='ou_unregistered' (未注册联系人兜底) → 计入 team total_files,
    但不归到任何 pinyin 个人。"""
    alice = _user("alice")
    ev = _event(file="f1", file_type="think", creator="ou_unregistered_xxxxx")
    activities, summary = aggregate([ev], [], [], [alice], _window())
    by_pinyin = {a.pinyin: a for a in activities}
    assert len(by_pinyin["alice"].file_creates) == 0
    assert summary.total_files == 1


def test_team_summary_fetch_warning_propagates():
    """fetch_warning 直接传到 summary,渲染层用以标'代码仓库未刷新'。"""
    alice = _user("alice")
    _, summary = aggregate(
        [], [], [], [alice], _window(),
        fetch_warning="git fetch 失败:network unreachable",
    )
    assert summary.fetch_warning == "git fetch 失败:network unreachable"
