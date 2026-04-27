from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from server.posts import read_post

log = logging.getLogger("server.ai.tools")

# Hard limits to prevent a tool call from flooding the model context.
MAX_TITLES_RETURNED = 50
MAX_SEARCH_HITS = 20
MAX_SNIPPET_CHARS = 240
MAX_INDEX_BYTES = 60_000
MAX_POST_BODY_CHARS = 20_000
WHITELIST_TTL_SECONDS = 60


class ToolError(Exception):
    """Raised to surface a controlled error back to the model as tool_result."""


@dataclass
class _WhitelistCache:
    built_at: float
    posts: set[str]  # relative paths like "Pivot/slug/001_xxx.md"


class AITools:
    """
    AI-facing tool handlers. The model can call these through the tool-use
    protocol. Every handler returns a plain string (ready to send back as a
    `tool_result`), or raises ToolError to deliver an error message.

    All file access is sandboxed to workspace.discussions_dir and
    workspace.index_dir, with both path-traversal checks and (for read_post)
    an index-derived whitelist.
    """

    def __init__(self, discussions_dir: Path, index_dir: Path):
        self._discussions_dir = Path(discussions_dir).resolve()
        self._index_dir = Path(index_dir).resolve()
        self._whitelist: _WhitelistCache | None = None

    # ── Tool specs (OpenAI-tools format for OpenRouter) ────────────────────────

    def specs(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_thread_titles",
                    "description": (
                        "列出 workspace 下所有 thread 的标题。无入参。"
                        "返回一个纯字符串列表，用于快速发现还有哪些 thread 存在。"
                        "每次最多返回 50 个标题。"
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_matters",
                    "description": (
                        "列出 workspace 下所有 matter（事项）。无入参。"
                        "每条返回 matter_id / title / current_status / updated_at,"
                        "按 updated_at 降序排列。"
                        "用于跨 matter 汇总场景（如『近期都讨论了什么』『X / Y / Z 现在啥状态』）"
                        "的入口；拿到候选后再用 read_matter_index 读细节。"
                        "每次最多返回 50 条。"
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_indexes",
                    "description": (
                        "在所有 thread 和 matter 的 index 文件内容里做关键词搜索。"
                        "返回命中的标题 / matter_id + 命中上下文片段，"
                        "每条标注 kind=thread 或 kind=matter，方便后续选用 "
                        "read_thread_index 或 read_matter_index。"
                        "用于在不记得 ID 时定位相关讨论。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词，区分大小写按子串匹配。",
                            }
                        },
                        "required": ["keyword"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_thread_index",
                    "description": (
                        "读取某个 thread 的 index YAML 全文。"
                        "index 包含时间线、文件列表、引用关系等，是了解 thread 全貌的最佳入口。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "thread_slug": {
                                "type": "string",
                                "description": (
                                    "thread 的 slug（= index 文件名前缀，"
                                    "通常也就是 thread 标题）。"
                                ),
                            }
                        },
                        "required": ["thread_slug"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_matter_index",
                    "description": (
                        "读取某个 matter（事项）的 index YAML 全文。"
                        "matter index 包含 matter 元信息（status / owner）和"
                        "时间线（按时间顺序排列的全部文件 + summary + 类型 + 状态变更等）,"
                        "是了解 matter 全貌的最佳入口。"
                        "matter_id 通常可从 starting_post 的 path 字段 "
                        "discussions/<category>/<matter_id>/... 中提取。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "matter_id": {
                                "type": "string",
                                "description": (
                                    "matter 的 ID（也是 index 文件名前缀,"
                                    "实际文件名为 {matter_id}.index.yaml）。"
                                ),
                            }
                        },
                        "required": ["matter_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_post",
                    "description": (
                        "读取某篇帖子（.md 文件）的正文。"
                        "path 必须是某个 index 里已经挂过号的路径,例如通过 "
                        "read_thread_index 或 read_matter_index 先了解到这篇文件存在。"
                        "路径形如 'discussions/<category>/<slug>/<filename>.md'。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "帖子相对 workspace 根目录的完整路径。",
                            }
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    # ── Dispatch ───────────────────────────────────────────────────────────────

    def dispatch(self, name: str, arguments: dict) -> str:
        try:
            if name == "list_thread_titles":
                return self._list_thread_titles()
            if name == "list_matters":
                return self._list_matters()
            if name == "search_indexes":
                return self._search_indexes(str(arguments.get("keyword") or "").strip())
            if name == "read_thread_index":
                return self._read_thread_index(str(arguments.get("thread_slug") or "").strip())
            if name == "read_matter_index":
                return self._read_matter_index(str(arguments.get("matter_id") or "").strip())
            if name == "read_post":
                return self._read_post(str(arguments.get("path") or "").strip())
            raise ToolError(f"未知工具：{name}")
        except ToolError as e:
            return f"[tool error] {e}"
        except Exception:
            log.exception("ai tool %s crashed", name)
            return "[tool error] 工具执行异常，请稍后重试或换一种方式"

    # ── Handlers ───────────────────────────────────────────────────────────────

    def _list_thread_titles(self) -> str:
        titles: list[str] = []
        if self._index_dir.is_dir():
            for p in sorted(self._index_dir.iterdir()):
                if p.is_file() and p.name.endswith("-discuss.index.yaml"):
                    titles.append(p.name[: -len("-discuss.index.yaml")])
        if not titles:
            return "（当前 workspace 没有 thread）"
        clipped = titles[:MAX_TITLES_RETURNED]
        header = f"共 {len(titles)} 个 thread" + (
            f"，仅显示前 {MAX_TITLES_RETURNED} 个" if len(titles) > MAX_TITLES_RETURNED else ""
        )
        body = "\n".join(f"- {t}" for t in clipped)
        return f"{header}:\n{body}"

    def _list_matters(self) -> str:
        """List all matter index files with their key metadata, sorted by updated_at desc."""
        if not self._index_dir.is_dir():
            return "（没有 index 目录）"

        rows: list[tuple[str, str, str, str]] = []  # (updated_at, matter_id, title, status)
        for p in sorted(self._index_dir.iterdir()):
            if not (p.is_file() and p.name.endswith(".index.yaml")):
                continue
            if p.name.endswith("-discuss.index.yaml"):
                continue  # skip legacy thread indexes
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            m = data.get("matter") if isinstance(data, dict) else None
            if not isinstance(m, dict):
                continue
            matter_id = str(m.get("id") or p.name[: -len(".index.yaml")])
            title = str(m.get("title") or "(untitled)")
            status = str(m.get("current_status") or "")
            updated_at = str(m.get("updated_at") or "")
            rows.append((updated_at, matter_id, title, status))

        if not rows:
            return "（当前 workspace 没有 matter）"

        rows.sort(key=lambda r: r[0], reverse=True)
        clipped = rows[:MAX_TITLES_RETURNED]
        header = f"共 {len(rows)} 个 matter" + (
            f"，仅显示前 {MAX_TITLES_RETURNED} 个（按 updated_at 降序）"
            if len(rows) > MAX_TITLES_RETURNED
            else "（按 updated_at 降序）"
        )
        body_lines = [
            f"- [{status or '?'}] {matter_id} — {title}"
            for _, matter_id, title, status in clipped
        ]
        return f"{header}:\n" + "\n".join(body_lines)

    def _search_indexes(self, keyword: str) -> str:
        if not keyword:
            raise ToolError("search_indexes 需要非空 keyword")
        if not self._index_dir.is_dir():
            return "（没有 index 目录）"

        # (kind, slug_or_id, snippet)
        hits: list[tuple[str, str, str]] = []
        for p in sorted(self._index_dir.iterdir()):
            if not (p.is_file() and p.name.endswith(".index.yaml")):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            idx = text.find(keyword)
            if idx < 0:
                continue
            if p.name.endswith("-discuss.index.yaml"):
                kind = "thread"
                key = p.name[: -len("-discuss.index.yaml")]
            else:
                kind = "matter"
                key = p.name[: -len(".index.yaml")]
            start = max(0, idx - MAX_SNIPPET_CHARS // 2)
            end = min(len(text), idx + MAX_SNIPPET_CHARS // 2)
            snippet = text[start:end].replace("\n", " ")
            hits.append((kind, key, snippet))
            if len(hits) >= MAX_SEARCH_HITS:
                break

        if not hits:
            return f"未找到包含「{keyword}」的 index"
        lines = [f"命中 {len(hits)} 条（关键词「{keyword}」）:"]
        for kind, key, snippet in hits:
            label = f"matter_id={key}" if kind == "matter" else f"thread_slug={key}"
            lines.append(f"\n▶ kind={kind}  {label}\n  …{snippet}…")
        return "\n".join(lines)

    def _read_thread_index(self, slug: str) -> str:
        if not slug:
            raise ToolError("read_thread_index 需要非空 thread_slug")
        path = self._index_dir / f"{slug}-discuss.index.yaml"
        resolved = path.resolve()
        if self._index_dir not in resolved.parents and resolved != self._index_dir:
            raise ToolError("非法路径（越权）")
        if not resolved.is_file():
            raise ToolError(f"未找到 thread「{slug}」的 index")
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as e:
            raise ToolError(f"读取失败：{e}") from e
        if len(text) > MAX_INDEX_BYTES:
            text = text[:MAX_INDEX_BYTES] + f"\n...（已截断，原文 {len(text)} 字节）"
        return text

    def _read_matter_index(self, matter_id: str) -> str:
        if not matter_id:
            raise ToolError("read_matter_index 需要非空 matter_id")
        path = self._index_dir / f"{matter_id}.index.yaml"
        resolved = path.resolve()
        if self._index_dir not in resolved.parents and resolved != self._index_dir:
            raise ToolError("非法路径（越权）")
        if not resolved.is_file():
            raise ToolError(f"未找到 matter「{matter_id}」的 index")
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as e:
            raise ToolError(f"读取失败：{e}") from e
        if len(text) > MAX_INDEX_BYTES:
            text = text[:MAX_INDEX_BYTES] + f"\n...（已截断,原文 {len(text)} 字节）"
        return text

    def _read_post(self, path: str) -> str:
        if not path:
            raise ToolError("read_post 需要非空 path")
        # Accept either "discussions/cat/slug/file.md" or "cat/slug/file.md".
        rel = path
        if rel.startswith("discussions/"):
            rel = rel[len("discussions/") :]
        parts = rel.split("/")
        if len(parts) != 3 or not parts[2].endswith(".md"):
            raise ToolError(
                "path 必须形如 'discussions/<category>/<slug>/<filename>.md'"
            )

        full = (self._discussions_dir / Path(*parts)).resolve()
        if self._discussions_dir not in full.parents:
            raise ToolError("非法路径（越权）")

        whitelist = self._get_whitelist()
        if rel not in whitelist:
            raise ToolError(
                f"路径 {path} 未在任何 index 里挂号，无法读取。"
                "请先用 read_thread_index 或 search_indexes 找到合法路径。"
            )

        if not full.is_file():
            raise ToolError(f"文件不存在：{path}")

        try:
            post = read_post(full)
        except Exception as e:
            raise ToolError(f"解析失败：{e}") from e

        body = post.body
        clipped = ""
        if len(body) > MAX_POST_BODY_CHARS:
            clipped = f"\n...（已截断，原文 {len(body)} 字符）"
            body = body[:MAX_POST_BODY_CHARS]

        fm_text = yaml.safe_dump(
            post.frontmatter or {},
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        return f"---\n{fm_text}\n---\n{body}{clipped}"

    # ── Whitelist ──────────────────────────────────────────────────────────────

    def _get_whitelist(self) -> set[str]:
        now = time.monotonic()
        if self._whitelist and now - self._whitelist.built_at < WHITELIST_TTL_SECONDS:
            return self._whitelist.posts
        self._whitelist = _WhitelistCache(built_at=now, posts=self._build_whitelist())
        return self._whitelist.posts

    def _build_whitelist(self) -> set[str]:
        """Collect every post path mentioned by any index file."""
        out: set[str] = set()

        # (1) Filesystem discovery — every .md file under discussions_dir is
        #     always reachable via its own thread's index in practice. We do
        #     not rely on filesystem alone; we also reconcile with index data
        #     below so path→index mapping stays authoritative.
        if self._discussions_dir.is_dir():
            for md in self._discussions_dir.rglob("*.md"):
                try:
                    rel = md.resolve().relative_to(self._discussions_dir)
                except ValueError:
                    continue
                parts = rel.parts
                if len(parts) == 3:
                    out.add("/".join(parts))

        # (2) Index-declared paths (timeline.file, discussions.files.path, refs.path)
        if self._index_dir.is_dir():
            for p in self._index_dir.iterdir():
                if not (p.is_file() and p.name.endswith("-discuss.index.yaml")):
                    continue
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                except (OSError, yaml.YAMLError):
                    continue
                for path in _extract_index_paths(data):
                    # Normalize to discussions-relative form.
                    if path.startswith("discussions/"):
                        rel = path[len("discussions/") :]
                    else:
                        rel = path
                    if rel.count("/") == 2 and rel.endswith(".md"):
                        out.add(rel)

        return out


def _extract_index_paths(data: dict) -> list[str]:
    paths: list[str] = []
    for disc in data.get("discussions") or []:
        if not isinstance(disc, dict):
            continue
        origin = disc.get("path") or ""
        for f in disc.get("files") or []:
            if not isinstance(f, dict):
                continue
            fname = f.get("path")
            if fname:
                paths.append(f"{origin}{fname}" if origin else str(fname))
            for ref in f.get("refs") or []:
                if isinstance(ref, dict) and ref.get("path"):
                    paths.append(str(ref["path"]))
    for entry in data.get("timeline") or []:
        if isinstance(entry, dict) and entry.get("file"):
            paths.append(str(entry["file"]))
    return paths


def list_thread_slugs(index_dir: Path) -> list[str]:
    """Shared helper — same slug set used by tools and by prompt injection."""
    out: list[str] = []
    index_dir = Path(index_dir)
    if not index_dir.is_dir():
        return out
    for p in sorted(index_dir.iterdir()):
        if p.is_file() and p.name.endswith("-discuss.index.yaml"):
            out.append(p.name[: -len("-discuss.index.yaml")])
    return out


def find_file_entry_in_index(
    index_dir: Path, slug: str, filename: str
) -> dict[str, Any] | None:
    """Return the `files` entry for `filename` inside thread `slug`'s index."""
    path = Path(index_dir) / f"{slug}-discuss.index.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    for disc in data.get("discussions") or []:
        if not isinstance(disc, dict):
            continue
        for f in disc.get("files") or []:
            if isinstance(f, dict) and f.get("path") == filename:
                return f
    return None


