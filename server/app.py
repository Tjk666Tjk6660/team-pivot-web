from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.ai import build_router as build_ai_router
from server.api.contacts import build_router as build_contacts_router
from server.api.discussions import build_router as build_discussions_router
from server.api.drafts import build_router as build_drafts_router
from server.api.inbox import build_router as build_inbox_router
from server.api.tokens import build_router as build_tokens_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import make_current_user, make_current_user_cookie_only
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
from server.ai_conversations import AIConversationRepo
from server.read_state import ReadStateRepo
from server.settings import SettingsRepo
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
    settings = SettingsRepo(db)
    ai_conversations = AIConversationRepo(db)
    api_tokens = ApiTokenRepo(db)

    tokens = FeishuTokenManager(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        cache_dir=cfg.data_dir,
    )
    syncer = FeishuContactSyncer(contacts=contacts, tenant_token_getter=tokens.get)

    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    sessions = SessionStore(db)
    purged = sessions.sweep_expired()
    if purged > 0:
        log.info("sessions swept on startup purged=%d", purged)
    expired_tokens = api_tokens.sweep_expired()
    if expired_tokens > 0:
        log.info("expired api tokens purged=%d", expired_tokens)

    current_user_dep = make_current_user(sessions, users, api_tokens)
    current_user_cookie_dep = make_current_user_cookie_only(sessions, users)

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
            contacts,
            cfg.session_secret,
            post_login_redirect=cfg.web_dev_origin + "/",
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    app.include_router(build_discussions_router(
        workspace, users, contacts, notifier, read_states, current_user_dep,
    ))
    app.include_router(build_drafts_router(
        workspace, drafts, contacts, notifier, current_user_dep,
    ))
    app.include_router(build_inbox_router(
        workspace, users, read_states, current_user_dep,
    ))
    app.include_router(build_contacts_router(
        sessions, contacts, syncer, current_user_dep, current_user_cookie_dep,
    ))
    app.include_router(build_ai_router(
        workspace, settings, ai_conversations, current_user_dep, current_user_cookie_dep,
    ))
    app.include_router(build_tokens_router(api_tokens, current_user_cookie_dep))
    return app
