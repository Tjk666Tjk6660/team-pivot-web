from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from server.settings import SettingsRepo
from server.workspace import Workspace
from server.workspace_config import (
    WorkspaceConfig,
    load_workspace_config,
    load_workspace_draft,
)

log = logging.getLogger("server.workspace_runtime")


class WorkspaceRuntime:
    def __init__(self, *, base_dir: Path, settings: SettingsRepo) -> None:
        self._base_dir = Path(base_dir)
        self._settings = settings
        self._workspace: Workspace | None = None
        self._config: WorkspaceConfig | None = None
        self.reload()

    @property
    def path(self) -> Path:
        if self._workspace is not None:
            return self._workspace.path
        draft = load_workspace_draft(self._settings)
        if draft.repo_url.strip():
            return self._base_dir / Path(draft.repo_url.rstrip("/").rsplit("/", 1)[-1]).stem
        return self._base_dir / "workspace"

    @property
    def discussions_dir(self) -> Path:
        return self._require().discussions_dir

    @property
    def index_dir(self) -> Path:
        return self._require().index_dir

    def configured(self) -> bool:
        return self._config is not None

    def is_cloned(self) -> bool:
        return self._workspace is not None and self._workspace.is_cloned()

    def head(self) -> str | None:
        if self._workspace is None:
            return None
        return self._workspace.head()

    def refresh(self) -> None:
        self._require().refresh()

    def write_session(self, **kwargs):
        return self._require().write_session(**kwargs)

    def reload(self) -> None:
        cfg = load_workspace_config(self._settings)
        if cfg is None:
            self._config = None
            self._workspace = None
            log.info("workspace runtime not configured yet")
            return

        workspace = Workspace(
            path=self._base_dir / cfg.repo_name,
            repo_url=cfg.repo_url,
            branch=cfg.branch,
            token=cfg.write_token,
        )
        try:
            workspace.ensure_cloned()
            workspace.recover()
        except Exception:
            if workspace.is_cloned():
                log.exception(
                    "workspace startup refresh failed; continuing with existing local clone path=%s",
                    workspace.path,
                )
            else:
                raise
        self._config = cfg
        self._workspace = workspace
        log.info("workspace runtime ready repo=%s path=%s", cfg.repo_url, workspace.path)

    def mirror_payload(self) -> dict:
        cfg = self._config
        if cfg is None:
            raise HTTPException(status_code=503, detail="workspace_not_configured")
        return {
            "repo_url": cfg.repo_url,
            "visibility": cfg.visibility,
            "branch": cfg.branch,
            "repo_name": cfg.repo_name,
            "provider": cfg.provider,
            "readonly": True,
            "git_username": cfg.git_username,
            "git_token": cfg.git_token,
            "head": self.head(),
        }

    def _require(self) -> Workspace:
        if self._workspace is None:
            raise HTTPException(status_code=503, detail="workspace_not_configured")
        return self._workspace
