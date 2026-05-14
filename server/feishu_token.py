from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_REFRESH_THRESHOLD = 300
_TIMEOUT = 10.0


class FeishuTokenManager:
    def __init__(self, *, app_id: str, app_secret: str, cache_dir: Path) -> None:
        # 保存飞书应用凭证，用于后续申请 tenant access token。
        self._app_id = app_id
        self._app_secret = app_secret
        # 基于 app_id 生成本地缓存文件路径，避免不同应用互相覆盖。
        self._cache_path = Path(cache_dir) / f".feishu-token-{_safe(app_id)}.json"
        # 使用互斥锁保证多线程下 token 读取和刷新过程安全。
        self._lock = threading.Lock()
        # 内存中缓存当前 token，减少重复读盘和重复请求。
        self._token: str | None = None
        # 记录 token 的过期时间，便于判断是否需要刷新。
        self._expires_at: float = 0.0

    def get(self) -> str:
        # 对外暴露的获取方法：优先返回未过期的内存 token。
        with self._lock:
            if self._token and self._expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            # 内存不可用时尝试从本地缓存恢复。
            self._load_cache()
            if self._token and self._expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            # 本地缓存也不可用时，主动向飞书刷新 token。
            return self._refresh()

    def _refresh(self) -> str:
        # 调用飞书接口获取新的 tenant access token。
        resp = httpx.post(
            TOKEN_ENDPOINT,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu token error: {data}")
        # 保存新 token 和过期时间到内存中。
        self._token = data["tenant_access_token"]
        self._expires_at = time.time() + float(data["expire"])
        # 刷新成功后同步写入缓存文件，便于下次启动复用。
        self._save_cache()
        log.debug("feishu token refreshed")
        return self._token  # type: ignore[return-value]

    def _load_cache(self) -> None:
        # 尝试从磁盘读取缓存 token，降低启动后首次请求成本。
        try:
            if not self._cache_path.is_file():
                return
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "token" in data and "expire_at" in data:
                self._token = data["token"]
                self._expires_at = float(data["expire_at"])
        except Exception:
            # 缓存损坏或读取失败时忽略，后续会走刷新流程。
            pass

    def _save_cache(self) -> None:
        # 将当前 token 原子写入磁盘缓存，供后续进程复用。
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"token": self._token, "expire_at": self._expires_at}),
                encoding="utf-8",
            )
            tmp.replace(self._cache_path)
        except Exception:
            # 缓存写入失败不影响主流程，只记录调试日志。
            log.debug("token cache write failed", exc_info=True)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)
