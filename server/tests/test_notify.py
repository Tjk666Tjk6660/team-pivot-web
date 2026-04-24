from __future__ import annotations

from pathlib import Path

from server.notify import (
    FeishuNotifier,
    NoOpNotifier,
    build_mention_dm_card,
    build_reply_card,
    build_standalone_mention_card,
    build_status_change_card,
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


# ─── status_change 卡片（P4.5 G 补遗） ────────────────────────────────────


def test_status_change_card_matter_labels():
    """_STATUS_LABEL 现在覆盖 matter 6 态，从/到的中文映射应生效。"""
    card = build_status_change_card(
        thread_title="Auth Redesign",
        author_name="邓柯",
        from_state="executing",
        to_state="finished",
        reason=None,
        thread_url="http://localhost:5173/auth/entry?next=%2Fm%2Fauth-redesign",
    )
    md = card["body"]["elements"][0]["content"]
    assert "执行中" in md and "已完成" in md, md
    # 没传触发文件时不渲染"触发"行
    assert "**触发**" not in md
    assert card["header"]["title"]["content"] == "状态变更：Auth Redesign"


def test_status_change_card_with_trigger_file():
    """matter 路径带触发三件套时，卡片出"触发：<type> — <summary>"行。"""
    card = build_status_change_card(
        thread_title="Auth Redesign",
        author_name="邓柯",
        from_state="executing",
        to_state="finished",
        reason=None,
        thread_url="http://x/auth/entry",
        trigger_type="result",
        trigger_summary="主链路完成，结果可接受",
    )
    md = card["body"]["elements"][0]["content"]
    assert "**触发**：result — 主链路完成，结果可接受" in md


def test_status_change_card_without_matter_labels_fallback_to_raw():
    """unknown state (旧 thread 残留调用、或非标值) fallback 到原字符串，不炸。"""
    card = build_status_change_card(
        thread_title="Legacy",
        author_name="u",
        from_state="open",  # 老 thread 态，不在新 _STATUS_LABEL 里
        to_state="concluded",
        reason=None,
        thread_url="http://x/auth/entry",
    )
    md = card["body"]["elements"][0]["content"]
    assert "open" in md and "concluded" in md


def test_feishu_notifier_matter_status_change_uses_matter_url(monkeypatch):
    """trigger_filename 提供时，按钮跳转应走 /m/:matter_id，而非 /t/:cat/:slug。"""
    captured: list[dict] = []

    class _StubTokens:
        def get(self) -> str:
            return "token"

    n = FeishuNotifier(
        tokens=_StubTokens(),
        web_base_url="http://localhost:5173",
        workspace=None,
    )

    def _fake_broadcast(card, *, event):
        captured.append({"card": card, "event": event})

    monkeypatch.setattr(n, "_broadcast", _fake_broadcast)

    n.notify_status_change(
        category="Pivot", slug="auth-redesign", thread_title="Auth Redesign",
        from_state="executing", to_state="finished",
        author_name="邓柯", reason=None,
        trigger_type="result",
        trigger_summary="完成",
        trigger_filename="004_dengke_result_abc.md",
    )

    assert len(captured) == 1
    card = captured[0]["card"]
    # 按钮链接走 /m/<matter_id>（matter 路由）；next= 参数是 URL-encoded
    btn_url = _extract_button_url(card)
    assert "%2Fm%2Fauth-redesign" in btn_url, btn_url
    assert "%2Ft%2F" not in btn_url, btn_url


def test_feishu_notifier_thread_status_change_uses_thread_url(monkeypatch):
    """未提供 trigger_filename 时按老 thread 路径走 /t/:cat/:slug，兼容老客户端。"""
    captured: list[dict] = []

    class _StubTokens:
        def get(self) -> str:
            return "token"

    n = FeishuNotifier(
        tokens=_StubTokens(),
        web_base_url="http://localhost:5173",
        workspace=None,
    )
    monkeypatch.setattr(n, "_broadcast", lambda card, *, event: captured.append(card))

    n.notify_status_change(
        category="general", slug="legacy-thread", thread_title="Legacy",
        from_state="open", to_state="concluded",
        author_name="u", reason="some reason",
    )

    btn_url = _extract_button_url(captured[0])
    assert "%2Ft%2Fgeneral%2Flegacy-thread" in btn_url


def _extract_button_url(card: dict) -> str:
    """Pull the action URL out of a card (schema 2.0)."""
    import json as _json
    raw = _json.dumps(card, ensure_ascii=False)
    return raw
