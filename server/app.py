from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.discussions import build_router as build_discussions_router
from server.api.drafts import build_router as build_drafts_router
from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router as build_auth_router
from server.auth.session import SessionStore
from server.config import load_config
from server.db import Database
from server.drafts import DraftRepo
from server.logging_setup import configure_logging
from server.notify import FeishuNotifier, NoOpNotifier, Notifier
from server.users import UserRepo
from server.workspace import Workspace, repo_dir_name


def create_app() -> FastAPI:
    cfg = load_config()
    configure_logging(cfg.log_level)
    log = logging.getLogger("server.app")
    log.info("starting team-pivot-web log_level=%s data_dir=%s", cfg.log_level, cfg.data_dir)

    db = Database(cfg.data_dir / "data.db")
    users = UserRepo(db)
    drafts = DraftRepo(db)
    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    sessions = SessionStore()

    notifier: Notifier
    if cfg.notify_enabled:
        notifier = FeishuNotifier(
            app_id=cfg.feishu_app_id,
            app_secret=cfg.feishu_app_secret,
            web_base_url=cfg.web_dev_origin,
            cache_dir=cfg.data_dir,
        )
        log.info("notifier enabled (feishu)")
    else:
        notifier = NoOpNotifier()
        log.info("notifier disabled (no-op)")

    workspace = Workspace(
        path=cfg.data_dir / "git" / repo_dir_name(cfg.workspace_repo_url),
        repo_url=cfg.workspace_repo_url,
        branch=cfg.workspace_branch,
        token=cfg.git_token,
    )
    workspace.ensure_cloned()
    workspace.recover()

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
    app.include_router(build_discussions_router(workspace, sessions, users, notifier))
    app.include_router(build_drafts_router(workspace, sessions, users, drafts, notifier))
    return app
