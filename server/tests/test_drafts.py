from __future__ import annotations

import pytest

from server.drafts import DraftRepo


@pytest.fixture
def drafts(db):
    return DraftRepo(db)


def test_create_proposal_draft(drafts):
    d = drafts.create(
        user_open_id="ou_1",
        type_="proposal",
        title="Foo",
        category="general",
        body_md="hello",
    )
    assert d.id
    assert d.type == "proposal"
    assert d.title == "Foo"
    assert d.thread_key is None
    assert d.created_at == d.updated_at


def test_create_reply_draft(drafts):
    d = drafts.create(
        user_open_id="ou_1",
        type_="reply",
        thread_key="general/hello",
        body_md="+1",
    )
    assert d.type == "reply"
    assert d.thread_key == "general/hello"


def test_rejects_invalid_type(drafts):
    with pytest.raises(ValueError):
        drafts.create(user_open_id="ou_1", type_="unknown", body_md="x")


def test_list_for_user_returns_only_owned(drafts):
    a = drafts.create(user_open_id="ou_a", type_="proposal", body_md="a")
    drafts.create(user_open_id="ou_b", type_="proposal", body_md="b")
    items = drafts.list_for_user("ou_a")
    assert [d.id for d in items] == [a.id]


def test_list_sorted_by_updated_desc(drafts):
    import time as _t
    a = drafts.create(user_open_id="ou_a", type_="proposal", body_md="first")
    _t.sleep(0.01)
    b = drafts.create(user_open_id="ou_a", type_="proposal", body_md="second")
    items = drafts.list_for_user("ou_a")
    assert [d.id for d in items] == [b.id, a.id]


def test_update_patches_only_given_fields(drafts):
    d = drafts.create(
        user_open_id="ou_1", type_="proposal",
        title="T", category="c", body_md="orig",
    )
    updated = drafts.update(d.id, body_md="new body")
    assert updated is not None
    assert updated.body_md == "new body"
    assert updated.title == "T"
    assert updated.updated_at > d.updated_at


def test_update_empty_returns_current(drafts):
    d = drafts.create(user_open_id="ou_1", type_="proposal", body_md="x")
    same = drafts.update(d.id)
    assert same is not None and same.body_md == "x"


def test_delete_removes(drafts):
    d = drafts.create(user_open_id="ou_1", type_="proposal", body_md="x")
    assert drafts.delete(d.id) is True
    assert drafts.get(d.id) is None
    assert drafts.delete(d.id) is False


def test_get_unknown(drafts):
    assert drafts.get("nope") is None
