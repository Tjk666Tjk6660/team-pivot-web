"""Tests for the ULID-aware mention helpers added in Task 19.5."""
from __future__ import annotations

import pytest

from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUserRepo
from server.publish import (
    _normalize_mentions_to_pivot_user_ids,
    _ulids_to_feishu_open_ids,
)


@pytest.fixture
def repos(db):
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    contacts = ContactRepo(db)
    return pivot_users, bindings, contacts


def test_normalize_passes_ulids_through(repos):
    pivot_users, bindings, contacts = repos
    u = pivot_users.create(
        display_name="Alice", pinyin="alice", email=None, avatar_url="",
        role="member",
    )
    out = _normalize_mentions_to_pivot_user_ids([u.id], pivot_users, bindings)
    assert out == [u.id]


def test_normalize_resolves_open_id_via_binding(repos):
    pivot_users, bindings, contacts = repos
    u = pivot_users.create(
        display_name="Bob", pinyin="bob", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_bob000000000000",
        external_union_id=None, raw_profile_json=None,
    )
    out = _normalize_mentions_to_pivot_user_ids(
        ["ou_bob000000000000"], pivot_users, bindings,
    )
    assert out == [u.id]


def test_normalize_preserves_unbound_open_id(repos):
    """External feishu user with no pivot_user binding yet — preserve
    open_id so the read-side resolver can still render via contacts."""
    pivot_users, bindings, _ = repos
    out = _normalize_mentions_to_pivot_user_ids(
        ["ou_external00000000000"], pivot_users, bindings,
    )
    assert out == ["ou_external00000000000"]


def test_normalize_returns_none_for_empty(repos):
    pivot_users, bindings, _ = repos
    assert _normalize_mentions_to_pivot_user_ids(None, pivot_users, bindings) is None
    assert _normalize_mentions_to_pivot_user_ids([], pivot_users, bindings) is None


def test_normalize_drops_blank_strings(repos):
    pivot_users, bindings, _ = repos
    out = _normalize_mentions_to_pivot_user_ids(
        ["", None], pivot_users, bindings,  # type: ignore[list-item]
    )
    assert out == []


def test_normalize_resolves_contact_name(repos):
    pivot_users, bindings, contacts = repos
    u = pivot_users.create(
        display_name="Carol", pinyin="carol", email=None, avatar_url="",
        role="member",
    )
    contacts.upsert_many([
        {"open_id": "ou_carol00000000000_", "name": "Carol", "union_id": None},
    ])
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_carol00000000000_",
        external_union_id=None, raw_profile_json=None,
    )
    out = _normalize_mentions_to_pivot_user_ids(
        ["Carol"], pivot_users, bindings, contacts,
    )
    assert out == [u.id]


def test_ulids_to_feishu_open_ids_passes_through_open_ids(repos):
    pivot_users, bindings, _ = repos
    out = _ulids_to_feishu_open_ids(
        ["ou_x" + "0" * 16, "on_y" + "0" * 16], pivot_users, bindings,
    )
    assert out == ["ou_x" + "0" * 16, "on_y" + "0" * 16]


def test_ulids_to_feishu_open_ids_resolves_via_binding(repos):
    pivot_users, bindings, _ = repos
    u = pivot_users.create(
        display_name="Dave", pinyin="dave", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_dave000000000000",
        external_union_id=None, raw_profile_json=None,
    )
    out = _ulids_to_feishu_open_ids([u.id], pivot_users, bindings)
    assert out == ["ou_dave000000000000"]


def test_ulids_to_feishu_open_ids_drops_user_without_feishu_binding(repos):
    """Invite-only user with no feishu binding — drop from DM target list."""
    pivot_users, bindings, _ = repos
    u = pivot_users.create(
        display_name="Eve", pinyin="eve", email="eve@x.com", avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="invite",
        external_id="eve@x.com",
        external_union_id=None, raw_profile_json=None,
        password_hash="x",
    )
    out = _ulids_to_feishu_open_ids([u.id], pivot_users, bindings)
    assert out == []


def test_ulids_to_feishu_open_ids_drops_unknown_ulid(repos):
    pivot_users, bindings, _ = repos
    out = _ulids_to_feishu_open_ids(
        ["ghost_ulid_not_in_db"], pivot_users, bindings,
    )
    assert out == []


def test_ulids_to_feishu_open_ids_handles_mixed_input(repos):
    pivot_users, bindings, _ = repos
    u = pivot_users.create(
        display_name="Frank", pinyin="frank", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_frank0000000000_",
        external_union_id=None, raw_profile_json=None,
    )
    out = _ulids_to_feishu_open_ids(
        [u.id, "ou_external00000000000"], pivot_users, bindings,
    )
    assert sorted(out) == sorted(["ou_frank0000000000_", "ou_external00000000000"])
