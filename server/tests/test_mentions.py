from __future__ import annotations

from server.contacts import ContactRepo
from server.external_bindings import ExternalBindingRepo
from server.mentions import (
    DisplayInfo,
    DisplayResolver,
    resolve_avatar_url,
    resolve_id,
    resolve_text,
)
from server.pivot_users import PivotUserRepo


def _make_resolver(
    db, *, with_contacts: bool = False,
) -> tuple[DisplayResolver, PivotUserRepo, ExternalBindingRepo, ContactRepo | None]:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    contacts = ContactRepo(db) if with_contacts else None
    resolver = DisplayResolver(pivot_users, bindings, contacts)
    return resolver, pivot_users, bindings, contacts


def test_direct_lookup_by_pivot_user_id_skips_binding(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Alice", pinyin="alice", email="a@x.com",
        avatar_url="https://x/a.png", role="member",
    )

    # Spy on bindings.lookup_any_provider to assert it isn't called on direct hit.
    calls = {"n": 0}
    real = bindings.lookup_any_provider

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    bindings.lookup_any_provider = counting  # type: ignore[method-assign]

    info = resolver.resolve(user.id)
    assert info == DisplayInfo("Alice", "https://x/a.png", "active")
    assert calls["n"] == 0


def test_binding_fallback_for_legacy_open_id(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Bob", pinyin="bob", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id="ou_bob000000000000",
        external_union_id="on_bob000000000000",
        raw_profile_json=None,
    )
    info = resolver.resolve("ou_bob000000000000")
    assert info.display_name == "Bob"
    assert info.status == "active"


def test_binding_fallback_via_union_id(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Carol", pinyin="carol", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id="ou_carol00000000000",
        external_union_id="on_carol00000000000",
        raw_profile_json=None,
    )
    info = resolver.resolve("on_carol00000000000")
    assert info.display_name == "Carol"


def test_status_propagates_through_binding(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Dave", pinyin="dave", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id="ou_dave00000000000_",
        external_union_id=None, raw_profile_json=None,
    )
    pivot_users.update_status(
        user_id=user.id, status="suspended", note=None, changed_by="admin",
    )
    resolver.invalidate()  # state changed
    info = resolver.resolve("ou_dave00000000000_")
    assert info.status == "suspended"


def test_contacts_fallback_for_unbound_open_id(db):
    resolver, _, _, contacts = _make_resolver(db, with_contacts=True)
    contacts.upsert_many([
        {"open_id": "ou_contact000000000000", "name": "联系人A"},
    ])
    info = resolver.resolve("ou_contact000000000000")
    assert info.display_name == "联系人A"
    assert info.status == "unknown"


def test_unknown_ref_echoes_back(db):
    resolver, *_ = _make_resolver(db)
    info = resolver.resolve("ou_ghost000000000000")
    assert info == DisplayInfo("ou_ghost000000000000", "", "unknown")


def test_empty_ref(db):
    resolver, *_ = _make_resolver(db)
    assert resolver.resolve(None) == DisplayInfo("", "", "unknown")
    assert resolver.resolve("") == DisplayInfo("", "", "unknown")


def test_cache_avoids_repeated_db_hits(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="E", pinyin="e", email=None, avatar_url="", role="member",
    )

    calls = {"n": 0}
    real = pivot_users.get

    def counting(uid, *a, **k):
        calls["n"] += 1
        return real(uid, *a, **k)

    pivot_users.get = counting  # type: ignore[method-assign]

    resolver.resolve(user.id)
    resolver.resolve(user.id)
    resolver.resolve(user.id)
    assert calls["n"] == 1


def test_invalidate_clears_cache(db):
    resolver, pivot_users, _, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Old", pinyin="old", email=None, avatar_url="",
        role="member",
    )
    assert resolver.resolve(user.id).display_name == "Old"
    pivot_users.update_profile(user.id, display_name="New")
    resolver.invalidate()
    assert resolver.resolve(user.id).display_name == "New"


def test_resolve_id_thin_wrapper(db):
    resolver, pivot_users, _, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Frank", pinyin="frank", email=None, avatar_url="",
        role="member",
    )
    assert resolve_id(user.id, resolver) == "Frank"
    assert resolve_id("ou_unknown000000000000", resolver) == "ou_unknown000000000000"
    assert resolve_id("", resolver) == ""
    assert resolve_id(None, resolver) is None


def test_resolve_avatar_url_thin_wrapper(db):
    resolver, pivot_users, _, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Gina", pinyin="gina", email=None,
        avatar_url="https://x/g.png", role="member",
    )
    assert resolve_avatar_url(user.id, resolver) == "https://x/g.png"
    assert resolve_avatar_url("ou_missing0000000000", resolver) is None
    assert resolve_avatar_url(None, resolver) is None


def test_resolve_text_replaces_known_open_ids(db):
    resolver, pivot_users, bindings, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Ken", pinyin="ken", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=user.id, provider="feishu",
        external_id="ou_ken00000000000000",
        external_union_id=None, raw_profile_json=None,
    )
    body = "hi ou_ken00000000000000 and ou_missing0000000000, see you"
    out = resolve_text(body, resolver)
    assert out == "hi @Ken and ou_missing0000000000, see you"


def test_resolve_text_falls_back_to_contacts(db):
    resolver, _, _, contacts = _make_resolver(db, with_contacts=True)
    contacts.upsert_many([
        {"open_id": "ou_contact000000000000", "name": "联系人A"},
    ])
    out = resolve_text("ping ou_contact000000000000 please", resolver)
    assert out == "ping @联系人A please"


def test_resolve_text_no_matches_unchanged(db):
    resolver, *_ = _make_resolver(db)
    assert resolve_text("plain text, no mentions", resolver) == "plain text, no mentions"
