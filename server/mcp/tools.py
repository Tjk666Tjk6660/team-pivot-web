from __future__ import annotations

import logging

import httpx

from server.matter_status import (
    ALLOWED_TRANSITIONS,
    TRIGGER_TYPES_BY_TRANSITION,
)
from server.mcp.context import (
    ContextUrlError,
    build_user_facing_summary,
    build_view_url,
    parse_context_url,
)
from server.mcp.schemas import (
    AvailableTransition,
    CreateFileIn,
    CreateFileOut,
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


# Human-readable labels for each (from, to) transition. Used in
# AvailableTransition.label and in user_facing_summary so the user sees a
# product-level prompt rather than a raw status name.
_TRANSITION_LABELS: dict[tuple[str, str], str] = {
    ("planning", "executing"): "开始执行",
    ("planning", "paused"): "暂停",
    ("executing", "paused"): "暂停",
    ("executing", "finished"): "完成",
    ("executing", "cancelled"): "取消",
    ("paused", "planning"): "回到规划",
    ("paused", "executing"): "继续执行",
    ("finished", "reviewed"): "复盘归档",
    ("cancelled", "reviewed"): "复盘归档",
}


def _compute_available_transitions(current_status: str) -> list[AvailableTransition]:
    out: list[AvailableTransition] = []
    for to in ALLOWED_TRANSITIONS.get(current_status, frozenset()):
        for trigger in sorted(
            TRIGGER_TYPES_BY_TRANSITION.get((current_status, to), frozenset())
        ):
            label = _TRANSITION_LABELS.get((current_status, to), to)
            out.append(AvailableTransition(to=to, trigger_type=trigger, label=label))
    out.sort(key=lambda x: (x.to, x.trigger_type))
    return out


def _format_transitions_hint(transitions: list[AvailableTransition]) -> str:
    if not transitions:
        return ""
    parts = [
        f"{t.label}（→{t.to}，需 type={t.trigger_type}）"
        for t in transitions
    ]
    return f" 当前可触发的状态迁移：{'、'.join(parts)}。要随这次发布一起切换状态吗？"

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
        # MCP → Matter API is always a loopback / intranet call. Bypass the
        # system proxy (HTTP_PROXY / HTTPS_PROXY / Windows proxy) so that
        # client-side proxies like Clash don't intercept 127.0.0.1 traffic
        # and return 502. See docs/designs — Phase 6 E2E hit the same issue.
        self._client = httpx.Client(trust_env=False, timeout=10.0)

    def get_matter(self, matter_id: str) -> dict:
        resp = self._client.get(
            f"{self._base}/api/matters/{matter_id}",
            headers=self._headers,
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
        resp = self._client.get(
            f"{self._base}/api/matters",
            headers=self._headers,
            params=params,
        )
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])

    def post_file(self, matter_id: str, body: dict) -> dict:
        """POST a new timeline item to /api/matters/{id}/files.

        Returns a dict. If the backend returned 422 validation errors, the dict
        will contain a `__validation_errors__` key with the error payload.
        Otherwise it's the normal success response with `item` and `matter` keys.
        """
        resp = self._client.post(
            f"{self._base}/api/matters/{matter_id}/files",
            headers={**self._headers, "Content-Type": "application/json"},
            json=body,
            timeout=15.0,
        )
        if resp.status_code == 401:
            raise ToolError(401, "invalid_token")
        if resp.status_code == 403:
            raise ToolError(403, "forbidden")
        if resp.status_code == 404:
            raise ToolError(404, "matter_not_found")
        if resp.status_code == 409:
            # Stale state (matter changed between prepare and submit) — surface to AI
            raise ToolError(409, "stale_state")
        if resp.status_code == 422:
            # Validation failure — return as data, not exception, so AI can iterate
            return {"__validation_errors__": resp.json()}
        resp.raise_for_status()
        return resp.json()


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

    current_status = matter.get("current_status", "unknown")
    transitions = _compute_available_transitions(current_status)

    summary_text = build_user_facing_summary(matter, file_path, timeline)
    summary_text += _format_transitions_hint(transitions)

    result = ResolveContextOut(
        matter_id=matter_id,
        file_path=file_path,
        matter_snapshot=MatterSnapshot(
            id=matter.get("id", matter_id),
            title=matter.get("title", ""),
            current_status=current_status,
            updated_at=matter.get("updated_at", ""),
            available_transitions=transitions,
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

    current_status = matter.get("current_status", "unknown")
    return GetMatterOut(
        matter=MatterSnapshot(
            id=matter.get("id", input_.matter_id),
            title=matter.get("title", ""),
            current_status=current_status,
            updated_at=matter.get("updated_at", ""),
            available_transitions=_compute_available_transitions(current_status),
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


def tool_create_file(
    payload: dict,
    client: MatterApiClient,
    web_base_url: str,
) -> dict:
    """Write a new timeline item. Returns success + view_url + summary_for_ai,
    or {errors: ...} if validation failed (so AI can retry with fixes)."""
    input_ = CreateFileIn.model_validate(payload)

    api_body: dict = {
        "type": input_.type,
        "summary": input_.summary,
        "body": input_.body,
    }
    if input_.quote is not None:
        api_body["quote"] = input_.quote
    if input_.refer is not None:
        api_body["refer"] = input_.refer
    if input_.owner is not None:
        api_body["owner"] = input_.owner
    if input_.verifications is not None:
        api_body["verifications"] = [v.model_dump() for v in input_.verifications]
    if input_.outcome is not None:
        api_body["outcome"] = input_.outcome
    if input_.status_change is not None:
        api_body["status_change"] = {
            "from": input_.status_change.from_,
            "to": input_.status_change.to,
        }

    resp = client.post_file(input_.matter_id, api_body)

    if "__validation_errors__" in resp:
        # Design §四 agreement: surface 422 as {errors: ...} so AI can fix & retry
        return {"errors": resp["__validation_errors__"]}

    item = resp.get("item") or {}
    matter = resp.get("matter") or {}
    file_path = item.get("file", "")
    view_url = build_view_url(web_base_url, input_.matter_id, file_path)

    title = matter.get("title") or input_.matter_id
    file_count = matter.get("file_count")
    if isinstance(file_count, int) and file_count > 0:
        summary_ai = (
            f"✅ 已提交。这是 matter「{title}」的第 {file_count} 篇。"
            f"点这里查看：{view_url}"
        )
    else:
        # POST /api/matters/{id}/files doesn't include file_count; fall back
        # to a version that doesn't pretend to know the sequence number.
        summary_ai = (
            f"✅ 已提交到 matter「{title}」。点这里查看：{view_url}"
        )

    return CreateFileOut(
        ok=True,
        file_path=file_path,
        view_url=view_url,
        summary_for_ai=summary_ai,
    ).model_dump(mode="json")
