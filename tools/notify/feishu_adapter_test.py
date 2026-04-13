"""Tests for FeishuAdapter."""
from unittest.mock import patch, MagicMock

from tools.notify.feishu_adapter import FeishuAdapter, FeishuConfig


class TestFeishuAdapter:
    def test_send_card_posts_to_webhook(self):
        cfg = FeishuConfig(webhook_url="https://feishu.example/hook", secret="s")
        adapter = FeishuAdapter(cfg)
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            ok = adapter.send_card(
                title="New Discussion",
                summary="**摘要**：test\n**亮点**：demo",
                thread_url="https://example.com/thread/1",
                author="ken",
            )
            assert ok is True
            mock_post.assert_called_once()
            url = mock_post.call_args[0][0]
            assert url == "https://feishu.example/hook"
            body = mock_post.call_args[1]["json"]
            assert "msg_type" in body
            assert body["msg_type"] == "interactive"

    def test_send_card_returns_false_on_http_error(self):
        cfg = FeishuConfig(webhook_url="https://feishu.example/hook", secret="s")
        adapter = FeishuAdapter(cfg)
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500, json=lambda: {})
            ok = adapter.send_card(
                title="x",
                summary="y",
                thread_url="z",
                author="a",
            )
            assert ok is False

    def test_from_env_reads_webhook_url_and_secret(self, monkeypatch):
        monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://feishu.example/hook")
        monkeypatch.setenv("FEISHU_SECRET", "s1")
        adapter = FeishuAdapter.from_env()
        assert adapter.config.webhook_url == "https://feishu.example/hook"
        assert adapter.config.secret == "s1"


def _extract_summary_content(mock_post_call):
    """Read the summary div's lark_md content from a mock requests.post call."""
    body = mock_post_call[1]["json"]
    return body["card"]["elements"][0]["text"]["content"]


class TestMentionCard:
    def test_no_mention_names_preserves_legacy_content(self):
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body text",
                thread_url="u",
                author="ken",
            )
            content = _extract_summary_content(mock_post.call_args)
            assert content == "**Author**：ken\n\nbody text"
            assert "<at" not in content

    def test_mention_with_feishu_id_emits_at_element(self):
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        user_map = {"ken": {"feishu_id": "ou_xxx"}}
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body",
                thread_url="u",
                author="ken",
                mention_names=["ken"],
                user_map=user_map,
            )
            content = _extract_summary_content(mock_post.call_args)
            assert '<at id="ou_xxx"></at>' in content
            assert content.find("<at") < content.find("**Author**")

    def test_mention_without_feishu_id_falls_back_to_text(self):
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        user_map = {"new_user": {}}
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body",
                thread_url="u",
                author="a",
                mention_names=["new_user"],
                user_map=user_map,
            )
            content = _extract_summary_content(mock_post.call_args)
            assert "@new_user" in content
            assert "<at" not in content

    def test_mention_missing_from_map_falls_back_to_text(self):
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body",
                thread_url="u",
                author="a",
                mention_names=["unknown"],
                user_map={},
            )
            content = _extract_summary_content(mock_post.call_args)
            assert "@unknown" in content
            assert "<at" not in content

    def test_mixed_mention_names(self):
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        user_map = {"ken": {"feishu_id": "ou_xxx"}}
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body",
                thread_url="u",
                author="a",
                mention_names=["ken", "new_user"],
                user_map=user_map,
            )
            content = _extract_summary_content(mock_post.call_args)
            assert '<at id="ou_xxx"></at>' in content
            assert "@new_user" in content
            assert content.find("<at") < content.find("@new_user")

    def test_user_map_auto_loaded_from_env_when_not_provided(self, monkeypatch):
        monkeypatch.setenv(
            "PIVOT_USER_MAP",
            '{"ken": {"feishu_id": "ou_env"}}',
        )
        cfg = FeishuConfig(webhook_url="https://h", secret="")
        adapter = FeishuAdapter(cfg)
        with patch("tools.notify.feishu_adapter.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"code": 0})
            adapter.send_card(
                title="t",
                summary="body",
                thread_url="u",
                author="a",
                mention_names=["ken"],
            )
            content = _extract_summary_content(mock_post.call_args)
            assert '<at id="ou_env"></at>' in content
