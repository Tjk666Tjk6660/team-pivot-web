from __future__ import annotations

import pytest


def test_upsert_inserts_new_user(users):
    u = users.upsert_from_feishu(
        open_id="ou_1", union_id="on_1", name="Ken", avatar_url="http://a/1.png"
    )
    assert u.open_id == "ou_1"
    assert u.name == "Ken"
    assert u.pinyin is None
    assert u.github_username is None
    assert u.needs_setup is True
    assert u.created_at > 0


def test_upsert_updates_name_and_avatar_preserves_profile(users):
    users.upsert_from_feishu(
        open_id="ou_1", union_id="on_1", name="Ken", avatar_url="old.png"
    )
    users.update_profile("ou_1", pinyin="dengke", github_username="ken-d")

    u = users.upsert_from_feishu(
        open_id="ou_1", union_id="on_1", name="Ken Deng", avatar_url="new.png"
    )
    assert u.name == "Ken Deng"
    assert u.avatar_url == "new.png"
    assert u.pinyin == "dengke"
    assert u.github_username == "ken-d"


def test_get_unknown_returns_none(users):
    assert users.get("ou_missing") is None


def test_update_profile_rejects_invalid_pinyin(users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="x", avatar_url="")
    with pytest.raises(ValueError):
        users.update_profile("ou_1", pinyin="Invalid!")
    with pytest.raises(ValueError):
        users.update_profile("ou_1", pinyin="9starts-with-digit")


def test_update_profile_accepts_valid_pinyin(users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="x", avatar_url="")
    u = users.update_profile("ou_1", pinyin="keller.koh")
    assert u is not None and u.pinyin == "keller.koh"
    assert u.needs_setup is False


def test_update_profile_partial_only_sets_given_fields(users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="x", avatar_url="")
    users.update_profile("ou_1", pinyin="dengke", github_username="ken-d")
    u = users.update_profile("ou_1", github_username="new-gh")
    assert u is not None
    assert u.pinyin == "dengke"
    assert u.github_username == "new-gh"


def test_update_profile_empty_github_clears_field(users):
    users.upsert_from_feishu(open_id="ou_1", union_id=None, name="x", avatar_url="")
    users.update_profile("ou_1", github_username="ken-d")
    u = users.update_profile("ou_1", github_username="")
    assert u is not None and u.github_username is None
