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
    """Extract the lark_md content from the card in a mock requests.post call."""
    body = mock_post_call[1].get("json", {})
    card = json.loads(body["content"])
    return card["elements"][0]["text"]["content"]


class TestFromEnv:
    def test_loads_token_and_chat_ids(self, monkeypatch):
        monkeypatch.setenv("FEISHU_ACCESS_TOKEN", "t-xxx")
        monkeypatch.setenv("FEISHU_CHAT_IDS", '["oc_aaa","oc_bbb"]')
        adapter = FeishuBotAdapter.from_env()
        assert adapter.access_token == "t-xxx"
        assert adapter.chat_ids == ["oc_aaa", "oc_bbb"]

    def test_raises_without_token(self, monkeypatch):
        monkeypatch.delenv("FEISHU_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("FEISHU_CHAT_IDS", '["oc_aaa"]')
        with pytest.raises(FeishuBotConfigError, match="ACCESS_TOKEN"):
            FeishuBotAdapter.from_env()

    def test_raises_with_empty_chat_ids(self, monkeypatch):
        monkeypatch.setenv("FEISHU_ACCESS_TOKEN", "t-xxx")
        monkeypatch.setenv("FEISHU_CHAT_IDS", "[]")
        with pytest.raises(FeishuBotConfigError, match="CHAT_IDS"):
            FeishuBotAdapter.from_env()


class TestSendCardToAll:
    def test_sends_to_each_chat_id(self):
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1", "oc_2"])
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
            mock_post.return_value = _mock_success()
            sent = adapter.send_card_to_all(
                title="New thread",
                summary="test summary",
                thread_url="https://example.com",
                author="ken",
            )
            assert sent == 2
            assert mock_post.call_count == 2
            # Verify different chat_ids
            calls = mock_post.call_args_list
            chat_ids_sent = [c[1]["json"]["receive_id"] for c in calls]
            assert set(chat_ids_sent) == {"oc_1", "oc_2"}
            # Verify auth header
            assert calls[0][1]["headers"]["Authorization"] == "Bearer t-xxx"

    def test_mention_with_open_id_emits_at_element(self):
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1"])
        user_map = {"ken": {"feishu_id": "ou_ken123"}}
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
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
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1"])
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
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
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1"])
        user_map = {"ken": {"feishu_id": "ou_ken"}}
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
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
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1"])
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
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
        adapter = FeishuBotAdapter(access_token="t-xxx", chat_ids=["oc_1", "oc_2"])
        with patch("tools.notify.feishu_bot.requests.post") as mock_post:
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
            assert sent == 1  # only first succeeded
