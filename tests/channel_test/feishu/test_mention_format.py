"""Channel test: Feishu @mention element format."""
from tools.notify.feishu_bot import FeishuBotAdapter


class TestMentionFormat:
    def test_at_element_uses_user_id_attribute(self):
        prefix = FeishuBotAdapter._build_mention_prefix(
            ["ken"], {"ken": {"feishu_id": "ou_xxx"}}
        )
        assert prefix == '<at user_id="ou_xxx"></at>'

    def test_fallback_to_text_when_no_open_id(self):
        prefix = FeishuBotAdapter._build_mention_prefix(
            ["unknown"], {}
        )
        assert prefix == "@unknown"

    def test_empty_feishu_id_falls_back(self):
        prefix = FeishuBotAdapter._build_mention_prefix(
            ["ken"], {"ken": {"feishu_id": ""}}
        )
        assert prefix == "@ken"

    def test_user_not_in_map_falls_back(self):
        prefix = FeishuBotAdapter._build_mention_prefix(
            ["ghost"], {"ken": {"feishu_id": "ou_xxx"}}
        )
        assert prefix == "@ghost"

    def test_mixed_mention(self):
        prefix = FeishuBotAdapter._build_mention_prefix(
            ["ken", "new_user"],
            {"ken": {"feishu_id": "ou_ken"}},
        )
        assert '<at user_id="ou_ken"></at>' in prefix
        assert "@new_user" in prefix
        assert prefix.index("<at") < prefix.index("@new_user")

    def test_empty_mention_names(self):
        prefix = FeishuBotAdapter._build_mention_prefix([], {})
        assert prefix == ""

    def test_mention_prefix_before_author(self):
        adapter = FeishuBotAdapter(access_token="t")
        card = adapter._build_card(
            title="t", summary="s", thread_url="u", author="a",
            mention_names=["ken"],
            user_map={"ken": {"feishu_id": "ou_ken"}},
        )
        content = card["body"]["elements"][0]["content"]
        at_pos = content.find("<at")
        author_pos = content.find("**Author**")
        assert at_pos < author_pos
