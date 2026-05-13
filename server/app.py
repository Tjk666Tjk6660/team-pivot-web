from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.acl_cache import rebuild_acl_cache
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
from server.api.daily_report_v2 import build_router as build_daily_report_v2_router
from server.api.discussions import build_router as build_discussions_router
from server.api.drafts import build_router as build_drafts_router
from server.api.inbox import build_router as build_inbox_router
from server.api.init import build_router as build_init_router
from server.api.matters import build_router as build_matters_router
from server.api.matters_events import build_router as build_matters_events_router
from server.api.markdown_styles import build_router as build_markdown_styles_router
from server.api.preferences import build_router as build_preferences_router
from server.api.tokens import build_router as build_tokens_router
from server.api.users import build_router as build_users_router
from server.api.visibility_options import build_router as build_visibility_options_router
from server.api.workspace import build_router as build_workspace_router
from server.api_tokens import ApiTokenRepo
from server.auth.deps import (
    make_current_user,
    make_current_user_cookie_only,
    make_require_admin_user_cookie,
)
from server.daily_report.job_scheduler import JobScheduler
from server.daily_report.jobs_repo import JobsRepo
from server.daily_report.runs_repo import RunsRepo
from server.auth.feishu_oauth import FeishuOAuth
from server.auth.routes import build_router as build_auth_router
from server.auth.session import SessionStore
from server.config import load_config
from server.db import Database
from server.drafts import DraftRepo
from server.external_bindings import ExternalBindingRepo
from server.feishu_token import FeishuTokenManager
from server.favorites import FavoriteRepo
from server.file_reads import FileReadRepo
from server.git_ops import push as git_push
from server.git_outbox import GitPushOutbox
from server.git_worker import GitWorker
from server.invites import InviteRepo
from server.jobs.runner import JobRunner
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
from server.roles import PivotRoleRepo
from server.user_preferences import UserPreferenceRepo
from server.workspace_config import load_workspace_config, save_workspace_config
from server.workspace_runtime import WorkspaceRuntime


def create_app() -> FastAPI:
    # 读取配置并初始化日志系统。
    # 读取运行配置。
    cfg = load_config()
    # 初始化日志系统。
    configure_logging(cfg.log_level)
    # 获取模块日志对象。
    log = logging.getLogger("server.app")
    # 打印启动信息。
    log.info("starting team-pivot-web log_level=%s data_dir=%s", cfg.log_level, cfg.data_dir)

    # 初始化数据库连接。
    db = Database(cfg.data_dir / "data.db")
    # 用户仓储：负责用户增删改查与状态管理。
    pivot_users = PivotUserRepo(db)
    # 角色仓储：负责角色定义及成员关系管理。
    roles = PivotRoleRepo(db)
    # 外部绑定仓储：管理飞书/邀请/其他外部账号与内部用户的绑定关系。
    bindings = ExternalBindingRepo(db)
    # 加入申请仓储：保存用户申请与审核状态。
    applications = JoinApplicationRepo(db)
    # 邀请仓储：保存和管理邀请链接。
    invites = InviteRepo(db)
    # 草稿仓储：保存未发布内容。
    drafts = DraftRepo(db)
    # 已读状态仓储：记录用户对内容的阅读状态。
    read_states = ReadStateRepo(db)
    # 收藏仓储：记录用户收藏的内容。
    favorites = FavoriteRepo(db)
    # 文件阅读仓储：记录文件级别的已读信息。
    file_reads = FileReadRepo(db)
    # relevance 事件仓储：记录与相关性计算有关的事件。
    relevance_events = RelevanceEventsRepo(db)
    # 用户偏好仓储：保存个人偏好配置。
    user_prefs = UserPreferenceRepo(db)
    # 系统设置仓储：保存工作区与全局配置。
    settings = SettingsRepo(db)
    _migrate_legacy_workspace_env(settings)
    # AI 对话仓储：保存 AI 相关会话和上下文。
    ai_conversations = AIConversationRepo(db)
    # API Token 仓储：管理个人访问令牌。
    api_tokens = ApiTokenRepo(db)

    # 初始化飞书 token 缓存管理器。
    tokens = FeishuTokenManager(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        cache_dir=cfg.data_dir,
    )

    # 初始化飞书 OAuth 客户端。
    oauth = FeishuOAuth(
        app_id=cfg.feishu_app_id,
        app_secret=cfg.feishu_app_secret,
        redirect_uri=cfg.feishu_redirect_uri,
    )
    # 初始化会话存储。
    sessions = SessionStore(db)
    # 初始化显示名称解析器。
    resolver = DisplayResolver(pivot_users, bindings)
    # 启动时清理过期会话。
    purged = sessions.sweep_expired()
    if purged > 0:
        log.info("sessions swept on startup purged=%d", purged)
    # 启动时清理过期 API token。
    expired_tokens = api_tokens.sweep_expired()
    if expired_tokens > 0:
        log.info("expired api tokens purged=%d", expired_tokens)

    # 构建登录态依赖，供接口鉴权和管理员校验使用。
    current_user_dep = make_current_user(sessions, pivot_users, api_tokens)
    # 构建仅基于 Cookie 的当前用户依赖。
    current_user_cookie_dep = make_current_user_cookie_only(sessions, pivot_users)
    # 构建仅基于 Cookie 的管理员依赖。
    admin_user_cookie_dep = make_require_admin_user_cookie(sessions, pivot_users)

    # 初始化工作区运行时，负责本地仓库与索引目录管理。
    workspace = WorkspaceRuntime(base_dir=cfg.data_dir / "git", settings=settings)

    # 方案 A · Write Pipeline：构建 outbox 和 GitWorker，让写入先落本地并异步推送。
    # 之所以在这里组装，而不是塞进 WorkspaceRuntime，是因为 worker 依赖 reload 后才能拿到 repo 路径。
    git_outbox = GitPushOutbox(db)
    # 初始化 Git 推送 worker。
    git_worker = GitWorker(
        outbox=git_outbox,
        push_fn=git_push,
        repo_dir=workspace.path,
    )
    # 将 outbox 和 worker 绑定到工作区。
    workspace.attach_outbox(outbox=git_outbox, worker_notify=git_worker.notify)

    # 方案 C：统一注册后台 Worker，便于在 lifespan 中统一启动/停止。
    # 当前只接入 GitWorker，ScoringWorker 仍保持独立队列模型。
    job_runner = JobRunner()
    job_runner.register(git_worker)

    # 根据配置决定是否启用飞书通知。
    notifier: Notifier
    if cfg.notify_enabled:
        # 初始化飞书通知器。
        notifier = FeishuNotifier(
            tokens=tokens,
            web_base_url=cfg.web_dev_origin,
            workspace=workspace,
        )
        log.info("notifier enabled (feishu)")
    else:
        # 使用空通知器，关闭外部通知副作用。
        notifier = NoOpNotifier()
        log.info("notifier disabled (no-op)")

    # 安装实时 relevance 写入器，监听事件总线并写入 relevance_events。
    # 即使失败也不影响主流程，小时级扫描会兜底。
    install_relevance_writer(
        workspace=workspace, users_repo=pivot_users, bindings=bindings, repo=relevance_events,
    )

    # 初始化评分系统：事件触发 → 队列 → 后台 worker → AI 评估 → matter_scores。
    # 默认关闭，且只允许管理员使用。
    scoring_store = ScoringStore(db)
    # 启动时清理上次异常退出遗留的 running/queued 记录，避免界面卡在运行中。
    swept_runs = scoring_store.sweep_orphans(timeout_seconds=0)
    if swept_runs > 0:
        log.info("scoring orphan runs swept on startup purged=%d", swept_runs)
    # 初始化评分队列。
    scoring_queue = ScoringQueue()
    # 初始化评分 worker。
    scoring_worker = ScoringWorker(
        queue=scoring_queue, store=scoring_store, workspace=workspace,
        settings=settings, pivot_users=pivot_users,
    )
    # 安装评分触发器订阅。
    scoring_unsubscribe = install_scoring_trigger(
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        queue=scoring_queue, store=scoring_store,
    )

    # 构建 MCP 子应用，供外部 AI 客户端通过 HTTP 调用。
    # FastAPI 不会自动把 lifespan 传播给挂载子应用，所以这里由主应用显式接管。
    api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    # 构建 MCP 子应用实例。
    mcp_app = build_mcp_app(api_tokens, pivot_users, api_base_url, cfg.web_dev_origin)

    # 初始化日报任务仓库。
    jobs_repo = JobsRepo(db)
    # 初始化日报执行记录仓库。
    runs_repo = RunsRepo(db)

    # 读取日报相关的开发环境覆盖变量，仅影响日报路径，不影响主业务逻辑。
    dr_index_override = cfg.daily_report_index_dir_override
    dr_users_db = cfg.daily_report_users_db_path

    # 返回日报索引目录；若配置了覆盖路径则优先使用覆盖值。
    def _dr_index_dir() -> Path:
        if dr_index_override is not None:
            return dr_index_override
        return workspace.path / "index"

    if dr_index_override is not None:
        log.info("daily-report index dir overridden: %s", dr_index_override)
    if dr_users_db is not None:
        log.info("daily-report users db overridden: %s (read-only)", dr_users_db)

    # 初始化日报调度器。
    daily_report_scheduler = JobScheduler(
        db_path=cfg.data_dir / "data.db",
        workspace_index_dir_provider=_dr_index_dir,
        jobs_repo=jobs_repo,
        runs_repo=runs_repo,
        settings=settings,
        notifier=notifier,
        users_db_path=dr_users_db,
        web_base_url=cfg.web_dev_origin,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await daily_report_scheduler.start()
        await scoring_worker.start()
        # Start every WorkerTask-style worker through JobRunner. Currently
        # holds GitWorker only; future image / batch workers register at
        # construction time and lifespan picks them up automatically.
        await job_runner.start_all()

        if workspace.configured():
            try:
                rebuild_acl_cache(
                    db,
                    index_dir=workspace.index_dir,
                    categories_dir=workspace.path / "categories",
                )
            except Exception:
                log.exception("startup acl cache rebuild failed")

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
                users_repo=pivot_users,
                bindings=bindings,
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
            workspace=workspace, users_repo=pivot_users, bindings=bindings, repo=relevance_events,
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
            # Stop JobRunner-managed workers BEFORE scoring/daily-report so
            # any in-flight push has a chance to ack its outbox row. The
            # ordering only matters for clean shutdown logs (correctness is
            # preserved by the outbox + crash-recovery sweep on next boot).
            await job_runner.stop_all()
            await scoring_worker.stop()
            scoring_unsubscribe()
            await daily_report_scheduler.stop()

    app = FastAPI(title="team-pivot-web", lifespan=lifespan)
    # 配置跨域中间件，允许前端站点跨域访问后端接口。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_dev_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 挂载飞书登录相关路由，处理 OAuth 入口、回调、当前用户与退出。
    app.include_router(
        build_auth_router(
            oauth, sessions, pivot_users, bindings, applications, notifier,
            cfg.session_secret,
            invites=invites,
            post_login_redirect=cfg.web_dev_origin + "/",
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    # 挂载首次初始化路由，用于创建系统第一个管理员账号。
    app.include_router(
        build_init_router(
            pivot_users, bindings, sessions,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    # 挂载邮箱密码登录路由，供非飞书登录场景使用。
    app.include_router(
        build_email_login_router(
            pivot_users, bindings, sessions,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    # 挂载邀请链路路由，用于处理邀请页、邀请确认和状态流转。
    app.include_router(
        build_invite_router(
            invites,
            feishu_oauth=oauth,
            state_secret=cfg.session_secret,
            secure_cookie=cfg.feishu_redirect_uri.startswith("https://"),
        )
    )
    # 挂载讨论/帖子相关路由。
    app.include_router(build_discussions_router(
        workspace, pivot_users, bindings, notifier, read_states, favorites,
        resolver, current_user_dep,
    ))
    # 事件流路由必须先注册，避免被 matters 的动态路由误匹配。
    app.include_router(build_matters_events_router(current_user_dep, workspace, db))
    # 挂载 matter 主接口，包括列表、详情、读状态、收藏与可见性。
    app.include_router(build_matters_router(
        workspace, pivot_users, bindings, notifier,
        read_states, favorites, file_reads, relevance_events,
        resolver, current_user_dep, db,
    ))
    # 挂载可见性选项路由，供前端配置 matter/线程可见范围。
    app.include_router(build_visibility_options_router(
        pivot_users,
        roles,
        categories_dir=workspace.path / "categories",
        current_user=current_user_dep,
    ))
    # 挂载个人偏好设置路由。
    app.include_router(build_preferences_router(user_prefs, current_user_dep))
    # 挂载工作区状态、刷新与管理配置路由。
    app.include_router(build_workspace_router(
        workspace, settings, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    # 挂载日报任务管理路由。
    app.include_router(build_daily_report_v2_router(
        workspace=workspace,
        settings=settings,
        notifier=notifier,
        db_path=cfg.data_dir / "data.db",
        jobs_repo=jobs_repo,
        runs_repo=runs_repo,
        current_user_cookie_only=current_user_cookie_dep,
        admin_dep=admin_user_cookie_dep,
        index_dir_provider=_dr_index_dir,
        users_db_path=dr_users_db,
        web_base_url=cfg.web_dev_origin,
    ))
    # 挂载草稿相关路由。
    app.include_router(build_drafts_router(
        workspace, drafts, pivot_users, bindings, notifier, current_user_dep,
    ))
    # 挂载收件箱路由。
    app.include_router(build_inbox_router(
        workspace, read_states, resolver, current_user_dep,
    ))
    # 挂载联系人路由。
    app.include_router(build_contacts_router(pivot_users, current_user_dep))
    # 挂载用户查询路由。
    app.include_router(build_users_router(pivot_users, current_user_dep))
    # 挂载 AI 配置、会话与对话接口。
    app.include_router(build_ai_router(
        workspace, settings, ai_conversations, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep, db,
    ))
    # 挂载首页数据路由。
    app.include_router(build_app_home_router(workspace, current_user_dep))
    # 挂载 Markdown 样式配置路由。
    app.include_router(build_markdown_styles_router(
        settings, user_prefs, current_user_dep, current_user_cookie_dep,
        admin_user_cookie_dep,
    ))
    # 挂载个人访问令牌管理路由。
    app.include_router(build_tokens_router(api_tokens, current_user_cookie_dep))
    # 挂载管理员申请审核路由。
    app.include_router(
        build_admin_applications_router(
            applications, pivot_users, bindings, notifier, admin_user_cookie_dep,
            invites=invites,
        )
    )
    # 挂载管理员用户与角色管理路由。
    app.include_router(
        build_admin_users_router(pivot_users, bindings, roles, admin_user_cookie_dep)
    )
    # 挂载管理员邀请管理路由。
    app.include_router(
        build_admin_invites_router(invites, admin_user_cookie_dep)
    )
    # 挂载管理员评分系统路由。
    app.include_router(build_admin_scoring_router(
        store=scoring_store, queue=scoring_queue,
        workspace=workspace, settings=settings, pivot_users=pivot_users,
        admin_user_dep=admin_user_cookie_dep,
    ))

    # 挂载 MCP 子应用，为外部 AI 客户端提供 Streamable HTTP 入口。
    # 该子应用的 PAT 鉴权在子应用内部完成。
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
