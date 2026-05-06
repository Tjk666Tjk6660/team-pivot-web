from __future__ import annotations

from dataclasses import dataclass

from server.pivot_users import PivotUser
from server.settings import SettingsRepo

DEFAULT_MARKDOWN_STYLE = "code-light"
KEY_MARKDOWN_DEFAULT_STYLE = "markdown.default_style"
KEY_USER_MARKDOWN_STYLE = "markdown_style"


@dataclass(frozen=True)
class MarkdownStyle:
    id: str
    label: str
    description: str
    tone: str


MARKDOWN_STYLES: tuple[MarkdownStyle, ...] = (
    MarkdownStyle(
        id="code-light",
        label="代码白",
        description="接近 GitHub 文档的浅色技术文档风格，代码和表格边界清晰。",
        tone="light",
    ),
    MarkdownStyle(
        id="collab-blue",
        label="协作蓝",
        description="清爽办公文档风格，蓝色标题强调，适合团队协作阅读。",
        tone="light",
    ),
    MarkdownStyle(
        id="page-brown",
        label="书页棕",
        description="偏长文和书页阅读的暖色衬线风格。",
        tone="light",
    ),
    MarkdownStyle(
        id="solarized-light",
        label="护眼浅",
        description="低刺激浅色配色，标题色彩层级明显。",
        tone="light",
    ),
    MarkdownStyle(
        id="neon-dark",
        label="霓虹暗",
        description="高对比暗色技术风格，适合夜间和代码阅读。",
        tone="dark",
    ),
    MarkdownStyle(
        id="nord-dark",
        label="极地暗",
        description="克制冷色暗色主题，适合长时间阅读。",
        tone="dark",
    ),
)

_STYLE_IDS = {style.id for style in MARKDOWN_STYLES}


def is_markdown_style_id(value: str | None) -> bool:
    return value in _STYLE_IDS


def normalize_markdown_style(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if is_markdown_style_id(value) else None


def markdown_style_dict(style: MarkdownStyle) -> dict:
    return {
        "id": style.id,
        "label": style.label,
        "description": style.description,
        "tone": style.tone,
    }


def all_markdown_style_dicts() -> list[dict]:
    return [markdown_style_dict(style) for style in MARKDOWN_STYLES]


def system_default_style(settings: SettingsRepo) -> str | None:
    return normalize_markdown_style(settings.get(KEY_MARKDOWN_DEFAULT_STYLE))


def effective_markdown_style(
    *, user: PivotUser | None = None, user_style: str | None = None, settings: SettingsRepo
) -> str:
    user_style = normalize_markdown_style(
        user_style if user_style is not None else (user.markdown_style if user else None)
    )
    if user_style:
        return user_style
    return system_default_style(settings) or DEFAULT_MARKDOWN_STYLE
