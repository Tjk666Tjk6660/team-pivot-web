"""Feishu (Lark) notifier adapter. Minimal card sender.

Full card DSL and collapsible panels to be ported from appv2/tools/notify.py
in a later phase. Phase 1 only supports a simple header + summary + link card;
Phase 1.1 adds @mention support via <at> element (see spec 3.3).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


class FeishuConfigError(Exception):
    pass


@dataclass
class FeishuConfig:
    webhook_url: str
    secret: str


class FeishuAdapter:
    def __init__(self, config: FeishuConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "FeishuAdapter":
        url = os.environ.get("FEISHU_WEBHOOK_URL")
        secret = os.environ.get("FEISHU_SECRET", "")
        if not url:
            raise FeishuConfigError("FEISHU_WEBHOOK_URL not set")
        return cls(FeishuConfig(webhook_url=url, secret=secret))

    def send_card(
        self,
        *,
        title: str,
        summary: str,
        thread_url: str,
        author: str,
        mention_names: Optional[list[str]] = None,
        user_map: Optional[dict[str, dict[str, str]]] = None,
    ) -> bool:
        """Send a Feishu card. Optionally @mentions users by pivot name.

        If mention_names is non-empty and user_map is None, the adapter loads
        the map from PIVOT_USER_MAP via config.get_user_map().
        """
        if mention_names and user_map is None:
            # Late import to avoid module-load cycle.
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
        body: dict[str, Any] = {
            "msg_type": "interactive",
            "card": card,
        }
        if self.config.secret:
            ts = str(int(time.time()))
            body["timestamp"] = ts
            body["sign"] = self._sign(ts)
        try:
            resp = requests.post(self.config.webhook_url, json=body, timeout=10)
        except requests.RequestException:
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        return data.get("code", 0) == 0

    def _sign(self, timestamp: str) -> str:
        key = f"{timestamp}\n{self.config.secret}"
        digest = hmac.new(
            key.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

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
        summary_content = f"**作者**：{author}\n\n{summary}"
        if mention_prefix:
            summary_content = f"{mention_prefix}\n\n{summary_content}"
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": summary_content,
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看全文"},
                            "url": thread_url,
                            "type": "primary",
                        }
                    ],
                },
            ],
        }

    @staticmethod
    def _build_mention_prefix(
        mention_names: list[str],
        user_map: dict[str, dict[str, str]],
    ) -> str:
        """Per-name decision: feishu_id -> <at> element; else -> text @name."""
        parts: list[str] = []
        for name in mention_names:
            user = user_map.get(name) or {}
            feishu_id = user.get("feishu_id", "") if isinstance(user, dict) else ""
            if feishu_id:
                parts.append(f'<at id="{feishu_id}"></at>')
            else:
                parts.append(f"@{name}")
        return " ".join(parts)
