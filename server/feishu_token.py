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
        self._app_id = app_id
        self._app_secret = app_secret
        self._cache_path = Path(cache_dir) / f".feishu-token-{_safe(app_id)}.json"
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str:
        with self._lock:
            if self._token and self._expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            self._load_cache()
            if self._token and self._expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            return self._refresh()

    def _refresh(self) -> str:
        resp = httpx.post(
            TOKEN_ENDPOINT,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu token error: {data}")
        self._token = data["tenant_access_token"]
        self._expires_at = time.time() + float(data["expire"])
        self._save_cache()
        log.debug("feishu token refreshed")
        return self._token  # type: ignore[return-value]

    def _load_cache(self) -> None:
        try:
            if not self._cache_path.is_file():
                return
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "token" in data and "expire_at" in data:
                self._token = data["token"]
                self._expires_at = float(data["expire_at"])
        except Exception:
            pass

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"token": self._token, "expire_at": self._expires_at}),
                encoding="utf-8",
            )
            tmp.replace(self._cache_path)
        except Exception:
            log.debug("token cache write failed", exc_info=True)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)
