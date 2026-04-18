"""Convert an uploaded file to markdown and save as a draft.

Supported formats:
  .md, .markdown  -> read as-is
  .txt            -> read as-is (treated as plain text)
  .docx, .doc     -> pandoc
  .pdf            -> pdftotext

Other extensions are rejected.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_ROOT))

from tools.drafts import (  # noqa: E402
    DraftLimitExceeded,
    MAX_DRAFTS_PER_USER,
    draft_to_dict,
    list_drafts,
    save_draft,
)


SUPPORTED_EXTS = {".md", ".markdown", ".txt", ".docx", ".doc", ".pdf"}


def _fail(msg: str, exit_code: int = 1) -> None:
    sys.stderr.write(f"draft-new-from-file: {msg}\n")
    sys.exit(exit_code)


def _fail_missing_tool(tool_name: str, for_ext: str) -> None:
    hints = {
        "pandoc": "brew install pandoc (macOS) 或 apt install pandoc (Linux)",
        "pdftotext": "brew install poppler (macOS) 或 apt install poppler-utils (Linux)",
    }
    hint = hints.get(tool_name, "")
    _fail(
        f"转换 {for_ext} 文件需要 `{tool_name}`，但系统未安装。\n"
        f"请安装后重试：{hint}\n"
        f"运行 `check-env` pipeline 可查看所有依赖状态。"
    )


def _convert_with_pandoc(src: Path) -> str:
    if not shutil.which("pandoc"):
        _fail_missing_tool("pandoc", src.suffix)
    result = subprocess.run(
        ["pandoc", "-f", src.suffix.lstrip("."), "-t", "markdown", str(src)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        _fail(f"pandoc 转换失败: {result.stderr.strip()}")
    return result.stdout


def _convert_pdf(src: Path) -> str:
    if not shutil.which("pdftotext"):
        _fail_missing_tool("pdftotext", ".pdf")
    result = subprocess.run(
        ["pdftotext", "-layout", str(src), "-"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        _fail(f"pdftotext 转换失败: {result.stderr.strip()}")
    return result.stdout


def _convert(src: Path) -> str:
    ext = src.suffix.lower()
    if ext in (".md", ".markdown", ".txt"):
        return src.read_text(encoding="utf-8", errors="replace")
    if ext in (".docx", ".doc"):
        return _convert_with_pandoc(src)
    if ext == ".pdf":
        return _convert_pdf(src)
    _fail(
        f"不支持的文件格式: {ext}。"
        f"仅支持: .md / .markdown / .txt / .docx / .doc / .pdf"
    )


def main():
    payload = json.loads(sys.stdin.read())
    inp = payload.get("input", {})

    file_path = (inp.get("file_path", "") or "").strip()
    type_ = (inp.get("type", "") or "proposal").strip().lower()
    title_override = (inp.get("title", "") or "").strip()
    thread = (inp.get("thread", "") or "").strip() or None

    if not file_path:
        _fail("missing required param: file_path")
    if type_ not in ("proposal", "reply"):
        _fail(f"invalid type: {type_!r} (must be 'proposal' or 'reply')")
    if type_ == "reply" and not thread:
        _fail("type=reply requires 'thread'")

    src = Path(file_path).expanduser().resolve()
    if not src.is_file():
        _fail(f"文件不存在: {src}")
    if src.suffix.lower() not in SUPPORTED_EXTS:
        _fail(
            f"不支持的文件格式: {src.suffix}。"
            f"仅支持: {', '.join(sorted(SUPPORTED_EXTS))}"
        )

    content = _convert(src)
    if not content.strip():
        _fail("转换后内容为空，可能文件损坏或无文本内容")

    title = title_override or src.stem

    try:
        draft = save_draft(
            type_=type_,
            title=title,
            content=content,
            thread=thread,
            source=f"file:{src.name}",
        )
    except DraftLimitExceeded as e:
        _fail(str(e))

    count = len(list_drafts())
    sys.stdout.write(json.dumps({
        "output": {
            "draft": draft_to_dict(draft),
            "source_file": src.name,
            "count": count,
            "max_allowed": MAX_DRAFTS_PER_USER,
            "message": f"草稿已从 {src.name} 创建（ID: {draft.draft_id}，{count}/{MAX_DRAFTS_PER_USER}）",
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
