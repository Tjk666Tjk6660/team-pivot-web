"""Tests for `server.daily_report.attribution.attribute_commits` —
8-tier commit-author → pinyin matching."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from server.daily_report.attribution import attribute_commits
from server.daily_report.types import CommitRecord
from server.users import User


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _user(
    *, open_id: str, name: str, pinyin: str | None, github_username: str | None = None,
) -> User:
    return User(
        open_id=open_id, union_id=None, name=name, avatar_url="",
        pinyin=pinyin, github_username=github_username,
        markdown_style=None, created_at=0.0,
    )


def _commit(
    *, sha: str = "abc1234", author_name: str = "", author_email: str = "",
    subject: str = "test",
) -> CommitRecord:
    return CommitRecord(
        sha=sha, author_name=author_name, author_email=author_email,
        committed_at=datetime(2026, 4, 26, 15, 0, tzinfo=timezone.utc),
        subject=subject, files_changed=1, insertions=1, deletions=0,
    )


_DENGKE = _user(
    open_id="ou_d", name="邓柯", pinyin="dengke", github_username="dengke-d",
)
_LIUYU = _user(
    open_id="ou_l", name="刘昱", pinyin="liuyu", github_username="liu-yu",
)
_NEWBIE = _user(
    open_id="ou_n", name="新人", pinyin=None, github_username=None,
)


# --------------------------------------------------------------------------- #
# tier 1: manual override                                                     #
# --------------------------------------------------------------------------- #


def test_tier1_manual_override_wins(caplog):
    """Override is highest priority — even if another tier would match,
    the override mapping is used."""
    c = _commit(author_name="邓柯", author_email="anywhere@example.com")
    overrides = {"liuyu": ["anywhere@example.com"]}
    matched, unmatched = attribute_commits([c], [_DENGKE, _LIUYU], overrides)
    assert len(matched) == 1
    assert matched[0].matched_pinyin == "liuyu"
    assert unmatched == []


def test_tier1_override_case_insensitive_email():
    """Override email match is case-insensitive."""
    c = _commit(author_email="DengKe@PiVoT.LoCaL")
    matched, _ = attribute_commits(
        [c], [_DENGKE], {"dengke": ["dengke@pivot.local"]},
    )
    assert matched[0].matched_pinyin == "dengke"


# --------------------------------------------------------------------------- #
# tier 2: GitHub noreply                                                      #
# --------------------------------------------------------------------------- #


def test_tier2_github_noreply_privacy_form():
    """`12345+username@users.noreply.github.com` → match users.github_username."""
    c = _commit(author_email="98765+dengke-d@users.noreply.github.com")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier2_github_noreply_legacy_form():
    """`username@users.noreply.github.com` (no numeric prefix) also works."""
    c = _commit(author_email="liu-yu@users.noreply.github.com")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "liuyu"


def test_tier2_github_noreply_case_insensitive():
    c = _commit(author_email="123+DengKe-D@users.noreply.github.com")
    matched, _ = attribute_commits([c], [_DENGKE], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier2_github_noreply_no_match():
    """noreply email but github_username doesn't match anyone → fall through."""
    c = _commit(author_email="123+stranger@users.noreply.github.com")
    _, unmatched = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert len(unmatched) == 1


# --------------------------------------------------------------------------- #
# tier 3: author_name == pinyin                                               #
# --------------------------------------------------------------------------- #


def test_tier3_author_name_exact_pinyin():
    """git config user.name = "dengke" (some people set it to pinyin)."""
    c = _commit(author_name="dengke", author_email="dengke@stacs.cn")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier3_pinyin_match_is_case_sensitive():
    """pinyin match is exact (lowercase). 'DengKe' shouldn't match pinyin 'dengke'.
    But it might match github_username at tier 4 if set."""
    c = _commit(author_name="DengKe", author_email="x@y.z")
    # _DENGKE has github_username='dengke-d' — case-insensitive at tier 4 won't match either.
    # And users.name is 中文,doesn't match 'DengKe'. So → unmatched.
    _, unmatched = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert len(unmatched) == 1


# --------------------------------------------------------------------------- #
# tier 4: author_name == github_username (case-insensitive)                   #
# --------------------------------------------------------------------------- #


def test_tier4_author_name_github_username():
    """git config user.name = 'dengke-d' (GitHub handle)."""
    c = _commit(author_name="dengke-d", author_email="x@y.z")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier4_case_insensitive():
    c = _commit(author_name="DENGKE-D", author_email="x@y.z")
    matched, _ = attribute_commits([c], [_DENGKE], {})
    assert matched[0].matched_pinyin == "dengke"


# --------------------------------------------------------------------------- #
# tier 5: author_name == users.name (Chinese / arbitrary)                     #
# --------------------------------------------------------------------------- #


def test_tier5_chinese_name():
    c = _commit(author_name="邓柯", author_email="x@y.z")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier5_homonym_takes_first_with_warning(caplog):
    """两人同中文名 — 取第一个,log warning。"""
    twin_a = _user(open_id="ou_a", name="王伟", pinyin="wangwei_a")
    twin_b = _user(open_id="ou_b", name="王伟", pinyin="wangwei_b")
    c = _commit(author_name="王伟", author_email="x@y.z")
    with caplog.at_level(logging.WARNING):
        matched, _ = attribute_commits([c], [twin_a, twin_b], {})
    assert matched[0].matched_pinyin == "wangwei_a"
    assert any("matched 2 users by name" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- #
# tier 6 + 7: email local-part                                                #
# --------------------------------------------------------------------------- #


def test_tier6_email_local_part_pinyin():
    """`dengke@stacs.cn` 邮箱前缀正好是 pinyin。"""
    c = _commit(author_name="random whatever", author_email="dengke@stacs.cn")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


def test_tier7_email_local_part_github_username():
    """没人用 pinyin 做 local part,但有人 github_username 做 local part。"""
    c = _commit(author_name="random", author_email="dengke-d@gmail.com")
    matched, _ = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched[0].matched_pinyin == "dengke"


# --------------------------------------------------------------------------- #
# tier 8: miss                                                                #
# --------------------------------------------------------------------------- #


def test_unmatched_when_nothing_matches():
    c = _commit(
        author_name="External Contributor",
        author_email="random@externaldomain.com",
    )
    matched, unmatched = attribute_commits([c], [_DENGKE, _LIUYU], {})
    assert matched == []
    assert len(unmatched) == 1
    assert unmatched[0].matched_pinyin is None


def test_user_without_pinyin_is_not_eligible_target():
    """A user with `pinyin=None` (未完成 setup) cannot be a match target,
    even if name/github match. Daily report only routes to known pinyin."""
    c = _commit(author_name="新人", author_email="newbie@stacs.cn")
    _, unmatched = attribute_commits([c], [_NEWBIE], {})
    assert len(unmatched) == 1


# --------------------------------------------------------------------------- #
# overrides robustness                                                        #
# --------------------------------------------------------------------------- #


def test_overrides_malformed_silently_ignored():
    """junk overrides shouldn't crash; just behave as no override."""
    junk = {"": ["x@y.z"], "valid": "not-a-list", 123: ["q@r.s"]}
    c = _commit(author_name="dengke", author_email="x@y.z")
    matched, _ = attribute_commits([c], [_DENGKE], junk)   # type: ignore[arg-type]
    # Falls through to tier 3 (author_name == pinyin)
    assert matched[0].matched_pinyin == "dengke"


def test_empty_inputs():
    """No commits → empty result tuple, no exception."""
    matched, unmatched = attribute_commits([], [_DENGKE], {})
    assert matched == []
    assert unmatched == []


def test_no_users():
    """No users at all → everything is unmatched."""
    c = _commit(author_name="anyone", author_email="x@y.z")
    matched, unmatched = attribute_commits([c], [], {})
    assert matched == []
    assert len(unmatched) == 1
