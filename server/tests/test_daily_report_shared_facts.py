"""Tests for `server.daily_report.shared_facts`.

Covers:
- `category_of()` 解析 file path
- `build_shared_facts()` 派生 status_breakdown / file_type_breakdown /
  verify_judgements / top_active_matters
- 同 matter 多 event 不重复计数(status_breakdown 仅统计 matter 数)
- top_active_matters activity_score 排序
- `active_users` / `n_active` 属性
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from server.daily_report.shared_facts import (
    SharedFacts,
    build_shared_facts,
    category_of,
)
from server.daily_report.types import (
    MatterEvent,
    MatterEventComment,
    TeamSummary,
    TimeWindow,
    UserActivity,
)
from server.daily_report.window import CHINA_TZ


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _w() -> TimeWindow:
    return TimeWindow(
        since=datetime(2026, 4, 28, 9, 0, tzinfo=CHINA_TZ),
        until=datetime(2026, 4, 29, 9, 0, tzinfo=CHINA_TZ),
    )


def _ev(
    *,
    matter_id: str,
    matter_status: str = "executing",
    file: str,
    creator: str = "alice",
    owner: str | None = None,
    file_type: str = "act",
    has_status_change: bool = False,
    comments: tuple[MatterEventComment, ...] = (),
    verifications: tuple[dict, ...] = (),
    file_in_window: bool = True,
) -> MatterEvent:
    return MatterEvent(
        matter_id=matter_id,
        matter_title=matter_id,
        matter_current_status=matter_status,
        file=file,
        file_type=file_type,
        created_at=_w().since + timedelta(hours=2),
        file_in_window=file_in_window,
        creator=creator,
        owner=owner or creator,
        summary=f"{matter_id} {file_type}",
        status_change=({"from": "planning", "to": "executing"}
                       if has_status_change else None),
        verifications=verifications,
        comments_in_window=comments,
    )


def _activity(pinyin: str, *, active: bool = True) -> UserActivity:
    if active:
        ev = _ev(
            matter_id="m-x",
            file=f"discussions/Pivot/m-x/{pinyin}_think.md",
            creator=pinyin,
        )
        creates = (ev,)
    else:
        creates = ()
    return UserActivity(
        pinyin=pinyin,
        display_name=pinyin,
        file_creates=creates,
        file_owns=(),
        verifications_given=(),
        status_changes_triggered=(),
        comments_given=(),
        mentions_received=0,
    )


def _summary(**overrides) -> TeamSummary:
    base = dict(
        window=_w(),
        total_files=0,
        total_status_changes=0,
        total_comments=0,
        matters_touched=0,
        inactive_users=(),
    )
    base.update(overrides)
    return TeamSummary(**base)


# --------------------------------------------------------------------------- #
# category_of                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path,expected", [
    ("discussions/Pivot/abc-matter/001_alice_think_xxx.md", "Pivot"),
    ("discussions/enclaws/foo/002_bob_act_yyy.md", "enclaws"),
    ("discussions/外部客户实施/碧桂园项目/003_x_y.md", "外部客户实施"),
    # 缺路径 → 未分类
    ("", "未分类"),
    # 不以 discussions 开头 → 未分类(防御性)
    ("other/Pivot/abc/file.md", "未分类"),
    # 只有 discussions/ 没 category → 未分类
    ("discussions/", "未分类"),
])
def test_category_of(path, expected):
    assert category_of(path) == expected


# --------------------------------------------------------------------------- #
# build_shared_facts                                                          #
# --------------------------------------------------------------------------- #


def test_file_type_breakdown_counts_in_window_only():
    """只统计 file_in_window 的文件,按 type 分桶。"""
    events = [
        _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think"),
        _ev(matter_id="m2", file="discussions/Pivot/m2/001.md", file_type="act"),
        _ev(matter_id="m3", file="discussions/Pivot/m3/001.md", file_type="verify"),
        _ev(matter_id="m4", file="discussions/Pivot/m4/001.md", file_type="verify"),
        _ev(matter_id="m5", file="discussions/Pivot/m5/001.md",
            file_type="think", file_in_window=False),  # 不该被统计
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    assert sf.file_type_breakdown == {"think": 1, "act": 1, "verify": 2}


def test_verify_judgements_aggregated():
    """verify 文件的 judgements 全局聚合。"""
    events = [
        _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="verify",
            verifications=({"judgement": "passed"},)),
        _ev(matter_id="m2", file="discussions/Pivot/m2/001.md", file_type="verify",
            verifications=({"judgement": "passed"}, {"judgement": "failed"})),
        _ev(matter_id="m3", file="discussions/Pivot/m3/001.md", file_type="act"),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    assert sf.verify_judgements == {"passed": 2, "failed": 1}


def test_status_breakdown_counts_distinct_matters():
    events = [
        _ev(matter_id="m1", matter_status="executing",
            file="discussions/Pivot/m1/001.md"),
        _ev(matter_id="m1", matter_status="executing",
            file="discussions/Pivot/m1/002.md"),
        _ev(matter_id="m2", matter_status="planning",
            file="discussions/Pivot/m2/001.md"),
        _ev(matter_id="m3", matter_status="executing",
            file="discussions/Pivot/m3/001.md"),
        _ev(matter_id="m4", matter_status="paused",
            file="discussions/Pivot/m4/001.md"),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    # m1 出现两次,但只算 1 个 executing matter
    assert sf.matter_status_breakdown == {
        "executing": 2,    # m1 + m3
        "planning": 1,     # m2
        "paused": 1,       # m4
    }


def test_status_breakdown_skips_empty_status():
    """matter_current_status 为空字符串时不计入 breakdown。"""
    events = [
        _ev(matter_id="m1", matter_status="", file="discussions/Pivot/m1/001.md"),
        _ev(matter_id="m2", matter_status="executing",
            file="discussions/Pivot/m2/001.md"),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    assert sf.matter_status_breakdown == {"executing": 1}


def test_active_users_property():
    activities = [
        _activity("alice", active=True),
        _activity("bob", active=False),
        _activity("carol", active=True),
    ]
    sf = build_shared_facts([], activities, _summary(), _w())
    active_pinyins = {ua.pinyin for ua in sf.active_users}
    assert active_pinyins == {"alice", "carol"}
    assert sf.n_active == 2


def test_empty_inputs_yield_empty_facts():
    sf = build_shared_facts([], [], _summary(), _w())
    assert sf.matter_events == ()
    assert sf.user_activities == ()
    assert sf.matter_status_breakdown == {}
    assert sf.file_type_breakdown == {}
    assert sf.verify_judgements == {}
    assert sf.top_active_matters == ()
    assert sf.n_active == 0


def test_shared_facts_is_immutable():
    """SharedFacts 是 frozen dataclass,字段不应可写。"""
    sf = build_shared_facts([], [], _summary(), _w())
    with pytest.raises(Exception):  # FrozenInstanceError
        sf.matter_events = ()


# --------------------------------------------------------------------------- #
# top_active_matters                                                          #
# --------------------------------------------------------------------------- #


def test_top_active_matters_path_format_is_category_slash_slug():
    """path 必须形如 'Pivot/matter-slug',不是只 matter_id 也不是只 title。"""
    events = [
        _ev(matter_id="数据迁移方案", file="discussions/Pivot/数据迁移方案/001.md"),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    assert len(sf.top_active_matters) == 1
    assert sf.top_active_matters[0].path == "Pivot/数据迁移方案"


def test_top_active_matters_aggregates_per_matter():
    """同 matter 多文件聚合到一条;file_count / file_types 累加。"""
    events = [
        _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think"),
        _ev(matter_id="m1", file="discussions/Pivot/m1/002.md", file_type="act"),
        _ev(matter_id="m1", file="discussions/Pivot/m1/003.md", file_type="verify",
            verifications=({"judgement": "passed"},)),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    assert len(sf.top_active_matters) == 1
    m = sf.top_active_matters[0]
    assert m.path == "Pivot/m1"
    assert m.file_count == 3
    assert m.file_types == {"think": 1, "act": 1, "verify": 1}
    assert m.verify_judgements == {"passed": 1}


def test_top_active_matters_sorted_by_activity_score_descending():
    """活跃分高的排前。状态迁移和 verify passed 都加分。"""
    events = [
        # m1: 1 个 think,无迁移,无 verify → score 低
        _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think"),
        # m2: 1 个 verify passed + 1 个 result → score 高
        _ev(matter_id="m2", file="discussions/Pivot/m2/001.md", file_type="verify",
            verifications=({"judgement": "passed"},)),
        _ev(matter_id="m2", file="discussions/Pivot/m2/002.md", file_type="result",
            has_status_change=True),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    # m2 应该排第一
    assert sf.top_active_matters[0].path == "Pivot/m2"
    assert sf.top_active_matters[1].path == "Pivot/m1"
    assert sf.top_active_matters[0].activity_score > sf.top_active_matters[1].activity_score


def test_top_active_matters_caps_at_top_n():
    """top_n_matters 控制返回上限。"""
    events = [
        _ev(matter_id=f"m{i}", file=f"discussions/Pivot/m{i}/001.md", file_type="think")
        for i in range(10)
    ]
    sf = build_shared_facts(events, [], _summary(), _w(), top_n_matters=3)
    assert len(sf.top_active_matters) == 3


def test_top_active_matters_records_status_change():
    events = [
        _ev(matter_id="m1", file="discussions/Pivot/m1/001.md",
            file_type="result", has_status_change=True),
    ]
    sf = build_shared_facts(events, [], _summary(), _w())
    m = sf.top_active_matters[0]
    assert m.status_change == {"from": "planning", "to": "executing"}


def test_top_active_matters_carries_title_and_today_summaries():
    """company narrate 用 title + today_summaries 写"昨天干了什么业务"。"""
    e1 = _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think")
    e2 = _ev(matter_id="m1", file="discussions/Pivot/m1/002.md", file_type="act")
    sf = build_shared_facts([e1, e2], [], _summary(), _w())
    m = sf.top_active_matters[0]
    # _ev 给的 matter_title=matter_id;summary=f"{matter_id} {file_type}"
    assert m.title == "m1"
    assert m.today_summaries == ("m1 think", "m1 act")


def test_top_active_matters_dedups_summaries():
    """同 matter 多个 file 共享同一个 summary 字符串时只保留一份。"""
    e1 = _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think")
    e2 = _ev(matter_id="m1", file="discussions/Pivot/m1/002.md", file_type="think")
    sf = build_shared_facts([e1, e2], [], _summary(), _w())
    m = sf.top_active_matters[0]
    # 两个 think 的 summary 都是 "m1 think",去重后只剩一条
    assert m.today_summaries == ("m1 think",)


def test_top_active_matters_skips_empty_summaries():
    """空 summary 不进 today_summaries(避免污染 LLM 输入)。"""
    e = _ev(matter_id="m1", file="discussions/Pivot/m1/001.md", file_type="think")
    e_empty = MatterEvent(
        matter_id="m1", matter_title="m1", matter_current_status="executing",
        file="discussions/Pivot/m1/002.md", file_type="act",
        created_at=_w().since + timedelta(hours=3),
        file_in_window=True, creator="alice", owner="alice",
        summary="",
        status_change=None, verifications=(), comments_in_window=(),
    )
    sf = build_shared_facts([e, e_empty], [], _summary(), _w())
    m = sf.top_active_matters[0]
    assert m.today_summaries == ("m1 think",)


def test_top_active_matters_title_falls_back_to_matter_id_when_missing():
    """matter_title 为空时,标题回落到 matter_id。"""
    e = MatterEvent(
        matter_id="m1", matter_title="", matter_current_status="executing",
        file="discussions/Pivot/m1/001.md", file_type="think",
        created_at=_w().since + timedelta(hours=2),
        file_in_window=True, creator="alice", owner="alice",
        summary="some business note",
        status_change=None, verifications=(), comments_in_window=(),
    )
    sf = build_shared_facts([e], [], _summary(), _w())
    m = sf.top_active_matters[0]
    assert m.title == "m1"
