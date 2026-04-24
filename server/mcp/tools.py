from __future__ import annotations

import logging

import httpx

from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    parse_context_url,
)
from server.mcp.schemas import (
    FileContent,
    GetMatterIn,
    GetMatterOut,
    ListMattersIn,
    ListMattersOut,
    MatterListItem,
    MatterSnapshot,
    ReadFilesIn,
    ReadFilesOut,
    ResolveContextIn,
    ResolveContextOut,
    TimelineItem,
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


MAX_FILES_PER_READ = 5
MAX_TOTAL_CHARS_PER_READ = 50_000
MAX_CHARS_PER_FILE = 20_000


def tool_get_matter(payload: dict, client: MatterApiClient) -> dict:
    """Return matter header + timeline metadata (bodies stripped)."""
    input_ = GetMatterIn.model_validate(payload)
    data = client.get_matter(input_.matter_id)
    matter = data.get("matter") or {}
    timeline_raw = data.get("timeline") or []

    timeline = []
    for item in timeline_raw:
        # STRIP body here — AI only needs index from this tool.
        clean = {k: v for k, v in item.items() if k != "body"}
        timeline.append(TimelineItem.model_validate(clean).model_dump(mode="json"))

    return GetMatterOut(
        matter=MatterSnapshot(
            id=matter.get("id", input_.matter_id),
            title=matter.get("title", ""),
            current_status=matter.get("current_status", "unknown"),
            updated_at=matter.get("updated_at", ""),
        ),
        timeline=timeline,
    ).model_dump(mode="json")


def tool_read_files(payload: dict, client: MatterApiClient) -> dict:
    """Return bodies for the requested file paths, with hard caps."""
    input_ = ReadFilesIn.model_validate(payload)
    if not input_.paths:
        raise ToolError(400, "paths must not be empty")
    if len(input_.paths) > MAX_FILES_PER_READ:
        raise ToolError(
            400,
            f"too_many_files: requested {len(input_.paths)}, max is "
            f"{MAX_FILES_PER_READ}. Call again in batches.",
        )
    data = client.get_matter(input_.matter_id)
    timeline = data.get("timeline") or []
    by_path = {t.get("file"): t for t in timeline}

    results: list[FileContent] = []
    total_chars = 0
    for p in input_.paths:
        item = by_path.get(p)
        if item is None:
            raise ToolError(404, f"file_not_in_matter: {p}")
        body = item.get("body") or ""
        truncated = False
        if len(body) > MAX_CHARS_PER_FILE:
            body = body[:MAX_CHARS_PER_FILE]
            truncated = True
        total_chars += len(body)
        if total_chars > MAX_TOTAL_CHARS_PER_READ:
            raise ToolError(
                400,
                f"body_too_large: total chars would exceed "
                f"{MAX_TOTAL_CHARS_PER_READ}. Pick fewer / smaller files, "
                f"or request one at a time.",
            )
        results.append(FileContent(
            file_path=p,
            type=item.get("type", ""),
            creator=item.get("creator", ""),
            owner=item.get("owner", ""),
            created_at=item.get("created_at", ""),
            body=body,
            truncated=truncated,
        ))
    return ReadFilesOut(files=results).model_dump(mode="json")
