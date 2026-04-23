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
    assert "新讨论：Hello" in card["header"]["title"]["content"]

    md = card["body"]["elements"][0]["content"]
    # 6 字段都在
    assert "**项目**：general" in md
    assert "**主题**：hello" in md
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
    assert "Ken 回复：Parent" in card["header"]["title"]["content"]

    md = card["body"]["elements"][0]["content"]
    assert "**操作**：Ken 发布了新回复" in md
    assert "**文件**：002_ken_reply_xxx.md" in md


def test_card_no_longer_contains_raw_body():
    """v2: no 200-char body preview, no **作者** row."""
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


# ─── Mention 卡片 ───────────────────────────────────────────────────────────


def test_standalone_mention_card_structure():
    card = build_standalone_mention_card(
        category="general",
        thread_slug="hello",
        thread_title="Hello",
        author_name="Alice",
        target_filename="002_bob_reply_zzz.md",
        mention_open_ids=["ou_aaa", "ou_bbb"],
        mention_comments="请看一下",
        post_excerpt="这是 bob 的回复正文",
        post_url="http://x/deep-link",
    )
    md = card["body"]["elements"][0]["content"]
    # 必须展示: 圈谁 / 哪个 thread / 哪条 post / mention 内容 / 相关内容
    assert '<at user_id="ou_aaa"' in md
    assert '<at user_id="ou_bbb"' in md
    assert "**{} ".format("Alice") in md or "Alice" in md
    assert "**项目**：general" in md
    assert "**主题**：Hello" in md
    assert "**帖子**：002_bob_reply_zzz.md" in md
    assert "**说明**：请看一下" in md
    assert "**相关内容**：" in md
    # 按钮必须 deep-link 到 post 级
    button = card["body"]["elements"][-1]
    assert button["multi_url"]["url"] == "http://x/deep-link"
    assert button["text"]["content"] == "查看该帖子"


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
        post_excerpt="body",
    )
