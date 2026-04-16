"""Draft file management for team-pivot.

Drafts are stored per-user under the EC user workspace:
  $ENCLAWS_USER_WORKSPACE/skill-team-pivot-drafts/{draft_id}.md

Each draft is a markdown file with YAML frontmatter:
  ---
  draft_id: abc123
  type: proposal          # or "reply"
  category: general
  title: "..."
  thread: "..."           # only when type=reply
  source: text            # or "file:filename.ext"
  created_at: 2026-04-17T01:00:00Z
  ---

  <body content>
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


DRAFT_DIR_NAME = "skill-team-pivot-drafts"

# Business rule: maximum drafts per user (prevent unbounded accumulation).
# Enforced at the pipeline level so all channels (Feishu, WebView, CLI...)
# share the same constraint.
MAX_DRAFTS_PER_USER = 5


class DraftLimitExceeded(Exception):
    """Raised when trying to create a draft beyond MAX_DRAFTS_PER_USER."""
    def __init__(self, current: int, limit: int):
        self.current = current
        self.limit = limit
        super().__init__(
            f"草稿数量已达上限（{current}/{limit}），请先删除不需要的草稿"
        )


def _user_workspace() -> str:
    """Return the EC user workspace path, falling back to env var parents."""
    ws = os.environ.get("ENCLAWS_USER_WORKSPACE", "")
    if not ws:
        raise RuntimeError(
            "ENCLAWS_USER_WORKSPACE environment variable not set. "
            "Drafts require EC to inject the user workspace path."
        )
    return ws


def drafts_dir() -> Path:
    """Return the directory holding the current user's drafts (creates it if needed)."""
    d = Path(_user_workspace()) / DRAFT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_draft_id() -> str:
    """Return a human-readable draft_id with timestamp + sequence number.

    Format: draft-YYYYMMDD-HHMM-{n}
    Example: draft-20260417-0238-1

    The sequence number starts at 1 and increments if a file with the same
    timestamp already exists.
    """
    dd = drafts_dir()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    n = 1
    while True:
        candidate = f"draft-{ts}-{n}"
        if not (dd / f"{candidate}.md").exists():
            return candidate
        n += 1


@dataclass
class Draft:
    draft_id: str
    type: str
    category: str
    title: str
    thread: Optional[str]
    source: str
    created_at: str
    content: str
    file_path: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_draft(
    *,
    type_: str,
    category: str,
    title: str,
    content: str,
    thread: Optional[str] = None,
    source: str = "text",
    draft_id: Optional[str] = None,
) -> Draft:
    """Create or overwrite a draft file. Returns the Draft object.

    Raises DraftLimitExceeded if creating a new draft would exceed MAX_DRAFTS_PER_USER.
    Overwriting an existing draft (draft_id provided) bypasses the limit check.
    """
    if type_ not in ("proposal", "reply"):
        raise ValueError(f"type must be 'proposal' or 'reply', got {type_!r}")
    if type_ == "reply" and not thread:
        raise ValueError("type=reply requires 'thread' to be set")

    # Only enforce limit when creating a NEW draft (draft_id not specified).
    # Editing an existing draft should never fail due to the limit.
    if draft_id is None:
        current = len(list(drafts_dir().glob("*.md")))
        if current >= MAX_DRAFTS_PER_USER:
            raise DraftLimitExceeded(current, MAX_DRAFTS_PER_USER)

    draft_id = draft_id or generate_draft_id()
    frontmatter: dict = {
        "draft_id": draft_id,
        "type": type_,
        "category": category,
        "title": title,
        "source": source,
        "created_at": _now_iso(),
    }
    if thread:
        frontmatter["thread"] = thread

    file_path = drafts_dir() / f"{draft_id}.md"
    body = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + content
    file_path.write_text(body, encoding="utf-8")

    return Draft(
        draft_id=draft_id,
        type=type_,
        category=category,
        title=title,
        thread=thread,
        source=source,
        created_at=frontmatter["created_at"],
        content=content,
        file_path=str(file_path),
    )


def load_draft(draft_id: str) -> Optional[Draft]:
    """Load a draft by id. Returns None if not found or malformed."""
    file_path = drafts_dir() / f"{draft_id}.md"
    if not file_path.is_file():
        return None

    raw = file_path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return None

    # Split frontmatter and body
    end = raw.find("\n---\n", 4)
    if end < 0:
        return None
    fm_text = raw[4:end]
    content = raw[end + 5:].lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None

    return Draft(
        draft_id=str(fm.get("draft_id", draft_id)),
        type=str(fm.get("type", "")),
        category=str(fm.get("category", "")),
        title=str(fm.get("title", "")),
        thread=fm.get("thread"),
        source=str(fm.get("source", "text")),
        created_at=str(fm.get("created_at", "")),
        content=content,
        file_path=str(file_path),
    )


def list_drafts() -> list[Draft]:
    """Return all drafts in the current user's draft dir, sorted by created_at desc."""
    dd = drafts_dir()
    result: list[Draft] = []
    for f in dd.glob("*.md"):
        draft_id = f.stem
        d = load_draft(draft_id)
        if d:
            result.append(d)
    result.sort(key=lambda x: x.created_at, reverse=True)
    return result


def delete_draft(draft_id: str) -> bool:
    """Delete a draft by id. Returns True if deleted, False if not found."""
    file_path = drafts_dir() / f"{draft_id}.md"
    if not file_path.is_file():
        return False
    file_path.unlink()
    return True


def draft_to_dict(d: Draft) -> dict:
    """Convert a Draft to a JSON-serializable dict."""
    return {
        "draft_id": d.draft_id,
        "type": d.type,
        "category": d.category,
        "title": d.title,
        "thread": d.thread,
        "source": d.source,
        "created_at": d.created_at,
        "content": d.content,
    }
