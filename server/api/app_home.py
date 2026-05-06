from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends

from server.pivot_users import PivotUser
from server.workspace_runtime import WorkspaceRuntime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
HOME_PATH = PROJECT_ROOT / "HOME.md"
CHANGELOG_PATH = PROJECT_ROOT / "CHANGELOG.md"

DEFAULT_HOME_MD = """# 欢迎使用 Pivot

## 它是做什么的
Pivot 是一个以 Markdown 和 Git 为中心的团队讨论工作台。每个讨论主题都可以沉淀想法、行动、验证、洞察和结果。

## 快速开始
1. 点击顶部 `新讨论`，创建一个新的讨论主题。
2. 在讨论里持续追加 `think / act / verify / insight / result` 文件。
3. 通过状态流转标记进度，并用 `result` 收口讨论。
"""

CHANGELOG_HEADER_RE = re.compile(r"^##\s+([^\s]+)\s*-\s*(.+?)\s*$")


@dataclass(frozen=True)
class ReleaseNote:
    version: str
    date: str
    title: str
    body_md: str


def build_router(
    workspace: WorkspaceRuntime,
    current_user: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/app")

    @router.get("/home")
    def get_home(_: PivotUser = Depends(current_user)):
        releases = load_recent_releases()
        return {
            "app": {
                "name": "team-pivot",
                "version": load_app_version(),
                "head": workspace.head(),
            },
            "welcome": {
                "title": "欢迎使用 Pivot",
                "body_md": load_home_markdown(),
            },
            "latest_release": _release_to_dict(releases[0]) if releases else None,
            "recent_releases": [_release_to_dict(r) for r in releases],
        }

    return router


def load_app_version(path: Path | None = None) -> str:
    path = path or PYPROJECT_PATH
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return str(data.get("project", {}).get("version") or "0.0.0")
    except Exception:
        return "0.0.0"


def load_home_markdown(path: Path | None = None) -> str:
    path = path or HOME_PATH
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return DEFAULT_HOME_MD
    return content or DEFAULT_HOME_MD


def load_recent_releases(path: Path | None = None, limit: int = 3) -> list[ReleaseNote]:
    path = path or CHANGELOG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    sections = _split_release_sections(text)
    return [_parse_release(version, date, body) for version, date, body in sections[:limit]]


def _split_release_sections(text: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    current_version: str | None = None
    current_date: str | None = None
    body_lines: list[str] = []

    for line in text.splitlines():
        match = CHANGELOG_HEADER_RE.match(line.strip())
        if match:
            if current_version is not None and current_date is not None:
                sections.append((current_version, current_date, "\n".join(body_lines).strip()))
            current_version = match.group(1).strip()
            current_date = match.group(2).strip()
            body_lines = []
            continue
        if current_version is not None:
            body_lines.append(line)

    if current_version is not None and current_date is not None:
        sections.append((current_version, current_date, "\n".join(body_lines).strip()))
    return sections


def _parse_release(version: str, date: str, body_md: str) -> ReleaseNote:
    lines = body_md.splitlines()
    kept: list[str] = []
    title: str | None = None
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.strip() == "### Title":
            i += 1
            title_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("### "):
                title_lines.append(lines[i])
                i += 1
            title_text = "\n".join(title_lines).strip()
            if title_text:
                title = next((part.strip() for part in title_text.splitlines() if part.strip()), None)
            continue
        kept.append(line)
        i += 1

    final_body = "\n".join(kept).strip()
    return ReleaseNote(
        version=version,
        date=date,
        title=title or f"{version} 更新",
        body_md=final_body,
    )


def _release_to_dict(release: ReleaseNote) -> dict:
    return {
        "version": release.version,
        "date": release.date,
        "title": release.title,
        "body_md": release.body_md,
    }
