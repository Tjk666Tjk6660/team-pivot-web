"""PAT bearer authentication for the MCP sub-app.

MCP clients (Claude Code, Claude Desktop, etc.) send
`Authorization: Bearer pvt_xxx` on every request. We validate the token
against the same `ApiTokenRepo` used by /api/* routes so that a single PAT
works for both the REST API and MCP.
"""
from __future__ import annotations

from starlette.requests import Request

from server.api_tokens import ApiTokenRepo
from server.users import User, UserRepo


class McpAuthError(Exception):
    """Raised when a request to the MCP endpoint fails auth.

    The caller is expected to translate this into an HTTP response with
    the given `status` code and `{"detail": <detail>}` JSON body.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def authenticate(
    request: Request,
    tokens: ApiTokenRepo,
    users: UserRepo,
) -> tuple[User, str]:
    """Extract Bearer PAT and return (User, plaintext_token).

    Raises McpAuthError with proper HTTP status on failure.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise McpAuthError(401, "missing_bearer_token")
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise McpAuthError(401, "missing_bearer_token")

    # lookup_by_plaintext handles hashing + the "not expired" check
    # (returns None for expired tokens), so we don't duplicate that logic.
    record = tokens.lookup_by_plaintext(token)
    if record is None:
        raise McpAuthError(401, "invalid_token")
    user = users.get(record.pivot_user_id)
    if user is None:
        raise McpAuthError(401, "user_not_found")
    tokens.touch_last_used(record.token_hash)
    return user, token
