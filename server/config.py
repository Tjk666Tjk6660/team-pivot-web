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


def load_config(env_file: str | Path | None = None) -> Config:
    if env_file is None:
        env_file = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_file, override=False)
    return Config(
        feishu_app_id=_require("FEISHU_APP_ID"),
        feishu_app_secret=_require("FEISHU_APP_SECRET"),
        feishu_redirect_uri=_require("FEISHU_REDIRECT_URI"),
        session_secret=_require("SESSION_SECRET"),
        web_dev_origin=os.getenv("WEB_DEV_ORIGIN", "http://localhost:5173"),
    )


def _require(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"missing env var: {key}")
    return v
