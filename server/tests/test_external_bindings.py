from __future__ import annotations

import pytest

from server.db import Database
from server.external_bindings import ExternalBinding, ExternalBindingRepo
from server.pivot_users import PivotUserRepo


@pytest.fixture
def deps(tmp_path):
    db = Database(tmp_path / "test.db")
    users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    user = users.create(display_name="Alice", pinyin="alice", email=None, avatar_url="", role="member")
    return users, bindings, user


def test_bind_creates_row(deps):
    _, bindings, user = deps
    b = bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id="on_xxx", raw_profile_json='{"name":"Alice"}',
    )
    assert isinstance(b, ExternalBinding)
    assert b.provider == "feishu"
    assert b.external_id == "ou_xxx"


def test_lookup_by_provider_external_id(deps):
    _, bindings, user = deps
    bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id=None, raw_profile_json=None,
    )
    found = bindings.lookup(provider="feishu", external_id="ou_xxx")
    assert found is not None
    assert found.pivot_user_id == user.id
    assert bindings.lookup(provider="feishu", external_id="nonexistent") is None


def test_user_already_bound_in_provider_rejected(deps):
    users, bindings, user = deps
    bindings.bind(
        pivot_user_id=user.id, provider="feishu", external_id="ou_xxx",
        external_union_id=None, raw_profile_json=None,
    )
    with pytest.raises(ValueError):
        bindings.bind(
            pivot_user_id=user.id, provider="feishu", external_id="ou_yyy",
            external_union_id=None, raw_profile_json=None,
        )


def test_invite_password_storage(deps):
    _, bindings, user = deps
    b = bindings.bind(
        pivot_user_id=user.id, provider="invite", external_id="alice@example.com",
        external_union_id=None, raw_profile_json=None,
        password_hash="$2b$12$abc",
    )
    assert b.password_hash == "$2b$12$abc"
    found = bindings.lookup(provider="invite", external_id="alice@example.com")
    assert found.password_hash == "$2b$12$abc"


def test_list_bindings_for_user(deps):
    _, bindings, user = deps
    bindings.bind(pivot_user_id=user.id, provider="feishu", external_id="ou_x",
                  external_union_id=None, raw_profile_json=None)
    bindings.bind(pivot_user_id=user.id, provider="invite", external_id="a@x.com",
                  external_union_id=None, raw_profile_json=None,
                  password_hash="$2b$12$x")
    rows = bindings.list_for_user(user.id)
    assert {b.provider for b in rows} == {"feishu", "invite"}
