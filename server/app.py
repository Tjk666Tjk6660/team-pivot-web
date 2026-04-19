from __future__ import annotations

import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.contacts import build_router as build_contacts_router
from server.api.discussions import build_router as build_discussions_router
from server.api.drafts import build_router as build_drafts_router
from server.api.inbox import build_router as build_inbox_router
from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router as build_auth_router
from server.auth.session import SessionStore
from server.config import load_config
from server.contacts import ContactRepo
from server.db import Database
from server.drafts import DraftRepo
from server.feishu_contacts import FeishuContactSyncer
from server.feishu_token import FeishuTokenManager
from server.logging_setup import configure_logging
from server.notify import FeishuNotifier, NoOpNotifier, Notifier
from server.read_state import ReadStateRepo
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
    read_states = ReadStateRepo(db)
    contacts = ContactRepo(db)

    tokens = FeishuTokenManager(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        cache_dir=cfg.data_dir,
    )
    syncer = FeishuContactSyncer(token_getter=tokens.get, contacts=contacts)

    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    sessions = SessionStore(db)
    purged = sessions.sweep_expired()
    if purged > 0:
        log.info("sessions swept on startup purged=%d", purged)

    notifier: Notifier
    if cfg.notify_enabled:
        notifier = FeishuNotifier(tokens=tokens, web_base_url=cfg.web_dev_origin)
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

    def _bg_sync_contacts() -> None:
        try:
            n = syncer.sync()
            log.info("initial contact sync done count=%d", n)
        except Exception:
            log.warning("initial contact sync failed (manual sync button still available)", exc_info=True)

    threading.Thread(target=_bg_sync_contacts, daemon=True).start()

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
    app.include_router(build_discussions_router(workspace, sessions, users, contacts, notifier))
    app.include_router(build_drafts_router(workspace, sessions, users, drafts, contacts, notifier))
    app.include_router(build_inbox_router(workspace, sessions, users, read_states))
    app.include_router(build_contacts_router(sessions, users, contacts, syncer))
    return app
