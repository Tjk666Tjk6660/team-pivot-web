from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from server.settings import SettingsRepo
from server.workspace import repo_dir_name

KEY_REPO_URL = "workspace.repo_url"
KEY_VISIBILITY = "workspace.visibility"
KEY_WRITE_TOKEN = "workspace.write_token"
KEY_READONLY_TOKEN = "workspace.readonly_token"

VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
VALID_VISIBILITIES = frozenset({VISIBILITY_PUBLIC, VISIBILITY_PRIVATE})
DEFAULT_BRANCH = "main"
DEFAULT_PROVIDER = "github"
DEFAULT_GIT_USERNAME = "x-access-token"


@dataclass(frozen=True)
class WorkspaceConfig:
    repo_url: str
    visibility: str
    write_token: str
    readonly_token: str | None

    @property
    def branch(self) -> str:
        return DEFAULT_BRANCH

    @property
    def provider(self) -> str:
        parsed = urlparse(self.repo_url)
        host = (parsed.hostname or "").lower()
        if "github.com" in host:
            return "github"
        return DEFAULT_PROVIDER

    @property
    def repo_name(self) -> str:
        return repo_dir_name(self.repo_url)

    @property
    def git_username(self) -> str | None:
        if self.visibility == VISIBILITY_PRIVATE:
            return DEFAULT_GIT_USERNAME
        return None

    @property
    def git_token(self) -> str | None:
        if self.visibility == VISIBILITY_PRIVATE:
            return self.readonly_token
        return None


@dataclass(frozen=True)
class WorkspaceConfigDraft:
    repo_url: str = ""
    visibility: str = ""
    write_token: str = ""
    readonly_token: str = ""

    def is_configured(self) -> bool:
        return bool(self.repo_url.strip() and self.visibility in VALID_VISIBILITIES)


def load_workspace_draft(settings: SettingsRepo) -> WorkspaceConfigDraft:
    return WorkspaceConfigDraft(
        repo_url=settings.get(KEY_REPO_URL) or "",
        visibility=settings.get(KEY_VISIBILITY) or "",
        write_token=settings.get(KEY_WRITE_TOKEN) or "",
        readonly_token=settings.get(KEY_READONLY_TOKEN) or "",
    )


def load_workspace_config(settings: SettingsRepo) -> WorkspaceConfig | None:
    draft = load_workspace_draft(settings)
    if not draft.is_configured():
        return None
    return validate_workspace_config(
        repo_url=draft.repo_url,
        visibility=draft.visibility,
        write_token=draft.write_token,
        readonly_token=draft.readonly_token,
    )


def save_workspace_config(
    settings: SettingsRepo,
    *,
    repo_url: str,
    visibility: str,
    write_token: str,
    readonly_token: str,
) -> WorkspaceConfig:
    cfg = validate_workspace_config(
        repo_url=repo_url,
        visibility=visibility,
        write_token=write_token,
        readonly_token=readonly_token,
    )
    settings.set(KEY_REPO_URL, cfg.repo_url)
    settings.set(KEY_VISIBILITY, cfg.visibility)
    settings.set(KEY_WRITE_TOKEN, cfg.write_token)
    settings.set(KEY_READONLY_TOKEN, cfg.readonly_token or "")
    return cfg


def validate_workspace_config(
    *,
    repo_url: str,
    visibility: str,
    write_token: str,
    readonly_token: str,
) -> WorkspaceConfig:
    repo_url = repo_url.strip()
    visibility = visibility.strip().lower()
    write_token = write_token.strip()
    readonly_token = readonly_token.strip()

    if not repo_url:
        raise ValueError("repo_url is required")
    if visibility not in VALID_VISIBILITIES:
        raise ValueError("visibility must be 'public' or 'private'")
    if not write_token:
        raise ValueError("write_token is required")
    if visibility == VISIBILITY_PRIVATE and not readonly_token:
        raise ValueError("readonly_token is required for private repos")

    return WorkspaceConfig(
        repo_url=repo_url,
        visibility=visibility,
        write_token=write_token,
        readonly_token=readonly_token or None,
    )
