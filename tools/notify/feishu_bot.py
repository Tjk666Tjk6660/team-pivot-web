"""Feishu Bot API adapter. Sends interactive cards via application messaging.

Auto-discovers all groups the bot has joined via Feishu API, then broadcasts
cards to all of them. No manual FEISHU_CHAT_IDS configuration needed.

ENV vars required (injected by EC):
  FEISHU_ACCESS_TOKEN — tenant_access_token (cached by EC)
  PIVOT_USER_MAP — {name: {feishu_id: "ou_xxx"}} (existing)
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests


class FeishuBotConfigError(Exception):
    pass


class FeishuBotAdapter:
    def __init__(self, access_token: str):
        self.access_token = access_token

    @classmethod
    def from_env(cls) -> "FeishuBotAdapter":
        token = os.environ.get("FEISHU_ACCESS_TOKEN", "")
        if not token:
            raise FeishuBotConfigError("FEISHU_ACCESS_TOKEN not set")
        return cls(access_token=token)

    def _get_bot_chats(self) -> list[str]:
        """Auto-discover all groups the bot has joined via Feishu API."""
        chat_ids: list[str] = []
        page_token = ""
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            try:
                resp = requests.get(
                    "https://open.feishu.cn/open-apis/im/v1/chats",
                    params=params,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=10,
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("code") != 0:
                    break
                items = data.get("data", {}).get("items", [])
                for item in items:
                    chat_id = item.get("chat_id", "")
                    if chat_id:
                        chat_ids.append(chat_id)
                page_token = data.get("data", {}).get("page_token", "")
                if not data.get("data", {}).get("has_more", False):
                    break
            except requests.RequestException:
                break
        return chat_ids

    def send_card_to_all(
        self,
        *,
        title: str,
        summary: str,
        thread_url: str,
        author: str,
        mention_names: Optional[list[str]] = None,
        user_map: Optional[dict[str, dict[str, str]]] = None,
    ) -> int:
        """Send a card to all groups the bot has joined. Returns count of successful sends."""
        if mention_names and user_map is None:
            from tools.config import get_user_map
            user_map = get_user_map()

        card = self._build_card(
            title=title,
            summary=summary,
            thread_url=thread_url,
            author=author,
            mention_names=mention_names or [],
            user_map=user_map or {},
        )
        card_json = json.dumps(card)

        chat_ids = self._get_bot_chats()
        sent = 0
        for chat_id in chat_ids:
            try:
                resp = requests.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "receive_id": chat_id,
                        "msg_type": "interactive",
                        "content": card_json,
                    },
                    timeout=10,
                )
                if resp.status_code == 200 and resp.json().get("code") == 0:
                    sent += 1
            except requests.RequestException:
                pass
        return sent

    def _build_card(
        self,
        *,
        title: str,
        summary: str,
        thread_url: str,
        author: str,
        mention_names: list[str],
        user_map: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        mention_prefix = self._build_mention_prefix(mention_names, user_map)
        summary_content = f"**Author**: {author}\n\n{summary}"
        if mention_prefix:
            summary_content = f"{mention_prefix}\n\n{summary_content}"
        from tools.config import get_version
        version = get_version()
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": summary_content,
                },
            },
        ]
        if version and version != "unknown":
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"Team-Pivot v{version}"},
                ],
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }

    @staticmethod
    def _build_mention_prefix(
        mention_names: list[str],
        user_map: dict[str, dict[str, str]],
    ) -> str:
        """Per-name decision: open_id found -> <at> element; else -> text @name."""
        parts: list[str] = []
        for name in mention_names:
            user = user_map.get(name) or {}
            feishu_id = user.get("feishu_id", "") if isinstance(user, dict) else ""
            if feishu_id:
                parts.append(f'<at user_id="{feishu_id}"></at>')
            else:
                parts.append(f"@{name}")
        return " ".join(parts)
