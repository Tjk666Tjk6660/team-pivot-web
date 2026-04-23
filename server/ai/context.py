from __future__ import annotations

from pathlib import Path

from server.ai.tools import find_file_entry_in_index
from server.posts import read_post
from server.threads import ThreadDetail

MAX_STARTING_POST_CHARS = 40_000
CHARS_PER_TOKEN = 4  # rough approximation


class ContextTooLongError(Exception):
    pass


def build_thread_context(detail: ThreadDetail) -> str:
    """Format a thread into a text block (retained as a utility for callers
    that want to inline an entire thread; no longer used by the chat endpoint
    directly)."""
    meta = detail.meta
    lines = [
        f"# {meta.title}",
        f"分类: {meta.category}  状态: {meta.status or '未知'}  帖子数: {meta.post_count}",
        "",
        "## 帖子列表",
    ]
    for post in detail.posts:
        fm = post.frontmatter
        ptype = fm.get("type", "")
        author = str(fm.get("author", "unknown"))
        created = fm.get("created", "")
        lines.append(f"\n### [{ptype}] {author}  {created}")
        if post.body.strip():
            lines.append(post.body.strip())
    return "\n".join(lines)


def build_starting_post_block(
    discussions_dir: Path,
    index_dir: Path,
    reply_target: str,
) -> str:
    """
    Build the <starting_post> XML block that we inject into the system prompt.

    reply_target is "<category>/<slug>/<filename.md>".

    Emits index-derived metadata alongside the body so future schema
    extensions (matter status, doc type, quote/refer/verifications/
    status_change) can be added by widening this function alone.
    """
    parts = reply_target.split("/")
    if len(parts) != 3:
        raise ContextTooLongError(
            f"reply_target 格式非法：{reply_target}，应为 '<category>/<slug>/<filename>.md'"
        )
    category, slug, filename = parts
    full = Path(discussions_dir) / category / slug / filename
    if not full.is_file():
        raise ContextTooLongError(f"起点帖子不存在：{reply_target}")

    try:
        post = read_post(full)
    except Exception as e:
        raise ContextTooLongError(f"起点帖子解析失败：{e}") from e

    fm = post.frontmatter or {}
    entry = find_file_entry_in_index(Path(index_dir), slug, filename)
    attrs = _attr_pairs(
        path=f"discussions/{reply_target}",
        type=str(fm.get("type") or ""),
        creator=str(fm.get("author") or fm.get("creator") or ""),
        owner=str(fm.get("owner") or ""),
        created=str(fm.get("created") or ""),
    )

    refs_xml = ""
    if entry:
        refs = entry.get("refs") or []
        if refs:
            ref_lines = []
            for r in refs:
                if not isinstance(r, dict):
                    continue
                rtype = str(r.get("type") or "")
                rpath = str(r.get("path") or "")
                if rtype and rpath:
                    ref_lines.append(f'    <ref type="{rtype}" path="{_esc(rpath)}"/>')
            if ref_lines:
                refs_xml = "\n  <refs>\n" + "\n".join(ref_lines) + "\n  </refs>"

    body = post.body
    clipped = ""
    if len(body) > MAX_STARTING_POST_CHARS:
        clipped = f"\n...（已截断，原文 {len(body)} 字符）"
        body = body[:MAX_STARTING_POST_CHARS]

    return (
        f"<starting_post {attrs}>{refs_xml}\n"
        f"  <body>\n{body}{clipped}\n  </body>\n"
        f"</starting_post>"
    )


def _attr_pairs(**kwargs: str) -> str:
    return " ".join(f'{k}="{_esc(v)}"' for k, v in kwargs.items() if v)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _message_length(msg: dict) -> int:
    """Rough length estimate for budgeting across text + tool_call arguments + tool results."""
    total = 0
    content = msg.get("content")
    if isinstance(content, str):
        total += len(content)
    elif isinstance(content, list):  # tool_result blocks in some providers
        for item in content:
            if isinstance(item, dict):
                total += len(str(item.get("text") or item.get("content") or ""))
    for tc in msg.get("tool_calls") or []:
        fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
        total += len(str(fn.get("arguments") or ""))
        total += len(str(fn.get("name") or ""))
    return total


def _split_into_blocks(messages: list[dict]) -> list[list[dict]]:
    """
    Group messages into atomic blocks so a truncation boundary never splits a
    tool_call/tool_result pair. Boundaries are:
      - right before every `role == 'user'`
      - between two consecutive assistant messages with no tool_calls
    An assistant message with `tool_calls` stays glued to the subsequent
    `tool` messages that answer it.
    """
    blocks: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            if current:
                blocks.append(current)
            current = [msg]
        elif role == "assistant":
            current.append(msg)
            if not msg.get("tool_calls"):
                blocks.append(current)
                current = []
        elif role == "tool":
            current.append(msg)
        else:
            # Unknown roles: isolate into their own block.
            if current:
                blocks.append(current)
            blocks.append([msg])
            current = []
    if current:
        blocks.append(current)
    return blocks


def truncate_messages(
    messages: list[dict],
    system_prompt_len: int,
    max_context_tokens: int,
    min_rounds: int,
    max_rounds: int,
) -> list[dict]:
    """
    Select messages to send to the LLM, from newest backwards, keeping
    tool_call/tool_result pairs intact. A "round" = one atomic block
    (user + assistant[+tool_calls + tool_results...]).
    """
    max_chars = max_context_tokens * CHARS_PER_TOKEN
    blocks = _split_into_blocks(messages)

    selected_blocks: list[list[dict]] = []
    total = system_prompt_len

    for block in reversed(blocks):
        current_round = len(selected_blocks) + 1
        block_len = sum(_message_length(m) for m in block)
        must_include = current_round <= min_rounds
        within_round_limit = current_round <= max_rounds
        within_char_limit = total + block_len <= max_chars

        if not within_round_limit:
            break
        if not must_include and not within_char_limit:
            break

        selected_blocks.insert(0, block)
        total += block_len

    out: list[dict] = []
    for block in selected_blocks:
        out.extend(block)
    return out


