"""Feishu tenant_access_token 管理：获取 / 缓存 / 过期刷新。

按 app_id 分文件缓存（$PIVOT_DATA_DIR/.feishu-token-{app_id}.json），
支持同租户多机器人绑定不同飞书应用场景。

ENV vars:
  FEISHU_APP_ID      — 飞书应用 ID（EC 注入）
  FEISHU_APP_SECRET  — 飞书应用密钥（EC 注入）
  PIVOT_DATA_DIR     — 数据目录（Runner 注入），缓存文件放此目录

Flow:
  1. get_tenant_access_token() 检查缓存文件
  2. 剩余有效期 > 5 分钟 → 直接返回缓存 token
  3. 否则调飞书 /auth/v3/tenant_access_token/internal 换新 token
  4. 原子写入缓存（先写 .tmp 再 os.replace）

并发：无锁。多进程同时刷新时"最后写入者胜"，飞书不会立即失效旧 token，
race condition 最坏后果是多几次 API 调用。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests


class FeishuTokenError(Exception):
    """飞书 token 获取失败（凭证缺失、API 错误、网络错误）。"""


_CACHE_FILENAME_TEMPLATE = ".feishu-token-{app_id}.json"
_REFRESH_THRESHOLD_SECONDS = 300  # 剩余 5 分钟内触发刷新
_TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_REQUEST_TIMEOUT = 10


def get_tenant_access_token() -> str:
    """返回有效 tenant_access_token，自动处理缓存和过期刷新。

    Raises:
        FeishuTokenError: 凭证缺失或飞书 API 调用失败
    """
    app_id, app_secret = _load_credentials()
    cached = _load_cache(app_id)
    if cached and cached["expire_at"] - time.time() > _REFRESH_THRESHOLD_SECONDS:
        return cached["token"]
    return _fetch_and_cache(app_id, app_secret)


def _load_credentials() -> tuple[str, str]:
    """读取 FEISHU_APP_ID / FEISHU_APP_SECRET，缺失抛异常。"""
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise FeishuTokenError("FEISHU_APP_ID or FEISHU_APP_SECRET not set")
    return app_id, app_secret


def _load_cache(app_id: str) -> dict | None:
    """读缓存文件，失败返回 None（不抛异常）。"""
    path = _cache_path(app_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "token" in data and "expire_at" in data:
            return data
    except Exception:
        pass
    return None


def _fetch_and_cache(app_id: str, app_secret: str) -> str:
    """调飞书 API 换新 token，原子写入缓存。"""
    try:
        resp = requests.post(
            _TOKEN_ENDPOINT,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=_REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise FeishuTokenError(f"Feishu token request failed: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise FeishuTokenError(f"Feishu token response not JSON: {resp.text[:200]}") from e

    if data.get("code") != 0:
        raise FeishuTokenError(f"Feishu API error: {data}")

    token = data.get("tenant_access_token")
    expire = data.get("expire")
    if not token or not isinstance(expire, (int, float)):
        raise FeishuTokenError(f"Feishu token response malformed: {data}")

    expire_at = time.time() + expire
    _save_cache(app_id, {"token": token, "expire_at": expire_at})
    return token


def _save_cache(app_id: str, payload: dict) -> None:
    """原子写入：先写 .tmp 再 os.replace。写入失败不抛异常。"""
    path = _cache_path(app_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _cache_path(app_id: str) -> Path:
    """返回按 app_id 隔离的缓存文件路径。"""
    data_dir = os.environ.get("PIVOT_DATA_DIR", "")
    if not data_dir:
        # fallback：PIVOT_DATA_DIR 未注入时（单测或未走 Runner），用临时目录
        data_dir = tempfile.gettempdir()
    # 安全保险：app_id 含非法字符时替换为下划线，避免路径逃逸
    safe_app_id = re.sub(r"[^A-Za-z0-9_-]", "_", app_id)
    return Path(data_dir) / _CACHE_FILENAME_TEMPLATE.format(app_id=safe_app_id)
