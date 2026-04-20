from __future__ import annotations

from server.contacts import ContactRepo
from server.mentions import resolve_id, resolve_text


def test_resolve_id_by_open_id(users):
    users.upsert_from_feishu(
        open_id="ou_abc123xxxxxxxxxxxx",
        union_id="on_def456xxxxxxxxxxxx",
        name="邓柯",
        avatar_url="",
    )
    assert resolve_id("ou_abc123xxxxxxxxxxxx", users) == "邓柯"


def test_resolve_id_by_union_id(users):
    users.upsert_from_feishu(
        open_id="ou_abc123xxxxxxxxxxxx",
        union_id="on_def456xxxxxxxxxxxx",
        name="邓柯",
        avatar_url="",
    )
    assert resolve_id("on_def456xxxxxxxxxxxx", users) == "邓柯"


def test_resolve_id_unknown_returns_input(users):
    assert resolve_id("ou_unknown000000000000", users) == "ou_unknown000000000000"


def test_resolve_id_empty(users):
    assert resolve_id("", users) == ""
    assert resolve_id(None, users) is None


def test_resolve_text_replaces_known_and_keeps_unknown(users):
    users.upsert_from_feishu(
        open_id="ou_abc123xxxxxxxxxxxx", union_id=None, name="Ken", avatar_url=""
    )
    body = "hi ou_abc123xxxxxxxxxxxx and ou_missing0000000000000, see you"
    out = resolve_text(body, users)
    assert out == "hi @Ken and ou_missing0000000000000, see you"


def test_resolve_text_handles_union_id_in_body(users):
    users.upsert_from_feishu(
        open_id="ou_a" + "0" * 20, union_id="on_b" + "0" * 20, name="Alice", avatar_url=""
    )
    out = resolve_text("ping on_b00000000000000000000 please", users)
    assert out == "ping @Alice please"


def test_resolve_text_no_match_unchanged(users):
    assert resolve_text("plain text, no mentions", users) == "plain text, no mentions"


def test_resolve_id_falls_back_to_contacts(db, users):
    contacts = ContactRepo(db)
    contacts.upsert_many([
        {"open_id": "ou_contact000000000000", "union_id": "on_contact000000000000", "name": "联系人A"},
    ])
    assert resolve_id("ou_contact000000000000", users, contacts) == "联系人A"
    assert resolve_id("on_contact000000000000", users, contacts) == "联系人A"


def test_resolve_text_falls_back_to_contacts(db, users):
    contacts = ContactRepo(db)
    contacts.upsert_many([
        {"open_id": "ou_contact000000000000", "name": "联系人A"},
    ])
    out = resolve_text("ping ou_contact000000000000 please", users, contacts)
    assert out == "ping @联系人A please"
