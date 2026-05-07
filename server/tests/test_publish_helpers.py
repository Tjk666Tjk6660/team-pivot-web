"""Tests for the ULID-aware mention helpers added in Task 19.5."""
from __future__ import annotations

import pytest

from server.external_bindings import ExternalBindingRepo
from server.pivot_users import PivotUser, PivotUserRepo
from server.publish import (
    _normalize_mentions_to_pinyin,
    _resolve_inline_stakeholders,
    _ulids_to_feishu_open_ids,
)


@pytest.fixture
def repos(db):
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    return pivot_users, bindings


def test_normalize_resolves_ulid_to_pinyin(repos):
    """ULID input → user's pinyin (matches creator/owner/author format
    in the index)."""
    pivot_users, bindings = repos
    u = pivot_users.create(
        display_name="Alice", pinyin="alice", email=None, avatar_url="",
        role="member",
    )
    out = _normalize_mentions_to_pinyin([u.id], pivot_users, bindings)
    assert out == ["alice"]


def test_normalize_resolves_open_id_via_binding_to_pinyin(repos):
    pivot_users, bindings = repos
    u = pivot_users.create(
        display_name="Bob", pinyin="bob", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_bob000000000000",
        external_union_id=None, raw_profile_json=None,
    )
    out = _normalize_mentions_to_pinyin(
        ["ou_bob000000000000"], pivot_users, bindings,
    )
    assert out == ["bob"]


def test_normalize_preserves_unbound_open_id(repos):
    """Feishu open_id with no pivot_user binding — preserve as-is so the
    read-side resolver echoes it back with status='unknown'."""
    pivot_users, bindings = repos
    out = _normalize_mentions_to_pinyin(
        ["ou_external00000000000"], pivot_users, bindings,
    )
    assert out == ["ou_external00000000000"]


def test_normalize_returns_none_for_empty(repos):
    pivot_users, bindings = repos
    assert _normalize_mentions_to_pinyin(None, pivot_users, bindings) is None
    assert _normalize_mentions_to_pinyin([], pivot_users, bindings) is None


def test_normalize_drops_blank_strings(repos):
    pivot_users, bindings = repos
    out = _normalize_mentions_to_pinyin(
        ["", None], pivot_users, bindings,  # type: ignore[list-item]
    )
    assert out == []


def test_normalize_resolves_display_name_to_pinyin(repos):
    """display_name exact match → user's pinyin."""
    pivot_users, bindings = repos
    pivot_users.create(
        display_name="Carol", pinyin="carol", email=None, avatar_url="",
        role="member",
    )
    out = _normalize_mentions_to_pinyin(
        ["Carol"], pivot_users, bindings,
    )
    assert out == ["carol"]


def test_normalize_passes_pinyin_through(repos):
    """pinyin input → same pinyin (round-trips cleanly)."""
    pivot_users, bindings = repos
    pivot_users.create(
        display_name="赵六", pinyin="zhaoliu", email=None, avatar_url="",
        role="member",
    )
    out = _normalize_mentions_to_pinyin(
        ["zhaoliu"], pivot_users, bindings,
    )
    assert out == ["zhaoliu"]


def test_normalize_falls_back_to_ulid_when_pinyin_missing(repos):
    """Profile-incomplete user (no pinyin) → ULID fallback so the row
    still has a stable identifier; read-side resolver picks it up."""
    pivot_users, bindings = repos
    u = pivot_users.create(
        display_name="Newbie", pinyin=None, email="x@y.com", avatar_url="",
        role="member",
    )
    out = _normalize_mentions_to_pinyin([u.id], pivot_users, bindings)
    assert out == [u.id]


def test_ulids_to_feishu_open_ids_passes_through_open_ids(repos):
    pivot_users, bindings = repos
    out = _ulids_to_feishu_open_ids(
        ["ou_x" + "0" * 16, "on_y" + "0" * 16], pivot_users, bindings,
    )
    assert out == ["ou_x" + "0" * 16, "on_y" + "0" * 16]


def test_ulids_to_feishu_open_ids_resolves_via_binding(repos):
    pivot_users, bindings = repos
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
    pivot_users, bindings = repos
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
    pivot_users, bindings = repos
    out = _ulids_to_feishu_open_ids(
        ["ghost_ulid_not_in_db"], pivot_users, bindings,
    )
    assert out == []


def test_ulids_to_feishu_open_ids_handles_mixed_input(repos):
    pivot_users, bindings = repos
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


# ---------- _resolve_inline_stakeholders ----------
#
# V2 helper: resolve file.creator + matter.owner + matter.creator into the
# DM/relevance recipient list. Shared by mention + annotation paths so the
# behavior here is load-bearing for both flows.


def _make_user(pivot_users, bindings, *, pinyin: str, with_feishu: bool = True):
    """Helper: create a pivot_user, optionally bind a feishu open_id, return
    (user, expected_recipient_id). Recipient id is the feishu open_id when
    bound, else the pivot_user.id (matches the helper's fallback)."""
    u = pivot_users.create(
        display_name=pinyin, pinyin=pinyin, email=None, avatar_url="",
        role="member",
    )
    if with_feishu:
        oid = f"ou_{pinyin}_000000000000"
        bindings.bind(
            pivot_user_id=u.id, provider="feishu",
            external_id=oid, external_union_id=None, raw_profile_json=None,
        )
        return u, oid
    return u, u.id


def _matter_with_three_roles(file_creator: str, matter_owner: str, matter_creator: str) -> dict:
    """Build a matter index dict where the first non-event timeline item's
    creator == matter_creator (matches `_matter_creator_pinyin` derivation),
    the matter.owner field is matter_owner, and `target_file` exists in the
    timeline with file_creator as its creator."""
    return {
        "matter": {"id": "m-x", "owner": matter_owner},
        "timeline": [
            {
                "file": "discussions/cat/m-x/01_creator_think.md",
                "type": "think",
                "creator": matter_creator,
                "owner": matter_creator,
                "summary": "",
                "created_at": "2026-04-28T10:00:00+08:00",
            },
            {
                "file": "discussions/cat/m-x/02_target.md",
                "type": "act",
                "creator": file_creator,
                "owner": file_creator,
                "summary": "",
                "created_at": "2026-04-28T11:00:00+08:00",
            },
        ],
    }


def test_resolve_inline_stakeholders_returns_three_roles_when_all_distinct(repos):
    pivot_users, bindings = repos
    fc, fc_oid = _make_user(pivot_users, bindings, pinyin="alice")  # file.creator
    mo, mo_oid = _make_user(pivot_users, bindings, pinyin="bob")    # matter.owner
    mc, mc_oid = _make_user(pivot_users, bindings, pinyin="carol")  # matter.creator
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")

    data = _matter_with_three_roles("alice", "bob", "carol")
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
    )
    # Order: file.creator, matter.owner, matter.creator (helper iterates that
    # tuple) — order-stable so callers can reason about DM ordering.
    assert out == [fc_oid, mo_oid, mc_oid]


def test_resolve_inline_stakeholders_dedups_when_roles_overlap(repos):
    """Common case: matter.creator owns the matter and creates the targeted
    file. One person plays all three roles → exactly one recipient."""
    pivot_users, bindings = repos
    same, same_oid = _make_user(pivot_users, bindings, pinyin="alice")
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")

    data = _matter_with_three_roles("alice", "alice", "alice")
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
    )
    assert out == [same_oid]


def test_resolve_inline_stakeholders_excludes_actor_in_any_role(repos):
    """Actor is matter.owner AND matter.creator — they should NOT DM
    themselves. file.creator (a different user) still receives."""
    pivot_users, bindings = repos
    actor, _ = _make_user(pivot_users, bindings, pinyin="alice")
    fc, fc_oid = _make_user(pivot_users, bindings, pinyin="bob")

    data = _matter_with_three_roles("bob", "alice", "alice")
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
    )
    assert out == [fc_oid]


def test_resolve_inline_stakeholders_excludes_already_notified(repos):
    """If matter.owner is already in already_notified (because they were
    explicitly @-ed), don't add them again as a stakeholder."""
    pivot_users, bindings = repos
    fc, fc_oid = _make_user(pivot_users, bindings, pinyin="alice")
    mo, mo_oid = _make_user(pivot_users, bindings, pinyin="bob")
    mc, mc_oid = _make_user(pivot_users, bindings, pinyin="carol")
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")

    data = _matter_with_three_roles("alice", "bob", "carol")
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
        already_notified=[mo_oid],
    )
    assert out == [fc_oid, mc_oid]


def test_resolve_inline_stakeholders_skips_missing_roles_gracefully(repos):
    """matter.owner unset, matter.creator references a user that never
    registered, file.creator resolves fine. We return file.creator only —
    we never refuse the mention because a stakeholder didn't resolve."""
    pivot_users, bindings = repos
    fc, fc_oid = _make_user(pivot_users, bindings, pinyin="alice")
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")

    data = {
        "matter": {"id": "m-x"},  # no matter.owner
        "timeline": [
            {
                "file": "discussions/cat/m-x/01.md",
                "type": "think",
                "creator": "ghost_pinyin_no_user",  # matter.creator unresolvable
                "owner": "ghost_pinyin_no_user",
                "summary": "",
                "created_at": "2026-04-28T10:00:00+08:00",
            },
            {
                "file": "discussions/cat/m-x/02_target.md",
                "type": "act",
                "creator": "alice",
                "owner": "alice",
                "summary": "",
                "created_at": "2026-04-28T11:00:00+08:00",
            },
        ],
    }
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
    )
    # matter.owner falls through to first timeline item's owner (also unresolvable),
    # matter.creator likewise unresolvable. Only file.creator survives.
    assert out == [fc_oid]


def test_resolve_inline_stakeholders_falls_back_to_pivot_user_id_without_feishu(repos):
    """When a stakeholder has no feishu binding, use pivot_user.id as the
    recipient id — they still get a relevance row (DM is best-effort, but
    the writer needs a stable id to dedupe)."""
    pivot_users, bindings = repos
    fc, fc_pid = _make_user(pivot_users, bindings, pinyin="alice", with_feishu=False)
    actor, _ = _make_user(pivot_users, bindings, pinyin="actor_zz")

    data = _matter_with_three_roles("alice", "alice", "alice")
    out = _resolve_inline_stakeholders(
        data, "discussions/cat/m-x/02_target.md",
        actor=actor, pivot_users=pivot_users, bindings=bindings,
    )
    assert out == [fc_pid]
