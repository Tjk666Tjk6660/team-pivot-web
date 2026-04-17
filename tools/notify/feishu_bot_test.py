"""Tests for FeishuBotAdapter."""
import json
from unittest.mock import patch, MagicMock

import pytest

from tools.notify.feishu_bot import FeishuBotAdapter, FeishuBotConfigError


def _mock_success():
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"code": 0}
    return m


def _extract_card_content(mock_post_call):
    """Extract the markdown content from the v2 card in a mock requests.post call."""
    body = mock_post_call[1].get("json", {})
    card = json.loads(body["content"])
    return card["body"]["elements"][0]["content"]


class TestFromEnv:
    def test_loads_token_via_token_module(self, monkeypatch):
        """from_env() 应该调 get_tenant_access_token() 拿 token。"""
        with patch(
            "tools.notify.feishu_token.get_tenant_access_token",
            return_value="t-fetched",
        ):
            adapter = FeishuBotAdapter.from_env()
            assert adapter.access_token == "t-fetched"

    def test_raises_when_token_module_raises(self, monkeypatch):
        """token 模块抛 FeishuTokenError 时，from_env 转为 FeishuBotConfigError。"""
        from tools.notify.feishu_token import FeishuTokenError
        with patch(
            "tools.notify.feishu_token.get_tenant_access_token",
            side_effect=FeishuTokenError("FEISHU_APP_ID or FEISHU_APP_SECRET not set"),
        ):
            with pytest.raises(FeishuBotConfigError, match="FEISHU_APP_ID"):
                FeishuBotAdapter.from_env()


class TestSendCardToAll:
    def test_sends_to_all_discovered_chats(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1", "oc_2"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            sent = adapter.send_card_to_all(
                title="New thread",
                summary="test summary",
                thread_url="https://example.com",
                author="ken",
            )
            assert sent == 2
            assert mock_post.call_count == 2
            calls = mock_post.call_args_list
            chat_ids_sent = [c[1]["json"]["receive_id"] for c in calls]
            assert set(chat_ids_sent) == {"oc_1", "oc_2"}
            assert calls[0][1]["headers"]["Authorization"] == "Bearer t-xxx"

    def test_no_chats_discovered_sends_nothing(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        with patch.object(adapter, "_get_bot_chats", return_value=[]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            sent = adapter.send_card_to_all(
                title="t", summary="s", thread_url="u", author="a",
            )
            assert sent == 0
            assert mock_post.call_count == 0

    def test_mention_with_open_id_emits_at_element(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        user_map = {"ken": {"feishu_id": "ou_ken123"}}
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            adapter.send_card_to_all(
                title="t",
                summary="s",
                thread_url="u",
                author="a",
                mention_names=["ken"],
                user_map=user_map,
            )
            content = _extract_card_content(mock_post.call_args)
            assert '<at user_id="ou_ken123"></at>' in content

    def test_mention_without_open_id_falls_back_to_text(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            adapter.send_card_to_all(
                title="t",
                summary="s",
                thread_url="u",
                author="a",
                mention_names=["unknown_user"],
                user_map={},
            )
            content = _extract_card_content(mock_post.call_args)
            assert "@unknown_user" in content
            assert "<at" not in content

    def test_mixed_mention(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        user_map = {"ken": {"feishu_id": "ou_ken"}}
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            adapter.send_card_to_all(
                title="t",
                summary="s",
                thread_url="u",
                author="a",
                mention_names=["ken", "new_user"],
                user_map=user_map,
            )
            content = _extract_card_content(mock_post.call_args)
            assert '<at user_id="ou_ken"></at>' in content
            assert "@new_user" in content

    def test_auto_loads_user_map_from_env(self, monkeypatch):
        monkeypatch.setenv("PIVOT_USER_MAP", '{"ken": {"feishu_id": "ou_env"}}')
        adapter = FeishuBotAdapter(access_token="t-xxx")
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            adapter.send_card_to_all(
                title="t",
                summary="s",
                thread_url="u",
                author="a",
                mention_names=["ken"],
            )
            content = _extract_card_content(mock_post.call_args)
            assert '<at user_id="ou_env"></at>' in content

    def test_http_failure_counted_as_not_sent(self):
        adapter = FeishuBotAdapter(access_token="t-xxx")
        with patch.object(adapter, "_get_bot_chats", return_value=["oc_1", "oc_2"]), \
             patch("tools.notify.feishu_bot.requests.post") as mock_post:
            fail_resp = MagicMock()
            fail_resp.status_code = 500
            fail_resp.json.return_value = {"code": -1}
            mock_post.side_effect = [
                _mock_success(),
                fail_resp,
            ]
            sent = adapter.send_card_to_all(
                title="t", summary="s", thread_url="u", author="a",
            )
            assert sent == 1
