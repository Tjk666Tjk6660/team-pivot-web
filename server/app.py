from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router
from server.auth.session import SessionStore
from server.config import load_config


def create_app() -> FastAPI:
    cfg = load_config()
    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    sessions = SessionStore()

    app = FastAPI(title="team-pivot-web")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_dev_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        build_router(
            oauth,
            sessions,
            cfg.session_secret,
            post_login_redirect=cfg.web_dev_origin + "/",
        )
    )
    return app
