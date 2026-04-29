from __future__ import annotations

from server.relevance import (
    REASON_IN_MY_MATTER,
    REASON_OWNER_ASSIGNED,
    REASON_REPLY_TO_MY_FILE,
    REASON_REPLY_TO_MY_OWNED,
    REASON_VERIFY_MY_FILE,
    compute_relevance,
)
from server.users import User


# ---------- helpers ----------


def _user(pinyin: str | None) -> User:
    """Construct a User instance with only `pinyin` filled — the rest is
    irrelevant to compute_relevance."""
    return User(
        open_id=f"ou_{pinyin or 'none'}",
        union_id=None,
        name=pinyin or "Anonymous",
        avatar_url="",
        pinyin=pinyin,
        github_username=None,
        markdown_style=None,
        created_at=0.0,
    )


def _matter(*items: dict) -> dict:
    return {
        "matter": {"id": "m-x", "current_status": "executing"},
        "timeline": list(items),
    }


def _proposal(creator: str, owner: str | None = None, file: str = "01.md") -> dict:
    return {
        "file": file,
        "type": "think",
        "creator": creator,
        "owner": owner or creator,
        "summary": "",
    }


def _act(
    creator: str,
    owner: str | None = None,
    file: str = "02.md",
    quote: str | None = None,
) -> dict:
    return {
        "file": file,
        "type": "act",
        "creator": creator,
        "owner": owner or creator,
        "summary": "",
        "quote": quote,
    }


def _verify(
    creator: str,
    targets: list[str],
    file: str = "03.md",
) -> dict:
    return {
        "file": file,
        "type": "verify",
        "creator": creator,
        "owner": creator,
        "summary": "",
        "verifications": [
            {"target": t, "judgement": "passed", "comment": ""} for t in targets
        ],
    }


# ---------- self-exclusion ----------


def test_self_creator_returns_not_relevant(self_user=None):
    me = _user("alice")
    item = _proposal(creator="alice")
    matter = _matter(item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is False
    assert reason is None


def test_self_creator_owner_returns_not_relevant():
    """即使 owner 也是我,creator 是我就不算相关(自己的事不通知自己)。"""
    me = _user("alice")
    item = _proposal(creator="alice", owner="alice")
    matter = _matter(item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is False


def test_user_without_pinyin_never_relevant():
    """用户没设置 pinyin 时,无法跟任何 item 比对。"""
    me = _user(None)
    item = _proposal(creator="bob", owner="alice")
    matter = _matter(item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is False
    assert reason is None


# ---------- Rule 1: owner_assigned ----------


def test_owner_assigned_when_creator_other_owner_me():
    me = _user("alice")
    item = _act(creator="bob", owner="alice")
    matter = _matter(_proposal("bob"), item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is True
    assert reason == REASON_OWNER_ASSIGNED


def test_owner_assigned_skipped_when_creator_is_me():
    """self-exclusion 优先于 owner 检查。"""
    me = _user("alice")
    item = _act(creator="alice", owner="alice")
    matter = _matter(item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is False


# ---------- Rule 2: reply_to_my_file ----------


def test_reply_to_my_file_when_quote_creator_is_me():
    me = _user("alice")
    my_file = _act(creator="alice", file="02.md")
    new_item = _act(creator="bob", owner="bob", file="03.md", quote="02.md")
    matter = _matter(_proposal("alice"), my_file, new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is True
    assert reason == REASON_REPLY_TO_MY_FILE


def test_reply_to_my_file_skipped_when_quote_unknown():
    """quote 指向不存在的文件 → 不命中。"""
    me = _user("alice")
    new_item = _act(creator="bob", owner="bob", file="03.md", quote="ghost.md")
    matter = _matter(_proposal("bob"), new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is False


# ---------- Rule 3: reply_to_my_owned ----------


def test_reply_to_my_owned_when_quote_owner_is_me_and_creator_is_other():
    me = _user("alice")
    # 02.md: bob 创建,alice 负责
    quoted = _act(creator="bob", owner="alice", file="02.md")
    new_item = _act(creator="charlie", owner="charlie", file="03.md", quote="02.md")
    matter = _matter(_proposal("bob"), quoted, new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is True
    assert reason == REASON_REPLY_TO_MY_OWNED


def test_reply_to_my_file_takes_priority_over_my_owned():
    """同一被引用文件如果 creator=alice & owner=alice,reply_to_my_file 先命中。"""
    me = _user("alice")
    quoted = _act(creator="alice", owner="alice", file="02.md")
    new_item = _act(creator="charlie", owner="charlie", file="03.md", quote="02.md")
    matter = _matter(_proposal("alice"), quoted, new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is True
    assert reason == REASON_REPLY_TO_MY_FILE  # 不是 reply_to_my_owned


# ---------- Rule 4: verify_my_file ----------


def test_verify_my_file_when_target_creator_is_me():
    me = _user("alice")
    my_act = _act(creator="alice", file="02.md")
    verify = _verify(creator="bob", targets=["02.md"], file="03.md")
    matter = _matter(_proposal("alice"), my_act, verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is True
    assert reason == REASON_VERIFY_MY_FILE


def test_verify_my_file_when_target_owner_is_me():
    me = _user("alice")
    my_act = _act(creator="bob", owner="alice", file="02.md")
    verify = _verify(creator="charlie", targets=["02.md"], file="03.md")
    matter = _matter(_proposal("bob"), my_act, verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is True
    assert reason == REASON_VERIFY_MY_FILE


def test_verify_with_unknown_target_does_not_fire():
    me = _user("alice")
    verify = _verify(creator="bob", targets=["ghost.md"], file="03.md")
    matter = _matter(_proposal("bob"), verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is False


def test_verify_with_multiple_targets_one_matching_fires():
    me = _user("alice")
    other_act = _act(creator="charlie", file="01.md")
    my_act = _act(creator="alice", file="02.md")
    verify = _verify(creator="bob", targets=["01.md", "02.md"], file="03.md")
    matter = _matter(_proposal("charlie"), other_act, my_act, verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is True
    assert reason == REASON_VERIFY_MY_FILE


def test_verify_self_authored_excluded():
    """alice 自己写 verify,即使 target 是 alice 自己的 act 也不算相关。"""
    me = _user("alice")
    my_act = _act(creator="alice", file="02.md")
    verify = _verify(creator="alice", targets=["02.md"], file="03.md")
    matter = _matter(_proposal("alice"), my_act, verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is False


# ---------- Rule 5: in_my_matter ----------


def test_in_my_matter_when_first_proposal_creator_is_me():
    me = _user("alice")
    other_item = _act(creator="bob", owner="bob", file="02.md")
    matter = _matter(_proposal("alice", file="01.md"), other_item)
    ok, reason = compute_relevance(other_item, matter, me)
    assert ok is True
    assert reason == REASON_IN_MY_MATTER


def test_in_my_matter_does_not_fire_when_first_creator_is_other():
    me = _user("alice")
    item = _act(creator="bob", owner="bob", file="02.md")
    matter = _matter(_proposal("charlie", file="01.md"), item)
    ok, reason = compute_relevance(item, matter, me)
    assert ok is False


def test_in_my_matter_skipped_when_creator_is_me():
    """self-exclusion 优先 — 即使是我创建的 matter,自己写的 item 不算相关。"""
    me = _user("alice")
    own_item = _act(creator="alice", owner="alice", file="02.md")
    matter = _matter(_proposal("alice", file="01.md"), own_item)
    ok, reason = compute_relevance(own_item, matter, me)
    assert ok is False


def test_empty_timeline_no_in_my_matter():
    me = _user("alice")
    isolated_item = _act(creator="bob", owner="bob", file="02.md")
    matter = {"matter": {"id": "m-x"}, "timeline": []}
    ok, reason = compute_relevance(isolated_item, matter, me)
    assert ok is False


# ---------- 优先级冲突 ----------


def test_owner_assigned_beats_reply_to_my_file():
    """同时命中 owner_assigned 和 reply_to_my_file → owner_assigned(优先级 1)赢。"""
    me = _user("alice")
    my_old_file = _act(creator="alice", file="02.md")  # I created old file
    new_item = _act(
        creator="bob", owner="alice",  # bob 创建,owner=alice → owner_assigned
        file="03.md", quote="02.md",   # 同时 quote 到 alice 创建的文件
    )
    matter = _matter(_proposal("bob"), my_old_file, new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is True
    assert reason == REASON_OWNER_ASSIGNED  # 不是 reply_to_my_file


def test_reply_to_my_file_beats_in_my_matter():
    """quote 命中我的文件 → reply_to_my_file 赢,不会回退到 in_my_matter。"""
    me = _user("alice")
    proposal = _proposal("alice", file="01.md")  # 我创建 matter
    my_act = _act(creator="alice", file="02.md")  # 我创建 act
    new_item = _act(
        creator="bob", owner="bob",
        file="03.md", quote="02.md",
    )
    matter = _matter(proposal, my_act, new_item)
    ok, reason = compute_relevance(new_item, matter, me)
    assert ok is True
    assert reason == REASON_REPLY_TO_MY_FILE


def test_verify_my_file_beats_in_my_matter():
    me = _user("alice")
    proposal = _proposal("alice", file="01.md")
    my_act = _act(creator="alice", file="02.md")
    verify = _verify(creator="bob", targets=["02.md"], file="03.md")
    matter = _matter(proposal, my_act, verify)
    ok, reason = compute_relevance(verify, matter, me)
    assert ok is True
    assert reason == REASON_VERIFY_MY_FILE


# ---------- 不相关边界 ----------


def test_unrelated_item_returns_not_relevant():
    me = _user("alice")
    proposal = _proposal("bob", file="01.md")  # 别人的 matter
    other_act = _act(creator="charlie", owner="charlie", file="02.md")  # 别人的 act
    matter = _matter(proposal, other_act)
    ok, reason = compute_relevance(other_act, matter, me)
    assert ok is False
    assert reason is None
