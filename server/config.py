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
    workspace_repo_url: str
    workspace_branch: str
    git_token: str | None
    log_level: str


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
        workspace_repo_url=_require("WORKSPACE_REPO_URL"),
        workspace_branch=os.getenv("WORKSPACE_BRANCH", "main"),
        git_token=os.getenv("GIT_TOKEN") or None,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _require(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"missing env var: {key}")
    return v
