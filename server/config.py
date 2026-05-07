from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    feishu_app_id: str
    feishu_app_secret: str
    feishu_redirect_uri: str
    session_secret: str
    web_dev_origin: str
    data_dir: Path
    log_level: str
    notify_enabled: bool

    # ─── Dev-time daily report overrides ───────────────────────────────
    # 仅影响日报路径(scheduler 定时跑 + UI 手动触发);其他业务路径无关。
    # 用于本地预览生产数据日报但绝不写入生产仓库 / 用户表。
    daily_report_index_dir_override: Path | None
    """如果设置,日报模块改用此目录读 matter index,而不用 workspace.path/index。
    用于:本地启动时让日报跑生产数据快照(克隆好的本地副本),其余业务仍用
    /admin 配置的 dev workspace。"""

    daily_report_users_db_path: Path | None
    """如果设置,日报模块通过 mode=ro 只读打开此 SQLite 取 users(personal 视角
    的全员列表),AI 配置仍走主 data.db。用于:本地启动时让 personal 报告
    覆盖真实生产团队成员,但绝不写入快照库。"""


def load_config(env_file: str | Path | None = None) -> Config:
    project_root = Path(__file__).resolve().parent.parent
    if env_file is None:
        env_file = project_root / ".env"
    load_dotenv(env_file, override=False)
    return Config(
        feishu_app_id=_require("FEISHU_APP_ID"),
        feishu_app_secret=_require("FEISHU_APP_SECRET"),
        feishu_redirect_uri=_require("FEISHU_REDIRECT_URI"),
        session_secret=_require("SESSION_SECRET"),
        web_dev_origin=os.getenv("WEB_DEV_ORIGIN", "http://localhost:5173"),
        data_dir=Path(os.getenv("DATA_DIR", project_root / "var")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        notify_enabled=os.getenv("NOTIFY_ENABLED", "true").lower() == "true",
        daily_report_index_dir_override=_optional_path("DAILY_REPORT_INDEX_DIR_OVERRIDE"),
        daily_report_users_db_path=_optional_path("DAILY_REPORT_USERS_DB_PATH"),
    )


def _optional_path(key: str) -> Path | None:
    v = (os.getenv(key) or "").strip()
    return Path(v) if v else None


def _require(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"missing env var: {key}")
    return v
