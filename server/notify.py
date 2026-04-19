from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

_TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_LIST_CHATS_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/chats"
_SEND_MESSAGE_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/messages"
_REFRESH_THRESHOLD = 300
_TIMEOUT = 10.0


class Notifier(Protocol):
    def notify_new_thread(
        self,
        *,
        category: str,
        slug: str,
        title: str,
        author_name: str,
        body: str,
    ) -> None: ...

    def notify_new_reply(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        author_name: str,
        body: str,
    ) -> None: ...

    def notify_status_change(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        from_state: str,
        to_state: str,
        author_name: str,
        reason: str | None,
    ) -> None: ...


class NoOpNotifier:
    def notify_new_thread(self, **_: object) -> None:
        log.debug("notify disabled: new_thread suppressed")

    def notify_new_reply(self, **_: object) -> None:
        log.debug("notify disabled: new_reply suppressed")

    def notify_status_change(self, **_: object) -> None:
        log.debug("notify disabled: status_change suppressed")


class FeishuNotifier:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        web_base_url: str,
        cache_dir: Path,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._web_base_url = web_base_url.rstrip("/")
        self._cache_path = Path(cache_dir) / f".feishu-token-{_safe(app_id)}.json"
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def notify_new_thread(
        self, *, category: str, slug: str, title: str, author_name: str, body: str,
    ) -> None:
        card = build_thread_card(
            title=title,
            author_name=author_name,
            body=body,
            thread_url=self._thread_url(category, slug),
        )
        self._broadcast(card, event=f"new_thread slug={slug}")

    def notify_new_reply(
        self, *, category: str, slug: str, thread_title: str, author_name: str, body: str,
    ) -> None:
        card = build_reply_card(
            thread_title=thread_title,
            author_name=author_name,
            body=body,
            thread_url=self._thread_url(category, slug),
        )
        self._broadcast(card, event=f"new_reply slug={slug}")

    def notify_status_change(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        from_state: str,
        to_state: str,
        author_name: str,
        reason: str | None,
    ) -> None:
        card = build_status_change_card(
            thread_title=thread_title,
            author_name=author_name,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            thread_url=self._thread_url(category, slug),
        )
        self._broadcast(card, event=f"status_change slug={slug} {from_state}->{to_state}")

    def _thread_url(self, category: str, slug: str) -> str:
        from urllib.parse import quote
        return f"{self._web_base_url}/t/{quote(category)}/{quote(slug)}"

    def _broadcast(self, card: dict, *, event: str) -> None:
        try:
            token = self._get_token()
            chats = self._list_chats(token)
            if not chats:
                log.warning("notify skipped (bot is not in any chats): %s", event)
                return
            sent = 0
            for chat_id in chats:
                if self._send_card(token, chat_id, card):
                    sent += 1
            log.info("notify sent to %d/%d chats: %s", sent, len(chats), event)
        except Exception:
            log.warning("notify failed: %s", event, exc_info=True)

    def _get_token(self) -> str:
        with self._lock:
            if self._token and self._token_expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            self._load_cache()
            if self._token and self._token_expires_at - time.time() > _REFRESH_THRESHOLD:
                return self._token
            return self._refresh_token()

    def _load_cache(self) -> None:
        try:
            if not self._cache_path.is_file():
                return
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "token" in data and "expire_at" in data:
                self._token = data["token"]
                self._token_expires_at = float(data["expire_at"])
        except Exception:
            pass

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"token": self._token, "expire_at": self._token_expires_at}),
                encoding="utf-8",
            )
            tmp.replace(self._cache_path)
        except Exception:
            log.debug("notify token cache write failed", exc_info=True)

    def _refresh_token(self) -> str:
        resp = httpx.post(
            _TOKEN_ENDPOINT,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu token API error: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires_at = time.time() + float(data["expire"])
        self._save_cache()
        log.debug("notify token refreshed expires_in=%ss", int(data["expire"]))
        return self._token  # type: ignore[return-value]

    def _list_chats(self, token: str) -> list[str]:
        chats: list[str] = []
        page_token = ""
        while True:
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = httpx.get(
                _LIST_CHATS_ENDPOINT,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"feishu list chats error: {data}")
            items = data.get("data", {}).get("items", [])
            for item in items:
                cid = item.get("chat_id")
                if cid:
                    chats.append(cid)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
            if not page_token:
                break
        return chats

    def _send_card(self, token: str, chat_id: str, card: dict) -> bool:
        try:
            resp = httpx.post(
                _SEND_MESSAGE_ENDPOINT,
                params={"receive_id_type": "chat_id"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                log.warning("notify send non-200 chat=%s status=%d", chat_id, resp.status_code)
                return False
            data = resp.json()
            if data.get("code") != 0:
                log.warning("notify send error chat=%s code=%s msg=%s",
                            chat_id, data.get("code"), data.get("msg"))
                return False
            return True
        except Exception:
            log.warning("notify send exception chat=%s", chat_id, exc_info=True)
            return False


def build_thread_card(
    *, title: str, author_name: str, body: str, thread_url: str,
) -> dict:
    return _build_card(
        header=f"新讨论：{title}",
        template="blue",
        author_name=author_name,
        body=body,
        button_text="去 Web 查看",
        thread_url=thread_url,
    )


def build_reply_card(
    *, thread_title: str, author_name: str, body: str, thread_url: str,
) -> dict:
    return _build_card(
        header=f"新回复：{thread_title}",
        template="green",
        author_name=author_name,
        body=body,
        button_text="查看讨论",
        thread_url=thread_url,
    )


_STATUS_LABEL = {
    "open": "讨论中",
    "concluded": "已达成结论",
    "produced": "已转为项目",
    "closed": "已关闭",
    "pending": "暂时搁置",
}


def build_status_change_card(
    *,
    thread_title: str,
    author_name: str,
    from_state: str,
    to_state: str,
    reason: str | None,
    thread_url: str,
) -> dict:
    from_label = _STATUS_LABEL.get(from_state, from_state)
    to_label = _STATUS_LABEL.get(to_state, to_state)
    md_parts = [
        f"**操作**：{author_name}",
        f"**状态**：{from_label} → {to_label}",
    ]
    if reason:
        md_parts.append(f"**原因**：{reason}")
    md = "\n\n".join(md_parts)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"状态变更：{thread_title}"},
            "template": "purple",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": md},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看讨论"},
                    "type": "primary",
                    "multi_url": {"url": thread_url, "pc_url": "", "android_url": "", "ios_url": ""},
                },
            ],
        },
    }


def _build_card(
    *,
    header: str,
    template: str,
    author_name: str,
    body: str,
    button_text: str,
    thread_url: str,
) -> dict:
    summary = _truncate(body, 200)
    md = f"**作者**：{author_name}\n\n{summary}"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": template,
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": md},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": button_text},
                    "type": "primary",
                    "multi_url": {"url": thread_url, "pc_url": "", "android_url": "", "ios_url": ""},
                },
            ],
        },
    }


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


def _safe(app_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", app_id)
