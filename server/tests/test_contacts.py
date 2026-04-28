from __future__ import annotations

import pytest

from server.contacts import ContactRepo


@pytest.fixture
def contacts(db):
    return ContactRepo(db)


def test_get_unknown(contacts):
    assert contacts.get("ou_nope") is None


def test_upsert_many_inserts_and_updates(contacts):
    n = contacts.upsert_many([
        {"open_id": "ou_1", "name": "张三", "avatar_url": "a.png"},
        {"open_id": "ou_2", "name": "Li Si", "en_name": "Li Si", "avatar_url": ""},
    ])
    assert n == 2
    assert contacts.count() == 2
    c = contacts.get("ou_1")
    assert c is not None and c.name == "张三"

    contacts.upsert_many([{"open_id": "ou_1", "name": "张三丰"}])
    c2 = contacts.get("ou_1")
    assert c2 is not None and c2.name == "张三丰"
    assert contacts.count() == 2


def test_search_empty_returns_all(contacts):
    contacts.upsert_many([
        {"open_id": f"ou_{i}", "name": f"N{i}"} for i in range(5)
    ])
    assert len(contacts.search("")) == 5


def test_search_by_name(contacts):
    contacts.upsert_many([
        {"open_id": "ou_1", "name": "张三"},
        {"open_id": "ou_2", "name": "李四"},
        {"open_id": "ou_3", "name": "张五"},
    ])
    r = contacts.search("张")
    names = sorted(c.name for c in r)
    assert names == ["张三", "张五"]


def test_search_limit(contacts):
    contacts.upsert_many([
        {"open_id": f"ou_{i}", "name": f"张{i}"} for i in range(30)
    ])
    assert len(contacts.search("张", limit=5)) == 5


def test_get_many(contacts):
    contacts.upsert_many([
        {"open_id": "ou_1", "name": "a"}, {"open_id": "ou_2", "name": "b"},
    ])
    got = contacts.get_many(["ou_1", "ou_2", "ou_3"])
    assert set(got.keys()) == {"ou_1", "ou_2"}


def test_get_by_any_id(contacts):
    contacts.upsert_many([
        {"open_id": "ou_1", "union_id": "on_1", "name": "Alice"},
    ])
    assert contacts.get_by_any_id("ou_1") is not None
    assert contacts.get_by_any_id("on_1") is not None
    assert contacts.get_by_any_id("missing") is None


def test_upsert_from_login_preserves_en_name(contacts):
    contacts.upsert_many([
        {
            "open_id": "ou_1",
            "union_id": "on_1",
            "name": "张三",
            "en_name": "Zhang San",
            "avatar_url": "old.png",
        }
    ])
    c = contacts.upsert_from_login(
        open_id="ou_1",
        union_id="on_1",
        name="张三（已激活）",
        avatar_url="new.png",
    )
    assert c.name == "张三（已激活）"
    assert c.en_name == "Zhang San"
    assert c.avatar_url == "new.png"


# ---------- lookup_for_mention ----------

def test_lookup_for_mention_by_open_id(contacts):
    contacts.upsert_many([{"open_id": "ou_1", "name": "邓柯", "en_name": "Tank"}])
    c = contacts.lookup_for_mention("ou_1")
    assert c is not None and c.open_id == "ou_1"


def test_lookup_for_mention_by_union_id(contacts):
    contacts.upsert_many([
        {"open_id": "ou_1", "union_id": "on_1", "name": "邓柯"},
    ])
    c = contacts.lookup_for_mention("on_1")
    assert c is not None and c.open_id == "ou_1"


def test_lookup_for_mention_by_unique_name(contacts):
    """User says '邓柯' in chat — backend resolves to ou_1 even though
    Web's MentionField would have sent the open_id directly."""
    contacts.upsert_many([
        {"open_id": "ou_1", "name": "邓柯"},
        {"open_id": "ou_2", "name": "李四"},
    ])
    c = contacts.lookup_for_mention("邓柯")
    assert c is not None and c.open_id == "ou_1"


def test_lookup_for_mention_by_unique_en_name(contacts):
    contacts.upsert_many([
        {"open_id": "ou_1", "name": "邓柯", "en_name": "Tank"},
        {"open_id": "ou_2", "name": "李四", "en_name": "Li Si"},
    ])
    c = contacts.lookup_for_mention("Tank")
    assert c is not None and c.open_id == "ou_1"


def test_lookup_for_mention_ambiguous_name_returns_none(contacts):
    """Two contacts share '张三' — return None so the caller can ask the user
    to disambiguate (rather than randomly picking one)."""
    contacts.upsert_many([
        {"open_id": "ou_a", "name": "张三"},
        {"open_id": "ou_b", "name": "张三"},
    ])
    assert contacts.lookup_for_mention("张三") is None


def test_lookup_for_mention_unknown_returns_none(contacts):
    contacts.upsert_many([{"open_id": "ou_1", "name": "邓柯"}])
    assert contacts.lookup_for_mention("不在通讯录里的人") is None


def test_lookup_for_mention_empty_returns_none(contacts):
    assert contacts.lookup_for_mention("") is None


def test_lookup_for_mention_id_match_wins_over_homonym_name(contacts):
    """If a value happens to be both a valid open_id AND someone's name,
    the open_id match takes precedence (it's the unambiguous form)."""
    contacts.upsert_many([
        {"open_id": "alice", "name": "Different Person"},
        {"open_id": "ou_2", "name": "alice"},
    ])
    c = contacts.lookup_for_mention("alice")
    assert c is not None and c.open_id == "alice"
