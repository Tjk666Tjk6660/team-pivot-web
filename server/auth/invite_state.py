"""HMAC-signed state envelope for the invite-bearing Feishu OAuth flow.

The Feishu OAuth `state` parameter is the only place the server can stash
context across the redirect. We sign it so the callback can trust the
invite_token came from our /api/invite/{token}/start handler — not from
a forged URL someone crafted to skip invite validation."""
from __future__ import annotations

import base64
import hashlib
import hmac

_PREFIX = "v1"
_SEP = "."


class InviteStateError(ValueError):
    """Raised when an OAuth state envelope fails decode / signature checks."""


def encode_invite_state(*, invite_token: str, secret: str) -> str:
    if not invite_token:
        raise ValueError("invite_token must be non-empty")
    payload = f"{_PREFIX}{_SEP}{invite_token}"
    sig = _sign(payload, secret)
    return f"{payload}{_SEP}{sig}"


def decode_invite_state(state: str, *, secret: str) -> str:
    parts = state.split(_SEP)
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise InviteStateError("malformed invite state envelope")
    prefix, invite_token, sig = parts
    payload = f"{prefix}{_SEP}{invite_token}"
    expected = _sign(payload, secret)
    if not hmac.compare_digest(expected, sig):
        raise InviteStateError("invite state signature mismatch")
    return invite_token


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
