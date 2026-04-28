from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from server.api_tokens import ApiToken
from server.mcp.auth import McpAuthError, authenticate
from server.users import User


def _mk_request(headers: dict) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def _mk_user(open_id: str = "ou_abc") -> User:
    return User(
        open_id=open_id,
        union_id=None,
        name="Test",
        avatar_url="",
        pinyin="test",
        github_username=None,
        markdown_style=None,
        created_at=0.0,
    )


def _mk_token(user_open_id: str = "ou_abc") -> ApiToken:
    return ApiToken(
        token_hash="x" * 64,
        user_open_id=user_open_id,
        name="Claude Code",
        created_at=0.0,
        last_used_at=None,
        expires_at=9e12,  # far future
    )


def test_missing_header_rejects():
    with pytest.raises(McpAuthError) as ei:
        authenticate(_mk_request({}), MagicMock(), MagicMock())
    assert ei.value.status == 401
    assert ei.value.detail == "missing_bearer_token"


def test_non_bearer_scheme_rejects():
    with pytest.raises(McpAuthError) as ei:
        authenticate(
            _mk_request({"Authorization": "Basic dXNlcjpwYXNz"}),
            MagicMock(),
            MagicMock(),
        )
    assert ei.value.status == 401
    assert ei.value.detail == "missing_bearer_token"


def test_invalid_token_rejects():
    tokens = MagicMock()
    tokens.lookup_by_plaintext.return_value = None
    with pytest.raises(McpAuthError) as ei:
        authenticate(
            _mk_request({"Authorization": "Bearer pvt_bad"}),
            tokens,
            MagicMock(),
        )
    assert ei.value.status == 401
    assert ei.value.detail == "invalid_token"


def test_user_not_found_rejects():
    tokens = MagicMock()
    tokens.lookup_by_plaintext.return_value = _mk_token()
    users = MagicMock()
    users.get.return_value = None
    with pytest.raises(McpAuthError) as ei:
        authenticate(
            _mk_request({"Authorization": "Bearer pvt_ok"}),
            tokens,
            users,
        )
    assert ei.value.status == 401
    assert ei.value.detail == "user_not_found"


def test_valid_token_returns_user_and_token():
    tok = _mk_token()
    tokens = MagicMock()
    tokens.lookup_by_plaintext.return_value = tok
    users = MagicMock()
    users.get.return_value = _mk_user()

    u, t = authenticate(
        _mk_request({"Authorization": "Bearer pvt_ok"}),
        tokens,
        users,
    )
    assert u.open_id == "ou_abc"
    assert t == "pvt_ok"
    tokens.touch_last_used.assert_called_once_with(tok.token_hash)


def test_case_insensitive_bearer():
    tok = _mk_token()
    tokens = MagicMock()
    tokens.lookup_by_plaintext.return_value = tok
    users = MagicMock()
    users.get.return_value = _mk_user()

    u, t = authenticate(
        _mk_request({"Authorization": "bearer pvt_ok"}),
        tokens,
        users,
    )
    assert u.open_id == "ou_abc"
    assert t == "pvt_ok"
