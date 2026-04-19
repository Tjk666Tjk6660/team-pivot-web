from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

from server.feishu_token import FeishuTokenManager

log = logging.getLogger(__name__)

_LIST_CHATS_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/chats"
_SEND_MESSAGE_ENDPOINT = "https://open.feishu.cn/open-apis/im/v1/messages"
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
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None: ...

    def notify_new_reply(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        author_name: str,
        body: str,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
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

    def notify_standalone_mention(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        target_filename: str,
        author_name: str,
        mention_open_ids: list[str],
        mention_comments: str,
        post_excerpt: str,
    ) -> None: ...


class NoOpNotifier:
    def notify_new_thread(self, **_: object) -> None: pass
    def notify_new_reply(self, **_: object) -> None: pass
    def notify_status_change(self, **_: object) -> None: pass
    def notify_standalone_mention(self, **_: object) -> None: pass


class FeishuNotifier:
    def __init__(
        self,
        *,
        tokens: FeishuTokenManager,
        web_base_url: str,
    ) -> None:
        self._tokens = tokens
        self._web_base_url = web_base_url.rstrip("/")

    def notify_new_thread(
        self,
        *,
        category: str,
        slug: str,
        title: str,
        author_name: str,
        body: str,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None:
        url = self._thread_url(category, slug)
        card = build_thread_card(
            title=title,
            author_name=author_name,
            body=body,
            thread_url=url,
            mention_open_ids=mention_open_ids or [],
            mention_comments=mention_comments,
        )
        self._broadcast(card, event=f"new_thread slug={slug}")
        if mention_open_ids:
            dm = build_mention_dm_card(
                author_name=author_name,
                thread_title=title,
                kind="发起讨论",
                comments=mention_comments,
                thread_url=url,
            )
            self._dm_many(mention_open_ids, dm, event=f"new_thread slug={slug}")

    def notify_new_reply(
        self,
        *,
        category: str,
        slug: str,
        thread_title: str,
        author_name: str,
        body: str,
        mention_open_ids: list[str] | None = None,
        mention_comments: str | None = None,
    ) -> None:
        url = self._thread_url(category, slug)
        card = build_reply_card(
            thread_title=thread_title,
            author_name=author_name,
            body=body,
            thread_url=url,
            mention_open_ids=mention_open_ids or [],
            mention_comments=mention_comments,
        )
        self._broadcast(card, event=f"new_reply slug={slug}")
        if mention_open_ids:
            dm = build_mention_dm_card(
                author_name=author_name,
                thread_title=thread_title,
                kind="回复讨论",
                comments=mention_comments,
                thread_url=url,
            )
            self._dm_many(mention_open_ids, dm, event=f"new_reply slug={slug}")

    def notify_standalone_mention(
        self, *, category, slug, thread_title, target_filename,
        author_name, mention_open_ids, mention_comments, post_excerpt,
    ) -> None:
        url = self._thread_url(category, slug)
        card = build_standalone_mention_card(
            thread_title=thread_title,
            author_name=author_name,
            mention_open_ids=mention_open_ids,
            mention_comments=mention_comments,
            post_excerpt=post_excerpt,
            thread_url=url,
        )
        self._broadcast(card, event=f"mention slug={slug} file={target_filename}")
        dm = build_mention_dm_card(
            author_name=author_name,
            thread_title=thread_title,
            kind="提及",
            comments=mention_comments,
            thread_url=url,
        )
        self._dm_many(mention_open_ids, dm, event=f"mention slug={slug}")

    def notify_status_change(
        self, *, category, slug, thread_title, from_state, to_state, author_name, reason,
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
            token = self._tokens.get()
            chats = self._list_chats(token)
            if not chats:
                log.warning("notify skipped (bot in no chats): %s", event)
                return
            sent = sum(1 for cid in chats if self._send(token, cid, "chat_id", card))
            log.info("notify sent to %d/%d chats: %s", sent, len(chats), event)
        except Exception:
            log.warning("notify broadcast failed: %s", event, exc_info=True)

    def _dm_many(self, open_ids: list[str], card: dict, *, event: str) -> None:
        try:
            token = self._tokens.get()
            sent = sum(1 for oid in open_ids if self._send(token, oid, "open_id", card))
            log.info("notify DM sent to %d/%d users: %s", sent, len(open_ids), event)
        except Exception:
            log.warning("notify dm failed: %s", event, exc_info=True)

    def _list_chats(self, token: str) -> list[str]:
        chats: list[str] = []
        page_token = ""
        while True:
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = httpx.get(
                _LIST_CHATS_ENDPOINT, params=params,
                headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"list chats error: {data}")
            for item in data.get("data", {}).get("items", []):
                if item.get("chat_id"):
                    chats.append(item["chat_id"])
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token", "")
            if not page_token:
                break
        return chats

    def _send(self, token: str, receive_id: str, receive_id_type: str, card: dict) -> bool:
        try:
            resp = httpx.post(
                _SEND_MESSAGE_ENDPOINT,
                params={"receive_id_type": receive_id_type},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                log.warning("send non-200 to=%s status=%d", receive_id, resp.status_code)
                return False
            data = resp.json()
            if data.get("code") != 0:
                log.warning("send error to=%s code=%s msg=%s",
                            receive_id, data.get("code"), data.get("msg"))
                return False
            return True
        except Exception:
            log.warning("send exception to=%s", receive_id, exc_info=True)
            return False


def build_thread_card(
    *,
    title: str,
    author_name: str,
    body: str,
    thread_url: str,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
) -> dict:
    return _build_card(
        header=f"新讨论：{title}",
        template="blue",
        author_name=author_name,
        body=body,
        button_text="去 Web 查看",
        thread_url=thread_url,
        mention_open_ids=mention_open_ids or [],
        mention_comments=mention_comments,
    )


def build_reply_card(
    *,
    thread_title: str,
    author_name: str,
    body: str,
    thread_url: str,
    mention_open_ids: list[str] | None = None,
    mention_comments: str | None = None,
) -> dict:
    return _build_card(
        header=f"新回复：{thread_title}",
        template="green",
        author_name=author_name,
        body=body,
        button_text="查看讨论",
        thread_url=thread_url,
        mention_open_ids=mention_open_ids or [],
        mention_comments=mention_comments,
    )


_STATUS_LABEL = {
    "open": "讨论中", "concluded": "已达成结论", "produced": "已转为项目",
    "closed": "已关闭", "pending": "暂时搁置",
}


def build_status_change_card(
    *, thread_title, author_name, from_state, to_state, reason, thread_url,
) -> dict:
    md_parts = [
        f"**操作**：{author_name}",
        f"**状态**：{_STATUS_LABEL.get(from_state, from_state)} → "
        f"{_STATUS_LABEL.get(to_state, to_state)}",
    ]
    if reason:
        md_parts.append(f"**原因**：{reason}")
    return _card_shell(
        header=f"状态变更：{thread_title}",
        template="purple",
        markdown="\n\n".join(md_parts),
        button_text="查看讨论",
        thread_url=thread_url,
    )


def build_standalone_mention_card(
    *,
    thread_title: str,
    author_name: str,
    mention_open_ids: list[str],
    mention_comments: str,
    post_excerpt: str,
    thread_url: str,
) -> dict:
    parts: list[str] = []
    if mention_open_ids:
        parts.append(" ".join(f'<at user_id="{oid}"></at>' for oid in mention_open_ids))
    parts.append(f"**{author_name}** 提及（主题：**{thread_title}**）")
    parts.append(f"**说明**：{mention_comments}")
    if post_excerpt:
        parts.append(f"**相关内容**：{_truncate(post_excerpt, 150)}")
    return _card_shell(
        header=f"提及：{thread_title}",
        template="orange",
        markdown="\n\n".join(parts),
        button_text="查看讨论",
        thread_url=thread_url,
    )


def build_mention_dm_card(
    *, author_name: str, thread_title: str, kind: str,
    comments: str | None, thread_url: str,
) -> dict:
    md_parts = [f"**{author_name}** 在{kind}中提到了你（主题：**{thread_title}**）"]
    if comments:
        md_parts.append(f"**说明**：{comments}")
    return _card_shell(
        header="有人 @ 了你",
        template="orange",
        markdown="\n\n".join(md_parts),
        button_text="去查看",
        thread_url=thread_url,
    )


def _build_card(
    *,
    header: str,
    template: str,
    author_name: str,
    body: str,
    button_text: str,
    thread_url: str,
    mention_open_ids: list[str],
    mention_comments: str | None,
) -> dict:
    parts: list[str] = []
    if mention_open_ids:
        parts.append(" ".join(f'<at user_id="{oid}"></at>' for oid in mention_open_ids))
    if mention_comments:
        parts.append(f"**说明**：{mention_comments}")
    parts.append(f"**作者**：{author_name}")
    parts.append(_truncate(body, 200))
    return _card_shell(
        header=header, template=template,
        markdown="\n\n".join(parts),
        button_text=button_text, thread_url=thread_url,
    )


def _card_shell(*, header: str, template: str, markdown: str, button_text: str, thread_url: str) -> dict:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": template,
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": markdown},
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
    return s if len(s) <= n else s[:n].rstrip() + "…"
