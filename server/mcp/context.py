from __future__ import annotations

from urllib.parse import unquote, urlparse


class ContextUrlError(ValueError):
    pass


def parse_context_url(url: str) -> tuple[str, str | None]:
    """Parse a Pivot context URL.

    Accepted shapes:
      https://<host>/m/<matter_id>
      https://<host>/m/<matter_id>/f/<file_path>

    Returns (matter_id, file_path or None).
    Raises ContextUrlError if the URL does not match.
    """
    if not url:
        raise ContextUrlError("empty url")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ContextUrlError(f"unsupported scheme: {parsed.scheme}")
    path = parsed.path
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "m":
        raise ContextUrlError("URL must be in the form /m/<matter_id> or /m/<matter_id>/f/<path>")
    matter_id = unquote(parts[1])
    if len(parts) == 2:
        return matter_id, None
    if len(parts) < 4 or parts[2] != "f":
        raise ContextUrlError("file part must be /f/<path>")
    file_path = "/".join(unquote(p) for p in parts[3:])
    return matter_id, file_path


def build_user_facing_summary(matter: dict, file_path: str | None, timeline: list[dict]) -> str:
    """Compose a one-liner the AI shows to the user after resolve_context."""
    title = matter.get("title") or matter.get("id")
    status = matter.get("current_status") or "unknown"
    if not file_path:
        return f'我读到了「{title}」这个 matter（状态：{status}）。你想做什么？'
    matched = next((t for t in timeline if t.get("file") == file_path), None)
    if matched:
        ftype = matched.get("type", "file")
        fsummary = matched.get("summary", "")
        return (
            f'我读到了「{title}」matter 的一篇 {ftype} 文件：《{fsummary}》。'
            f'当前 matter 状态：{status}。你想做什么？'
        )
    return f'我读到了「{title}」matter 的一篇文件（{file_path}）。当前状态：{status}。你想做什么？'


def build_view_url(web_base_url: str, matter_id: str, file_path: str) -> str:
    """Compose a Web URL for 'where to view this file'."""
    base = web_base_url.rstrip("/")
    return f"{base}/m/{matter_id}/f/{file_path}"
