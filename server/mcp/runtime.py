"""Per-request runtime state for MCP tool handlers.

MCP tool callbacks are invoked deep inside the session manager, with no easy
way to thread the caller's PAT down to them. We stash the plaintext token in
a ContextVar at request-authentication time so tool implementations can
retrieve it to forward to Matter API calls (acting on behalf of the user).
"""
from __future__ import annotations

from contextvars import ContextVar

_token: ContextVar[str] = ContextVar("mcp_user_token")


def set_user_token(token: str) -> None:
    _token.set(token)


def current_user_token() -> str:
    try:
        return _token.get()
    except LookupError:
        raise RuntimeError("current_user_token called outside an MCP request")
