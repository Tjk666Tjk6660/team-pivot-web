from __future__ import annotations

import logging

import httpx

from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    parse_context_url,
)
from server.mcp.schemas import (
    ListMattersIn,
    ListMattersOut,
    MatterListItem,
    MatterSnapshot,
    ResolveContextIn,
    ResolveContextOut,
)

log = logging.getLogger(__name__)


class ToolError(Exception):
    """Raised by tool implementations to signal a structured error to MCP.

    The MCP dispatcher translates this into a JSON payload with
    `{"error": {"status": <status>, "detail": <detail>}}`.
    """

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class MatterApiClient:
    """Thin wrapper around Matter API, using the calling user's PAT.

    Each MCP tool call constructs one of these with the plaintext token
    pulled from the per-request ContextVar; the same token that authed the
    MCP request is used to act on behalf of the user against /api/matters/*.
    """

    def __init__(self, base_url: str, token: str):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    def get_matter(self, matter_id: str) -> dict:
        resp = httpx.get(
            f"{self._base}/api/matters/{matter_id}",
            headers=self._headers,
            timeout=10.0,
        )
        if resp.status_code == 404:
            raise ToolError(404, "matter_not_found")
        if resp.status_code == 403:
            raise ToolError(403, "forbidden")
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        resp.raise_for_status()
        return resp.json()

    def list_matters(
        self,
        status: str | None = None,
        owner: str | None = None,
        q: str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if owner:
            params["owner"] = owner
        if q:
            params["q"] = q
        resp = httpx.get(
            f"{self._base}/api/matters",
            headers=self._headers,
            params=params,
            timeout=10.0,
        )
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])


def tool_resolve_context(
    payload: dict,
    client: MatterApiClient,
) -> dict:
    """Parse a Pivot URL + verify access + return summary for AI to echo."""
    input_ = ResolveContextIn.model_validate(payload)
    try:
        matter_id, file_path = parse_context_url(input_.url)
    except ContextUrlError as e:
        raise ToolError(400, f"bad_url: {e}")

    data = client.get_matter(matter_id)
    matter = data.get("matter") or {}
    timeline = data.get("timeline") or []

    if file_path is not None:
        found = any(t.get("file") == file_path for t in timeline)
        if not found:
            raise ToolError(404, "file_not_in_matter")

    summary_text = build_user_facing_summary(matter, file_path, timeline)

    result = ResolveContextOut(
        matter_id=matter_id,
        file_path=file_path,
        matter_snapshot=MatterSnapshot(
            id=matter.get("id", matter_id),
            title=matter.get("title", ""),
            current_status=matter.get("current_status", "unknown"),
            updated_at=matter.get("updated_at", ""),
        ),
        user_facing_summary=summary_text,
    )
    return result.model_dump(mode="json")


def tool_list_matters(payload: dict, client: MatterApiClient) -> dict:
    input_ = ListMattersIn.model_validate(payload)
    raw_items = client.list_matters(
        status=input_.status,
        owner=input_.owner,
        q=input_.q,
    )
    items = [
        MatterListItem(
            id=it.get("id", ""),
            title=it.get("title", ""),
            current_status=it.get("current_status", ""),
            updated_at=it.get("updated_at", ""),
            file_count=it.get("file_count"),
        )
        for it in raw_items
    ]
    return ListMattersOut(items=items).model_dump(mode="json")
