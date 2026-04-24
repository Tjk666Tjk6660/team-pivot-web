from __future__ import annotations

from pathlib import Path

from server.notify import (
    FeishuNotifier,
    NoOpNotifier,
    build_mention_dm_card,
    build_reply_card,
    build_standalone_mention_card,
    build_thread_card,
    build_thread_directory,
)


# ─── 6 字段卡片 ─────────────────────────────────────────────────────────────


def test_thread_card_shape_6_fields():
    card = build_thread_card(
        category="general",
        thread_slug="hello",
        title="Hello",
        author_name="邓柯",
        filename="001_deng_proposal_xxx.md",
        thread_url="http://localhost:5173/auth/entry?next=%2Ft%2Fgeneral%2Fhello",
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert card["header"]["title"]["content"] == "📨 来自 邓柯 的新讨论主题通知：Hello"

    md = card["body"]["elements"][0]["content"]
    # 6 字段都在
    assert "**项目**：general" in md
    assert "**主题**：Hello" in md
    assert "**操作**：邓柯 发起了新讨论" in md
    assert "**文件**：001_deng_proposal_xxx.md" in md
    assert "**时间**：" in md
    # 不再有摘要行
    assert "**摘要**" not in md
    # 行间用 <br>
    assert "<br>" in md

    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"


def test_reply_card_header_carries_author():
    card = build_reply_card(
        category="general",
        thread_slug="parent",
        thread_title="Parent",
        author_name="Ken",
        filename="002_ken_reply_xxx.md",
        thread_url="http://x/y",
    )
    assert card["header"]["template"] == "green"
    assert card["header"]["title"]["content"] == "📩 来自 Ken 的新回复通知：Parent"

    md = card["body"]["elements"][0]["content"]
    assert "**主题**：Parent" in md
    assert "**操作**：Ken 发布了新回复" in md
    assert "**文件**：002_ken_reply_xxx.md" in md


def test_card_no_author_row():
    """No **作者** row — author lives in header / 操作."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**作者**：" not in md


def test_card_omits_body_preview_when_no_body():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**内容**" not in md


def test_thread_card_body_preview_strips_markdown():
    body = (
        "# Hello\n\n"
        "This is **bold** and *italic* text with `inline code`.\n\n"
        "- item one\n- item two\n\n"
        "See [link](http://x) and ![img](http://y)."
    )
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        body=body,
    )
    md = card["body"]["elements"][0]["content"]
    assert "**内容**：" in md
    # Extract the 内容 row
    preview_row = next(
        r for r in md.split("<br>") if r.startswith("**内容**：")
    )
    preview = preview_row[len("**内容**："):]
    # No raw markdown left
    for junk in ("**", "*", "`", "#", "[", "]", "(http", "!["):
        assert junk not in preview, f"found {junk!r} in {preview!r}"
    assert "bold" in preview
    assert "italic" in preview
    assert "link" in preview
    assert "img" in preview
    assert "inline code" in preview


def test_mention_comments_collapsed_to_single_line():
    """Multi-line mention_comments must not introduce paragraph breaks."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        mention_open_ids=["ou_abc"],
        mention_comments="请看\n\n\n   一下   \n重要事项",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**说明**：请看 一下 重要事项" in md
    # No paragraph-break sequence inside the info block
    assert "\n\n" not in md


def test_mention_comments_rendered_below_time_row():
    """说明 must sit below 时间 (not at top) so the first row of the card
    is always a compact meta field, avoiding the Feishu first-paragraph
    top-margin gap when a 说明 is present."""
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        mention_comments="重要说明",
    )
    md = card["body"]["elements"][0]["content"]
    rows = md.split("<br>")
    time_idx = next(i for i, r in enumerate(rows) if r.startswith("**时间**"))
    说明_idx = next(i for i, r in enumerate(rows) if r.startswith("**说明**"))
    assert 说明_idx > time_idx


def test_card_body_has_tight_top_padding():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    assert card["body"]["padding"].startswith("4px ")


def test_reply_card_body_preview_truncates_at_200():
    body = "一" * 300
    card = build_reply_card(
        category="c",
        thread_slug="s",
        thread_title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
        body=body,
    )
    md = card["body"]["elements"][0]["content"]
    preview_row = next(
        r for r in md.split("<br>") if r.startswith("**内容**：")
    )
    preview = preview_row[len("**内容**："):]
    assert preview.endswith("...")
    # 200 chars + "..."
    assert len(preview) == 203


# ─── Mention 卡片 ───────────────────────────────────────────────────────────


def test_standalone_mention_card_structure():
    card = build_standalone_mention_card(
        category="enclaws",
        thread_slug="hello",
        thread_title="EnClaws 内容营销推广方案",
        author_name="邓柯",
        target_filename="003_daisy_reply_bac194.md",
        target_author_name="Daisy",
        target_type="reply",
        mention_open_ids=["ou_aaa", "ou_bbb", "ou_ccc"],
        mention_comments="我觉得Daisy文档里面提的问题都挺不错，欢迎大家一起来发表意见。头脑风暴",
        post_url="http://x/deep-link",
    )
    md = card["body"]["elements"][0]["content"]

    # 1. 真 @ 语法：schema 2.0 用 id=，content 留空
    assert '<at id="ou_aaa"></at>' in md
    assert '<at id="ou_bbb"></at>' in md
    assert '<at id="ou_ccc"></at>' in md
    assert "user_id=" not in md  # 旧 schema 1.0 写法必须全部清除

    # 2. 评论行：橙色主评论人 + 蓝色被评人 + 被 @ 人 + 说：comment
    assert "**评论**：" in md
    assert "<font color='orange'>**邓柯**</font>" in md
    assert "<font color='blue'>**Daisy**</font>" in md
    assert "的回复" in md  # target_type=reply → "回复"
    assert "说：" in md
    assert "我觉得Daisy文档里面提的问题都挺不错" in md

    # 3. 评论行结构：主评论人 → 对 → 被评人 → 的回复 → @ 标签 → 说：<br>comment
    i_author = md.index("<font color='orange'>**邓柯**</font>")
    i_target = md.index("<font color='blue'>**Daisy**</font>")
    i_ats = md.index('<at id="ou_aaa"></at>')
    i_say = md.index("说：<br>")
    assert i_author < i_target < i_ats < i_say

    # 4. 元信息块 4 个字段齐全且顺序正确：时间 → 项目 → 主题 → 被评文件
    i_time = md.index("**时间**：")
    i_proj = md.index("**项目**：enclaws")
    i_topic = md.index("**主题**：EnClaws 内容营销推广方案")
    i_file = md.index("**被评文件**：003_daisy_reply_bac194.md")
    assert i_time < i_proj < i_topic < i_file

    # 5. 已去掉的字段/短语
    assert "提及了以上成员" not in md
    assert "**说明**：" not in md   # 合并进评论行
    assert "**帖子**：" not in md   # 改叫"被评文件"
    assert "**相关内容**：" not in md  # post_excerpt 段已废弃

    # 6. 按钮保持 post 级深链
    button = card["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["multi_url"]["url"] == "http://x/deep-link"
    assert button["text"]["content"] == "查看该帖子"

    # 7. header 和模板
    assert card["header"]["template"] == "orange"
    assert "📣 提及：EnClaws 内容营销推广方案" in card["header"]["title"]["content"]


def test_standalone_mention_card_target_type_proposal():
    """target_type=proposal → 评论行里显示'的提及'。"""
    card = build_standalone_mention_card(
        category="c", thread_slug="s", thread_title="t",
        author_name="Alice",
        target_filename="001_bob_proposal_x.md",
        target_author_name="Bob",
        target_type="proposal",
        mention_open_ids=["ou_x"],
        mention_comments="hi",
        post_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    assert "的提及" in md
    assert "的回复" not in md


def test_mention_dm_card_structure():
    card = build_mention_dm_card(
        author_name="Alice",
        thread_title="Hello",
        thread_slug="hello",
        target_filename="002_bob_reply_zzz.md",
        kind="提及",
        comments="帮忙看一下",
        post_url="http://x/deep-link",
        post_excerpt="这是 bob 的回复正文",
    )
    md = card["body"]["elements"][0]["content"]
    assert "Alice" in md
    assert "Hello" in md
    assert "提及" in md
    assert "**帖子**：002_bob_reply_zzz.md" in md
    assert "**说明**：帮忙看一下" in md
    assert "**相关内容**：" in md
    assert card["body"]["elements"][-1]["multi_url"]["url"] == "http://x/deep-link"


# ─── Post-level deep link URL ──────────────────────────────────────────────


def test_feishu_notifier_uses_auth_entry_thread_url():
    notifier = FeishuNotifier(tokens=None, web_base_url="https://pivot.enclaws.ai")  # type: ignore[arg-type]
    url = notifier._thread_url("产品", "讨论")
    assert (
        url
        == "https://pivot.enclaws.ai/auth/entry?next=%2Ft%2F%E4%BA%A7%E5%93%81%2F%E8%AE%A8%E8%AE%BA"
    )


def test_feishu_notifier_post_url_carries_anchor():
    notifier = FeishuNotifier(tokens=None, web_base_url="https://pivot.enclaws.ai")  # type: ignore[arg-type]
    url = notifier._post_url("general", "hello", "001_user_proposal_abc.md")
    # URL-encoded next should include both ?post=<anchor> and #post-<anchor>
    assert "post%3D001_user_proposal_abc" in url
    assert "%23post-001_user_proposal_abc" in url


# ─── Discussion directory ──────────────────────────────────────────────────


def _write_post(path: Path, *, type_: str, author: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        f"type: {type_}\n"
        f"author: {author}\n"
        "created: 2026-04-23T10:00:00+08:00\n"
        "index_state: indexed\n"
    )
    path.write_text(f"---\n{fm}---\n# body\n", encoding="utf-8")


class _WorkspaceStub:
    def __init__(self, discussions_dir: Path, index_dir: Path) -> None:
        self.discussions_dir = discussions_dir
        self.index_dir = index_dir


def test_build_thread_directory_highlights_current_post(tmp_path):
    discussions = tmp_path / "discussions"
    index_dir = tmp_path / "index"
    _write_post(
        discussions / "general" / "hello" / "001_alice_proposal_abc.md",
        type_="proposal", author="alice",
    )
    _write_post(
        discussions / "general" / "hello" / "002_bob_reply_def.md",
        type_="reply", author="bob",
    )

    content, count = build_thread_directory(
        _WorkspaceStub(discussions, index_dir),  # type: ignore[arg-type]
        category="general",
        slug="hello",
        current_filename="002_bob_reply_def.md",
    )
    assert count == 2
    assert "001_alice_proposal_abc.md" in content
    assert "002_bob_reply_def.md" in content
    # current post highlighted with blue font + 🔷
    assert "<font color='blue'>🔷" in content
    # non-current entry prefixed with 📄
    assert "📄 " in content
    # No per-post summary in v2 (summary deferred)
    assert "**摘要**" not in content


def test_thread_card_includes_directory_panel():
    card = build_thread_card(
        category="general",
        thread_slug="hello",
        title="Hello",
        author_name="Ken",
        filename="001_ken_proposal_xxx.md",
        thread_url="http://x/y",
        directory_content="📄 **001_ken_proposal_xxx.md** · Ken · 2026-04-23",
        directory_post_count=1,
    )
    tags = [e.get("tag") for e in card["body"]["elements"]]
    assert "collapsible_panel" in tags
    panel = next(e for e in card["body"]["elements"] if e.get("tag") == "collapsible_panel")
    assert "讨论目录" in panel["header"]["title"]["content"]


def test_thread_card_omits_directory_panel_when_empty():
    card = build_thread_card(
        category="c",
        thread_slug="s",
        title="T",
        author_name="a",
        filename="f.md",
        thread_url="http://x",
    )
    tags = [e.get("tag") for e in card["body"]["elements"]]
    assert "collapsible_panel" not in tags
    assert tags == ["markdown", "button"]


# ─── NoOpNotifier accepts v2 signature ─────────────────────────────────────


def test_noop_notifier_silent():
    n = NoOpNotifier()
    n.notify_new_thread(
        category="c", slug="s", title="t", author_name="a",
        filename="f.md",
    )
    n.notify_new_reply(
        category="c", slug="s", thread_title="t", author_name="a",
        filename="f.md",
    )
    n.notify_standalone_mention(
        category="c", slug="s", thread_title="t", target_filename="f.md",
        author_name="a", mention_open_ids=["ou_x"], mention_comments="hi",
    )


def test_feishu_notifier_standalone_mention_does_not_dm(monkeypatch):
    """群卡片里 <at id=…> 已能触发推送，不再额外发 DM（避免双通知）。"""
    notifier = FeishuNotifier(tokens=None, web_base_url="https://x")  # type: ignore[arg-type]

    calls: dict[str, int] = {"broadcast": 0, "dm": 0}

    def fake_broadcast(self, card, *, event):
        calls["broadcast"] += 1

    def fake_dm_many(self, open_ids, card, *, event):
        calls["dm"] += 1

    monkeypatch.setattr(FeishuNotifier, "_broadcast", fake_broadcast)
    monkeypatch.setattr(FeishuNotifier, "_dm_many", fake_dm_many)

    notifier.notify_standalone_mention(
        category="c", slug="s", thread_title="t",
        target_filename="001_a.md",
        target_author_name="Bob",
        target_type="reply",
        author_name="Alice",
        mention_open_ids=["ou_x"],
        mention_comments="hi",
    )

    assert calls["broadcast"] == 1
    assert calls["dm"] == 0
