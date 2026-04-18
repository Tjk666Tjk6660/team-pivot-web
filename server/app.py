from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.discussions import build_router as build_api_router
from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router as build_auth_router
from server.auth.session import SessionStore
from server.config import load_config
from server.db import Database
from server.users import UserRepo
from server.workspace import Workspace, repo_dir_name


def create_app() -> FastAPI:
    cfg = load_config()

    db = Database(cfg.data_dir / "data.db")
    users = UserRepo(db)
    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    sessions = SessionStore()

    workspace = Workspace(
        path=cfg.data_dir / "git" / repo_dir_name(cfg.workspace_repo_url),
        repo_url=cfg.workspace_repo_url,
        branch=cfg.workspace_branch,
        token=cfg.git_token,
    )
    workspace.ensure_cloned()

    app = FastAPI(title="team-pivot-web")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_dev_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        build_auth_router(
            oauth,
            sessions,
            users,
            cfg.session_secret,
            post_login_redirect=cfg.web_dev_origin + "/",
        )
    )
    app.include_router(build_api_router(workspace, sessions, users))
    return app
