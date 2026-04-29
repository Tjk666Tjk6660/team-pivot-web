from __future__ import annotations

from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.pivot_users import PivotUser
from server.settings import SettingsRepo
from server.users import User
from server.workspace_config import (
    WorkspaceConfigDraft,
    load_workspace_draft,
    save_workspace_config,
)
from server.workspace_runtime import WorkspaceRuntime


class WorkspaceConfigBody(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)
    visibility: Literal["public", "private"]
    write_token: str = Field(min_length=1, max_length=500)
    readonly_token: str = Field(default="", max_length=500)


def build_router(
    workspace: WorkspaceRuntime,
    settings: SettingsRepo,
    current_user: Callable,
    current_user_cookie_only: Callable,
    admin_user_cookie_only: Callable,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/workspace/status")
    def status(_: User = Depends(current_user)):
        return {
            "ready": workspace.is_cloned(),
            "path": str(workspace.path),
            "head": workspace.head(),
        }

    @router.post("/workspace/refresh")
    def refresh(_: User = Depends(current_user)):
        workspace.refresh()
        return {"ok": True, "head": workspace.head()}

    @router.get("/workspace/mirror")
    def mirror(_: User = Depends(current_user)):
        return workspace.mirror_payload()

    @router.get("/admin/workspace-config")
    def get_workspace_config(_: PivotUser = Depends(admin_user_cookie_only)):
        draft: WorkspaceConfigDraft = load_workspace_draft(settings)
        return {
            "repo_url": draft.repo_url,
            "visibility": draft.visibility,
            "write_token": draft.write_token,
            "readonly_token": draft.readonly_token,
            "branch": "main",
        }

    @router.put("/admin/workspace-config")
    def update_workspace_config(
        body: WorkspaceConfigBody,
        _: PivotUser = Depends(admin_user_cookie_only),
    ):
        try:
            cfg = save_workspace_config(
                settings,
                repo_url=body.repo_url,
                visibility=body.visibility,
                write_token=body.write_token,
                readonly_token=body.readonly_token,
            )
            workspace.reload()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "ok": True,
            "repo_url": cfg.repo_url,
            "visibility": cfg.visibility,
            "branch": cfg.branch,
        }

    return router
