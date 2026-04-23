from __future__ import annotations

from pathlib import Path

from server.posts import read_post
from server.threads import ThreadDetail

MAX_CONTEXT_CHARS = 80_000
CHARS_PER_TOKEN = 4  # rough approximation


def build_thread_context(detail: ThreadDetail) -> str:
    """Format a thread into a text block for the LLM system prompt."""
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

    text = "\n".join(lines)
    if len(text) > MAX_CONTEXT_CHARS:
        raise ContextTooLongError(
            f"讨论内容过长（{len(text)} 字符），超出上下文限制（{MAX_CONTEXT_CHARS}）"
        )
    return text


def build_context_from_files(
    discussions_dir: Path,
    reply_target: str | None,
    references: list[str] | None = None,
) -> str:
    """
    Load and format the reply target file and reference files.
    Paths are in form "category/slug/filename.md".
    Raises ContextTooLongError if total exceeds MAX_CONTEXT_CHARS.
    """
    references = references or []

    def _section(label: str, path: str) -> str | None:
        # Accept both the legacy thread-style 3-part form
        # ("category/slug/filename.md") and the matter-style 4-part form
        # ("discussions/category/slug/filename.md").
        rel = path[len("discussions/"):] if path.startswith("discussions/") else path
        parts = rel.split("/")
        if len(parts) != 3:
            return None
        cat, slug, fname = parts
        full_path = Path(discussions_dir) / cat / slug / fname
        if not full_path.is_file():
            return None
        try:
            post = read_post(full_path)
        except Exception:
            return None
        fm = post.frontmatter
        ptype = fm.get("type", "")
        author = str(fm.get("author", "unknown"))
        created = fm.get("created", "")
        header = (
            f"### 【{label}】 {path}\n"
            f"类型: {ptype}  作者: {author}  时间: {created}"
        )
        return f"{header}\n\n{post.body.strip()}"

    sections: list[str] = []
    if reply_target:
        s = _section("回复对象", reply_target)
        if s:
            sections.append(s)
    for ref in references:
        s = _section("引用文件", ref)
        if s:
            sections.append(s)

    text = "\n\n---\n\n".join(sections)
    if len(text) > MAX_CONTEXT_CHARS:
        raise ContextTooLongError(
            f"选中文件内容过长（{len(text)} 字符），超出上下文限制（{MAX_CONTEXT_CHARS}）"
        )
    return text


def truncate_messages(
    messages: list[dict],
    system_prompt_len: int,
    max_context_tokens: int,
    min_rounds: int,
    max_rounds: int,
) -> list[dict]:
    """
    Select messages to send to LLM, from newest backwards.
    - Always includes min_rounds rounds (even if over char budget).
    - Stops at max_rounds regardless of remaining char budget.
    - Stops early if char budget exceeded (after min_rounds guaranteed).
    A "round" = one user message + one assistant message (2 messages).
    """
    max_chars = max_context_tokens * CHARS_PER_TOKEN
    total = system_prompt_len
    selected: list[dict] = []

    for msg in reversed(messages):
        current_round = (len(selected) // 2) + 1

        must_include = current_round <= min_rounds
        within_round_limit = current_round <= max_rounds
        within_char_limit = total + len(msg.get("content", "")) <= max_chars

        if not within_round_limit:
            break
        if not must_include and not within_char_limit:
            break

        selected.insert(0, msg)
        total += len(msg.get("content", ""))

    return selected


class ContextTooLongError(Exception):
    pass
