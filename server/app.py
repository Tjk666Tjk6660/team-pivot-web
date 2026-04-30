from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.admin_applications import (
    build_router as build_admin_applications_router,
)
from server.api.admin_invites import build_router as build_admin_invites_router
from server.api.admin_scoring import build_router as build_admin_scoring_router
from server.api.admin_users import build_router as build_admin_users_router
from server.api.ai import build_router as build_ai_router
from server.api.app_home import build_router as build_app_home_router
from server.api.auth_email_password import build_router as build_email_login_router
from server.api.auth_invite import build_router as build_invite_router
from server.api.contacts import build_router as build_contacts_router
from server.api.daily_report import build_router as build_daily_report_router
from server.api.discussions import build_router as build_discussions_router
from server.api.drafts import build_router as build_drafts_router
from server.api.inbox import build_router as build_inbox_router
from server.api.init import build_router as build_init_router
from server.api.matters import build_router as build_matters_router
from server.api.matters_events import build_router as build_matters_events_router
from server.api.markdown_styles import build_router as build_markdown_styles_router
from server.api.preferences import build_router as build_preferences_router
from server.api.tokens import build_router as build_tokens_router
from server.api.workspace import build_router as build_workspace_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user_cookie,
)
from server.daily_report.scheduler import DailyReportScheduler
from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router as build_auth_router
from server.auth.session import SessionStore
from server.config import load_config
from server.contacts import ContactRepo
from server.db import Database
from server.drafts import DraftRepo
from server.external_bindings import ExternalBindingRepo
from server.feishu_contacts import FeishuContactSyncer
from server.feishu_token import FeishuTokenManager
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo
from server.invites import InviteRepo
from server.join_applications import JoinApplicationRepo
from server.logging_setup import configure_logging
from server.mcp.server import build_mcp_app
from server.mentions import DisplayResolver
from server.notify import FeishuNotifier, NoOpNotifier, Notifier
from server.ai_conversations import AIConversationRepo
from server.pivot_users import PivotUserRepo
from server.read_state import ReadStateRepo
from server.relevance_events import RelevanceEventsRepo
from server.relevance_scanner import (
    get_scan_interval_minutes,
    scan_all as scan_relevance_all,
    schedule_hourly_scan,
)
from server.relevance_writer import install as install_relevance_writer
from server.scoring.store import ScoringStore
from server.scoring.trigger import install as install_scoring_trigger
from server.scoring.worker import ScoringQueue, ScoringWorker
from server.settings import SettingsRepo
from server.user_preferences import UserPreferenceRepo
from server.users import UserRepo
from server.workspace_config import load_workspace_config, save_workspace_config
from server.workspace_runtime import WorkspaceRuntime


def create_app() -> FastAPI:
    cfg = load_config()
    configure_logging(cfg.log_level)
    log = logging.getLogger("server.app")
    log.info("starting team-pivot-web log_level=%s data_dir=%s", cfg.log_level, cfg.data_dir)

    db = Database(cfg.data_dir / "data.db")
    users = UserRepo(db)
    pivot_users = PivotUserRepo(db)
    bindings = ExternalBindingRepo(db)
    applications = JoinApplicationRepo(db)
    invites = InviteRepo(db)
    drafts = DraftRepo(db)
    read_states = ReadStateRepo(db)
    favorites = FavoriteRepo(db)
    file_reads = FileReadRepo(db)
    relevance_events = RelevanceEventsRepo(db)
    user_prefs = UserPreferenceRepo(db)
    contacts = ContactRepo(db)
    settings = SettingsRepo(db)
    _migrate_legacy_workspace_env(settings)
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
    resolver = DisplayResolver(pivot_users, bindings, contacts)
    purged = sessions.sweep_expired()
    if purged > 0:
        log.info("sessions swept on startup purged=%d", purged)
    expired_tokens = api_tokens.sweep_expired()
    if expired_tokens > 0:
        log.info("expired api tokens purged=%d", expired_tokens)

    current_user_dep = make_current_user(sessions, pivot_users, api_tokens)
    current_user_cookie_dep = make_current_user_cookie_only(sessions, pivot_users)
    admin_user_cookie_dep = make_require_admin_user_cookie(sessions, pivot_users)

    workspace = WorkspaceRuntime(base_dir=cfg.data_dir / "git", settings=settings)

    notifier: Notifier
    if cfg.notify_enabled:
        notifier = FeishuNotifier(
            tokens=tokens,
            web_base_url=cfg.web_dev_origin,
            workspace=workspace,
        )
        log.info("notifier enabled (feishu)")
    else:
        notifier = NoOpNotifier()
        log.info("notifier disabled (no-op)")

    # Real-time relevance writer: subscribes to the in-process event bus and
    # writes relevance_events rows on each matter mutation. Failures are
    # swallowed; the hourly scanner is the safety net.
    install_relevance_writer(
        workspace=workspace, users_repo=users, repo=relevance_events,
    )

    # Scoring system: TOPIC_RESULT_CREATED → trigger → ScoringQueue → background
    # worker → AI eval → matter_scores rows. v1 admin-only (decision B);
    # disabled by default (settings 'scoring.enabled' = '0').
    scoring_store = ScoringStore(db)
    swept_runs = scoring_store.sweep_orphans()
    if swept_runs > 0:
        log.info("scoring orphan runs swept on startup purged=%d", swept_runs)
    scoring_queue = ScoringQueue()
    scoring_worker = ScoringWorker(
        queue=scoring_queue, store=scoring_store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )
    scoring_unsubscribe = install_scoring_trigger(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=scoring_queue,
    )

    # Build MCP sub-app once; FastAPI does not propagate lifespan to mounted
    # sub-apps, so we enter its lifespan_context from our own lifespan below.
    # The sub-app enforces PAT bearer auth on every HTTP request using the
    # same ApiTokenRepo / UserRepo as /api/*.
    # api_base_url: where MCP tool handlers loopback to call /api/matters.
    # Stays on 127.0.0.1 even in prod (same uvicorn worker).
    api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    mcp_app = build_mcp_app(api_tokens, users, api_base_url, cfg.web_dev_origin)

    daily_report_scheduler = DailyReportScheduler(
        db_path=cfg.data_dir / "data.db",
        workspace_index_dir_provider=lambda: workspace.path / "index",
        settings=settings,
        notifier=notifier,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await daily_report_scheduler.start()
        await scoring_worker.start()

        # Cold-start vs warm-start is decided by table state, not config:
        # an empty relevance_events table means we've never run before —
        # historical activity should land as already-read so users don't get
        # drowned in retroactive unread badges. A non-empty table means this
        # is a regular restart and any rows the scan turns up are genuine
        # compensation for events the real-time writer missed, so they stay
        # unread.
        cold_start = relevance_events.is_empty()
        log.info(
            "relevance startup backfill entering cold_start=%s",
            cold_start,
        )
        try:
            await asyncio.to_thread(
                scan_relevance_all,
                workspace=workspace,
                users_repo=users,
                repo=relevance_events,
                mark_as_read=cold_start,
            )
        except Exception:
            log.exception("startup relevance scan_all failed")

        scan_interval_seconds = get_scan_interval_minutes() * 60
        log.info(
            "relevance scheduled scan interval=%ds (%dmin)",
            scan_interval_seconds, scan_interval_seconds // 60,
        )
        hourly_task = asyncio.create_task(schedule_hourly_scan(
            workspace=workspace, users_repo=users, repo=relevance_events,
            interval_seconds=scan_interval_seconds,
        ))
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            hourly_task.cancel()
            try:
                await hourly_task
            except (asyncio.CancelledError, Exception):
                pass
            await scoring_worker.stop()
            scoring_unsubscribe()
            await daily_report_scheduler.stop()

    app = FastAPI(title="team-pivot-web", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_dev_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        build_auth_router(
            oauth, sessions, pivot_users, bindings, applications, notifier,
            contacts, cfg.session_secret,
            post_login_redirect=cfg.web_dev_origin + "/",
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    app.include_router(
        build_init_router(
            pivot_users, bindings, sessions,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    app.include_router(
        build_email_login_router(
            pivot_users, bindings, sessions,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    app.include_router(
        build_invite_router(
            invites, pivot_users, bindings, sessions,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    app.include_router(build_discussions_router(
        workspace, users, contacts, notifier, read_states, favorites,
        resolver, current_user_dep,
    ))
    # The events stream MUST be registered before the matters router,
    # otherwise GET /api/matters/{matter_id} matches first and treats
    # "events" as a matter_id (returning 404 matter_not_found).
    app.include_router(build_matters_events_router(current_user_dep))
    app.include_router(build_matters_router(
        workspace, users, contacts, notifier,
        read_states, favorites, file_reads, relevance_events,
        resolver, current_user_dep,
    ))
    app.include_router(build_preferences_router(user_prefs, current_user_dep))
    app.include_router(build_workspace_router(
        workspace, settings, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    app.include_router(build_daily_report_router(
        workspace, settings, notifier,
        cfg.data_dir / "data.db",
        admin_user_cookie_dep,
    ))
    app.include_router(build_drafts_router(
        workspace, drafts, contacts, notifier, current_user_dep,
    ))
    app.include_router(build_inbox_router(
        workspace, users, contacts, read_states, resolver, current_user_dep,
    ))
    app.include_router(build_contacts_router(
        sessions, contacts, syncer, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    app.include_router(build_ai_router(
        workspace, settings, ai_conversations, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    app.include_router(build_app_home_router(workspace, current_user_dep))
    app.include_router(build_markdown_styles_router(
        settings, users, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    app.include_router(build_tokens_router(api_tokens, current_user_cookie_dep))
    app.include_router(
        build_admin_applications_router(
            applications, pivot_users, bindings, notifier, admin_user_cookie_dep,
        )
    )
    app.include_router(
        build_admin_users_router(pivot_users, bindings, admin_user_cookie_dep)
    )
    app.include_router(
        build_admin_invites_router(invites, admin_user_cookie_dep)
    )
    app.include_router(build_admin_scoring_router(
        store=scoring_store, queue=scoring_queue,
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        admin_user_dep=admin_user_cookie_dep,
    ))

    # MCP Streamable HTTP endpoint for external AI clients. PAT auth is
    # enforced inside the sub-app; this file only wires the mount.
    # Lifespan propagation for mcp_app is handled in the `lifespan` above.
    app.mount("/mcp", mcp_app)
    return app


def _migrate_legacy_workspace_env(settings: SettingsRepo) -> None:
    """One-time import path for older deployments that still have workspace config in .env.

    New code treats SQLite settings as the single source of truth. On upgraded servers,
    we opportunistically import the legacy env values if the DB has not been configured yet.
    """
    if load_workspace_config(settings) is not None:
        return

    repo_url = (os.getenv("WORKSPACE_REPO_URL") or "").strip()
    write_token = (os.getenv("GIT_TOKEN") or "").strip()
    if not repo_url or not write_token:
        return

    logging.getLogger("server.app").warning(
        "migrating legacy workspace config from env into SQLite settings"
    )
    save_workspace_config(
        settings,
        repo_url=repo_url,
        visibility="private",
        write_token=write_token,
        # Temporary compatibility fallback for old deployments; admin can replace
        # this with a real read-only token in /admin after startup.
        readonly_token=write_token,
    )
