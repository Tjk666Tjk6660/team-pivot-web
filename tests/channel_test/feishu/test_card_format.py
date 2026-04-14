"""Channel test: Feishu card JSON structure validation."""
from tools.notify.feishu_bot import FeishuBotAdapter


class TestCardFormat:
    def _build(self, **kwargs):
        defaults = {
            "title": "Test Title",
            "summary": "Test summary",
            "thread_url": "https://example.com/thread/test/x",
            "author": "ken",
            "mention_names": [],
            "user_map": {},
        }
        defaults.update(kwargs)
        adapter = FeishuBotAdapter(access_token="t", chat_ids=["oc_1"])
        return adapter._build_card(**defaults)

    def test_card_has_header(self):
        card = self._build()
        assert card["header"]["title"]["tag"] == "plain_text"
        assert card["header"]["title"]["content"] == "Test Title"
        assert card["header"]["template"] == "blue"

    def test_card_has_wide_screen_mode(self):
        card = self._build()
        assert card["config"]["wide_screen_mode"] is True

    def test_card_has_summary_div(self):
        card = self._build(summary="My summary text")
        div = card["elements"][0]
        assert div["tag"] == "div"
        assert div["text"]["tag"] == "lark_md"
        assert "My summary text" in div["text"]["content"]

    def test_card_has_no_view_button(self):
        # View button removed — thread_url is a placeholder. Re-add once configured.
        card = self._build(thread_url="https://pivot.example.com/thread/a/b")
        for element in card["elements"]:
            assert element.get("tag") != "action", "View button should not be rendered"

    def test_card_includes_author(self):
        card = self._build(author="shengli")
        content = card["elements"][0]["text"]["content"]
        assert "**Author**: shengli" in content
