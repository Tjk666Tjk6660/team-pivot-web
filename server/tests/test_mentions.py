from __future__ import annotations

from server.external_bindings import ExternalBindingRepo
from server.mentions import (
    DisplayInfo,
    DisplayResolver,
    author_view,
    resolve_avatar_url,
    resolve_id,
    resolve_text,
)
from server.pivot_users import PivotUserRepo


def _make_resolver(
    db,
) -> tuple[DisplayResolver, PivotUserRepo, ExternalBindingRepo]:
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    resolver = DisplayResolver(pivot_users, bindings)
    return resolver, pivot_users, bindings


def test_direct_lookup_by_pivot_user_id_skips_binding(db):
    resolver, pivot_users, bindings = _make_resolver(db)
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
    resolver, pivot_users, bindings = _make_resolver(db)
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
    resolver, pivot_users, bindings = _make_resolver(db)
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
    resolver, pivot_users, bindings = _make_resolver(db)
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


def test_unknown_ref_echoes_back(db):
    resolver, *_ = _make_resolver(db)
    info = resolver.resolve("ou_ghost000000000000")
    assert info == DisplayInfo("ou_ghost000000000000", "", "unknown")


def test_empty_ref(db):
    resolver, *_ = _make_resolver(db)
    assert resolver.resolve(None) == DisplayInfo("", "", "unknown")
    assert resolver.resolve("") == DisplayInfo("", "", "unknown")


def test_cache_avoids_repeated_db_hits(db):
    resolver, pivot_users, bindings = _make_resolver(db)
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
    resolver, pivot_users, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Old", pinyin="old", email=None, avatar_url="",
        role="member",
    )
    assert resolver.resolve(user.id).display_name == "Old"
    pivot_users.update_profile(user.id, display_name="New")
    resolver.invalidate()
    assert resolver.resolve(user.id).display_name == "New"


def test_resolve_id_thin_wrapper(db):
    resolver, pivot_users, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Frank", pinyin="frank", email=None, avatar_url="",
        role="member",
    )
    assert resolve_id(user.id, resolver) == "Frank"
    assert resolve_id("ou_unknown000000000000", resolver) == "ou_unknown000000000000"
    assert resolve_id("", resolver) == ""
    assert resolve_id(None, resolver) is None


def test_resolve_avatar_url_thin_wrapper(db):
    resolver, pivot_users, _ = _make_resolver(db)
    user = pivot_users.create(
        display_name="Gina", pinyin="gina", email=None,
        avatar_url="https://x/g.png", role="member",
    )
    assert resolve_avatar_url(user.id, resolver) == "https://x/g.png"
    assert resolve_avatar_url("ou_missing0000000000", resolver) is None
    assert resolve_avatar_url(None, resolver) is None


def test_resolve_text_replaces_known_open_ids(db):
    resolver, pivot_users, bindings = _make_resolver(db)
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


def test_resolve_text_no_matches_unchanged(db):
    resolver, *_ = _make_resolver(db)
    assert resolve_text("plain text, no mentions", resolver) == "plain text, no mentions"


def test_author_view_active_user(db):
    resolver, pivot_users, _ = _make_resolver(db)
    u = pivot_users.create(
        display_name="Hank", pinyin="hank", email=None,
        avatar_url="https://x/h.png", role="member",
    )
    view = author_view(u.id, resolver)
    assert view == {
        "user_id": u.id,
        "open_id": u.id,
        "display_name": "Hank",
        "avatar_url": "https://x/h.png",
        "status": "active",
    }


def test_author_view_legacy_open_id_resolves_to_active(db):
    resolver, pivot_users, bindings = _make_resolver(db)
    u = pivot_users.create(
        display_name="Ivy", pinyin="ivy", email=None, avatar_url="",
        role="member",
    )
    bindings.bind(
        pivot_user_id=u.id, provider="feishu",
        external_id="ou_ivy00000000000000",
        external_union_id=None, raw_profile_json=None,
    )
    view = author_view("ou_ivy00000000000000", resolver)
    # ref preserved as-is so it stays consistent with what's on disk
    assert view["user_id"] == "ou_ivy00000000000000"
    assert view["open_id"] == "ou_ivy00000000000000"
    assert view["display_name"] == "Ivy"
    assert view["status"] == "active"


def test_author_view_unknown_ref(db):
    resolver, *_ = _make_resolver(db)
    view = author_view("ou_ghost000000000000", resolver)
    assert view == {
        "user_id": "ou_ghost000000000000",
        "open_id": "ou_ghost000000000000",
        "display_name": "ou_ghost000000000000",
        "avatar_url": None,
        "status": "unknown",
    }


def test_author_view_empty_ref_returns_none(db):
    resolver, *_ = _make_resolver(db)
    assert author_view(None, resolver) is None
    assert author_view("", resolver) is None


def test_author_view_reflects_suspended_status(db):
    resolver, pivot_users, _ = _make_resolver(db)
    u = pivot_users.create(
        display_name="J", pinyin="j", email=None, avatar_url="",
        role="member",
    )
    pivot_users.update_status(
        user_id=u.id, status="suspended", note=None, changed_by="admin",
    )
    resolver.invalidate()
    view = author_view(u.id, resolver)
    assert view["status"] == "suspended"
